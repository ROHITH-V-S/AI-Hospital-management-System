"""RQ2 -- Can next-week occupancy be forecast, and does trust filtering help?

    python experiments/rq2_forecast.py

Trains on 2020-08..2022-06, calibrates intervals on 2022-07..2022-12, and
tests on 2023-01..2024-04 (weeks never seen in training). Compares:

  persistence     next week = latest trusted week          (no learning)
  mean4           average of the last 4 weeks              (no learning)
  last_year       same week one year earlier               (no learning)
  model_trusted   MAHROS forecaster, untrusted reports masked
  model_raw       same model trained on every report as published

All are scored on the same rows: test weeks whose true value is trusted and
where persistence has a value. Uncertainty in the MAE difference comes from a
bootstrap over *hospitals* (1,000 resamples), because weeks of one hospital
are not independent.

Writes results/rq2_forecast.json and data/cache/forecasts_h1.parquet (the
next-week forecasts the coordinator uses in RQ3).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros import forecast as F  # noqa: E402
from mahros.data import hhs  # noqa: E402
from mahros.forecast.model import fit_persistence  # noqa: E402
from mahros.pipeline import assessed, data_stamp, write_json  # noqa: E402

N_BOOT = 1000


def mae(y, p):
    return float(np.mean(np.abs(y - p)))


def boot_diff(df: pd.DataFrame, a: str, b: str, seed: int = 0) -> dict:
    """MAE(a) - MAE(b) with a 95% CI from resampling hospitals."""
    g = df.assign(ea=(df["y"] - df[a]).abs(), eb=(df["y"] - df[b]).abs())
    per = g.groupby("hospital_pk").agg(sa=("ea", "sum"), sb=("eb", "sum"), n=("ea", "size"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per), size=(N_BOOT, len(per)))
    sa, sb, n = per["sa"].to_numpy(), per["sb"].to_numpy(), per["n"].to_numpy()
    diffs = (sa[idx].sum(1) - sb[idx].sum(1)) / n[idx].sum(1)
    point = (sa.sum() - sb.sum()) / n.sum()
    return {"diff_points": 100 * point,
            "ci95_points": [100 * float(np.quantile(diffs, 0.025)),
                            100 * float(np.quantile(diffs, 0.975))],
            "share_of_boot_below_zero": float((diffs < 0).mean())}


def main() -> int:
    t0 = time.perf_counter()
    df = assessed("corrected")
    levels = df["level"]
    out = {"data": data_stamp(), "split": {
        "train": f"{F.model.START.date()} .. {F.model.TRAIN_END.date()}",
        "calibrate": f"{F.model.TRAIN_END.date()} .. {F.model.CALIB_END.date()} (exclusive start)",
        "test": f"{F.model.CALIB_END.date()} .. {F.model.TEST_END.date()} (exclusive start)"},
        "coverage_target": F.model.COVERAGE, "horizons": {}}

    panel_t = F.build_panel(df, levels, trusted=True)
    panel_r = F.build_panel(df, levels, trusted=False)
    print(f"panel: {panel_t.occ.shape[0]} weeks x {panel_t.occ.shape[1]} hospitals")

    for h in F.HORIZONS:
        fr_t, fr_r = F.features(panel_t, h), F.features(panel_r, h)
        m_t = F.fit(fr_t, h)
        m_r = F.fit(fr_r, h, train_on_untrusted=True)
        m_p = fit_persistence(fr_t, h)

        test_t = F.split(fr_t)["test"]
        test_r = F.split(fr_r)["test"].loc[test_t.index]
        keep = test_t["y_trusted"] & test_t["y"].notna() & test_t["base_last"].notna()
        ev = test_t[keep].copy()
        pt = m_t.predict(ev)
        ev["model_trusted"], ev["lo"], ev["hi"] = pt["pred"], pt["lo"], pt["hi"]
        ev["model_raw"] = m_r.predict(test_r[keep])["pred"]
        ev["persistence"] = ev["base_last"]
        ev["mean4"] = ev["base_mean4"].fillna(ev["base_last"])

        res = {"n_rows": int(len(ev)), "n_hospitals": int(ev["hospital_pk"].nunique()),
               "mae_points": {}, "vs_persistence": {}}
        for name in ("persistence", "mean4", "model_raw", "model_trusted"):
            res["mae_points"][name] = 100 * mae(ev["y"], ev[name])
        ly = ev[ev["base_lastyear"].notna()]
        res["last_year_subset"] = {
            "n_rows": int(len(ly)),
            "last_year": 100 * mae(ly["y"], ly["base_lastyear"]),
            "model_trusted": 100 * mae(ly["y"], ly["model_trusted"])}
        for name in ("model_trusted", "model_raw", "mean4"):
            res["vs_persistence"][name] = boot_diff(ev, name, "persistence")
        res["trusted_vs_raw_model"] = boot_diff(ev, "model_trusted", "model_raw")

        inside = (ev["y"] >= ev["lo"]) & (ev["y"] <= ev["hi"])
        res["interval"] = {"coverage": float(inside.mean()),
                           "mean_width_points": float(100 * (ev["hi"] - ev["lo"]).mean()),
                           "halfwidth_by_size_quartile": m_t.halfwidth}
        # Where the model helps: by hospital size and by reporting history.
        q = pd.qcut(ev["beds_0"], 4, labels=["smallest", "small", "large", "largest"])
        res["by_size"] = {str(k): {"persistence": 100 * mae(g["y"], g["persistence"]),
                                   "model_trusted": 100 * mae(g["y"], g["model_trusted"]),
                                   "n": int(len(g))}
                          for k, g in ev.groupby(q, observed=True)}
        res["feature_count"] = len(F.FEATURES)
        out["horizons"][str(h)] = res
        print(f"h={h}: MAE persistence {res['mae_points']['persistence']:.2f}  "
              f"model {res['mae_points']['model_trusted']:.2f}  raw-model "
              f"{res['mae_points']['model_raw']:.2f}  coverage {res['interval']['coverage']:.3f}")

        if h == 1:
            # Next-week forecasts for every decision week the coordinator needs
            # (calibration + test), from all three forecasters.
            dec = fr_t[fr_t["target_week"] > F.model.TRAIN_END]
            dec_r = fr_r.loc[dec.index]
            p1, p2, p3 = m_t.predict(dec), m_r.predict(dec_r), m_p.predict(dec)
            fc = pd.DataFrame({
                "hospital_pk": dec["hospital_pk"], "week": dec["week"],
                "target_week": dec["target_week"],
                "ml_pred": p1["pred"], "ml_hi": p1["hi"],
                "raw_pred": p2["pred"], "raw_hi": p2["hi"],
                "persist_pred": p3["pred"], "persist_hi": p3["hi"],
                "beds_0": dec["beds_0"], "occ_0": dec["occ_0"]})
            fc.to_parquet(hhs.CACHE / "forecasts_h1.parquet", index=False)

    out["runtime_s"] = round(time.perf_counter() - t0, 1)
    print("wrote", write_json("rq2_forecast.json", out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
