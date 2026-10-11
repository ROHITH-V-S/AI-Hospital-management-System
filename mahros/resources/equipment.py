"""Equipment: an inventory the STATE ENTERS (no public per-hospital data exists).

The table is seeded once with clearly labelled estimates so the demo has
something to show; a presenter can edit any count on screen. Nothing in the
research results rests on equipment. Every ratio below is an assumption.
"""

from __future__ import annotations

import math

#: item -> label, seed rule (from usual staffed beds), use rule (from this week's census)
ITEMS = {
    "ventilator": {"label": "Ventilators",
                   "seed": "1 per usual staffed ICU bed",
                   "use": "40% of ICU patients (assumption)"},
    "ecmo": {"label": "ECMO machines",
             "seed": "2 at hospitals with cardiac surgery (CMS) or >= 50 ICU beds, else 0",
             "use": "2% of ICU patients, at hospitals that have ECMO (assumption)"},
    "dialysis": {"label": "Dialysis machines (ICU)",
                 "seed": "1 per 6 usual ICU beds",
                 "use": "10% of ICU patients (assumption)"},
    "monitor": {"label": "Portable monitors",
                "seed": "1 per 10 usual staffed beds",
                "use": "1 per 12 inpatients (assumption)"},
}
SURGE_BUFFER = 1.15        # hospitals in a warned area plan for 15% more (assumption)
KEEP_SPARE = 1             # a lender always keeps one spare unit


def seed(icu_usual: float, beds_usual: float, cardiac: bool) -> dict:
    icu = max(0.0, icu_usual or 0.0)
    beds = max(0.0, beds_usual or 0.0)
    return {"ventilator": int(round(icu)),
            "ecmo": 2 if (cardiac or icu >= 50) else 0,
            "dialysis": int(round(icu / 6)),
            "monitor": int(round(beds / 10))}


def need(item: str, icu_used: float, used: float, has_item: bool) -> float:
    icu = max(0.0, icu_used or 0.0)
    if item == "ventilator":
        return 0.40 * icu
    if item == "ecmo":
        return 0.02 * icu if has_item else 0.0
    if item == "dialysis":
        return 0.10 * icu
    if item == "monitor":
        return max(0.0, used or 0.0) / 12
    raise ValueError(item)


def shortfall_surplus(units: int, needed: float, warned: bool) -> tuple[int, int]:
    n = math.ceil(needed * (SURGE_BUFFER if warned else 1.0) - 1e-9)
    return max(0, n - units), max(0, units - n - KEEP_SPARE)
