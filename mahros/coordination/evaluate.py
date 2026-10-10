"""Plan one week, then check it against what actually happened the week after.

This is the shared core that both the RQ3 experiment and the live platform
call, so the numbers in the paper and the plans on screen come from the same
code.

Inputs for a decision week, one row per hospital
------------------------------------------------
state, lat, lon         where the hospital is
pred, hi                forecast occupancy for next week (point, 90% upper)
beds                    staffed beds the coordinator believes it has
can_receive             False if the Data Steward does not trust its report
used_next, beds_next    what the hospital actually reported the next week
trusted_next            whether that next report is trusted (GREEN/AMBER)

Everything about next week is used **only** to score the plan, never to make
it -- except in the ``oracle`` arm, which exists to show the ceiling.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
import pandas as pd

from .planner import (Params, execute, overload, send_capacity, solve_greedy,
                      solve_lp, spare_capacity)

SOLVERS = {"lp": solve_lp, "greedy": solve_greedy}


@dataclass
class WeekResult:
    week: pd.Timestamp
    overload: float = 0.0          # average census above safe level, next week
    planned: float = 0.0           # average census the plan proposed to move
    executed: float = 0.0          # what hospitals could actually move
    unverifiable: float = 0.0      # planned onto hospitals with untrusted next reports
    overfill_if_blind: float = 0.0 # receivers pushed over safe level had nobody checked
    arcs: int = 0
    km_weighted: float = 0.0       # sum of executed * distance
    transfers: list[dict] = field(default_factory=list)
    by_state: dict = field(default_factory=dict)   # state -> [overload, executed]


def plan_week(frame: pd.DataFrame, prm: Params, solver: str = "lp",
              keep_arcs: bool = False) -> WeekResult:
    """Plan per state, execute against next week's reports, and total up."""
    res = WeekResult(week=frame["week"].iloc[0] if len(frame) else pd.NaT)
    solve = SOLVERS[solver]
    for state, g in frame.groupby("state", sort=True):
        lat, lon = g["lat"].to_numpy(float), g["lon"].to_numpy(float)
        beds = g["beds"].to_numpy(float)
        cap = send_capacity(g["pred"].to_numpy(float), beds, prm)
        spare = spare_capacity(g["hi"].to_numpy(float), beds,
                               g["can_receive"].to_numpy(bool), prm)
        used_n = g["used_next"].to_numpy(float)
        beds_n = g["beds_next"].to_numpy(float)
        trusted_n = g["trusted_next"].to_numpy(bool)
        ov = overload(used_n, beds_n, trusted_n, prm)
        res.overload += ov
        res.by_state[state] = [ov, 0.0]
        plan = solve(lat, lon, cap, spare, prm)
        if len(plan.amount) == 0:
            continue
        ex = execute(plan, used_n, beds_n, trusted_n, prm)
        res.by_state[state][1] = float(ex.executed.sum())
        res.planned += float(plan.amount.sum())
        res.executed += float(ex.executed.sum())
        res.unverifiable += float(plan.amount[ex.unverifiable].sum())
        res.arcs += int(len(plan.amount))
        res.km_weighted += float((ex.executed * plan.distance_km).sum())
        # What would have happened if receivers took the full plan unchecked.
        into = np.bincount(plan.receivers, plan.amount, minlength=len(g))
        ok = trusted_n
        over_after = np.maximum(0, used_n + into - prm.theta * beds_n)
        over_before = np.maximum(0, used_n - prm.theta * beds_n)
        res.overfill_if_blind += float(np.nansum(np.where(ok, over_after - over_before, 0)))
        if keep_arcs:
            ids = g["hospital_pk"].to_numpy()
            for k in range(len(plan.amount)):
                res.transfers.append({
                    "state": state, "from": ids[plan.senders[k]],
                    "to": ids[plan.receivers[k]],
                    "planned": float(plan.amount[k]),
                    "executed": float(ex.executed[k]),
                    "km": float(plan.distance_km[k]),
                    "sender_factor": float(ex.sender_factor[k]),
                    "receiver_factor": float(ex.receiver_factor[k]),
                    "unverifiable": bool(ex.unverifiable[k]),
                })
    return res


def by_state(weeks: list[WeekResult]) -> dict:
    """Overload and absorbed patient-days per state, summed over weeks."""
    tot: dict[str, list[float]] = {}
    for w in weeks:
        for st, (ov, ex) in w.by_state.items():
            t = tot.setdefault(st, [0.0, 0.0])
            t[0] += ov
            t[1] += ex
    return {st: {"overload_patient_days": 7 * ov, "absorbed_patient_days": 7 * ex,
                 "share_absorbed": ex / ov if ov else None}
            for st, (ov, ex) in sorted(tot.items())}


def summarise(weeks: list[WeekResult]) -> dict:
    ov = sum(w.overload for w in weeks)
    ex = sum(w.executed for w in weeks)
    pl = sum(w.planned for w in weeks)
    return {
        "weeks": len(weeks),
        "overload_patient_days": 7 * ov,
        "absorbed_patient_days": 7 * ex,
        "share_of_overload_absorbed": ex / ov if ov else 0.0,
        "planned_patient_days": 7 * pl,
        "plan_realised": ex / pl if pl else None,
        "unverifiable_patient_days": 7 * sum(w.unverifiable for w in weeks),
        "overfill_if_unchecked_patient_days": 7 * sum(w.overfill_if_blind for w in weeks),
        "mean_km_per_moved_patient": (sum(w.km_weighted for w in weeks) / ex) if ex else None,
        "arcs": sum(w.arcs for w in weeks),
    }
