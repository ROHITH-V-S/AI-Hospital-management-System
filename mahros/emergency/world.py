"""One simulated week in one state: real hospitals, simulated minutes.

What is real and what is simulated
----------------------------------
Real (observed): the hospitals, their capability (CMS POS), road times
(OSRM), each hospital's reported ICU beds and patients this week, its reported
emergency-department visits this week, and the state's real share of
hospitals reporting a critical staffing shortage this week.

Simulated (grounded in the real numbers):
* Each ICU starts at its REAL reported census. Own admissions arrive at random
  (Poisson) at rate census / mean ICU stay, and each patient stays a random
  time with that mean, so the expected census equals the reported weekly
  average. This is CALIBRATION to the report, not validation: it shows the
  simulation starts from reality, not that it reproduces minute-level reality
  (no public minute-level data exists).
* Emergency transfer needs arise at each hospital at rate (ED visits this
  week) x transfer_rate, spread uniformly over the week.
* Which hospitals are short-staffed is drawn with the real state share.

Common random numbers: every random draw comes from a stream fixed by the
seed and NOT by the policy, so MAHROS and the phone baseline face exactly the
same patients, at the same minutes, in the same hospitals.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from .agents import DAY, Bus, HospitalAgent, Message, Sim, steward_check
from .network import Network
from .params import NEEDS, Params

WEEK = 7 * DAY
POLICIES = ("mahros", "phone_nearest", "phone_informed")


@dataclass
class Case:
    id: int
    origin: int
    need: str
    window: float
    t0: float
    los_min: float
    vented: bool
    acuity: str = "critical"
    policy: str = ""
    asked: list = field(default_factory=list)         # MAHROS: hospitals asked at once
    replies: dict = field(default_factory=dict)       # idx -> {"yes", "t", ...}
    ranking: list = field(default_factory=list)       # MAHROS: ranked bids with reasons
    calls: list = field(default_factory=list)         # phone calls / acceptance calls: (idx, t, yes, reason)
    flags: dict = field(default_factory=dict)         # idx -> Steward reason
    chosen: int | None = None
    t_placed: float | None = None
    status: str = "open"                               # open | placed | not_placed

    def metrics(self, net: Network, prm: Params) -> dict:
        placed = self.status == "placed"
        travel = float(net.minutes[self.origin, self.chosen]) if placed else None
        ready = self.replies.get(self.chosen, {}).get("ready_min") if placed else None
        if placed and ready is None:            # phone path: ready time from the call
            ready = next((c[4] for c in self.calls if c[0] == self.chosen and c[2]), 0.0)
        ttb = (self.t_placed - self.t0) if placed else None
        definitive = ttb + max(travel, ready or 0.0) if placed else None
        return {"case": self.id, "need": self.need, "policy": self.policy, "placed": placed,
                "time_to_bed_min": ttb, "travel_min": travel, "definitive_min": definitive,
                "within_window": bool(placed and definitive <= self.window),
                "phone_calls": len(self.calls),
                "asked_automatically": len(self.asked),
                "coordinator_min": len(self.calls) * prm.call_min,
                "steward_flags": len(self.flags),
                "chosen": net.sites[self.chosen].pk if placed else None}


def erlang_b(c: int, a: float) -> float:
    """Probability a c-bed unit is full when offered a Erlangs (Erlang loss formula)."""
    b = 1.0
    for k in range(1, c + 1):
        b = a * b / (k + a * b)
    return b


def offered_load(census: float, c: int) -> float:
    """Arrival rate x stay that makes a CAPPED c-bed unit average ``census`` patients.

    A full unit turns patients away, so offering exactly ``census`` would leave
    it emptier than reported (found in the calibration check: 4-16% too empty
    at nearly full hospitals). Solved by bisection; a unit reported at or above
    capacity is offered up to 3x its beds (it then stays almost always full).
    """
    if c <= 0 or census <= 0:
        return 0.0
    target = min(census, c * 0.995)
    lo, hi = 0.0, 3.0 * c + 10
    if hi * (1 - erlang_b(c, hi)) < target:
        return hi
    for _ in range(60):
        mid = (lo + hi) / 2
        if mid * (1 - erlang_b(c, mid)) < target:
            lo = mid
        else:
            hi = mid
    return (lo + hi) / 2


class World:
    def __init__(self, net: Network, prm: Params, seed: int, policy: str = "mahros",
                 record: bool = False, horizon: float = WEEK) -> None:
        assert policy in POLICIES
        self.net, self.prm, self.seed, self.policy = net, prm, seed, policy
        self.horizon = horizon
        self.sim = Sim()
        self.bus = Bus(self.sim, record)
        share = net.staffing_share or 0.0
        short = np.random.default_rng([seed, 1]).random(len(net.sites)) < share
        self.agents = []
        for i, s in enumerate(net.sites):
            a = HospitalAgent(s, i, prm, bool(short[i]), None, seed)
            a.world = self
            self.agents.append(a)
        self.cases: list[Case] = []
        self.local = 0                       # needs met inside the origin hospital
        self.no_origin_data = sum(1 for s in net.sites if not s.ed_visits_week)
        self._reply_rng = np.random.default_rng([seed, 4])
        self._background()
        self._requests()

    # ----------------------------------------------------------- randomness
    def _background(self) -> None:
        """Own ICU / children's ICU admissions and discharges (calibrated to the report)."""
        los = self.prm.los_icu_days * DAY
        for i, a in enumerate(self.agents):
            rng = np.random.default_rng([self.seed, 2, i])
            for unit, census, cap in (("icu", a._icu, a._icu_usable),
                                      ("picu", a._picu, a._picu_cap)):
                if cap <= 0:
                    continue
                n_vent = a._vented if unit == "icu" else 0
                for k in range(census):              # patients already there: remaining stay
                    self.sim.at(rng.exponential(los), self._discharge, a, unit, k < n_vent)
                reported = (a.site.icu_used if unit == "icu" else a.site.picu_used) or 0.0
                lam = offered_load(reported, cap) / los          # arrivals per minute
                t = 0.0
                while lam > 0:
                    t += rng.exponential(1 / lam)
                    if t > self.horizon:
                        break
                    stay = rng.exponential(los)
                    vent = bool(rng.random() < self.prm.icu_vent_share) and unit == "icu"
                    self.sim.at(t, self._local_admit, a, unit, vent, stay)

    def _discharge(self, a: HospitalAgent, unit: str, vent: bool) -> None:
        a.discharge(self.sim.now, unit, vent)

    def _local_admit(self, a: HospitalAgent, unit: str, vent: bool, stay: float) -> None:
        if a.admit_local(self.sim.now, unit, vent):
            self.sim.after(stay, self._discharge, a, unit, vent)

    def _requests(self) -> None:
        rng = np.random.default_rng([self.seed, 3])
        needs = list(NEEDS)
        p = np.array([NEEDS[n]["share"] for n in needs])
        p = p / p.sum()
        los = self.prm.los_icu_days * DAY
        n = 0
        for i, s in enumerate(self.net.sites):
            ed = s.ed_visits_week or 0.0
            lam = ed / WEEK * self.prm.transfer_rate
            t = 0.0
            while lam > 0:
                t += rng.exponential(1 / lam)
                if t > self.horizon:
                    break
                need = needs[rng.choice(len(needs), p=p)]
                stay = rng.exponential(los)
                vent = need == "ventilator" or (need in ("icu", "trauma", "neurosurgery", "burns")
                                                and rng.random() < self.prm.icu_vent_share)
                n += 1
                self.sim.at(t, self.on_need, i, need, stay, vent, n)

    # ----------------------------------------------------------- a patient needs care
    def on_need(self, origin: int, need: str, stay: float, vent: bool, n: int,
                acuity: str = "critical", force_transfer: bool = False) -> Case | None:
        o = self.agents[origin]
        if not force_transfer and o.take(need, self.sim.now, vent, own_patient=True):
            self.local += 1                                   # treated where they are
            self.sim.after(stay, self._discharge, o, "picu" if need == "picu" else "icu", vent)
            return None
        from .params import ACUITY
        window = NEEDS[need]["window"] * self.prm.window_scale * ACUITY[acuity]
        c = Case(n, origin, need, window, self.sim.now, stay, vent, acuity, self.policy)
        self.cases.append(c)
        self.bus.note(Message("REQUEST", o.address, "coordinator", self.sim.now,
                              {"case": n, "need": need, "window_min": window}))
        if self.policy == "mahros":
            self._mahros_start(c)
        else:
            self._phone_start(c)
        return c

    def _reach(self, c: Case) -> list[int]:
        """Capable hospitals (public CMS facts) that can be reached inside the window."""
        mins = self.net.minutes[c.origin]
        able = [j for j, s in enumerate(self.net.sites) if j != c.origin and s.can_treat(c.need)]
        near = [j for j in able if mins[j] <= c.window]
        if not near:                                  # nobody in time: still find the nearest beds
            near = sorted(able, key=lambda j: mins[j])[:10]
        return sorted(near, key=lambda j: mins[j])

    # ----------------------------------------------------------- MAHROS: parallel call-for-bids
    def _mahros_start(self, c: Case) -> None:
        c.asked = self._reach(c)
        for j in c.asked:
            self.bus.send(Message("CFB", "coordinator", self.agents[j].address, self.sim.now,
                                  {"case": c.id, "need": c.need,
                                   "origin": self.net.sites[c.origin].pk}), self.agents[j])
        self.sim.after(self.prm.bid_window_min, self._mahros_close, c)

    def on_hospital_message(self, a: HospitalAgent, msg: Message) -> None:
        if msg.kind == "CFB":
            # Each hospital answers by itself, after its own short delay, from its own state.
            c = next(x for x in reversed(self.cases) if x.id == msg.body["case"])
            delay = self._reply_rng.uniform(0.2, 1.0) * self.prm.bid_window_min
            self.sim.after(delay * 0.999, self._mahros_reply, a, c)

    def _mahros_reply(self, a: HospitalAgent, c: Case) -> None:
        yes, d = a.decide(c.need, self.sim.now)
        travel = float(self.net.minutes[c.origin, a.idx])
        c.replies[a.idx] = {"yes": yes, "t": self.sim.now, "travel_min": round(travel, 1), **d}
        self.bus.note(Message("BID" if yes else "DECLINE", a.address, "coordinator", self.sim.now,
                              {"case": c.id, "travel_min": round(travel, 1), **d}))

    def _mahros_close(self, c: Case) -> None:
        prm, net = self.prm, self.net
        for j in c.asked:
            if j not in c.replies:
                c.replies[j] = {"yes": False, "t": None, "reason": "no answer in time",
                                "code": "no_answer"}
        bids = []
        for j, r in c.replies.items():
            if not r["yes"]:
                continue
            flag = steward_check(net.sites[j], c.need)
            if flag:
                c.flags[j] = flag
                self.bus.note(Message("STEWARD_FLAG", "steward", "coordinator", self.sim.now,
                                      {"case": c.id, "hospital": net.sites[j].pk, "why": flag}))
            definitive = max(r["travel_min"], r.get("ready_min") or 0.0) + (prm.call_min if flag else 0.0)
            backup = int(net.sites[j].caps.get("cardiac_surgery", False) and c.need == "cath_lab") + \
                int(net.sites[j].caps.get("trauma", False) and c.need == "neurosurgery")
            bids.append({"idx": j, "definitive_min": round(definitive, 1), "backup": backup,
                         "free": r.get("free", 0), "flag": flag})
        # Time to definitive care first (5-minute bands), then capability, then load.
        bids.sort(key=lambda b: (round(b["definitive_min"] / 5), -b["backup"], -b["free"],
                                 b["definitive_min"]))
        c.ranking = bids
        self._mahros_next(c, 0)

    def _mahros_next(self, c: Case, k: int) -> None:
        if k >= len(c.ranking):
            self._not_placed(c)
            return
        j = c.ranking[k]["idx"]
        self.bus.send(Message("AWARD", "coordinator", self.agents[j].address, self.sim.now,
                              {"case": c.id}), _Null(), 0.0)
        # One doctor-to-doctor acceptance call, the same length as any phone call.
        self.sim.after(self.prm.call_min, self._mahros_award, c, k)

    def _mahros_award(self, c: Case, k: int) -> None:
        j = c.ranking[k]["idx"]
        a = self.agents[j]
        ok = a.take(c.need, self.sim.now, c.vented)
        c.calls.append((j, self.sim.now, ok, "accepted" if ok else "bed went while confirming",
                        c.replies[j].get("ready_min", 0.0)))
        if ok:
            self._placed(c, j)
        else:
            self.bus.note(Message("REFUSE", a.address, "coordinator", self.sim.now,
                                  {"case": c.id, "reason": "the bed was taken while confirming"}))
            self._mahros_next(c, k + 1)

    # ----------------------------------------------------------- phone: one call at a time
    def _phone_order(self, c: Case) -> list[int]:
        order = self._reach(c)
        if self.policy == "phone_informed":
            def room(j):
                s = self.net.sites[j]
                if c.need == "picu":
                    return (s.picu_beds or 0) - (s.picu_used or 0) >= 1
                return (s.icu_beds or 0) - (s.icu_used or 0) >= 1
            order = [j for j in order if room(j)] + [j for j in order if not room(j)]
        return order

    def _phone_start(self, c: Case) -> None:
        c.asked = []
        order = self._phone_order(c)
        if not order:
            self._not_placed(c)
            return
        self.sim.after(self.prm.call_min, self._phone_answer, c, order, 0)

    def _phone_answer(self, c: Case, order: list[int], k: int) -> None:
        j = order[k]
        a = self.agents[j]
        yes, d = a.decide(c.need, self.sim.now)
        if yes:
            yes = a.take(c.need, self.sim.now, c.vented)
        c.calls.append((j, self.sim.now, yes, d["reason"], d.get("ready_min", 0.0)))
        self.bus.note(Message("PHONE_CALL", "caller", a.address, self.sim.now,
                              {"case": c.id, "yes": yes, "reason": d["reason"]}))
        if yes:                        # stop at the FIRST yes (never discard a yes)
            self._placed(c, j)
        elif k + 1 < len(order):
            self.sim.after(self.prm.call_min, self._phone_answer, c, order, k + 1)
        else:
            self._not_placed(c)

    # ----------------------------------------------------------- outcome
    def _placed(self, c: Case, j: int) -> None:
        c.status, c.chosen, c.t_placed = "placed", j, self.sim.now
        arrive = float(self.net.minutes[c.origin, j])
        self.sim.after(arrive + c.los_min, self._discharge, self.agents[j],
                       "picu" if c.need == "picu" else "icu", c.vented)
        self.bus.note(Message("PLACED", "coordinator", self.agents[j].address, self.sim.now,
                              {"case": c.id, "to": self.net.sites[j].pk,
                               "time_to_bed_min": round(self.sim.now - c.t0, 1)}))

    def _not_placed(self, c: Case) -> None:
        c.status, c.t_placed = "not_placed", self.sim.now
        self.bus.note(Message("NOT_PLACED", "coordinator", "ledger", self.sim.now, {"case": c.id}))

    # ----------------------------------------------------------- run
    def run(self, until: float | None = None) -> None:
        self.sim.run(self.horizon + DAY if until is None else until)

    def results(self) -> list[dict]:
        return [c.metrics(self.net, self.prm) for c in self.cases if c.status != "open"]

    def calibration(self) -> list[dict]:
        """Simulated vs reported mean ICU census per hospital (run with transfer_rate=0)."""
        out = []
        for a in self.agents:
            a._tick(self.sim.now)
            if a._icu_staffed and a.site.icu_used:
                out.append({"pk": a.site.pk, "reported": a.site.icu_used,
                            "simulated": a.stats_icu_minutes / self.sim.now,
                            "staffed": a._icu_staffed, "usable": a._icu_usable})
        return out


class _Null:
    def receive(self, msg) -> None:
        pass
