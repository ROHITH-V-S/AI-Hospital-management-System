"""Live operations: the agents replay real weeks, one step at a time.

Each step runs the real weekly agent cycle (``mahros.agents.Platform``) for one
state on the hospitals' real reports for that week, and turns the messages
into a feed a person can follow. Nothing is simulated: the reports, the
Steward's verdicts, the forecasts and the hospitals' answers are the same ones
the experiments use. The only thing a presenter can add is a deliberate
mistake in one hospital's report, to show what the Data Steward does with it.

Needs the national data cache (``python experiments/fetch_national.py`` and
``python experiments/rq2_forecast.py``). Without it the console says so and
the evidence tabs still work.
"""

from __future__ import annotations

import threading
import traceback
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from ..ledger.chain import AuditLedger
from ..trust import assess, explain

#: Mistakes a presenter can inject, mapped to what they do to the census.
MISTAKES = {
    "extra_zero": ("Extra zero typed (x10)", lambda u, b: (u * 10, b)),
    "lost_digit": ("Digit missing (/10)", lambda u, b: (u / 10, b)),
    "weekly_total": ("Weekly total typed as the daily figure (x7)", lambda u, b: (u * 7, b)),
    "zero": ("Blank sent as zero patients", lambda u, b: (0.0, b)),
    "swap": ("Beds and patients typed in each other's box", lambda u, b: (b, u)),
}

FEED_LIMIT = 12          # individual items per section before "...and N more"


@dataclass
class Session:
    state: str = ""
    week_idx: int = 0
    ledger: AuditLedger = field(default_factory=AuditLedger)
    history: list = field(default_factory=list)
    pending: dict = field(default_factory=dict)      # hospital id -> mistake key


