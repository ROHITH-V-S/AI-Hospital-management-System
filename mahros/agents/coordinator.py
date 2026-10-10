"""RegionalCoordinatorAgent: one per state. Proposes; never commands.

Uses the same optimiser as the experiments (``mahros.coordination``) and turns
each proposed transfer into a sentence a duty officer can check:

    "Send 4.0 patients/day from A (forecast 97%, safe level 90%) to B
     (forecast 78%, at most 83%), 31 km away."
"""

from __future__ import annotations

import numpy as np

from ..coordination import Params, send_capacity, solve_lp, spare_capacity
from .messages import Message


class RegionalCoordinatorAgent:
    def __init__(self, state: str, params: Params) -> None:
        self.state = state
        self.params = params

    @property
    def address(self) -> str:
        return f"coordinator:{self.state}"

    def propose(self, week: str, ids, names, lat, lon, pred, hi, beds, can_receive):
        """Return the plan arcs and one PROPOSAL message per arc."""
        prm = self.params
        cap = send_capacity(pred, beds, prm)
        spare = spare_capacity(hi, beds, can_receive, prm)
        plan = solve_lp(lat, lon, cap, spare, prm)
        msgs = []
        for k in range(len(plan.amount)):
            i, j = plan.senders[k], plan.receivers[k]
            why = (f"{names[i]} is forecast at {pred[i]:.0%} (safe level "
                   f"{prm.theta:.0%}); {names[j]} is forecast at {pred[j]:.0%} and "
                   f"at most {hi[j]:.0%}; {plan.distance_km[k]:.0f} km apart.")
            msgs.append(Message("PROPOSAL", self.address,
                                f"hospital:{ids[i]}->hospital:{ids[j]}", week,
                                {"from": str(ids[i]), "to": str(ids[j]),
                                 "patients_per_day": round(float(plan.amount[k]), 2),
                                 "km": round(float(plan.distance_km[k]), 1),
                                 "why": why}))
        return plan, msgs

    @staticmethod
    def senders_and_receivers(plan, n):
        out_amt = np.bincount(plan.senders, plan.amount, minlength=n)
        in_amt = np.bincount(plan.receivers, plan.amount, minlength=n)
        return out_amt, in_amt
