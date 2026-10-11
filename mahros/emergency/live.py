"""The live Emergency screen: one state's hospitals, a running simulated clock,
and "Find a bed" for a patient the presenter chooses.

Each press:
1. advances the simulated week to the current clock (other patients come and
   go, other hospitals send their own transfer requests);
2. runs the MAHROS call-for-bids for the chosen patient, agent by agent;
3. asks "what if we had phoned instead?" on exact copies of the same moment,
   with 5-, 10- and 15-minute calls (the result is a RANGE);
4. writes the request, every answer and the transfer into the database and
   seals the messages as one page of the record book.

Labelled everywhere as a simulation grounded in real data.
"""

from __future__ import annotations

import copy
import threading
import traceback
from datetime import date, datetime, timedelta, timezone

import numpy as np
import pandas as pd

from . import network as N
from .agents import DAY, NEED_WORD
from .params import ACUITY, NEEDS, Params
from .world import WEEK, World

START_CLOCK = DAY + 10 * 60 + 42          # day 2, 10:42 -- the world has warmed up
TEST_FIRST, TEST_LAST = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-04-14")


def nice(name: str) -> str:
    from ..server.live import nice_name
    return nice_name(name)


class EmergencyLive:
    def __init__(self, engine=None, book=None) -> None:
        self.engine, self.book = engine, book
        self.ready, self.loading, self.error = False, False, None
        self.lock = threading.Lock()
        self.sessions: dict[str, dict] = {}
        self.prm = Params()

    # ------------------------------------------------------------ loading
    def start_loading(self) -> None:
        if self.loading or self.ready:
            return
        self.loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from ..db.frames import assessed_frame, loaded
            from ..db.io import read_frame
            if self.engine is not None and loaded(self.engine):
                df = assessed_frame(self.engine, list(N.STATES))
                st = read_frame(self.engine, "SELECT * FROM state_staffing")
                st["date"] = pd.to_datetime(st["date"])
                self.source = "database"
            else:
                from ..data import hhs
                from ..pipeline import assessed
                df = assessed()
                df = df[df["state"].isin(list(N.STATES))]
                ex = hhs.load_extra()
                df = df.merge(ex[["hospital_pk", "week"] + list(hhs.EXTRA_FIELDS)],
                              on=["hospital_pk", "week"], how="left")
                st = hhs.load_state_staffing()
                self.source = "research files (database not loaded)"
            self.df, self.st = df, st
            self.weeks = {}
            for s in N.STATES:
                d = df[(df["state"] == s) & (df["week"] >= TEST_FIRST) & (df["week"] <= TEST_LAST)
                       & df["level"].isin(["GREEN", "AMBER"])]
                g = d.groupby("week")[["icu_used", "icu_beds"]].sum()
                occ = g["icu_used"] / g["icu_beds"]
                self.weeks[s] = [{"week": str(w.date()), "icu_occupancy": round(float(o), 3)}
                                 for w, o in occ.items()]
            self.ready = True
            for s in N.STATES:
                busiest = max(self.weeks[s], key=lambda x: x["icu_occupancy"])["week"]
                self.reset(s, busiest)
        except Exception as exc:
            self.error = str(exc)
            traceback.print_exc()
        finally:
            self.loading = False

    # ------------------------------------------------------------ sessions
    def reset(self, state: str, week: str, seed: int = 7) -> dict:
        net = N.build(state, week, self.df, self.st)
        w = World(net, self.prm, seed, "mahros", record=True, horizon=WEEK)
        w.run(START_CLOCK)
        self.sessions[state] = {"net": net, "world": w, "week": week, "clock": START_CLOCK,
                                "cases": [], "n": 0}
        return self.status(state)

    def status(self, state: str | None = None) -> dict:
        out = {"ready": self.ready, "loading": self.loading, "error": self.error,
               "data_source": getattr(self, "source", None)}
        if not self.ready:
            return out
        out["states"] = [{"state": s, "name": n} for s, n in N.STATES.items()]
        out["needs"] = {k: {"label": v["label"], "window": v["window"]} for k, v in NEEDS.items()}
        out["acuity"] = list(ACUITY)
        if state:
            s = self.sessions[state]
            out.update({"state": state, "state_name": N.STATES[state], "week": s["week"],
                        "weeks": self.weeks[state], "clock": self.clock_text(s),
                        "cases_done": len(s["cases"]),
                        "staffing": self._staffing_text(s["net"])})
        return out

    def _staffing_text(self, net) -> str:
        if net.staffing_share is None:
            return "No real staffing report for this week."
        return (f"Real staffing report this week: {net.staffing_share:.0%} of the "
                f"{net.staffing_answered} {N.STATES[net.state]} hospitals that answered said they had a "
                f"critical staffing shortage ({net.staffing_silent} did not answer). Short-staffed "
                f"hospitals in the simulation are drawn with that share.")

    def clock_text(self, s, t: float | None = None) -> str:
        return self.clock(s, t).strftime("%a %d %b %Y, %H:%M")

    def clock(self, s, t: float | None = None) -> datetime:
        return datetime.combine(date.fromisoformat(s["week"]), datetime.min.time()) + \
            timedelta(minutes=s["clock"] if t is None else t)

    def hospitals(self, state: str) -> list[dict]:
        """What the coordinator may know: public facts and the REAL weekly report."""
        s = self.sessions[state]
        out = []
        for x in s["net"].sites:
            out.append({"id": x.pk, "name": nice(x.name), "city": x.city.title() if x.city else "",
                        "lat": x.lat, "lon": x.lon, "level": x.level,
                        "icu_beds": x.icu_beds, "icu_used": x.icu_used,
                        "icu_occ": round(x.icu_occ, 3) if x.icu_occ is not None else None,
                        "can": {n: x.can_treat(n) for n in NEEDS},
                        "cap_source": x.cap_source,
                        "ed_visits_week": x.ed_visits_week})
        return out

    def advance(self, state: str, minutes: float) -> dict:
        with self.lock:
            s = self.sessions[state]
            s["clock"] = min(WEEK, s["clock"] + max(0.0, minutes))
            s["world"].run(s["clock"])
            return self.status(state)

    # ------------------------------------------------------------ find a bed
    def find_bed(self, state: str, origin_pk: str, need: str, acuity: str = "critical") -> dict:
        if need not in NEEDS or acuity not in ACUITY:
            raise ValueError("unknown need or acuity")
        with self.lock:
            s = self.sessions[state]
            w, net = s["world"], s["net"]
            o = net.index(origin_pk)
            if s["clock"] >= WEEK - 3 * 60:
                raise ValueError("The simulated week is over -- press Restart to start it again.")
            w.run(s["clock"])
            stay = self.prm.los_icu_days * DAY
            vent = need == "ventilator"
            s["n"] += 1
            n = -s["n"]                              # presenter's cases: negative ids
            # The phone what-if, on exact copies of this moment (before anything changes).
            phone = {}
            for cm in (5.0, 10.0, 15.0):
                wc = copy.deepcopy(w)
                wc.policy, wc.prm, wc.bus.record = "phone_nearest", self.prm.with_(call_min=cm), False
                pc = wc.on_need(o, need, stay, vent, n, acuity, force_transfer=True)
                wc.run(s["clock"] + 24 * 60)
                phone[cm] = pc
            start = len(w.bus.transcript)
            c = w.on_need(o, need, stay, vent, n, acuity, force_transfer=True)
            t = s["clock"]
            while c.status == "open" and t < s["clock"] + DAY:     # until this case is settled
                t += self.prm.call_min
                w.run(t)
            msgs = [m for m in w.bus.transcript[start:] if m.body.get("case") == n]
            s["clock"] = (c.t_placed or s["clock"]) + 2.0
            result = self._explain(s, c, phone, msgs)
            result["book"] = self._record(s, c, msgs, result)
            s["cases"].append({"id": n, "origin": nice(net.sites[o].name), "need": need,
                               "placed": c.status == "placed"})
            result["status"] = self.status(state)
            return result

    # ------------------------------------------------------------ explaining
    def _explain(self, s, c, phone, msgs) -> dict:
        net, prm = s["net"], self.prm
        site = net.sites
        o = c.origin
        mins = net.minutes[o]
        ask = []
        for j in c.asked:
            r = c.replies.get(j, {})
            ask.append({"id": site[j].pk, "name": nice(site[j].name),
                        "road_min": round(float(mins[j])), "yes": bool(r.get("yes")),
                        "reason": r.get("reason", ""), "code": r.get("code"),
                        "ready_min": r.get("ready_min"),
                        "answered_at": self.clock(s, r["t"]).strftime("%H:%M:%S") if r.get("t") is not None else None,
                        "flag": c.flags.get(j)})
        ask.sort(key=lambda a: (not a["yes"], a["road_min"]))
        ranking = []
        for k, b in enumerate(c.ranking[:5]):
            j = b["idx"]
            why = (f"patient at definitive care in about {b['definitive_min']:.0f} min "
                   f"({mins[j]:.0f} min drive"
                   + (f", team ready in {c.replies[j].get('ready_min'):.0f} min" if c.replies[j].get("ready_min") else "")
                   + (", +{:.0f} min to confirm by phone".format(prm.call_min) if b["flag"] else "")
                   + f"); {b['free']} bed(s) free")
            ranking.append({"rank": k + 1, "id": site[j].pk, "name": nice(site[j].name), "why": why})
        placed = c.status == "placed"
        chosen = site[c.chosen] if placed else None
        ttb = (c.t_placed - c.t0) if placed else None

        def ph(pc):
            if pc is None:
                return None
            done = pc.status == "placed"
            return {"placed": done, "minutes": round(pc.t_placed - pc.t0, 1) if done else None,
                    "calls": len(pc.calls),
                    "to": nice(site[pc.chosen].name) if done else None,
                    "to_id": site[pc.chosen].pk if done else None,
                    "road_min": round(float(mins[pc.chosen])) if done else None,
                    "call_list": [{"name": nice(site[x[0]].name), "id": site[x[0]].pk,
                                   "yes": bool(x[2]), "reason": x[3]} for x in pc.calls]}
        phone_out = {f"{int(k)}": ph(v) for k, v in phone.items()}
        p10 = phone[10.0]
        lo = min((v.t_placed - v.t0) for v in phone.values() if v.status == "placed") if any(v.status == "placed" for v in phone.values()) else None
        hi = max((v.t_placed - v.t0) for v in phone.values() if v.status == "placed") if any(v.status == "placed" for v in phone.values()) else None
        timeline = [{"at": self.clock(s, m.t).strftime("%H:%M:%S"), "kind": m.kind,
                     "who": self._who(net, m.sender), "to": self._who(net, m.receiver),
                     "text": self._msg_text(net, m)} for m in msgs]
        yes = sum(1 for a in ask if a["yes"])
        if placed:
            r0 = c.ranking[0]
            headline = (f"Bed found at {nice(chosen.name)} — {ttb:.0f} minutes after the request "
                        f"({ttb * 60:.0f} seconds), {mins[c.chosen]:.0f} min away by road.")
        else:
            headline = "No hospital within reach could take this patient right now."
        return {
            "case": c.id, "need": c.need, "need_label": NEEDS[c.need]["label"],
            "acuity": c.acuity, "window_min": c.window,
            "origin": {"id": site[o].pk, "name": nice(site[o].name)},
            "requested_at": self.clock(s, c.t0).strftime("%a %H:%M:%S"),
            "asked": ask, "asked_count": len(ask), "yes_count": yes,
            "flags": [{"id": site[j].pk, "name": nice(site[j].name), "why": f}
                      for j, f in c.flags.items()],
            "ranking": ranking,
            "placed": placed, "chosen": {"id": chosen.pk, "name": nice(chosen.name),
                                         "road_min": round(float(mins[c.chosen]))} if placed else None,
            "time_to_bed_min": round(ttb, 1) if ttb is not None else None,
            "within_window": bool(placed and ttb + max(float(mins[c.chosen]),
                                  c.replies[c.chosen].get("ready_min") or 0) <= c.window),
            "headline": headline,
            "phone": phone_out, "phone_range_min": [lo, hi],
            "phone_text": self._phone_text(p10, lo, hi, net, mins),
            "timeline": timeline,
            "params": {"bid_window_min": prm.bid_window_min, "call_min": prm.call_min},
            "label": "Simulation grounded in real data: real hospitals, capability, road times and "
                     "this week's reports; simulated minute-by-minute beds and requests.",
        }

    def _phone_text(self, p10, lo, hi, net, mins) -> str:
        if p10 is None or p10.status != "placed":
            return "Phoning one hospital at a time would not have found a bed."
        n = len(p10.calls)
        rng = f"{lo:.0f}–{hi:.0f} minutes" if lo is not None and hi is not None and hi > lo else f"{lo:.0f} minutes"
        return (f"Phoning nearest-first: {n} call{'s' if n > 1 else ''}, bed at "
                f"{nice(net.sites[p10.chosen].name)}. With 5–15 minutes per call: {rng}.")

    @staticmethod
    def _who(net, address: str) -> str:
        if address.startswith("hospital:"):
            pk = address.split(":", 1)[1]
            return nice(next((x.name for x in net.sites if x.pk == pk), pk))
        return {"coordinator": "MAHROS coordinator", "steward": "Data Steward",
                "ledger": "Record book", "caller": "Phone caller"}.get(address, address)

    def _msg_text(self, net, m) -> str:
        b = m.body
        if m.kind == "REQUEST":
            return f"needs {NEEDS[b['need']]['label'].lower()} (within {b['window_min']:.0f} min)"
        if m.kind == "CFB":
            return "call for bids"
        if m.kind == "BID":
            return f"bid: {b.get('reason', '')}; {b.get('travel_min', 0):.0f} min away"
        if m.kind == "DECLINE":
            return f"declined: {b.get('reason', '')}"
        if m.kind == "STEWARD_FLAG":
            return f"check: {b.get('why', '')}"
        if m.kind == "AWARD":
            return "acceptance call (doctor to doctor)"
        if m.kind == "REFUSE":
            return b.get("reason", "")
        if m.kind == "PLACED":
            return f"bed confirmed after {b.get('time_to_bed_min', 0):.1f} min"
        if m.kind == "NOT_PLACED":
            return "no bed found"
        return ""

    # ------------------------------------------------------------ database
    def _record(self, s, c, msgs, res) -> dict | None:
        if self.engine is None or self.book is None:
            return None
        from ..db.models import Bid, Transfer, TransferRequest
        from ..db.session import session_scope
        net, book = s["net"], self.book
        site = net.sites
        iso = lambda t: self.clock(s, t).isoformat(timespec="seconds")
        blk = book.open_block(f"Emergency · {N.STATES[net.state]} · {res['origin']['name']} · "
                              f"{res['need_label']} · {res['requested_at']}")
        real_now = datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")
        with session_scope(self.engine) as ss:
            req = TransferRequest(
                state=net.state, origin_pk=site[c.origin].pk, need=c.need, acuity=c.acuity,
                window_min=round(c.window, 1), sim_week=date.fromisoformat(s["week"]),
                sim_time=iso(c.t0), status=c.status if c.status != "open" else "not_placed",
                chosen_pk=site[c.chosen].pk if c.chosen is not None else None,
                contacted=len(c.asked),
                time_to_bed_s=round(res["time_to_bed_min"] * 60, 1) if res["time_to_bed_min"] else None,
                phone_low_min=res["phone_range_min"][0], phone_high_min=res["phone_range_min"][1])
            ss.add(req)
            ss.flush()
            req.ledger_seq = book.append(
                "REQUEST", f"hospital:{site[c.origin].pk}", "coordinator",
                {"need": c.need, "acuity": c.acuity, "window_min": round(c.window, 1),
                 "written_at_real_time": real_now, "clock": "simulated"},
                block_id=blk, recorded_at=iso(c.t0), ref=("transfer_requests", req.id),
                record={"origin_pk": req.origin_pk, "need": req.need, "acuity": req.acuity},
                session=ss)
            book.append("CFB", "coordinator", f"{len(c.asked)} hospitals",
                        {"to": [site[j].pk for j in c.asked], "need": c.need},
                        block_id=blk, recorded_at=iso(c.t0), session=ss)
            bid_rows = {}
            for j in sorted(c.replies, key=lambda j: (c.replies[j].get("t") or 1e18)):
                r = c.replies[j]
                b = Bid(request_id=req.id, hospital_pk=site[j].pk,
                        answer="BID" if r["yes"] else "DECLINE",
                        travel_min=round(float(net.minutes[c.origin, j]), 2),
                        ready_min=round(r["ready_min"], 2) if r.get("ready_min") is not None else None,
                        reason=r.get("reason", ""), steward_flag=j in c.flags,
                        steward_note=c.flags.get(j), chosen=(j == c.chosen))
                ss.add(b)
                ss.flush()
                bid_rows[j] = b
                b.ledger_seq = book.append(
                    b.answer, f"hospital:{site[j].pk}", "coordinator",
                    {"reason": b.reason, "travel_min": b.travel_min, "ready_min": b.ready_min},
                    block_id=blk, recorded_at=iso(r["t"] if r.get("t") is not None else c.t0 + self.prm.bid_window_min),
                    ref=("bids", b.id),
                    record={"hospital_pk": b.hospital_pk, "answer": b.answer,
                            "travel_min": b.travel_min, "ready_min": b.ready_min,
                            "reason": b.reason}, session=ss)
            for j, why in c.flags.items():
                book.append("STEWARD_FLAG", "steward", "coordinator",
                            {"hospital": site[j].pk, "why": why}, block_id=blk,
                            recorded_at=iso(c.t0 + self.prm.bid_window_min), session=ss)
            for (j, t, ok, why, _r) in c.calls:
                book.append("AWARD" if ok else "REFUSE", "coordinator", f"hospital:{site[j].pk}",
                            {"accepted": ok, "note": why}, block_id=blk, recorded_at=iso(t), session=ss)
            if c.status == "placed":
                tr = Transfer(request_id=req.id, from_pk=site[c.origin].pk, to_pk=site[c.chosen].pk,
                              travel_min=round(float(net.minutes[c.origin, c.chosen]), 2),
                              confirmed_at=iso(c.t_placed))
                ss.add(tr)
                ss.flush()
                tr.ledger_seq = book.append(
                    "TRANSFER", "coordinator", f"hospital:{site[c.chosen].pk}",
                    {"time_to_bed_min": res["time_to_bed_min"]}, block_id=blk,
                    recorded_at=iso(c.t_placed), ref=("transfers", tr.id),
                    record={"from_pk": tr.from_pk, "to_pk": tr.to_pk, "travel_min": tr.travel_min},
                    session=ss)
            else:
                book.append("NOT_PLACED", "coordinator", "ledger", {}, block_id=blk,
                            recorded_at=iso(c.t_placed or c.t0), session=ss)
            req_id = req.id
        sealed = book.seal_block(blk)
        sealed["request_id"] = req_id
        return sealed
