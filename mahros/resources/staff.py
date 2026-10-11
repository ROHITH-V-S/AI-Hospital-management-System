"""Staff: per-hospital nurse and physician pools (ESTIMATED) and the shortfall this week.

No public dataset reports staff per hospital. So the pool is estimated from the
hospital's own usual staffed beds and published ratios, and labelled
``estimated`` everywhere:

* nurses: ICU 1 nurse : 2 patients, ward 1 : 5 (California Code of
  Regulations, Title 22, §70217 -- the only US state with mandated ratios).
* intensivists 1 : 14 ICU patients (Ward et al., Crit Care Med 2013: ratios
  worse than 1:14 were linked to harm in academic ICUs; the task force did not
  set a fixed maximum). Ward physicians 1 : 15 (assumption).

Pool  = what the hospital's USUAL staffed beds need (median of its previous
        12 trusted weeks), i.e. the staff it normally has.
Need  = what THIS week's patients need at the same ratios.
Gap   = need - pool  (> 0: short of staff this week).

Validated only in DIRECTION against the real state-level series of hospitals
reporting a critical staffing shortage (``experiments/staffing_check.py``).
"""

from __future__ import annotations

import numpy as np
import pandas as pd

NURSE_ICU, NURSE_WARD = 2.0, 5.0
DOC_ICU, DOC_WARD = 14.0, 15.0
USUAL_WEEKS = 12


def _staff(icu: pd.Series, ward: pd.Series):
    nurses = np.ceil(icu.clip(lower=0) / NURSE_ICU) + np.ceil(ward.clip(lower=0) / NURSE_WARD)
    docs = np.ceil(icu.clip(lower=0) / DOC_ICU) + np.ceil(ward.clip(lower=0) / DOC_WARD)
    return nurses, docs


def pools(df: pd.DataFrame) -> pd.DataFrame:
    """One row per trusted hospital-week: pool, need and gap (nurses and physicians per shift)."""
    d = df[["hospital_pk", "week", "state", "level", "beds", "used", "icu_beds", "icu_used"]].copy()
    d = d.sort_values(["hospital_pk", "week"])
    ok = d["level"].isin(["GREEN", "AMBER"]) & d["beds"].notna() & d["used"].notna()
    icu_b = d["icu_beds"].fillna(0).where(ok)
    ward_b = (d["beds"] - d["icu_beds"].fillna(0)).where(ok)
    g = d.assign(icu_b=icu_b, ward_b=ward_b).groupby("hospital_pk")
    # Usual beds: median of the PREVIOUS 12 trusted weeks (causal; this week excluded).
    usual_icu = g["icu_b"].transform(lambda s: s.shift(1).rolling(USUAL_WEEKS, min_periods=4).median())
    usual_ward = g["ward_b"].transform(lambda s: s.shift(1).rolling(USUAL_WEEKS, min_periods=4).median())
    pool_n, pool_d = _staff(usual_icu, usual_ward)
    icu_u = d["icu_used"].fillna(0).where(ok)
    ward_u = (d["used"] - d["icu_used"].fillna(0)).where(ok)
    need_n, need_d = _staff(icu_u, ward_u)
    out = d[["hospital_pk", "week", "state"]].copy()
    out["nurses_per_shift"] = pool_n
    out["nurses_needed"] = need_n
    out["physicians_per_shift"] = pool_d
    out["physicians_needed"] = need_d
    out["nurse_gap"] = need_n - pool_n
    keep = ok & usual_icu.notna() & usual_ward.notna()
    return out[keep.to_numpy()].reset_index(drop=True)
