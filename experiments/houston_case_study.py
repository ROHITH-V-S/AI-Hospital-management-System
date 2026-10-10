"""Houston case study -- is straight-line distance good enough?

    python experiments/houston_case_study.py      (after rq2_forecast.py)

The national analysis decides which hospitals are "nearby" by straight-line
distance (80 km). For 27 Houston hospitals we also have real driving times
(OSRM over OpenStreetMap, vendored in mahros/calibration/data). This script:

1. compares straight-line distance with road distance and driving time for
   every pair, and
2. re-plans every test week for these 27 hospitals twice -- once with the
   80 km straight-line radius, once with a 60-minute driving radius -- and
   compares what each plan could actually move.

If the two plans move about the same load to about the same places, the
straight-line shortcut does not drive the national result.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.coordination.frames import arm_frame, base_frame  # noqa: E402
from mahros.coordination.planner import (Params, execute, haversine_km,  # noqa: E402
                                         overload, send_capacity, solve_lp,
                                         spare_capacity)
from mahros.data import hhs  # noqa: E402
from mahros.pipeline import ROOT, assessed, data_stamp, write_json  # noqa: E402

ROUTES = ROOT / "mahros" / "calibration" / "data" / "us_houston_metro_routes.json"
DRIVE_RADIUS_MIN = 60.0


def main() -> int:
    t0 = time.perf_counter()
    routes = json.loads(ROUTES.read_text())
    ccns = [str(c) for c in routes["ccns"]]
    minutes = np.array(routes["durations_seconds"], float) / 60.0
    road_km = np.array(routes["distances_metres"], float) / 1000.0

    df = assessed("corrected")
    fc = pd.read_parquet(hhs.CACHE / "forecasts_h1.parquet")
    frame = arm_frame(base_frame(df), fc, "mahros")
    frame = frame[frame["hospital_pk"].isin(ccns)]
    present = sorted(frame["hospital_pk"].unique())
    missing = sorted(set(ccns) - set(present))
    order = {c: i for i, c in enumerate(ccns)}

    # 1. Pairwise geometry.
    loc = frame.drop_duplicates("hospital_pk").set_index("hospital_pk")[["lat", "lon"]]
    pairs = []
    for a in present:
        for b in present:
            if a < b:
                i, j = order[a], order[b]
                pairs.append({"straight_km": float(haversine_km(*loc.loc[a], *loc.loc[b])),
                              "road_km": float(road_km[i, j]),
                              "drive_min": float(minutes[i, j])})
    P = pd.DataFrame(pairs)
    P["detour"] = P["road_km"] / P["straight_km"]
    geometry = {
        "pairs": int(len(P)),
        "road_over_straight_median": float(P["detour"].median()),
        "road_over_straight_p90": float(P["detour"].quantile(0.9)),
        "drive_minutes_per_straight_km_median": float((P["drive_min"] / P["straight_km"]).median()),
        "max_straight_km": float(P["straight_km"].max()),
        "max_drive_min": float(P["drive_min"].max()),
        "corr_straight_vs_drive": float(np.corrcoef(P["straight_km"], P["drive_min"])[0, 1]),
        "pairs_within_80km_straight": int((P["straight_km"] <= 80).sum()),
        "pairs_within_60min_drive": int((P["drive_min"] <= DRIVE_RADIUS_MIN).sum()),
    }

    # 2. Same weeks, two notions of "nearby".
    prm_km = Params()
    prm_min = Params(radius_km=DRIVE_RADIUS_MIN)       # unit: minutes here
    totals = {"straight_80km": [0.0, 0.0], "drive_60min": [0.0, 0.0]}
    overlap_num = overlap_den = 0.0
    weeks = 0
    for wk, g in frame.groupby("week"):
        g = g.set_index("hospital_pk").loc[[c for c in present if c in set(g["hospital_pk"])]]
        if len(g) < 2:
            continue
        idx = [order[c] for c in g.index]
        D = minutes[np.ix_(idx, idx)]
        lat, lon = g["lat"].to_numpy(float), g["lon"].to_numpy(float)
        beds = g["beds"].to_numpy(float)
        cap = send_capacity(g["pred"].to_numpy(float), beds, prm_km)
        spare = spare_capacity(g["hi"].to_numpy(float), beds, g["can_receive"].to_numpy(bool), prm_km)
        un, bn, tn = (g["used_next"].to_numpy(float), g["beds_next"].to_numpy(float),
                      g["trusted_next"].to_numpy(bool))
        ov = overload(un, bn, tn, prm_km)
        plans = {"straight_80km": solve_lp(lat, lon, cap, spare, prm_km),
                 "drive_60min": solve_lp(lat, lon, cap, spare, prm_min, distance=D)}
        moved = {}
        for k, p in plans.items():
            ex = execute(p, un, bn, tn, prm_km)
            moved[k] = {(int(s), int(r)): float(x)
                        for s, r, x in zip(p.senders, p.receivers, ex.executed) if x > 1e-9}
            totals[k][0] += ov
            totals[k][1] += float(ex.executed.sum())
        keys = set(moved["straight_80km"]) | set(moved["drive_60min"])
        overlap_num += sum(min(moved["straight_80km"].get(k, 0), moved["drive_60min"].get(k, 0)) for k in keys)
        overlap_den += sum(max(moved["straight_80km"].get(k, 0), moved["drive_60min"].get(k, 0)) for k in keys)
        weeks += 1

    out = {"data": data_stamp(), "hospitals_in_routes": len(ccns),
           "hospitals_matched": len(present), "unmatched_ccns": missing,
           "geometry": geometry, "weeks": weeks,
           "plans": {k: {"overload_patient_days": 7 * v[0], "absorbed_patient_days": 7 * v[1],
                         "share_absorbed": v[1] / v[0] if v[0] else None}
                     for k, v in totals.items()},
           "weighted_overlap_of_transfers": overlap_num / overlap_den if overlap_den else None,
           "runtime_s": round(time.perf_counter() - t0, 1)}
    print(json.dumps(out["geometry"], indent=1))
    print(json.dumps(out["plans"], indent=1), "overlap", out["weighted_overlap_of_transfers"])
    print("wrote", write_json("houston_case_study.json", out))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
