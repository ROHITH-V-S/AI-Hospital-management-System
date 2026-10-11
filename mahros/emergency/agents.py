"""The agents of the emergency module.

HospitalAgent
    One per hospital. Holds PRIVATE live state that no other agent can read:
    ICU beds in use, nurses on shift (short-staffed or not), ventilators in
    use, cath-lab rooms busy, children's ICU, and its own policy of how many
    ICU beds to keep back for its own emergency department. It answers a
    call-for-bids, an award or a phone call BY ITSELF, from that state: a bid
    (travel time, when the team is ready, beds free) or a decline with a reason.
    It answers honestly -- there are no "lying" hospitals in this model.

DataStewardAgent (bid check)
    Compares each bid with the hospital's own most recent weekly report. A bid
    for an ICU bed from a hospital whose report says its ICU is full, or whose
    report could not be verified, is flagged: the coordinator must confirm it
    by voice before relying on it. A flag is a reason to check, not an
    accusation.

EmergencyCoordinator (MAHROS)
    Knows only public facts: where hospitals are, road times, CMS capability
    and the weekly reports. Broadcasts a call-for-bids to every capable
    hospital within reach AT ONCE, waits a fixed bid window, ranks the answers
    (time to definitive care first, then capability, then load), and makes one
    acceptance call to the winner.

PhoneCoordinator (baseline: today's practice)
    Same public facts. Calls capable hospitals ONE AT A TIME, nearest first
    (or, in the "informed" variant, the ones whose weekly report shows ICU room
    first), and stops at the FIRST hospital that says yes.

All agents talk through ``Bus`` messages in simulated time; every message can
be written to the audit ledger.
"""

from __future__ import annotations

import heapq
import math
import zlib
from dataclasses import dataclass, field

import numpy as np

from .network import REQUIRES, Site
from .params import NEEDS, Params

DAY = 1440.0


# --------------------------------------------------------------------------- #
# Simulation kernel and message bus
# --------------------------------------------------------------------------- #

class Sim:
    """A minimal discrete-event kernel (minutes since the start of the week)."""

    def __init__(self) -> None:
        self.now = 0.0
        self._q: list = []
        self._n = 0

    def at(self, t: float, fn, *args) -> None:
        self._n += 1
        heapq.heappush(self._q, (t, self._n, fn, args))

    def after(self, d: float, fn, *args) -> None:
        self.at(self.now + max(0.0, d), fn, *args)

    def run(self, until: float) -> None:
        while self._q and self._q[0][0] <= until:
            t, _, fn, args = heapq.heappop(self._q)
            self.now = t
            fn(*args)
        self.now = max(self.now, until)


@dataclass
class Message:
    kind: str            # REQUEST CFB BID DECLINE NO_ANSWER STEWARD_FLAG AWARD CONFIRM REFUSE PHONE_CALL PLACED NOT_PLACED
    sender: str
    receiver: str
    t: float
    body: dict = field(default_factory=dict)


class Bus:
    """Delivers messages after a delay and keeps a transcript (for the ledger and the UI)."""

    def __init__(self, sim: Sim, record: bool = False) -> None:
        self.sim = sim
        self.record = record
        self.transcript: list[Message] = []

    def send(self, msg: Message, to, delay: float = 0.0) -> None:
        # A bound method, not a closure, so a copied world (the phone what-if)
        # delivers to its own copies of the agents.
        self.sim.after(delay, self._deliver, msg, to)

    def _deliver(self, msg: Message, to) -> None:
        msg.t = self.sim.now
        if self.record:
            self.transcript.append(msg)
        to.receive(msg)

    def note(self, msg: Message) -> None:
        """A message with no recipient agent (e.g. the Steward's flag, the outcome)."""
        msg.t = self.sim.now
        if self.record:
            self.transcript.append(msg)


# --------------------------------------------------------------------------- #
# Hospital agent
# --------------------------------------------------------------------------- #

