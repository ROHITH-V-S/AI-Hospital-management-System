"""Neighbourhood surge signals, built only from real weekly reports.

A *neighbourhood* is a hospital plus every hospital within ``RADIUS_KM``
(straight line). For each neighbourhood and week:

  area_occ             patients / staffed beds over trusted reports (GREEN/AMBER)
  area_occ_d1, _d2     change in area occupancy over 1 and 2 weeks (points)
  area_icu_occ         same for adult ICU
  covid_adm_growth     log growth of new COVID-19 admissions vs the week before
  flu_adm_growth       log growth of new influenza admissions
  ed_growth            log growth of emergency-department visits (often missing
                       after 2023-06-11, when CDC made ED reporting optional)
  rising_neighbours    hospitals in the area whose occupancy rose >= 3 points
                       over 2 weeks
  rising_share         that count / hospitals in the area

Everything is causal: week t uses weeks <= t. CDC-withheld small counts (a true
value of 1-3) enter area admission totals as 2 (stated, derived).

Target (for the model and the scoring): ``exceed_1_2`` = the area's
occupancy reaches ``THRESHOLD`` at t+1 or t+2. Used ONLY for training and
scoring, never as an input.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

RADIUS_KM = 50.0
THRESHOLD = 0.85
RISE_PTS = 0.03
WITHHELD_VALUE = 2.0
SUBTYPES = ("Short Term", "Critical Access Hospitals")

FEATURES = ["area_occ", "area_occ_d1", "area_occ_d2", "area_icu_occ", "area_icu_d1",
            "covid_adm_growth", "flu_adm_growth", "ed_growth", "covid_adm_per_100beds",
            "flu_adm_per_100beds", "rising_share", "rising_neighbours", "log_area_beds",
            "n_neighbours", "woy_sin", "woy_cos"]


def neighbours(info: pd.DataFrame, radius_km: float = RADIUS_KM) -> list[np.ndarray]:
    """For each hospital (row of ``info`` with lat/lon), indices of hospitals within radius."""
    from sklearn.neighbors import BallTree
    X = np.radians(info[["lat", "lon"]].to_numpy(float))
    tree = BallTree(X, metric="haversine")
    return list(tree.query_radius(X, r=radius_km / 6371.0))


def panel(df: pd.DataFrame) -> dict:
    """Week x hospital matrices of the inputs (trusted values only)."""
    d = df[df["subtype"].isin(SUBTYPES) & df["lat"].notna()].copy()
    ok = d["level"].isin(["GREEN", "AMBER"])
    for c in ("used", "beds", "icu_used", "icu_beds"):
        d[c] = d[c].where(ok)
    for c in ("covid_adm_adult", "covid_adm_peds", "flu_adm", "ed_visits"):
        sup = d.get(f"{c}_suppressed")
        if sup is not None:
            d[c] = d[c].where(~sup.fillna(False).astype(bool), WITHHELD_VALUE)
    d["covid_adm"] = d["covid_adm_adult"].fillna(0) + d["covid_adm_peds"].fillna(0)
    d.loc[d["covid_adm_adult"].isna() & d["covid_adm_peds"].isna(), "covid_adm"] = np.nan
    info = d.sort_values("week").groupby("hospital_pk")[["state", "lat", "lon", "name", "city"]].last()
    weeks = pd.DatetimeIndex(sorted(d["week"].unique()))
    piv = lambda c: d.pivot_table(index="week", columns="hospital_pk", values=c, aggfunc="first") \
        .reindex(index=weeks, columns=info.index)
    return {"weeks": weeks, "info": info,
            **{c: piv(c) for c in ("used", "beds", "icu_used", "icu_beds", "covid_adm", "flu_adm",
                                   "ed_visits")}}


def _area_sum(M: np.ndarray, nb: list[np.ndarray]) -> np.ndarray:
    """Sum over each neighbourhood, ignoring NaN; NaN when nobody reported."""
    out = np.full((M.shape[0], len(nb)), np.nan)
    have = ~np.isnan(M)
    Z = np.where(have, M, 0.0)
    for j, idx in enumerate(nb):
        s = Z[:, idx].sum(1)
        n = have[:, idx].sum(1)
        out[:, j] = np.where(n > 0, s, np.nan)
    return out


def _growth(A: np.ndarray) -> np.ndarray:
    g = np.full_like(A, np.nan)
    g[1:] = np.log((A[1:] + 1.0) / (A[:-1] + 1.0))
    return g


def build(df: pd.DataFrame, radius_km: float = RADIUS_KM, threshold: float = THRESHOLD) -> pd.DataFrame:
    """One row per (hospital-centred neighbourhood, week) with features and target."""
    P = panel(df)
    info, weeks = P["info"], P["weeks"]
    nb = neighbours(info, radius_km)
    used, beds = P["used"].to_numpy(float), P["beds"].to_numpy(float)
    # Occupancy sums only over hospitals that reported BOTH numbers.
    both = ~np.isnan(used) & ~np.isnan(beds)
    U = _area_sum(np.where(both, used, np.nan), nb)
    B = _area_sum(np.where(both, beds, np.nan), nb)
    occ = U / np.where(B > 0, B, np.nan)
    iu, ib = P["icu_used"].to_numpy(float), P["icu_beds"].to_numpy(float)
    ib_ok = ~np.isnan(iu) & ~np.isnan(ib) & (ib > 0)
    IU = _area_sum(np.where(ib_ok, iu, np.nan), nb)
    IB = _area_sum(np.where(ib_ok, ib, np.nan), nb)
    icu = IU / np.where(IB > 0, IB, np.nan)
    cov = _area_sum(P["covid_adm"].to_numpy(float), nb)
    flu = _area_sum(P["flu_adm"].to_numpy(float), nb)
    ed = _area_sum(P["ed_visits"].to_numpy(float), nb)
    hocc = used / np.where(beds > 0, beds, np.nan)
    rise = np.zeros_like(hocc)
    rise[2:] = (hocc[2:] - hocc[:-2]) >= RISE_PTS
    rise[np.isnan(hocc)] = 0
    RN = np.stack([rise[:, idx].sum(1) for idx in nb], axis=1)
    REP = np.stack([(~np.isnan(hocc[:, idx])).sum(1) for idx in nb], axis=1)

    def lag(A, k):
        out = np.full_like(A, np.nan)
        out[k:] = A[:-k]
        return out

    def lead(A, k):
        out = np.full_like(A, np.nan)
        out[:-k] = A[k:]
        return out

    T, H = occ.shape
    woy = np.asarray(weeks.isocalendar().week, float)
    nn = np.array([len(i) for i in nb], float)
    frame = {
        "week": np.repeat(weeks.values, H),
        "hospital_pk": np.tile(info.index.values, T),
        "state": np.tile(info["state"].values, T),
        "area_occ": occ.ravel(),
        "area_occ_d1": (occ - lag(occ, 1)).ravel(),
        "area_occ_d2": (occ - lag(occ, 2)).ravel(),
        "area_icu_occ": icu.ravel(),
        "area_icu_d1": (icu - lag(icu, 1)).ravel(),
        "covid_adm_growth": _growth(cov).ravel(),
        "flu_adm_growth": _growth(flu).ravel(),
        "ed_growth": _growth(ed).ravel(),
        "covid_adm_per_100beds": (100 * cov / np.where(B > 0, B, np.nan)).ravel(),
        "flu_adm_per_100beds": (100 * flu / np.where(B > 0, B, np.nan)).ravel(),
        "rising_neighbours": RN.ravel(),
        "rising_share": (RN / np.maximum(REP, 1)).ravel(),
        "log_area_beds": np.log1p(np.nan_to_num(B)).ravel(),
        "n_neighbours": np.tile(nn, T),
        "woy_sin": np.repeat(np.sin(2 * np.pi * woy / 52.18), H),
        "woy_cos": np.repeat(np.cos(2 * np.pi * woy / 52.18), H),
        "occ_next1": lead(occ, 1).ravel(),
        "occ_next2": lead(occ, 2).ravel(),
    }
    f = pd.DataFrame(frame)
    nxt = f[["occ_next1", "occ_next2"]].max(axis=1, skipna=False)
    f["exceed_1_2"] = (nxt >= threshold).astype(float).where(nxt.notna())
    f["below_now"] = f["area_occ"] < threshold
    return f[f["area_occ"].notna()].reset_index(drop=True)
