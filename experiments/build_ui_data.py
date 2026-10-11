"""Precompute the small JSON files the dashboard reads.

    python experiments/build_ui_data.py              (after the rq*/emergency/surge scripts)
    python experiments/build_ui_data.py --copy-only  (only re-copy headline result files)

The dashboard never needs the 1M-row national cache: everything it shows is
written here to ``results/ui/`` and committed, so the deployed page and a
reviewer's laptop show the same numbers. Every figure is copied from the
results JSON or recomputed from the same cached data the experiments used.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.agents import Platform  # noqa: E402
from mahros.data import hhs  # noqa: E402
from mahros.forecast.model import SUBTYPES  # noqa: E402
from mahros.pipeline import RESULTS, assessed  # noqa: E402
from mahros.trust import BIT, RULES, explain  # noqa: E402

UI = RESULTS / "ui"


def _f(v, nd=4):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, nd)


def dump(name: str, obj) -> None:
    UI.mkdir(parents=True, exist_ok=True)
    (UI / name).write_text(json.dumps(obj, separators=(",", ":"), default=str))


def trust_data(df: pd.DataFrame) -> dict:
    d = df[df["subtype"].isin(SUBTYPES)]
    # National share of reports by level, per month.
    m = d.assign(month=d["week"].dt.to_period("M").astype(str))
    share = (m.groupby("month")["level"].value_counts(normalize=True)
             .unstack(fill_value=0)[["GREEN", "AMBER", "RED", "MISSING"]])
    # Examples: for each RED rule, the flagged week with the clearest pattern.
    examples = []
    for code, rule in RULES.items():
        if rule.level != "RED":
            continue
        hit = d[(d["flags"] & BIT[code]) > 0]
        if hit.empty:
            continue
        if code == "FROZEN_CENSUS":
            hit = hit.sort_values("census_run", ascending=False)
        else:
            hit = hit[hit["used"].ge(30)].sample(frac=1, random_state=3)
        for _, r in hit.head(40).iterrows():
            ctx = d[(d["hospital_pk"] == r["hospital_pk"])
                    & d["week"].between(r["week"] - pd.Timedelta(weeks=16),
                                        r["week"] + pd.Timedelta(weeks=8))]
            if len(ctx) >= 18 and ctx["level"].eq("GREEN").sum() >= 8:
                examples.append({
                    "rule": code, "title": rule.title, "explain": rule.explain,
                    "hospital": r["name"], "city": r["city"], "state": r["state"],
                    "flag_week": str(r["week"].date()),
                    "series": [{"week": str(x.week.date()), "beds": _f(x.beds, 1),
                                "used": _f(x.used, 1), "level": x.level,
                                "why": [e["title"] for e in explain(int(x.flags))]}
                               for x in ctx.itertuples()]})
                break
    return {"monthly_share": {k: {c: round(float(v), 5) for c, v in row.items()}
                              for k, row in share.iterrows()},
            "examples": examples}


def forecast_data(df: pd.DataFrame) -> dict:
    fc = pd.read_parquet(hhs.CACHE / "forecasts_h1.parquet")
    d = df[df["subtype"].isin(SUBTYPES)][["hospital_pk", "week", "name", "city",
                                          "state", "used", "beds", "level"]]
    truth = d.assign(week=d["week"] - pd.Timedelta(days=7))      # align target week
    j = fc.merge(truth, on=["hospital_pk", "week"], how="inner")
    j = j[j["target_week"] > pd.Timestamp("2022-12-25")]
    j["actual"] = (j["used"] / j["beds"]).where(j["level"].isin(["GREEN", "AMBER"]))
    sizes = j.groupby("hospital_pk")["beds"].median()
    complete = j.groupby("hospital_pk")["actual"].count()
    pool = sizes[complete.reindex(sizes.index).fillna(0) >= 60]
    picks = []
    for q in (0.97, 0.75, 0.5, 0.2):
        target = pool.quantile(q)
        picks.append((pool - target).abs().idxmin())
    out = []
    for pk in picks:
        g = j[j["hospital_pk"] == pk].sort_values("target_week")
        lo = g["ml_pred"] - (g["ml_hi"] - g["ml_pred"])
        out.append({"hospital": g["name"].iloc[0], "city": g["city"].iloc[0],
                    "state": g["state"].iloc[0], "beds": _f(g["beds"].median(), 0),
                    "series": [{"week": str(w.date()), "actual": _f(a), "pred": _f(p),
                                "lo": _f(max(l, 0)), "hi": _f(h), "persist": _f(ps)}
                               for w, a, p, l, h, ps in zip(g["target_week"], g["actual"],
                                                            g["ml_pred"], lo, g["ml_hi"],
                                                            g["persist_pred"])]})
    return {"examples": out}


def runs_data(df: pd.DataFrame) -> dict:
    rq3 = json.loads((RESULTS / "rq3_coordination.json").read_text())
    weekly = pd.DataFrame(rq3["weekly"]["mahros"])
    weekly["week"] = pd.to_datetime(weekly["week"])
    order = weekly.sort_values("overload")
    chosen = {"Busiest week": order.iloc[-1]["week"],
              "Typical week": order.iloc[len(order) // 2]["week"],
              "Quietest week": order.iloc[0]["week"]}
    fc = pd.read_parquet(hhs.CACHE / "forecasts_h1.parquet")
    plat = Platform(df, fc)
    index = {"weeks": [], "states": plat.states()}
    for label, wk in chosen.items():
        wk_s = str(pd.Timestamp(wk).date())
        index["weeks"].append({"label": label, "week": wk_s})
        bundle = {}
        for st in plat.states():
            r = plat.run_week(st, wk)
            bundle[st] = {"totals": r.totals, "hospitals": r.hospitals,
                          "proposals": r.proposals, "responses": r.responses,
                          "block": r.block}
        dump(f"run_{wk_s}.json", bundle)
    v = plat.ledger.verify()
    index["ledger"] = {"verify": v,
                       "blocks": [{"index": b.index, "label": b.label, "hash": b.hash,
                                   "prev": b.prev_hash, "entries": len(b.entries)}
                                  for b in plat.ledger.blocks]}
    # The raw entries, so anyone (and the server, at startup) can rebuild the
    # chain from scratch and check it lands on the same hashes.
    dump("ledger_entries.json", [{"label": b.label, "entries": b.entries}
                                 for b in plat.ledger.blocks])
    return index


#: Headline results copied verbatim (minus bulky per-unit rows) so the page never
#: recomputes them. v0.3 files are copied when present.
COPY = {"rq1_trust_audit": (), "rq2_forecast": (), "rq3_coordination": ("weekly_full",),
        "houston_case_study": (), "emergency_eval": ("units",), "surge_warning": ("weekly",),
        "staffing_check": ("state_weeks",)}


def copy_results() -> None:
    for name, drop in COPY.items():
        f = RESULTS / f"{name}.json"
        if not f.exists():
            print(f"  (skip {name}: not built yet)")
            continue
        src = json.loads(f.read_text())
        for k in drop:
            src.pop(k, None)
        dump(f"{name}.json", src)
    dump("manifest.json", json.loads(hhs.MANIFEST.read_text()))


def main() -> int:
    t0 = time.perf_counter()
    if "--copy-only" in sys.argv:          # fast: only re-copy the headline result files
        copy_results()
        print(f"copied ({time.perf_counter() - t0:.1f}s)")
        return 0
    df = assessed("corrected")
    print("trust ..."); dump("trust.json", trust_data(df))
    print("forecast ..."); dump("forecast.json", forecast_data(df))
    print("runs ..."); idx = runs_data(df)
    dump("index.json", idx)
    copy_results()
    sizes = {p.name: p.stat().st_size for p in UI.glob("*.json")}
    print(json.dumps(sizes, indent=1), f"total {sum(sizes.values()) / 1e6:.1f} MB",
          f"({time.perf_counter() - t0:.0f}s)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