class HospitalAgent:
    def __init__(self, site: Site, idx: int, prm: Params, short_staffed: bool,
                 rng: np.random.Generator, seed: int) -> None:
        self.site = site
        self.idx = idx
        self.address = f"hospital:{site.pk}"
        # ---------------- private state (never read by other agents) ----------
        staffed = int(round(site.icu_beds or 0))
        self._icu_staffed = staffed
        self._short = short_staffed
        # Estimated from the Title 22 ratio. Rounded UP: a staffed bed is, by
        # definition, a bed the hospital has nurses for (rounding down made a
        # 105-bed ICU lose a bed and wrongly call itself short-staffed).
        nurses = math.ceil(staffed / prm.nurse_ratio_icu)
        if short_staffed:
            nurses = math.floor(nurses * (1 - prm.short_staff_cut))
        self._nurses = nurses
        self._icu_usable = min(staffed, int(nurses * prm.nurse_ratio_icu))
        self._icu = min(int(round(site.icu_used or 0)), self._icu_usable)
        self._vents = int(round(staffed * prm.vents_per_icu_bed))
        self._vented = int(round(self._icu * prm.icu_vent_share))
        self._picu_cap = int(round(site.picu_beds or 0))
        self._picu = min(int(round(site.picu_used or 0)), self._picu_cap)
        self._reserve = int(prm.reserve_beds) if staffed >= 10 else 0
        self._cath_rooms = site.cath_rooms if site.caps.get("cath_lab") else 0
        self._cath_busy_until: list[float] = [0.0] * self._cath_rooms
        self._prm = prm
        self._seed = seed
        self.blocked = 0                      # own admissions turned away (full)
        self.stats_icu_minutes = 0.0          # for the calibration check
        self._last_t = 0.0

    # ------------------------------------------------ local events (own patients)
    def _tick(self, now: float) -> None:
        self.stats_icu_minutes += self._icu * (now - self._last_t)
        self._last_t = now

    def admit_local(self, now: float, unit: str, vented: bool) -> bool:
        self._tick(now)
        if unit == "picu":
            if self._picu < self._picu_cap:
                self._picu += 1
                return True
        elif self._icu < self._icu_usable:
            self._icu += 1
            self._vented += int(vented and self._vented < self._vents)
            return True
        self.blocked += 1
        return False

    def discharge(self, now: float, unit: str, vented: bool) -> None:
        self._tick(now)
        if unit == "picu":
            self._picu = max(0, self._picu - 1)
        else:
            self._icu = max(0, self._icu - 1)
            if vented:
                self._vented = max(0, self._vented - 1)

    # ------------------------------------------------ deciding
    def _cath_ready(self, now: float) -> float | None:
        """Minutes until a cath room and team are ready, from private state."""
        if self._cath_rooms == 0:
            return None
        best = None
        for r in range(self._cath_rooms):
            t = max(now, self._cath_busy_until[r])
            # other (scheduled) work in 30-minute slots, daytime only
            for _ in range(16):
                hour = (t % DAY) / 60
                if 7 <= hour < 19 and self._slot_busy(r, int(t // 30)):
                    t = (int(t // 30) + 1) * 30
                    continue
                break
            ready = t - now
            hour = (t % DAY) / 60
            if not (7 <= hour < 19):
                ready = max(ready, self._prm.cath_callin_min)   # team called in at night
            best = ready if best is None else min(best, ready)
        return best

    def _slot_busy(self, room: int, slot: int) -> bool:
        # zlib.crc32, not hash(): Python's str hash changes between runs.
        h = (self._seed * 1_000_003 + zlib.crc32(self.site.pk.encode()) * 101 + room * 7919 + slot) % (2**32)
        return np.random.default_rng(h).random() < self._prm.cath_day_util

    def decide(self, need: str, now: float, own_patient: bool = False) -> tuple[bool, dict]:
        """(yes?, details). The same rule answers a bid request, an award and a phone call.

        ``own_patient``: a patient already in this hospital's emergency department
        may use the beds the hospital keeps back for exactly that.
        """
        s, prm = self.site, self._prm
        missing = [c for c in REQUIRES[need] if not s.caps.get(c, False)]
        if missing:
            return False, {"reason": f"we do not provide {NEED_WORD[missing[0]]}", "code": "capability"}
        if need == "picu":
            free = self._picu_cap - self._picu
            if free <= 0:
                return False, {"reason": f"children's ICU full ({self._picu} of {self._picu_cap} beds)",
                               "code": "full"}
            return True, {"ready_min": 0.0, "free": free,
                          "reason": f"{free} children's ICU bed(s) free"}
        free = self._icu_usable - self._icu
        if free <= 0:
            if self._icu < self._icu_staffed and self._short:
                return False, {"reason": (f"beds are empty but not enough nurses on shift "
                                          f"({self._nurses} ICU nurses; short-staffed this week)"),
                               "code": "staff"}
            return False, {"reason": f"ICU full ({self._icu} of {self._icu_staffed} beds in use)",
                           "code": "full"}
        if free <= self._reserve and not own_patient:
            return False, {"reason": (f"only {free} ICU bed(s) free, kept for our own emergency "
                                      f"department (our policy)"), "code": "reserve"}
        if need == "ventilator" and self._vented >= self._vents:
            return False, {"reason": f"no ventilator free ({self._vents} in use)", "code": "equipment"}
        ready = 0.0
        if need == "cath_lab":
            ready = self._cath_ready(now)
        elif need in ("trauma", "neurosurgery", "burns"):
            ready = prm.surgery_ready_min
        word = "ICU bed" if free == 1 else "ICU beds"
        extra = {"cath_lab": f"; cath lab ready in {ready:.0f} min",
                 "trauma": f"; trauma team ready in {ready:.0f} min",
                 "neurosurgery": f"; neurosurgeon ready in {ready:.0f} min",
                 "burns": f"; burns team ready in {ready:.0f} min",
                 "ventilator": f"; {self._vents - self._vented} ventilator(s) free"}.get(need, "")
        return True, {"ready_min": round(ready, 1), "free": free,
                      "reason": f"{free} {word} free{extra}"}

    def take(self, need: str, now: float, vented: bool, own_patient: bool = False) -> bool:
        """Reserve the bed (and the cath room) for an accepted patient."""
        ok, d = self.decide(need, now, own_patient)
        if not ok:
            return False
        self._tick(now)
        if need == "picu":
            self._picu += 1
        else:
            self._icu += 1
            self._vented += int(vented)
        if need == "cath_lab" and self._cath_rooms:
            r = int(np.argmin(self._cath_busy_until))
            self._cath_busy_until[r] = now + d["ready_min"] + self._prm.cath_proc_min
        return True

    # ------------------------------------------------ messages
    def receive(self, msg: Message) -> None:
        self.world.on_hospital_message(self, msg)

    # Public, read-only facts for the UI after the fact (never used by other agents).
    def snapshot(self) -> dict:
        return {"icu_in_use": self._icu, "icu_staffed": self._icu_staffed,
                "icu_usable": self._icu_usable, "nurses_icu": self._nurses,
                "short_staffed": self._short, "vents": self._vents, "vented": self._vented,
                "picu": self._picu, "picu_cap": self._picu_cap, "reserve": self._reserve}


NEED_WORD = {"icu": "intensive care", "cath_lab": "a cath lab", "trauma": "trauma surgery",
             "neurosurgery": "neurosurgery", "picu": "children's intensive care",
             "burns": "a burns unit", "cardiac_surgery": "cardiac surgery"}


# --------------------------------------------------------------------------- #
# Data Steward: check bids against the hospital's own weekly report
# --------------------------------------------------------------------------- #

def steward_check(site: Site, need: str) -> str | None:
    """A reason to confirm by voice, or None. Uses only the PUBLIC weekly report."""
    if site.level in ("RED", "MISSING"):
        return ("its weekly report this week could not be verified "
                f"({'not sent' if site.level == 'MISSING' else 'flagged RED'}) — confirm by phone")
    if need == "picu":
        if site.picu_beds and site.picu_used is not None and site.picu_used >= site.picu_beds:
            return "it offers a children's ICU bed, but its weekly report says that unit is full — confirm by phone"
        return None
    occ = site.icu_occ
    if occ is not None and occ >= 1.0:
        return (f"it offers an ICU bed, but its weekly report says its ICU is {occ:.0%} full "
                f"— confirm by phone")
    return None