class LiveEngine:
    def __init__(self) -> None:
        self.ready = False
        self.error: str | None = None
        self.loading = False
        self.lock = threading.Lock()
        self.session = Session()

    # ---------------------------------------------------------------- loading
    def start_loading(self) -> None:
        if self.loading or self.ready:
            return
        self.loading = True
        threading.Thread(target=self._load, daemon=True).start()

    def _load(self) -> None:
        try:
            from ..agents import Platform
            from ..data import hhs
            from ..pipeline import assessed

            fc_path = hhs.CACHE / "forecasts_h1.parquet"
            if not fc_path.exists():
                raise FileNotFoundError(
                    "forecasts not found -- run python experiments/rq2_forecast.py")
            df = assessed("corrected")
            fc = pd.read_parquet(fc_path)
            self.platform = Platform(df, fc)
            # Display only: HHS stores names in capitals.
            self.platform.frame["name"] = self.platform.frame["name"].map(nice_name)
            base_cols = [c for c in df.columns if c not in ("flags", "level", "census_run")]
            self._reports = df[base_cols]
            self._by_pk = self._reports.groupby("hospital_pk", sort=False).indices
            self.weeks = [pd.Timestamp(w) for w in self.platform.weeks()]
            counts = self.platform.frame.groupby("state")["hospital_pk"].nunique()
            self.states = [{"state": s, "hospitals": int(n)} for s, n in counts.items()]
            self.ready = True
            self.reset("TX" if "TX" in counts.index else counts.index[0], 0)
        except Exception as exc:                      # shown in the console
            self.error = f"{exc}"
            traceback.print_exc()
        finally:
            self.loading = False

    # ---------------------------------------------------------------- session
    def status(self) -> dict:
        s = self.session
        out = {"ready": self.ready, "loading": self.loading, "error": self.error}
        if self.ready:
            out.update({
                "states": self.states,
                "weeks": [str(w.date()) for w in self.weeks],
                "state": s.state, "week_idx": s.week_idx,
                "week": str(self.weeks[s.week_idx].date()) if s.week_idx < len(self.weeks) else None,
                "finished": s.week_idx >= len(self.weeks),
                "history": s.history,
                "pending": [{"id": k, "mistake": MISTAKES[v][0]} for k, v in s.pending.items()],
                "ledger": self._ledger_status(),
                "mistakes": {k: v[0] for k, v in MISTAKES.items()},
            })
        return out

    def reset(self, state: str, week_idx: int = 0) -> dict:
        self.session = Session(state=state, week_idx=max(0, min(week_idx, len(self.weeks) - 1)))
        return self.status()

    def hospitals(self) -> list[dict]:
        """Hospitals in the current state (for the map before the first step)."""
        s = self.session
        wk = self.weeks[min(s.week_idx, len(self.weeks) - 1)]
        g = self.platform.week_frame(s.state, wk)
        return [{"id": str(r.hospital_pk), "name": str(r.name), "city": str(r.city),
                 "lat": float(r.lat), "lon": float(r.lon), "beds": _f(r.beds, 0),
                 "occupancy": _f(r.used / r.beds) if r.beds and r.beds == r.beds else None,
                 "level": r.level} for r in g.itertuples()]

    def inject(self, hospital_id: str, mistake: str) -> dict:
        if mistake not in MISTAKES:
            raise ValueError(f"unknown mistake {mistake!r}")
        self.session.pending[str(hospital_id)] = mistake
        return self.status()

    # ---------------------------------------------------------------- step
    def step(self) -> dict:
        with self.lock:
            s = self.session
            if s.week_idx >= len(self.weeks):
                return {"finished": True, **self.status()}
            wk = self.weeks[s.week_idx]
            overrides, injected = self._apply_mistakes(s.state, wk)
            self.platform.ledger = s.ledger
            run = self.platform.run_week(s.state, wk, overrides)
            counter = self._without_steward(s.state, wk, overrides, injected)
            feed = self._feed(run, injected, counter)
            t = run.totals
            s.history.append({
                "week": run.week,
                "above_safe": round(t["overload_patient_days"] / 7, 1),
                "moved": round(t["moved_patient_days"] / 7, 1),
                "red": t["red_reports"]})
            s.pending = {}
            s.week_idx += 1
            return {"run": {"week": run.week, "state": run.state,
                            "next_week": str((wk + pd.Timedelta(days=7)).date()),
                            "hospitals": run.hospitals, "proposals": run.proposals,
                            "responses": run.responses, "totals": run.totals,
                            "block": run.block},
                    "feed": feed, "injected": injected, **self.status()}

    def _apply_mistakes(self, state: str, wk: pd.Timestamp):
        """Corrupt the chosen reports, then let the Steward judge them afresh."""
        overrides, injected = {}, []
        for hid, key in self.session.pending.items():
            idx = self._by_pk.get(hid)
            if idx is None:
                continue
            series = self._reports.iloc[idx]
            series = series[series["week"] <= wk].copy().reset_index(drop=True)
            if series.empty or series["week"].iloc[-1] != wk:
                continue
            last = series.index[-1]
            u0, b0 = float(series.at[last, "used"]), float(series.at[last, "beds"])
            if not (np.isfinite(u0) and np.isfinite(b0)):
                continue
            u1, b1 = MISTAKES[key][1](u0, b0)
            series.at[last, "used"], series.at[last, "beds"] = u1, b1
            cov = series.at[last, "used_cov"] if series.at[last, "used_cov"] == series.at[last, "used_cov"] else 7
            series.at[last, "used_sum"], series.at[last, "beds_sum"] = u1 * cov, b1 * cov
            v = assess(series).iloc[-1]
            level, flags = str(v["level"]), int(v["flags"])
            o = {"used": u1, "level": level, "flags": flags}
            if level in ("GREEN", "AMBER") and b1 > 0:
                # Not caught: the coordinator believes the report as written.
                o.update({"beds": b1, "pred": u1 / b1, "hi": u1 / b1})
            overrides[hid] = o
            name = nice_name(series.at[last, "name"])
            injected.append({"id": hid, "name": name, "mistake": MISTAKES[key][0],
                             "true_used": round(u0, 1), "true_beds": round(b0, 1),
                             "reported_used": round(u1, 1), "reported_beds": round(b1, 1),
                             "level": level, "reasons": explain(flags)})
        return overrides, injected

    def _without_steward(self, state, wk, overrides, injected) -> list[dict]:
        """What the coordinator would have proposed had it believed the mistake."""
        if not injected:
            return []
        from ..agents.coordinator import RegionalCoordinatorAgent
        believe = {}
        for inj in injected:
            u, b = inj["reported_used"], inj["reported_beds"]
            occ = u / b if b else np.nan
            believe[inj["id"]] = {"used": u, "beds": b, "level": "GREEN", "flags": 0,
                                  "pred": occ, "hi": occ}
        g = self.platform.week_frame(state, wk, believe)
        coord = RegionalCoordinatorAgent(state, self.platform.params)
        ids = g["hospital_pk"].astype(str).to_numpy()
        plan, _ = coord.propose(str(wk.date()), ids, g["name"].astype(str).to_numpy(),
                                g["lat"].to_numpy(float), g["lon"].to_numpy(float),
                                g["pred"].to_numpy(float), g["hi"].to_numpy(float),
                                g["beds"].to_numpy(float), g["can_receive"].to_numpy(bool))
        out = []
        for inj in injected:
            k = int(np.flatnonzero(ids == inj["id"])[0]) if (ids == inj["id"]).any() else -1
            into = float(plan.amount[plan.receivers == k].sum()) if k >= 0 else 0.0
            outof = float(plan.amount[plan.senders == k].sum()) if k >= 0 else 0.0
            room = max(0.0, self.platform.params.theta * inj["true_beds"] - inj["true_used"])
            out.append({"id": inj["id"], "name": inj["name"], "would_receive": round(into, 1),
                        "would_send": round(outof, 1), "real_room": round(room, 1)})
        return out

    # ---------------------------------------------------------------- feed
    def _feed(self, run, injected, counter) -> list[dict]:
        hs = {h["id"]: h for h in run.hospitals}
        n = len(run.hospitals)
        feed = [{"agent": "hospital", "focus": [],
                 "text": f"{n} hospital agents send their weekly reports for the week of {run.week}."}]
        for inj in injected:
            feed.append({"agent": "inject", "focus": [inj["id"]],
                         "text": (f"Mistake injected: {inj['name']} reports {inj['reported_used']:g} "
                                  f"patients and {inj['reported_beds']:g} beds "
                                  f"(really {inj['true_used']:g} and {inj['true_beds']:g}) — "
                                  f"{inj['mistake'].lower()}.")})
        lv = pd.Series([h["level"] for h in run.hospitals]).value_counts()
        feed.append({"agent": "steward", "focus": [],
                     "text": (f"Data Steward checks every report: {lv.get('GREEN', 0)} fine, "
                              f"{lv.get('AMBER', 0)} minor issue, {lv.get('RED', 0)} cannot be right, "
                              f"{lv.get('MISSING', 0)} missing.")})
        inj_ids = {i["id"] for i in injected}
        bad = [h for h in run.hospitals if h["level"] == "RED"]
        bad.sort(key=lambda h: h["id"] not in inj_ids)
        for h in bad[:FEED_LIMIT]:
            why = "; ".join(r["title"] for r in h["reasons"]) or "flagged"
            feed.append({"agent": "steward", "level": "RED", "focus": [h["id"]],
                         "text": f"RED — {h['name']}: {why}. Not used for planning this week."})
        if len(bad) > FEED_LIMIT:
            feed.append({"agent": "steward", "focus": [],
                         "text": f"…and {len(bad) - FEED_LIMIT} more RED reports."})
        for inj in injected:
            if inj["level"] in ("GREEN", "AMBER"):
                feed.append({"agent": "steward", "level": "MISS", "focus": [inj["id"]],
                             "text": (f"The Steward did NOT catch the mistake at {inj['name']} — "
                                      f"it looks plausible, so the report is believed.")})
        over = [h for h in run.hospitals if h["forecast"] is not None and h["forecast"] > 0.9]
        room = [h for h in run.hospitals if h["forecast_hi"] is not None and h["forecast_hi"] < 0.9]
        feed.append({"agent": "forecaster", "focus": [h["id"] for h in over],
                     "text": (f"Forecaster: {len(over)} hospitals are expected above the 90% safe "
                              f"level next week; {len(room)} should have room.")})
        props = sorted(run.proposals, key=lambda p: -p["patients_per_day"])
        if not props:
            feed.append({"agent": "coordinator", "focus": [],
                         "text": "Coordinator: no transfer needed or possible this week."})
        for p in props[:FEED_LIMIT]:
            feed.append({"agent": "coordinator", "focus": [p["from"], p["to"]],
                         "arc": {"from": p["from"], "to": p["to"], "planned": p["patients_per_day"]},
                         "text": (f"Proposal: {p['from_name']} → {p['to_name']}, "
                                  f"{p['patients_per_day']:.1f} patients, {p['km']:.0f} km. {p['why']}")})
        if len(props) > FEED_LIMIT:
            feed.append({"agent": "coordinator", "focus": [],
                         "text": f"…and {len(props) - FEED_LIMIT} more proposals."})
        feed.append({"agent": "clock", "focus": [],
                     "text": "One week later — each hospital checks the proposals against its real numbers."})
        resp = sorted(run.responses, key=lambda r: -r["proposed"])
        for r in resp[:FEED_LIMIT]:
            h = hs.get(r["hospital"], {})
            feed.append({"agent": "hospital", "level": r["verdict"], "focus": [r["hospital"]],
                         "text": f"{h.get('name', r['hospital'])} — {r['verdict']}: {r['why']}."})
        if len(resp) > FEED_LIMIT:
            feed.append({"agent": "hospital", "focus": [],
                         "text": f"…and {len(resp) - FEED_LIMIT} more answers."})
        for p in props:
            if p["executed"] > 0.01:
                feed.append({"agent": "move", "focus": [], "silent": True,
                             "arc": {"from": p["from"], "to": p["to"], "moved": p["executed"]}})
        for c in counter:
            if c["would_receive"] > 0.05:
                feed.append({"agent": "steward", "level": "SAVED", "focus": [c["id"]],
                             "text": (f"Without the Data Steward, the coordinator would have sent "
                                      f"{c['would_receive']:.1f} patients to {c['name']}, which really "
                                      f"had room for {c['real_room']:.1f}.")})
            elif c["would_send"] > 0.05:
                feed.append({"agent": "steward", "level": "SAVED", "focus": [c["id"]],
                             "text": (f"Without the Data Steward, the coordinator would have moved "
                                      f"{c['would_send']:.1f} patients out of {c['name']} on a false alarm.")})
            else:
                feed.append({"agent": "steward", "focus": [c["id"]],
                             "text": (f"Had the mistake at {c['name']} been believed, it would not have "
                                      f"changed this week's plan.")})
        t = run.totals
        feed.append({"agent": "ledger", "focus": [],
                     "text": (f"Week sealed in the audit log as block #{run.block['index']} "
                              f"({run.block['entries']} messages) · fingerprint "
                              f"{run.block['hash'][:16]}…")})
        feed.append({"agent": "summary", "focus": [],
                     "text": (f"Result: {t['overload_patient_days'] / 7:.0f} patients above the safe level "
                              f"next week; {t['moved_patient_days'] / 7:.0f} could be moved to hospitals "
                              f"with real room"
                              + (f" ({t['share_absorbed']:.0%})." if t["share_absorbed"] is not None else "."))})
        return feed

    # ---------------------------------------------------------------- ledger
    def _ledger_status(self) -> dict:
        v = self.session.ledger.verify()
        return {"ok": v["ok"], "blocks": v["blocks"], "first_bad_block": v.get("first_bad_block"),
                "head": v.get("head")}

    def tamper(self) -> dict:
        led = self.session.ledger
        if not led.blocks:
            raise ValueError("nothing in the log yet -- run a week first")
        b = led.blocks[len(led.blocks) // 2]
        for e in b.entries:
            if e.get("kind") == "REPORT" and e["body"].get("used"):
                before = e["body"]["used"]
                e["body"]["used"] = round(before * 0.5, 1)
                return {"block": b.index, "week": b.label, "hospital": e["sender"],
                        "before": before, "after": e["body"]["used"], **self.status()}
        raise ValueError("no report to change")


_KEEP_UPPER = {"HCA", "CHI", "UT", "MD", "UMC", "LLC", "LP", "VA", "UCSF", "UCLA", "NYU",
               "OSF", "SSM", "AHMC", "II", "III", "IV", "UPMC", "UAB", "UNC", "OU", "SCL",
               "ECU", "MUSC", "UVA", "UH", "JPS", "CHRISTUS", "TMC"}


def nice_name(name) -> str:
    """'ST LUKE'S HEALTH - BAYLOR' -> "St Luke's Health - Baylor" (keeps known acronyms)."""
    words = []
    for w in str(name).split(" "):
        if w.upper() in _KEEP_UPPER or (len(w) <= 3 and w.upper() not in ("ST", "MT", "FT", "DR")
                                        and w.isalpha()
                                        and not any(c in "AEIOUY" for c in w.upper())):
            words.append(w.upper() if w.upper() != "CHRISTUS" else "Christus")
        else:
            words.append("-".join(p[:1].upper() + p[1:].lower() for p in w.split("-")))
    return " ".join(words)


def _f(v, nd: int = 4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)
