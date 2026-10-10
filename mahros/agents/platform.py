"""The weekly cycle, run by the agents, written to the audit ledger.

For one state and one week:

  1. REPORT     every hospital agent submits its numbers
  2. VERDICT    the Data Steward judges each report and says why
  3. FORECAST   the Forecast agent predicts next week, with a 90% range
  4. PROPOSAL   the state coordinator proposes transfers, each with a reason
  5. RESPONSE   when the week arrives, each hospital accepts what its real
                numbers allow -- senders first, then receivers
  6. OUTCOME    totals; the week's messages are sealed into one ledger block

The numbers this produces are pinned equal to the fast path used in the
experiments (``tests/test_agents.py``), so what the dashboard shows is what the
paper reports.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

from ..coordination import Params
from ..coordination.frames import arm_frame, base_frame
from ..ledger.chain import AuditLedger
from ..trust import explain
from .coordinator import RegionalCoordinatorAgent
from .hospital import HospitalAgent
from .messages import Message


@dataclass
class WeekRun:
    state: str
    week: str
    hospitals: list[dict]
    proposals: list[dict]
    responses: list[dict]
    totals: dict
    block: dict


class Platform:
    def __init__(self, reports: pd.DataFrame, forecasts: pd.DataFrame,
                 params: Params | None = None, first=None, last=None) -> None:
        """``reports``: canonical frame with trust columns (``pipeline.assessed``)."""
        self.params = params or Params()
        kw = {k: v for k, v in (("first", first), ("last", last)) if v is not None}
        self.base = base_frame(reports, **kw)
        self.forecasts = forecasts
        # Verdicts are the Data Steward's rules, already applied to `reports`
        # (mahros.pipeline.assessed); forecasts are the Forecast agent's output.
        self.frame = arm_frame(self.base, forecasts, "mahros")
        self.ledger = AuditLedger()
        self._raw = reports.set_index(["hospital_pk", "week"])

    def weeks(self) -> list[pd.Timestamp]:
        return sorted(self.frame["week"].unique())

    def states(self) -> list[str]:
        return sorted(self.frame["state"].dropna().unique())

    def run_week(self, state: str, week) -> WeekRun:
        week = pd.Timestamp(week)
        wk = str(week.date())
        g = self.frame[(self.frame["state"] == state) & (self.frame["week"] == week)]
        g = g.reset_index(drop=True)
        prm = self.params
        agents = [HospitalAgent(str(r.hospital_pk), str(r.name), state,
                                float(r.lat), float(r.lon)) for r in g.itertuples()]
        msgs: list[Message] = []

        # 1-3. Reports, verdicts, forecasts.
        hospitals = []
        for a, r in zip(agents, g.itertuples()):
            raw = self._raw.loc[(r.hospital_pk, week)]
            msgs.append(a.report(wk, raw.to_dict()))
            reasons = explain(int(r.flags))
            msgs.append(Message("VERDICT", "steward", "coordinator", wk,
                                {"hospital": a.hospital_id, "level": r.level,
                                 "reasons": [x["title"] for x in reasons]}))
            msgs.append(Message("FORECAST", "forecaster", "coordinator", wk,
                                {"hospital": a.hospital_id,
                                 "occupancy": _r(r.pred), "upper_90": _r(r.hi)}))
            hospitals.append({
                "id": a.hospital_id, "name": a.name, "city": r.city,
                "lat": a.lat, "lon": a.lon,
                "level": r.level, "reasons": reasons,
                "beds": _r(r.beds, 1), "used": _r(r.used, 1),
                "occupancy_now": _r(r.used / r.beds if r.beds else np.nan),
                "forecast": _r(r.pred), "forecast_hi": _r(r.hi),
                "used_next": _r(r.used_next, 1), "beds_next": _r(r.beds_next, 1),
                "trusted_next": bool(r.trusted_next),
            })

        # 4. Proposals.
        coord = RegionalCoordinatorAgent(state, prm)
        names = g["name"].astype(str).to_numpy()
        ids = g["hospital_pk"].astype(str).to_numpy()
        plan, proposals = coord.propose(
            wk, ids, names, g["lat"].to_numpy(float), g["lon"].to_numpy(float),
            g["pred"].to_numpy(float), g["hi"].to_numpy(float),
            g["beds"].to_numpy(float), g["can_receive"].to_numpy(bool))
        msgs.extend(proposals)

        # 5. Responses: senders first, then receivers on what actually comes.
        n = len(g)
        used_n = g["used_next"].to_numpy(float)
        beds_n = g["beds_next"].to_numpy(float)
        trusted_n = g["trusted_next"].to_numpy(bool)
        out_amt = np.bincount(plan.senders, plan.amount, minlength=n) if len(plan.amount) else np.zeros(n)
        f_send = np.zeros(n)
        responses = []
        for i in np.flatnonzero(out_amt > 0):
            acc, m = agents[i].respond(wk, "send", out_amt[i], used_n[i], beds_n[i],
                                       prm.theta, trusted_n[i])
            f_send[i] = acc / out_amt[i]
            msgs.append(m)
            responses.append({"hospital": ids[i], **m.body})
        after_send = plan.amount * f_send[plan.senders] if len(plan.amount) else np.zeros(0)
        in_amt = np.bincount(plan.receivers, after_send, minlength=n) if len(plan.amount) else np.zeros(n)
        f_recv = np.zeros(n)
        for j in np.flatnonzero(in_amt > 0):
            acc, m = agents[j].respond(wk, "receive", in_amt[j], used_n[j], beds_n[j],
                                       prm.theta, trusted_n[j])
            f_recv[j] = acc / in_amt[j]
            msgs.append(m)
            responses.append({"hospital": ids[j], **m.body})
        executed = after_send * f_recv[plan.receivers] if len(plan.amount) else np.zeros(0)

        props = []
        for k, m in enumerate(proposals):
            props.append({**m.body, "from_name": names[plan.senders[k]],
                          "to_name": names[plan.receivers[k]],
                          "executed": round(float(executed[k]), 2)})

        over = np.where(trusted_n, np.nan_to_num(np.maximum(0, used_n - prm.theta * beds_n)), 0)
        totals = {
            "hospitals": n,
            "red_reports": int((g["level"] == "RED").sum()),
            "missing_reports": int((g["level"] == "MISSING").sum()),
            "overload_patient_days": round(7 * float(over.sum()), 1),
            "planned_patient_days": round(7 * float(plan.amount.sum()), 1),
            "moved_patient_days": round(7 * float(executed.sum()), 1),
            "share_absorbed": (round(float(executed.sum() / over.sum()), 4)
                               if over.sum() > 0 else None),
        }
        msgs.append(Message("OUTCOME", f"coordinator:{state}", "ledger", wk, totals))

        for m in msgs:
            self.ledger.append(m.entry())
        block = self.ledger.seal(f"{state} {wk}")
        return WeekRun(state, wk, hospitals, props, responses, totals,
                       {"index": block.index, "hash": block.hash,
                        "prev_hash": block.prev_hash, "entries": len(block.entries)})


def _r(v, nd: int = 4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)
