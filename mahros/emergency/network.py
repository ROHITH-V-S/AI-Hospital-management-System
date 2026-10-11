"""The real hospitals of one state for one week: who they are, what they can do,
how far apart they are by road, and what they reported.

Everything here is observed (HHS weekly report, CMS POS capability, OSRM road
times, HHS state staffing series) except where a field says ``estimated``.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from ..calibration.capability import (cath_lab_rooms, load_state_capability, onsite)

DATA = Path(__file__).resolve().parents[1] / "calibration" / "data"
STATES = {"AZ": "Arizona", "MA": "Massachusetts"}

#: POS field -> capability name (on-site codes 1/3 only; see calibration.capability).
POS_CAPS = {
    "cath_lab": "CRDC_CTHRTZTN_LAB_SRVC_CD",
    "cardiac_surgery": "OPEN_HRT_SRGRY_SRVC_CD",
    "neurosurgery": "NRSRGCL_SRVC_CD",
    "trauma": "SHCK_TRMA_SRVC_CD",
    "burns": "BURN_CARE_UNIT_SRVC_CD",
    "picu": "PED_ICU_SRVC_CD",
    "icu": "ICU_SRVC_CD",
}

#: What each need requires of a hospital (capability flags, all must be true).
REQUIRES = {
    "icu": ("icu",),
    "ventilator": ("icu",),
    "cath_lab": ("cath_lab", "icu"),
    "trauma": ("trauma", "icu"),
    "neurosurgery": ("neurosurgery", "icu"),
    "picu": ("picu",),
    "burns": ("burns", "icu"),
}


@dataclass
class Site:
    """Public facts about one hospital (what the coordinator may know)."""
    pk: str
    ccn: str
    name: str
    city: str
    lat: float
    lon: float
    caps: dict                       # capability -> bool
    cap_source: str                  # "CMS POS Q32022" or "HHS beds only (not in POS)"
    cath_rooms: int
    # This week's REAL report (observed); None if not reported.
    beds: float | None = None
    used: float | None = None
    icu_beds: float | None = None
    icu_used: float | None = None
    picu_beds: float | None = None
    picu_used: float | None = None
    ed_visits_week: float | None = None
    ed_source: str = "this week's report"
    level: str = "MISSING"           # Data Steward verdict on this week's report
    reasons: list = field(default_factory=list)

    def can_treat(self, need: str) -> bool:
        return all(self.caps.get(c, False) for c in REQUIRES[need])

    @property
    def icu_occ(self) -> float | None:
        if self.icu_beds and self.icu_used is not None and self.icu_beds > 0:
            return self.icu_used / self.icu_beds
        return None


@dataclass
class Network:
    state: str
    week: pd.Timestamp
    sites: list[Site]
    minutes: np.ndarray              # road minutes (OSRM, free-flow), sites x sites
    km: np.ndarray
    staffing_share: float | None     # REAL share of the state's hospitals short-staffed this week
    staffing_source: str = ""
    staffing_answered: int = 0       # hospital-days with a yes/no answer that week
    staffing_silent: int = 0         # hospital-days with "not reported"

    def index(self, pk: str) -> int:
        return next(i for i, s in enumerate(self.sites) if s.pk == pk)


def _load(name: str) -> dict:
    return json.loads((DATA / name).read_text(encoding="utf-8"))


def build(state: str, week, reports: pd.DataFrame, staffing: pd.DataFrame | None = None) -> Network:
    """``reports``: assessed frame (any source) incl. extra fields; ``staffing``: state series."""
    week = pd.Timestamp(week)
    net = _load(f"us_{state.lower()}_network.json")
    routes = _load(f"us_{state.lower()}_routes.json")
    cap = load_state_capability(state) or {"facilities": {}, "source": {}}
    pos_label = cap["source"].get("label", "CMS POS")
    assert routes["hospital_pks"] == [h["hospital_pk"] for h in net["hospitals"]]
    wk = reports[(reports["week"] == week) & (reports["state"] == state)].set_index("hospital_pk")
    ed_fallback = _ed_carry_forward(reports, state, week)
    sites = []
    for h in net["hospitals"]:
        row = cap["facilities"].get(h["ccn"])
        r = wk.loc[h["hospital_pk"]] if h["hospital_pk"] in wk.index else None
        g = (lambda k: _num(r.get(k)) if r is not None else None)
        if row:
            caps = {k: onsite(row, f) for k, f in POS_CAPS.items()}
            src, rooms = pos_label, cath_lab_rooms(row)
        else:
            caps = {k: False for k in POS_CAPS}
            src, rooms = "HHS beds only (not in CMS POS)", 0
        # Observed HHS beds also prove a unit exists.
        if (g("icu_beds") or 0) > 0:
            caps["icu"] = True
        if (g("picu_beds") or 0) > 0:
            caps["picu"] = True
        sites.append(Site(
            pk=h["hospital_pk"], ccn=h["ccn"], name=h["name"], city=h.get("city") or "",
            lat=h["lat"], lon=h["lon"], caps=caps, cap_source=src, cath_rooms=rooms,
            beds=g("beds"), used=g("used"), icu_beds=g("icu_beds"), icu_used=g("icu_used"),
            picu_beds=g("picu_beds"), picu_used=g("picu_used"),
            ed_visits_week=g("ed_visits") if g("ed_visits") else ed_fallback.get(h["hospital_pk"], (None, ""))[0],
            ed_source="this week's report" if g("ed_visits") else
                      ed_fallback.get(h["hospital_pk"], (None, "no ED visits ever reported"))[1],
            level=str(r["level"]) if r is not None else "MISSING",
            reasons=_reasons(int(r["flags"])) if r is not None else ["NOT_REPORTED"]))
    minutes = np.array(routes["durations_seconds"], float) / 60.0
    km = np.array(routes["distances_metres"], float) / 1000.0
    share, src = None, "not available"
    if staffing is not None and len(staffing):
        s = staffing[(staffing["state"] == state) & (staffing["date"] >= week)
                     & (staffing["date"] < week + pd.Timedelta(days=7))]
        yes, no = s["shortage_today_yes"].sum(), s["shortage_today_no"].sum()
        silent = s["shortage_today_not_reported"].sum()
        if yes + no > 0:
            share, src = float(yes / (yes + no)), "HHS g62h-syeh (real, state level)"
        days = max(1, s["date"].nunique())
        return Network(state, week, sites, minutes, km, share, src,
                       int(round((yes + no) / days)), int(round(silent / days)))
    return Network(state, week, sites, minutes, km, share, src)


def _ed_carry_forward(reports: pd.DataFrame, state: str, week: pd.Timestamp) -> dict:
    """Median of a hospital's last 8 reported weekly ED-visit totals up to ``week``.

    Why: CDC made the ED-visit fields OPTIONAL from 2023-06-11 (NHSN COVID
    hospital reporting guidance, data elements 19-20), and many hospitals
    stopped sending them (Massachusetts: almost all). ED volume only sets how
    often transfer requests arise in the simulation, so the hospital's own
    recent volume is used, and labelled with its date.
    """
    d = reports[(reports["state"] == state) & (reports["week"] <= week)
                & reports["ed_visits"].notna() & (reports["ed_visits"] > 0)]
    out = {}
    for pk, g in d.groupby("hospital_pk"):
        g = g.sort_values("week").tail(8)
        out[pk] = (float(g["ed_visits"].median()),
                   f"carried forward: median of its last {len(g)} reports, up to week of "
                   f"{g['week'].iloc[-1].date()} (ED reporting optional since 2023-06-11)")
    return out


def _reasons(flags: int) -> list[str]:
    from ..trust import BIT
    return [c for c, b in BIT.items() if flags & b]


def _num(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f
