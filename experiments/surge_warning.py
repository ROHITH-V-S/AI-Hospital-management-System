"""Surge early warning: will this neighbourhood's hospitals be >= 85% full within 1-2 weeks?

    python experiments/surge_warning.py

Real data only (HHS weekly reports: occupancy, ICU, COVID-19 and influenza
admissions, ED visits). This is a SURGE early warning for hospital capacity,
not a pandemic or outbreak predictor: symptom-level surveillance data is not
public.

Split by forecast week (no row's target crosses a boundary):
  train  2020-08-16 .. 2022-06-12
  calib  2022-07-03 .. 2022-12-11   (alert thresholds chosen here)
  test   2023-01-01 .. 2024-04-07   (never seen; target known by 2024-04-21)

Methods (all alert when a score passes a threshold tuned on the calibration window
for the best F1 on "onset" rows, i.e. neighbourhoods still below 85% now):
  near_threshold   area occupancy already within delta of 85%
  trend            occupancy + its 2-week change projected past 85%
  neighbours       k% of neighbouring hospitals rising >= 3 points over 2 weeks AND
                   COVID or flu admissions rising AND occupancy within 10 points
  model            gradient-boosted classifier on all signals (probability)

Scored on test: precision, recall, F1 (onset rows and all rows), lead time on
crossing events, a per-state bootstrap for uncertainty, an ablation without the
ED field, and the largest misses by name.

Writes results/surge_warning.json and data/cache/surge_scores.parquet.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.data import hhs  # noqa: E402
from mahros.pipeline import assessed, data_stamp, write_json  # noqa: E402
from mahros.surge import features as F  # noqa: E402

TRAIN = (pd.Timestamp("2020-08-16"), pd.Timestamp("2022-06-12"))
CALIB = (pd.Timestamp("2022-07-03"), pd.Timestamp("2022-12-11"))
TEST = (pd.Timestamp("2023-01-01"), pd.Timestamp("2024-04-07"))
N_BOOT = 1000


def frame() -> pd.DataFrame:
    df = assessed()
    df = df.merge(hhs.load_extra(), on=["hospital_pk", "week"], how="left")
    return F.build(df), df


def model(features):
    return HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                          min_samples_leaf=200, random_state=0)


def prf(y: np.ndarray, a: np.ndarray) -> dict:
    tp = float((a & y).sum()); fp = float((a & ~y).sum()); fn = float((~a & y).sum())
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    return {"precision": p, "recall": r, "f1": 2 * p * r / (p + r) if p + r else 0.0,
            "alerts": int(a.sum()), "events": int(y.sum()), "rows": int(len(y))}


def tune(score: np.ndarray, y: np.ndarray, grid) -> float:
    best, thr = -1, grid[0]
    for g in grid:
        f1 = prf(y, score >= g)["f1"]
        if f1 > best:
            best, thr = f1, g
    return float(thr)


def scores(f: pd.DataFrame, prob: np.ndarray) -> dict:
    X = F.THRESHOLD
    rising = ((f["covid_adm_growth"].fillna(0) > 0) | (f["flu_adm_growth"].fillna(0) > 0)) \
        & (f["area_occ"] >= X - 0.10)
    return {
        "near_threshold": f["area_occ"].to_numpy(),
        "trend": (f["area_occ"] + f["area_occ_d2"].fillna(0)).to_numpy(),
        "neighbours": np.where(rising, f["rising_share"], 0.0),
        "model": prob,
    }


GRIDS = {"near_threshold": np.arange(0.70, 0.851, 0.005), "trend": np.arange(0.75, 0.951, 0.005),
         "neighbours": np.arange(0.05, 0.951, 0.025), "model": np.arange(0.02, 0.9, 0.01)}


def lead_times(f: pd.DataFrame, alert: np.ndarray) -> dict:
    """Crossing events: area >= 85% in week e after 4 weeks below. Warned 1 or 2 weeks ahead?"""
    X = F.THRESHOLD
    g = f.assign(alert=alert).sort_values(["hospital_pk", "week"])
    out = []
    for pk, h in g.groupby("hospital_pk", sort=False):
        occ, al, wk = h["area_occ"].to_numpy(), h["alert"].to_numpy(), h["week"].to_numpy()
        for e in range(4, len(h)):
            if occ[e] >= X and (occ[e - 4:e] < X).all() and \
                    (wk[e] - wk[e - 4]) == np.timedelta64(28, "D"):
                lead = 2 if al[e - 2] else 1 if al[e - 1] else 0
                out.append((pk, wk[e], lead))
    if not out:
        return {"events": 0}
    L = np.array([x[2] for x in out])
    return {"events": int(len(L)), "warned_2_weeks": float((L == 2).mean()),
            "warned_1_week_or_more": float((L >= 1).mean()), "missed": float((L == 0).mean()),
            "_list": out}


def boot_state(f: pd.DataFrame, a1: np.ndarray, a2: np.ndarray, y: np.ndarray) -> dict:
    """F1(a1) - F1(a2) with a 95% CI from resampling STATES (areas overlap within a state)."""
    states = f["state"].to_numpy()
    uniq = np.unique(states)
    idx = {s: np.flatnonzero(states == s) for s in uniq}
    rng = np.random.default_rng(0)
    d = []
    for _ in range(N_BOOT):
        pick = np.concatenate([idx[s] for s in rng.choice(uniq, len(uniq))])
        d.append(prf(y[pick], a1[pick])["f1"] - prf(y[pick], a2[pick])["f1"])
    point = prf(y, a1)["f1"] - prf(y, a2)["f1"]
    return {"diff": point, "ci95": [float(np.quantile(d, .025)), float(np.quantile(d, .975))]}


def main() -> int:
    t0 = time.perf_counter()
    f, df = frame()
    f = f[f["exceed_1_2"].notna()].reset_index(drop=True)
    split = lambda a, b: (f["week"] >= a) & (f["week"] <= b)
    tr, ca, te = split(*TRAIN), split(*CALIB), split(*TEST)
    print(f"rows: train {tr.sum():,}  calib {ca.sum():,}  test {te.sum():,}")
    y = f["exceed_1_2"].to_numpy().astype(bool)
    onset = f["below_now"].to_numpy()

    def fit_predict(cols):
        m = model(cols)
        m.fit(f.loc[tr, cols], y[tr])
        return m.predict_proba(f[cols])[:, 1], m

    prob, mdl = fit_predict(F.FEATURES)
    no_ed = [c for c in F.FEATURES if c != "ed_growth"]
    prob_no_ed, _ = fit_predict(no_ed)
    no_adm = [c for c in F.FEATURES if not c.startswith(("covid_adm", "flu_adm"))]
    prob_no_adm, _ = fit_predict(no_adm)

    S = scores(f, prob)
    S_extra = {"model_without_ed": prob_no_ed, "model_without_admissions": prob_no_adm}
    thr, res = {}, {}
    cal_on = (ca & onset).to_numpy()
    te_on = (te & onset).to_numpy()
    te_all = te.to_numpy()
    alerts = {}
    for name, sc in {**S, **S_extra}.items():
        grid = GRIDS["model"] if name.startswith("model") else GRIDS[name]
        thr[name] = tune(sc[cal_on], y[cal_on], grid)
        a = sc >= thr[name]
        alerts[name] = a
        lt = lead_times(f[te_all], a[te_all])
        res[name] = {"threshold": thr[name],
                     "test_onset": prf(y[te_on], a[te_on]),
                     "test_all": prf(y[te_all], a[te_all]),
                     "calib_onset": prf(y[cal_on], a[cal_on]),
                     "lead": {k: v for k, v in lt.items() if not k.startswith("_")}}
        print(f"  {name:26s} thr {thr[name]:.3f}  onset P {res[name]['test_onset']['precision']:.2f} "
              f"R {res[name]['test_onset']['recall']:.2f} F1 {res[name]['test_onset']['f1']:.2f}   "
              f"warned>=1wk {res[name]['lead'].get('warned_1_week_or_more', 0):.2f}")
    best_base = max(("near_threshold", "trend", "neighbours"), key=lambda k: res[k]["test_onset"]["f1"])
    comp = {f"model_vs_{k}": boot_state(f[te_on], alerts["model"][te_on], alerts[k][te_on], y[te_on])
            for k in ("near_threshold", "trend", "neighbours")}

    # ED availability on test rows, and threshold sweep for the headline model.
    ed_avail = float(f.loc[te, "ed_growth"].notna().mean())
    sweep = {}
    for X in (0.80, 0.90):
        nxt = f[["occ_next1", "occ_next2"]].max(axis=1)
        yX = (nxt >= X).to_numpy()
        onX = (f["area_occ"] < X).to_numpy()
        mX = HistGradientBoostingClassifier(max_iter=300, learning_rate=0.05, max_leaf_nodes=31,
                                            min_samples_leaf=200, random_state=0)
        mX.fit(f.loc[tr, F.FEATURES], yX[tr])
        pX = mX.predict_proba(f[F.FEATURES])[:, 1]
        c_on, t_on = (ca.to_numpy() & onX), (te.to_numpy() & onX)
        tX = tune(pX[c_on], yX[c_on], GRIDS["model"])
        nt = tune(f["area_occ"].to_numpy()[c_on], yX[c_on], np.arange(X - 0.15, X + 0.001, 0.005))
        sweep[str(X)] = {"model": prf(yX[t_on], pX[t_on] >= tX),
                         "near_threshold": prf(yX[t_on], f["area_occ"].to_numpy()[t_on] >= nt),
                         "onset_base_rate": float(yX[t_on].mean())}

    # Monthly picture on test (alerts and real crossings), for the waves.
    t = f[te_all].assign(alert=alerts["model"][te_all], y=y[te_all], on=onset[te_all])
    t["month"] = t["week"].dt.to_period("M").astype(str)
    monthly = t.groupby("month").apply(lambda g: pd.Series({
        "areas_above_85": float((g["area_occ"] >= F.THRESHOLD).mean()),
        "alerts_share": float(g["alert"].mean()),
        "onset_events": int((g["y"] & g["on"]).sum()),
        "onset_caught": int((g["y"] & g["on"] & g["alert"]).sum())}), include_groups=False)

    # Largest missed crossing events (by area beds), named.
    lt = lead_times(f[te_all], alerts["model"][te_all])
    info = df.sort_values("week").groupby("hospital_pk")[["name", "city", "state"]].last()
    miss = [x for x in lt["_list"] if x[2] == 0]
    fb = f.set_index(["hospital_pk", "week"])["log_area_beds"]
    miss.sort(key=lambda x: -fb.get((x[0], pd.Timestamp(x[1])), 0))
    seen_state, misses = set(), []
    for pk, wk, _ in miss:
        st = info.loc[pk, "state"]
        if (st, str(pd.Timestamp(wk).date())[:7]) in seen_state:
            continue
        seen_state.add((st, str(pd.Timestamp(wk).date())[:7]))
        misses.append({"centre": info.loc[pk, "name"], "city": info.loc[pk, "city"], "state": st,
                       "week": str(pd.Timestamp(wk).date())})
        if len(misses) == 10:
            break

    # Scores for the platform (calib + test weeks, every neighbourhood).
    keep = (f["week"] >= CALIB[0]).to_numpy()
    out = f.loc[keep, ["hospital_pk", "week", "state", "n_neighbours", "area_occ", "area_occ_d1",
                       "area_occ_d2", "area_icu_occ", "covid_adm_growth", "flu_adm_growth",
                       "ed_growth", "rising_neighbours", "rising_share", "exceed_1_2"]].copy()
    out["probability"] = prob[keep]
    out["alert_model"] = alerts["model"][keep]
    out["alert_neighbours"] = alerts["neighbours"][keep]
    out.to_parquet(hhs.CACHE / "surge_scores.parquet", index=False)

    imp = None
    try:
        from sklearn.inspection import permutation_importance
        sub = f[te_on].sample(min(40000, int(te_on.sum())), random_state=0)
        pi = permutation_importance(mdl, sub[F.FEATURES], sub["exceed_1_2"].astype(bool),
                                    scoring="average_precision", n_repeats=3, random_state=0)
        imp = dict(sorted(zip(F.FEATURES, map(float, pi.importances_mean)), key=lambda kv: -kv[1]))
    except Exception as exc:                       # reported, not hidden
        imp = {"error": str(exc)}

    payload = {
        "what": "Surge early warning: neighbourhood (hospital + all within 50 km) reaches >= 85% "
                "occupancy within 1-2 weeks. Real weekly reports only.",
        "definition": {"radius_km": F.RADIUS_KM, "threshold": F.THRESHOLD, "horizon_weeks": [1, 2],
                       "rise_points": F.RISE_PTS, "withheld_count_value": F.WITHHELD_VALUE,
                       "features": F.FEATURES},
        "split": {"train": [str(TRAIN[0].date()), str(TRAIN[1].date())],
                  "calib": [str(CALIB[0].date()), str(CALIB[1].date())],
                  "test": [str(TEST[0].date()), str(TEST[1].date())]},
        "rows": {"train": int(tr.sum()), "calib": int(ca.sum()), "test": int(te.sum()),
                 "test_onset": int(te_on.sum()), "neighbourhoods": int(f["hospital_pk"].nunique())},
        "onset_base_rate_test": float(y[te_on].mean()),
        "methods": res, "best_baseline": best_base, "comparisons": comp,
        "ed_available_share_test": ed_avail, "threshold_sweep": sweep,
        "monthly": monthly.reset_index().to_dict(orient="records"),
        "largest_misses": misses, "importance": imp,
        "runtime_s": round(time.perf_counter() - t0, 1), "data": data_stamp(),
    }
    p = write_json("surge_warning.json", payload)
    print(f"wrote {p} ({time.perf_counter() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
