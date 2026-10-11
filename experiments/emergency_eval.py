"""Emergency transfer: MAHROS parallel call-for-bids vs serial phone calls.

    python experiments/emergency_eval.py           # ~10 min with all CPU cores
    python experiments/emergency_eval.py --quick   # 2 weeks x 3 seeds, for a smoke run

A SIMULATION GROUNDED IN REAL DATA (see mahros/emergency/world.py): real
hospitals, capability, road times, reported ICU census, ED visits and state
staffing; simulated minute-by-minute bed changes and transfer requests.

Design
------
* States: Arizona, Massachusetts. Weeks: for each state, the 4 test weeks with
  the highest reported state ICU occupancy plus 4 weeks evenly spread over
  2023-01..2024-04 (rule fixed before looking at any result).
* 10 seeds per week. Common random numbers: the three policies face the same
  patients at the same minutes in the same hospitals.
* Policies: mahros (parallel call-for-bids), phone_nearest (call capable
  hospitals nearest first, stop at first yes), phone_informed (call those whose
  weekly report shows a free ICU bed first).
* Paired differences per (state, week, seed) unit; 95% CI from 2,000 bootstrap
  resamples of units.
* Sensitivity: each swept parameter in mahros/emergency/params.py moved one at
  a time (5 seeds), plus a forced 20% short-staffed scenario.

Writes results/emergency_eval.json.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.data import hhs  # noqa: E402
from mahros.emergency import network as N  # noqa: E402
from mahros.emergency.params import REGISTRY, Params, registry_table  # noqa: E402
from mahros.emergency.world import POLICIES, WEEK, World  # noqa: E402
from mahros.pipeline import assessed, data_stamp, write_json  # noqa: E402

STATES = ("AZ", "MA")
TEST_FIRST, TEST_LAST = pd.Timestamp("2023-01-01"), pd.Timestamp("2024-04-21")
_FR: dict = {}


def frames():
    if not _FR:
        df = assessed()
        df = df[df["state"].isin(STATES)]
        ex = hhs.load_extra()[["hospital_pk", "week", "ed_visits", "picu_beds", "picu_used"]]
        _FR["df"] = df.merge(ex, on=["hospital_pk", "week"], how="left")
        _FR["st"] = hhs.load_state_staffing()
    return _FR["df"], _FR["st"]


def pick_weeks(df: pd.DataFrame, state: str, n_busy=4, n_spread=4) -> list[pd.Timestamp]:
    d = df[(df["state"] == state) & (df["week"] >= TEST_FIRST) & (df["week"] <= TEST_LAST)
           & df["level"].isin(["GREEN", "AMBER"])]
    g = d.groupby("week")[["icu_used", "icu_beds"]].sum()
    occ = g["icu_used"] / g["icu_beds"]
    busy = list(occ.sort_values(ascending=False).index[:n_busy])
    rest = [w for w in occ.index if w not in busy]
    spread = [rest[int(i)] for i in np.linspace(0, len(rest) - 1, n_spread)]
    return sorted(busy) + sorted(spread), {str(w.date()): float(occ[w]) for w in busy + spread}


def run_unit(args):
    state, week, seed, policy, prm_kw, force_short = args[:6]
    label = args[6] if len(args) > 6 else ""
    df, st = frames()
    net = N.build(state, week, df, st)
    if force_short is not None:
        net.staffing_share = force_short
    w = World(net, Params(**prm_kw), seed, policy)
    w.run()
    r = pd.DataFrame(w.results())
    if r.empty:
        return None
    pl = r[r["placed"]]
    return {"state": state, "week": str(pd.Timestamp(week).date()), "seed": seed, "policy": policy,
            "cases": len(r), "local": w.local,
            "placed": float(r["placed"].mean()),
            "within_window": float(r["within_window"].mean()),
            "ttb_mean": float(pl["time_to_bed_min"].mean()) if len(pl) else np.nan,
            "ttb_p50": float(pl["time_to_bed_min"].median()) if len(pl) else np.nan,
            "ttb_p90": float(pl["time_to_bed_min"].quantile(0.9)) if len(pl) else np.nan,
            "ttb_max": float(pl["time_to_bed_min"].max()) if len(pl) else np.nan,
            "definitive_mean": float(pl["definitive_min"].mean()) if len(pl) else np.nan,
            "travel_mean": float(pl["travel_min"].mean()) if len(pl) else np.nan,
            "calls_mean": float(r["phone_calls"].mean()),
            "calls_3plus": float((r["phone_calls"] >= 3).mean()),
            "asked_mean": float(r["asked_automatically"].mean()),
            "coord_min_mean": float(r["coordinator_min"].mean()),
            "flags_per_case": float(r["steward_flags"].mean()),
            "staffing_share": net.staffing_share, "label": label}


def run_many(jobs, workers):
    with ProcessPoolExecutor(max_workers=workers) as ex:
        return [x for x in ex.map(run_unit, jobs, chunksize=4) if x is not None]


def boot(diff: np.ndarray, n=2000, seed=0) -> list[float]:
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(diff), (n, len(diff)))
    m = np.nanmean(diff[idx], axis=1)
    return [float(np.quantile(m, 0.025)), float(np.quantile(m, 0.975))]


def paired(res: pd.DataFrame, a: str, b: str, metric: str) -> dict:
    k = ["state", "week", "seed"]
    x = res[res.policy == a].set_index(k)[metric]
    y = res[res.policy == b].set_index(k)[metric]
    d = (x - y).dropna().to_numpy()
    return {"mean_diff": float(d.mean()), "ci95": boot(d), "units": int(len(d)),
            "share_units_a_better": float((d < 0).mean()) if metric.startswith(("ttb", "coord", "calls", "def"))
            else float((d > 0).mean())}


def summarise(res: pd.DataFrame) -> dict:
    out = {}
    for pol in POLICIES:
        r = res[res.policy == pol]
        out[pol] = {m: float(r[m].mean()) for m in
                    ["cases", "placed", "within_window", "ttb_mean", "ttb_p50", "ttb_p90", "ttb_max",
                     "definitive_mean", "travel_mean", "calls_mean", "calls_3plus", "asked_mean",
                     "coord_min_mean", "flags_per_case"]}
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--quick", action="store_true")
    ap.add_argument("--workers", type=int, default=max(1, (os.cpu_count() or 2) - 1))
    a = ap.parse_args()
    t0 = time.perf_counter()
    df, st = frames()
    seeds = range(3) if a.quick else range(10)
    weeks, occ = {}, {}
    for s in STATES:
        w, o = pick_weeks(df, s, *((1, 1) if a.quick else (4, 4)))
        weeks[s], occ[s] = w, o
    busy = {s: [str(x.date()) for x in weeks[s][:(1 if a.quick else 4)]] for s in STATES}
    print("weeks:", {s: [str(x.date()) for x in v] for s, v in weeks.items()})

    jobs = [(s, w, seed, pol, {}, None) for s in STATES for w in weeks[s]
            for seed in seeds for pol in POLICIES]
    res = pd.DataFrame(run_many(jobs, a.workers))
    res["busy_week"] = [w in busy[s] for s, w in zip(res.state, res.week)]
    print(f"main runs: {len(res)} in {time.perf_counter() - t0:.0f}s")

    metrics = ["ttb_mean", "ttb_p90", "within_window", "placed", "coord_min_mean",
               "calls_mean", "definitive_mean", "travel_mean"]
    comps = {f"mahros_vs_{b}": {m: paired(res, "mahros", b, m) for m in metrics}
             for b in ("phone_nearest", "phone_informed")}
    by_group = {}
    for name, g in (("busy_weeks", res[res.busy_week]), ("other_weeks", res[~res.busy_week])):
        by_group[name] = {"summary": summarise(g),
                          "mahros_vs_phone_nearest": {m: paired(g, "mahros", "phone_nearest", m)
                                                      for m in ("ttb_mean", "ttb_p90", "within_window")}}
    by_state = {s: summarise(res[res.state == s]) for s in STATES}

    # Sensitivity: one parameter at a time (mahros vs phone_nearest), 5 seeds.
    sseeds = range(2) if a.quick else range(5)
    sens_jobs = []
    for name, p in REGISTRY.items():
        for v in p.sweep:
            if v == p.value:
                continue
            for s in STATES:
                for w in weeks[s]:
                    for seed in sseeds:
                        for pol in ("mahros", "phone_nearest"):
                            sens_jobs.append((s, w, seed, pol, {name: v}, None, f"{name}={v}"))
    for s in STATES:
        for w in weeks[s]:
            for seed in sseeds:
                for pol in ("mahros", "phone_nearest"):
                    sens_jobs.append((s, w, seed, pol, {}, 0.20, "short_staffed_share=0.2 (forced)"))
    sres = pd.DataFrame(run_many(sens_jobs, a.workers))
    sens = {}
    for lab, g in sres.groupby("label"):
        sens[lab] = {m: paired(g, "mahros", "phone_nearest", m)["mean_diff"]
                     for m in ("ttb_mean", "ttb_p90", "within_window", "coord_min_mean")}
        sens[lab]["mahros_ttb_mean"] = float(g[g.policy == "mahros"]["ttb_mean"].mean())
        sens[lab]["phone_ttb_mean"] = float(g[g.policy == "phone_nearest"]["ttb_mean"].mean())
    print(f"sensitivity runs: {len(sres)}")

    # Calibration (transfer_rate = 0): simulated vs reported ICU census.
    cal = []
    for s in STATES:
        for w in weeks[s]:
            net = N.build(s, w, df, st)
            for seed in range(3):
                wd = World(net, Params(transfer_rate=0.0), seed, "mahros")
                wd.run(WEEK)
                cal += wd.calibration()
    c = pd.DataFrame(cal).groupby("pk").mean()
    calib = {"hospital_weeks": int(len(cal) / 3), "total_simulated_over_reported":
             float(c["simulated"].sum() / c["reported"].sum()),
             "median_ratio": float((c["simulated"] / c["reported"]).median()),
             "iqr_ratio": [float(x) for x in (c["simulated"] / c["reported"]).quantile([.25, .75])],
             "note": "Calibration, not validation: arrival rates are solved so the expected "
                     "capped census equals each hospital's REPORTED weekly average."}

    nets = {s: N.build(s, weeks[s][0], df, st) for s in STATES}
    out = {
        "what": "Emergency transfer coordination: simulation grounded in real data",
        "states": {s: {"name": N.STATES[s], "hospitals": len(nets[s].sites),
                       "with_ed_visits": sum(1 for x in nets[s].sites if x.ed_visits_week),
                       "pos_matched": sum(1 for x in nets[s].sites if x.cap_source.startswith("CMS")),
                       "weeks": [str(x.date()) for x in weeks[s]], "busy_weeks": busy[s],
                       "state_icu_occupancy": occ[s]} for s in STATES},
        "seeds": len(seeds), "policies": list(POLICIES), "params": Params().as_dict(),
        "param_registry": registry_table(),
        "summary": summarise(res), "comparisons": comps, "by_group": by_group, "by_state": by_state,
        "sensitivity": sens, "calibration": calib,
        "units": res.to_dict(orient="records"),
        "runtime_s": round(time.perf_counter() - t0, 1), "data": data_stamp(),
    }
    p = write_json("emergency_eval.json", out)
    print(f"wrote {p} in {time.perf_counter() - t0:.0f}s")
    sm = out["summary"]
    for pol in POLICIES:
        print(f"  {pol:15s} time-to-bed mean {sm[pol]['ttb_mean']:.1f} p90 {sm[pol]['ttb_p90']:.1f} "
              f"within window {sm[pol]['within_window']:.1%} placed {sm[pol]['placed']:.1%} "
              f"calls {sm[pol]['calls_mean']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
