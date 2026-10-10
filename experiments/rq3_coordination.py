"""RQ3 -- How much overload could regional coordination have absorbed, and how
much do unreliable reports distort the plan?

    python experiments/rq3_coordination.py          (needs rq2_forecast.py first)

For every week of the test period (decisions 2022-12-25 .. 2024-04-14) and
every state, a plan is made from information available that week and scored
against what hospitals actually reported the following week.

Arms (all use the same safe level, radius and transfer cap)
  none         no coordination                                  (floor)
  greedy       ML forecast + trust, biggest excess to nearest   (no optimiser)
  persistence  "next week = this week" + trust, optimised       (no ML)
  no_trust     ML trained on raw reports, every report believed (no Steward)
  mahros       ML forecast + Data Steward + optimiser           (full system)
  oracle       perfect knowledge of next week, optimised        (ceiling)

Part B plants errors into a share of each week's reports (the same error types
as RQ1) and re-runs the forecasting and planning on the corrupted reports. The
plan is always scored against the *uncorrupted* next-week reports.

Uncertainty: weekly totals are compared pairwise (same weeks, same hospitals)
and the mean difference gets a 95% interval from a moving-block bootstrap over
weeks (block = 4 weeks, 2,000 resamples), because neighbouring weeks are
correlated.
"""

from __future__ import annotations

import pickle
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros import forecast as F  # noqa: E402
from mahros.coordination.evaluate import by_state, plan_week, summarise  # noqa: E402
from mahros.coordination.frames import (FIRST_DECISION, LAST_DECISION,  # noqa: E402
                                       arm_frame, base_frame)
from mahros.coordination.planner import Params  # noqa: E402
from mahros.data import hhs  # noqa: E402
from mahros.pipeline import assessed, data_stamp, write_json  # noqa: E402
from mahros.trust import assess  # noqa: E402

SUBTYPES = F.model.SUBTYPES
CORRUPTION_RATES = (0.02, 0.05, 0.10)
BLOCK, N_BOOT = 4, 2000


def run_arm(frame: pd.DataFrame, prm: Params, solver: str = "lp",
            zero: bool = False) -> list:
    out = []
    for wk, g in frame.groupby("week", sort=True):
        if zero:
            g = g.assign(pred=np.nan)
        out.append(plan_week(g, prm, solver))
    return out


def block_bootstrap(diff: np.ndarray, seed: int = 0) -> list[float]:
    rng = np.random.default_rng(seed)
    n = len(diff)
    starts = np.arange(0, n - BLOCK + 1)
    k = int(np.ceil(n / BLOCK))
    means = []
    for _ in range(N_BOOT):
        s = rng.choice(starts, size=k)
        idx = (s[:, None] + np.arange(BLOCK)[None, :]).ravel()[:n]
        means.append(diff[idx].mean())
    return [float(np.quantile(means, 0.025)), float(np.quantile(means, 0.975))]


def compare(a: list, b: list) -> dict:
    """Weekly absorbed patient-days, arm a minus arm b."""
    d = 7 * (np.array([w.executed for w in a]) - np.array([w.executed for w in b]))
    return {"mean_weekly_diff_patient_days": float(d.mean()),
            "ci95": block_bootstrap(d), "weeks_a_better": int((d > 0).sum()),
            "weeks_b_better": int((d < 0).sum()), "weeks": int(len(d))}


# --------------------------------------------------------------------------- #
# Part B: planted errors
# --------------------------------------------------------------------------- #

def corrupt(df: pd.DataFrame, rate: float, seed: int) -> tuple[pd.DataFrame, int]:
    """Plant errors into `rate` of clean, decision-week reports."""
    rng = np.random.default_rng(seed)
    c = df.copy()
    elig = (c["subtype"].isin(SUBTYPES) & c["level"].eq("GREEN") & c["used"].ge(20)
            & c["week"].between(FIRST_DECISION - pd.Timedelta(days=21), LAST_DECISION))
    idx = np.flatnonzero(elig.to_numpy())
    pick = rng.choice(idx, size=int(rate * len(idx)), replace=False)
    kinds = rng.integers(0, 6, size=len(pick))
    used = c["used"].to_numpy().copy()
    beds = c["beds"].to_numpy().copy()
    prev_used = c.groupby("hospital_pk")["used"].shift(3).to_numpy()
    for i, k in zip(pick, kinds):
        if k == 0:   used[i] *= 10                       # extra zero
        elif k == 1: used[i] /= 10                       # lost digit
        elif k == 2: used[i] *= 7                        # weekly sum as average
        elif k == 3: used[i] = 0.0                       # blank as zero
        elif k == 4: used[i], beds[i] = beds[i], used[i] # fields swapped
        else:        used[i] = prev_used[i] if np.isfinite(prev_used[i]) else used[i]  # stale
    c["used"], c["beds"] = used, beds
    cov = c["used_cov"].fillna(7)
    c["used_sum"], c["beds_sum"] = c["used"] * cov, c["beds"] * c["beds_cov"].fillna(7)
    return c, len(pick)


