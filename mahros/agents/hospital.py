"""HospitalAgent: reports its own numbers, and decides for itself.

The coordinator's plan is built on *forecasts*. Only the hospital knows what
actually happened when the week arrives. So the hospital agent has the last
word, and its rule is simple and safe:

* As a **sender**: send no more than I am really above the safe level.
* As a **receiver**: take no more than I really have room for below it.

A hospital never ends a week pushed over the safe level by the plan.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from .messages import Message


@dataclass
class HospitalAgent:
    hospital_id: str
    name: str
    state: str
    lat: float
    lon: float

    @property
    def address(self) -> str:
        return f"hospital:{self.hospital_id}"

    def report(self, week: str, row: dict) -> Message:
        body = {k: _num(row.get(k)) for k in ("used", "beds", "icu_used", "icu_beds")}
        return Message("REPORT", self.address, "steward", week, body)

    @staticmethod
    def room(used: float, beds: float, theta: float) -> float:
        if not (math.isfinite(used) and math.isfinite(beds)):
            return 0.0
        return max(0.0, theta * beds - used)

    @staticmethod
    def excess(used: float, beds: float, theta: float) -> float:
        if not (math.isfinite(used) and math.isfinite(beds)):
            return 0.0
        return max(0.0, used - theta * beds)

    def respond(self, week: str, role: str, proposed: float, used: float, beds: float,
                theta: float, trusted: bool) -> tuple[float, Message]:
        """Accept, part-accept or decline a proposal using this week's real numbers."""
        if not trusted:
            accepted, why = 0.0, ("my report this week could not be verified, so "
                                  "nothing is moved on my account")
        elif role == "send":
            real = self.excess(used, beds, theta)
            accepted = min(proposed, real)
            why = (f"I am {real:.1f} patients above the safe level; sending "
                   f"{accepted:.1f} of the {proposed:.1f} proposed")
        else:
            real = self.room(used, beds, theta)
            accepted = min(proposed, real)
            why = (f"I have room for {real:.1f} below the safe level; accepting "
                   f"{accepted:.1f} of the {proposed:.1f} proposed")
        verdict = ("ACCEPT" if accepted >= proposed - 1e-9 and proposed > 0
                   else "PARTIAL" if accepted > 1e-9 else "DECLINE")
        msg = Message("RESPONSE", self.address, "coordinator", week,
                      {"role": role, "proposed": round(proposed, 2),
                       "accepted": round(accepted, 2), "verdict": verdict, "why": why})
        return accepted, msg


def _num(v):
    try:
        f = float(v)
        return None if math.isnan(f) else round(f, 2)
    except (TypeError, ValueError):
        return None
