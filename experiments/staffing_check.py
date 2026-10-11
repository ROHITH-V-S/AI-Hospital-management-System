"""Do our ESTIMATED staff shortfalls point the same way as REAL staffing-shortage reports?

    python experiments/staffing_check.py

Per-hospital staff numbers are not public, so MAHROS estimates them
(``mahros/resources/staff.py``). The only real staffing signal is state-level:
how many hospitals said "critical staffing shortage today" (HHS g62h-syeh).
This checks DIRECTION and TIMING only:

* per state-week: estimated share of hospitals short of nurses vs the real
  share of answering hospitals reporting a critical shortage;
* correlation over time within each state (median across states), pooled
  correlation, and which series leads (lags -4..+4 weeks);
* split into 2020-08..2022-12 (most hospitals answered) and 2023-01..2024-04
  (most stopped answering).

It cannot validate any single hospital's staff count. Writes
results/staffing_check.json.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.data import hhs  # noqa: E402
from mahros.forecast.model import SUBTYPES  # noqa: E402
from mahros.pipeline import assessed, data_stamp, write_json  # noqa: E402
from mahros.resources.staff import pools  # noqa: E402

PERIODS = {"2020-08..2022-12": ("2020-08-02", "2022-12-25"),
           "2023-01..2024-04": ("2023-01-01", "2024-04-21")}
MIN_HOSP = 10


def real_weekly(st: pd.DataFrame, weeks: pd.DatetimeIndex) -> pd.DataFrame:
    rows = []
    s = st.copy()
    for w in weeks:
        g = s[(s["date"] >= w) & (s["date"] < w + pd.Timedelta(days=7))]
        if g.empty:
            continue
        agg = g.groupby("state")[["shortage_today_yes", "shortage_today_no",
                                  "shortage_today_not_reported"]].sum()
        agg["week"] = w
        rows.append(agg.reset_index())
    r = pd.concat(rows, ignore_index=True)
    ans = r["shortage_today_yes"] + r["shortage_today_no"]
    r["real_share"] = r["shortage_today_yes"] / ans.where(ans > 0)
    r["answered_share"] = ans / (ans + r["shortage_today_not_reported"]).where(lambda x: x > 0)
    return r[["state", "week", "real_share", "answered_share"]]


def main() -> int:
    t0 = time.perf_counter()
    df = assessed()
    df = df[df["subtype"].isin(SUBTYPES)]
    p = pools(df)
    est = p.groupby(["state", "week"]).agg(hospitals=("nurse_gap", "size"),
                                           est_share=("nurse_gap", lambda g: float((g > 0).mean())),
                                           mean_gap=("nurse_gap", "mean")).reset_index()
    est = est[est["hospitals"] >= MIN_HOSP]
    real = real_weekly(hhs.load_state_staffing(), pd.DatetimeIndex(sorted(est["week"].unique())))
    m = est.merge(real, on=["state", "week"], how="inner").dropna(subset=["est_share", "real_share"])
    out = {}
    for name, (a, b) in PERIODS.items():
        g = m[(m["week"] >= a) & (m["week"] <= b)]
        within, lags = [], {k: [] for k in range(-4, 5)}
        for st, h in g.groupby("state"):
            h = h.sort_values("week")
            if len(h) < 20 or h["real_share"].std() == 0 or h["est_share"].std() == 0:
                continue
            within.append(spearmanr(h["est_share"], h["real_share"]).statistic)
            for k in lags:
                x = h["est_share"].shift(k)       # k > 0: our estimate from k weeks EARLIER
                ok = x.notna()
                if ok.sum() >= 15 and x[ok].std() > 0:
                    lags[k].append(spearmanr(x[ok], h["real_share"][ok]).statistic)
        lag_med = {str(k): float(np.median(v)) for k, v in lags.items() if v}
        out[name] = {
            "state_weeks": int(len(g)), "states": int(g["state"].nunique()),
            "median_answered_share": float(g["answered_share"].median()),
            "pooled_spearman": float(spearmanr(g["est_share"], g["real_share"]).statistic) if len(g) > 10 else None,
            "within_state_spearman_median": float(np.median(within)) if within else None,
            "within_state_spearman_iqr": [float(np.quantile(within, .25)), float(np.quantile(within, .75))] if within else None,
            "states_positive": int(sum(1 for x in within if x > 0)), "states_tested": len(within),
            "lag_median_spearman": lag_med,
            "best_lag_weeks": int(max(lag_med, key=lag_med.get)) if lag_med else None,
            "mean_est_share": float(g["est_share"].mean()), "mean_real_share": float(g["real_share"].mean()),
        }
        print(name, {k: v for k, v in out[name].items() if k != "lag_median_spearman"})
    nat = m.groupby("week").agg(est_share=("est_share", "mean"), real_share=("real_share", "mean"),
                                answered=("answered_share", "median")).reset_index()
    payload = {
        "what": "Direction check: estimated nurse shortfall vs real state-level critical staffing shortage reports",
        "ratios": {"nurse_icu": 2, "nurse_ward": 5, "intensivist": 14, "ward_physician": 15,
                   "usual_beds": "median of the previous 12 trusted weeks"},
        "periods": out,
        "national_weekly": [{"week": str(r.week.date()), "est_share": r.est_share,
                             "real_share": r.real_share, "answered": r.answered}
                            for r in nat.itertuples()],
        "state_weeks": m.assign(week=m["week"].dt.strftime("%Y-%m-%d")).to_dict(orient="records"),
        "runtime_s": round(time.perf_counter() - t0, 1), "data": data_stamp(),
    }
    print("wrote", write_json("staffing_check.json", payload))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