def forecasts_for(df: pd.DataFrame, models: dict) -> pd.DataFrame:
    """Re-run the Steward and both forecasters on (possibly corrupted) reports."""
    base_cols = [c for c in df.columns if c not in ("flags", "level", "census_run")]
    raw = df[base_cols]
    lv = assess(raw)
    d = raw.join(lv)
    pt = F.build_panel(d, d["level"], trusted=True)
    pr = F.build_panel(d, d["level"], trusted=False)
    ft, fr = F.features(pt, 1), F.features(pr, 1)
    assert (ft["hospital_pk"].to_numpy() == fr["hospital_pk"].to_numpy()).all()
    assert (ft["week"].to_numpy() == fr["week"].to_numpy()).all()
    keep = (ft["week"] >= FIRST_DECISION) & (ft["week"] <= LAST_DECISION)
    ft, fr = ft[keep], fr[keep]
    p1, p2, p3 = (models["trusted"].predict(ft), models["raw"].predict(fr),
                  models["persistence"].predict(ft))
    fc = pd.DataFrame({"hospital_pk": ft["hospital_pk"], "week": ft["week"],
                       "ml_pred": p1["pred"], "ml_hi": p1["hi"],
                       "raw_pred": p2["pred"], "raw_hi": p2["hi"],
                       "persist_pred": p3["pred"], "persist_hi": p3["hi"]})
    return fc, d


def main() -> int:
    t0 = time.perf_counter()
    df = assessed("corrected")
    fc = pd.read_parquet(hhs.CACHE / "forecasts_h1.parquet")
    fc = fc[["hospital_pk", "week", "ml_pred", "ml_hi", "raw_pred", "raw_hi",
             "persist_pred", "persist_hi"]]
    base = base_frame(df)
    prm = Params()
    print(f"decision weeks: {base['week'].nunique()}  hospitals: {base['hospital_pk'].nunique()}")

    arms = {}
    for arm, solver in (("mahros", "lp"), ("greedy", "greedy"), ("persistence", "lp"),
                        ("no_trust", "lp"), ("oracle", "lp")):
        arms[arm] = run_arm(arm_frame(base, fc, arm), prm, solver)
        print(f"  {arm:12} {summarise(arms[arm])['share_of_overload_absorbed']:.3f}")
    arms["none"] = run_arm(arm_frame(base, fc, "mahros"), prm, zero=True)

    out = {"data": data_stamp(),
           "params": {"theta": prm.theta, "radius_km": prm.radius_km,
                      "kappa": prm.kappa, "eps": prm.eps},
           "decision_weeks": [str(base["week"].min().date()), str(base["week"].max().date())],
           "arms": {k: summarise(v) for k, v in arms.items()},
           "weekly": {k: [{"week": str(w.week.date()), "overload": 7 * w.overload,
                           "absorbed": 7 * w.executed, "planned": 7 * w.planned}
                          for w in v] for k, v in arms.items()},
           "by_state": {k: by_state(arms[k]) for k in ("mahros", "oracle")},
           "comparisons": {f"mahros_vs_{k}": compare(arms["mahros"], arms[k])
                           for k in ("none", "greedy", "persistence", "no_trust")}}
    out["comparisons"]["oracle_vs_mahros"] = compare(arms["oracle"], arms["mahros"])

    # Sensitivity: each declared parameter moved alone.
    sens = {}
    for name, p in (("theta=0.85", Params(theta=0.85)), ("theta=0.95", Params(theta=0.95)),
                    ("radius=40km", Params(radius_km=40)), ("radius=150km", Params(radius_km=150)),
                    ("kappa=0.02", Params(kappa=0.02)), ("kappa=0.10", Params(kappa=0.10))):
        m = summarise(run_arm(arm_frame(base, fc, "mahros"), p))
        o = summarise(run_arm(arm_frame(base, fc, "oracle"), p))
        sens[name] = {"mahros_share": m["share_of_overload_absorbed"],
                      "oracle_share": o["share_of_overload_absorbed"],
                      "mahros_absorbed": m["absorbed_patient_days"],
                      "overload": m["overload_patient_days"],
                      "plan_realised": m["plan_realised"]}
        print(f"  sens {name:13} mahros {m['share_of_overload_absorbed']:.3f} "
              f"oracle {o['share_of_overload_absorbed']:.3f}")
    out["sensitivity"] = sens

    # Part B.
    with (hhs.CACHE / "models_h1.pkl").open("rb") as fh:
        models = pickle.load(fh)
    planted = {}
    for rate in CORRUPTION_RATES:
        dc, n = corrupt(df, rate, seed=int(rate * 1000))
        fcc, dca = forecasts_for(dc, models)
        bc = base_frame(dca)
        # Score against the *uncorrupted* next week.
        truth = base.set_index(["hospital_pk", "week"])[["used_next", "beds_next", "trusted_next"]]
        bc = bc.drop(columns=["used_next", "beds_next", "trusted_next"]).join(
            truth, on=["hospital_pk", "week"])
        bc["trusted_next"] = bc["trusted_next"].astype("boolean").fillna(False).astype(bool)
        res = {a: run_arm(arm_frame(bc, fcc, a), prm, "lp")
               for a in ("mahros", "no_trust", "persistence")}
        planted[f"{rate:.2f}"] = {
            "reports_corrupted": n,
            "arms": {a: summarise(v) for a, v in res.items()},
            "mahros_vs_no_trust": compare(res["mahros"], res["no_trust"]),
        }
        s = planted[f"{rate:.2f}"]["arms"]
        print(f"  planted {rate:.0%}: mahros {s['mahros']['share_of_overload_absorbed']:.3f} "
              f"(overfill if unchecked {s['mahros']['overfill_if_unchecked_patient_days']:.0f})  "
              f"no_trust {s['no_trust']['share_of_overload_absorbed']:.3f} "
              f"(overfill {s['no_trust']['overfill_if_unchecked_patient_days']:.0f})")
    out["planted_errors"] = planted
    out["runtime_s"] = round(time.perf_counter() - t0, 1)
    print("wrote", write_json("rq3_coordination.json", out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
