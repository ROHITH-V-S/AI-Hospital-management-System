"""RQ1 -- How reliable is self-reported hospital capacity data, and can the
Data Steward agent tell which reports to distrust?

    python experiments/rq1_trust_audit.py

Five analyses, each answering a question a reviewer will ask:

1. Prevalence   How common is each problem, nationally, by year and type?
2. Chance       Could the frozen-census flags be honest coincidences?
                (measured repeat rate -> expected false alarms vs observed)
3. HHS labels   Does the Steward flag the reports HHS itself later corrected?
                (RAW vs corrected, joined on hospital and week)
4. Planted      For known error types planted into clean data: caught or not?
5. Thresholds   How do the counts move if each declared threshold changes?

Plus a random sample of RED flags exported for manual review by the team
(results/rq1_review_sample.csv), so precision can be checked by humans rather
than asserted.
"""

from __future__ import annotations

import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.pipeline import RESULTS, assessed, data_stamp, write_json  # noqa: E402
from mahros.trust import BIT, RULES, assess, repeat_base_rate  # noqa: E402
from mahros.trust import checks as C  # noqa: E402
from mahros.trust.inject import ERROR_TYPES, run_benchmark  # noqa: E402

SUBTYPES = ("Short Term", "Critical Access Hospitals")
#: A RAW value differs from the corrected value if it moved by more than this.
DIFF_ABS, DIFF_REL = 0.5, 0.01
MEASURES = ("used", "beds", "icu_used", "icu_beds")


def rule_counts(df: pd.DataFrame) -> dict:
    f = df["flags"].to_numpy()
    return {c: int(((f & BIT[c]) > 0).sum()) for c in RULES}


def prevalence(df: pd.DataFrame) -> dict:
    d = df[df["subtype"].isin(SUBTYPES)]
    hosp_red = d.groupby("hospital_pk")["level"].agg(lambda s: bool((s == "RED").any()))
    by_year = (d.assign(red=d["level"].eq("RED"), miss=d["level"].eq("MISSING"))
               .groupby(d["week"].dt.year)[["red", "miss"]].mean())
    by_type = (d.assign(red=d["level"].eq("RED"))
               .groupby("subtype")["red"].mean())
    by_state = (d.assign(red=d["level"].eq("RED")).groupby("state")["red"]
                .agg(["mean", "size"]).sort_values("mean", ascending=False))
    return {
        "scope": "Short Term + Critical Access hospitals",
        "rows": int(len(d)), "hospitals": int(d["hospital_pk"].nunique()),
        "level_share": d["level"].value_counts(normalize=True).round(5).to_dict(),
        "level_count": d["level"].value_counts().to_dict(),
        "rule_counts": rule_counts(d),
        "hospitals_with_any_red": int(hosp_red.sum()),
        "share_hospitals_with_any_red": float(hosp_red.mean()),
        "by_year": {int(k): {"red": float(v.red), "missing": float(v.miss)}
                    for k, v in by_year.iterrows()},
        "red_share_by_subtype": by_type.round(5).to_dict(),
        "red_share_by_state_top10": {k: round(float(v["mean"]), 5)
                                     for k, v in by_state.head(10).iterrows()},
        "red_share_by_state_bottom5": {k: round(float(v["mean"]), 5)
                                       for k, v in by_state.tail(5).iterrows()},
    }


def chance_analysis(df: pd.DataFrame) -> dict:
    d = df[df["subtype"].isin(SUBTYPES)].reset_index(drop=True)
    base = repeat_base_rate(d)
    cons = C._consecutive(d)
    prev = d["used"].shift(1).where(cons)
    eligible = int((cons & d["used"].ge(C.MIN_LEVEL) & prev.ge(C.MIN_LEVEL)).sum())
    observed = int(((d["flags"] & BIT["FROZEN_CENSUS"]) > 0).sum())
    # Alternative estimate that keeps every hospital but drops rows inside runs.
    in_run = d["census_run"].ge(C.FROZEN_RUN)
    ok = cons & d["used"].ge(C.MIN_LEVEL) & prev.ge(C.MIN_LEVEL) & ~in_run
    p_alt = float((ok & d["used"].eq(prev)).sum() / ok.sum())
    expected = eligible * base["p_repeat"] ** (C.FROZEN_RUN - 1)
    # Week-to-week movement in all eligible rows: where the spike threshold sits.
    r = (d["used"] / prev)[cons & prev.ge(C.MIN_LEVEL) & d["used"].ge(C.MIN_LEVEL)]
    q = r.quantile([0.0005, 0.001, 0.01, 0.5, 0.99, 0.999, 0.9995])
    return {
        **base,
        "p_repeat_alternative_estimate": p_alt,
        "eligible_weeks": eligible,
        "frozen_flags_observed": observed,
        "frozen_flags_expected_by_chance": float(expected),
        "share_explainable_by_chance": float(expected / observed) if observed else None,
        "week_ratio_quantiles_all_rows": {str(k): float(v) for k, v in q.items()},
        "spike_threshold": C.SPIKE_RATIO,
    }


def hhs_label_check(raw: pd.DataFrame, cor: pd.DataFrame) -> tuple[dict, pd.DataFrame]:
    key = ["hospital_pk", "week"]
    cols = key + list(MEASURES) + ["level", "flags", "subtype"]
    j = raw[cols].merge(cor[key + list(MEASURES) + ["is_corrected", "level"]],
                        on=key, suffixes=("_raw", "_cor"))
    changed = pd.Series(False, index=j.index)
    per = {}
    for m in MEASURES:
        a, b = j[f"{m}_raw"], j[f"{m}_cor"]
        diff = (a - b).abs()
        c = (diff > np.maximum(DIFF_ABS, DIFF_REL * b.abs())) | (a.isna() != b.isna())
        per[m] = int(c.sum())
        changed |= c
    j["hhs_changed"] = changed
    flagged = j["level_raw"].isin(["RED", "MISSING"])
    red = j["level_raw"].eq("RED")
    lab = j["hhs_changed"]
    # Size of the corrections HHS made (census), to describe the label set.
    ratio = (j.loc[lab, "used_raw"] / j.loc[lab, "used_cor"]).replace([np.inf, -np.inf], np.nan)
    out = {
        "joined_rows": int(len(j)),
        "rows_hhs_changed": int(lab.sum()),
        "rows_hhs_changed_by_measure": per,
        "rows_is_corrected_flag": int(j["is_corrected"].sum()),
        "agreement_changed_vs_is_corrected": float((lab == j["is_corrected"]).mean()),
        "recall_red_or_missing": float(flagged[lab].mean()) if lab.any() else None,
        "recall_red_only": float(red[lab].mean()) if lab.any() else None,
        "share_of_raw_red_that_hhs_changed": float(lab[red].mean()) if red.any() else None,
        "share_of_raw_green_that_hhs_changed": float(lab[j["level_raw"].eq("GREEN")].mean()),
        "enrichment_red_vs_green": float(lab[red].mean() / lab[j["level_raw"].eq("GREEN")].mean()),
        "recall_by_census_correction_size": _recall_by_size(j, red),
        "raw_over_corrected_census_ratio_quantiles": {
            str(k): float(v) for k, v in ratio.quantile([0.05, 0.25, 0.5, 0.75, 0.95]).items()},
        "note": ("HHS corrected a set of keyed-in errors; it did not attempt to label "
                 "stale or frozen values, so the share of RED rows HHS changed is a "
                 "lower bound on precision, not precision."),
    }
    return out, j


def _recall_by_size(j: pd.DataFrame, red: pd.Series) -> dict:
    """Recall against HHS corrections, split by how big the census correction was.

    Most HHS corrections are adjustments of about 1%, which no rule could or
    should flag. Recall is only meaningful against corrections large enough to
    be an error a reader of the data would care about.
    """
    r = (j["used_raw"] / j["used_cor"]).replace([np.inf, -np.inf], np.nan)
    size = (np.log(r).abs()).where(j["used_raw"].notna() & j["used_cor"].notna())
    bands = {"<5%": (0, np.log(1.05)), "5-25%": (np.log(1.05), np.log(1.25)),
             "25-100%": (np.log(1.25), np.log(2.0)), ">2x": (np.log(2.0), np.inf)}
    out = {}
    for name, (lo, hi) in bands.items():
        m = j["hhs_changed"] & size.gt(lo) & size.le(hi)
        out[name] = {"n": int(m.sum()),
                     "recall_red": float(red[m].mean()) if m.any() else None}
    return out


def threshold_sensitivity(df: pd.DataFrame) -> dict:
    d = df[df["subtype"].isin(SUBTYPES)].reset_index(drop=True)
    cols = ["hospital_pk", "week", "used", "beds", "icu_used", "icu_beds",
            "used_sum", "beds_sum", "used_cov", "beds_cov", "used_suppressed",
            "beds_suppressed"]
    base = d[cols]
    out = {}
    original = (C.FROZEN_RUN, C.SPIKE_RATIO, C.MIN_LEVEL)
    try:
        for run in (2, 3, 4, 6):
            C.FROZEN_RUN = run
            out[f"frozen_run={run}"] = rule_counts(base.join(assess(base)))["FROZEN_CENSUS"]
        C.FROZEN_RUN = original[0]
        for ratio in (2.0, 2.5, 3.0, 5.0):
            C.SPIKE_RATIO = ratio
            out[f"spike_ratio={ratio}"] = rule_counts(base.join(assess(base)))["CENSUS_SPIKE"]
        C.SPIKE_RATIO = original[1]
        for lvl in (5.0, 10.0, 20.0):
            C.MIN_LEVEL = lvl
            out[f"min_level={lvl}"] = rule_counts(base.join(assess(base)))["FROZEN_CENSUS"]
    finally:
        C.FROZEN_RUN, C.SPIKE_RATIO, C.MIN_LEVEL = original
    return out


def review_sample(df: pd.DataFrame, n_per_rule: int = 15, seed: int = 7) -> pd.DataFrame:
    """Random RED rows per rule, with 6 weeks of context, for manual review."""
    d = df[df["subtype"].isin(SUBTYPES)]
    rows = []
    rng = np.random.default_rng(seed)
    for code, rule in RULES.items():
        if rule.level != "RED":
            continue
        hit = d[(d["flags"] & BIT[code]) > 0]
        if hit.empty:
            continue
        pick = hit.iloc[rng.choice(len(hit), size=min(n_per_rule, len(hit)), replace=False)]
        for _, r in pick.iterrows():
            ctx = d[(d["hospital_pk"] == r["hospital_pk"])
                    & (d["week"] <= r["week"])].tail(6)
            rows.append({
                "rule": code, "hospital_pk": r["hospital_pk"], "name": r["name"],
                "state": r["state"], "week": r["week"].date(),
                "beds_last6": " | ".join(f"{v:.1f}" for v in ctx["beds"]),
                "census_last6": " | ".join(f"{v:.1f}" for v in ctx["used"]),
                "icu_census_last6": " | ".join(f"{v:.1f}" for v in ctx["icu_used"]),
                "reviewer_verdict": "", "reviewer_note": "",
            })
    return pd.DataFrame(rows)


def main() -> int:
    t0 = time.perf_counter()
    cor = assessed("corrected")
    raw = assessed("raw")
    out = {"data": data_stamp(),
           "thresholds": {"FROZEN_RUN": C.FROZEN_RUN, "SPIKE_RATIO": C.SPIKE_RATIO,
                          "MIN_LEVEL": C.MIN_LEVEL,
                          "OVER_CAPACITY_TOL": C.OVER_CAPACITY_TOL},
           "rules": {c: {"level": r.level, "title": r.title, "explain": r.explain}
                     for c, r in RULES.items()}}

    print("1. prevalence"); out["prevalence"] = prevalence(cor)
    print("2. chance"); out["chance"] = chance_analysis(cor)
    print("3. HHS labels"); out["hhs_labels"], joined = hhs_label_check(raw, cor)
    print("4. planted errors")
    bench = run_benchmark(cor[cor["subtype"].isin(SUBTYPES)].reset_index(drop=True),
                          cor.loc[cor["subtype"].isin(SUBTYPES), "level"].reset_index(drop=True),
                          per_type=400)
    out["planted"] = {
        et.code: {
            "description": et.description,
            "n": int((g := bench[bench["error"] == et.code]).shape[0]),
            "caught": float(g["caught"].mean()) if len(g) else None,
            "median_weeks_to_catch": (float(g["weeks_to_catch"].dropna().median())
                                      if g["weeks_to_catch"].notna().any() else None),
            "collateral_alarms_per_episode": float(g["collateral_alarms"].mean()) if len(g) else None,
            "caught_by_rule": (g.loc[g["caught"], "rules_fired"].str.split(",").explode()
                               .value_counts().to_dict()),
            "caught_when_occupancy_above_0.85": (
                float(g.loc[g["occupancy_before"] > 0.85, "caught"].mean())
                if (g["occupancy_before"] > 0.85).any() else None),
            "caught_when_occupancy_at_most_0.85": (
                float(g.loc[g["occupancy_before"] <= 0.85, "caught"].mean())
                if (g["occupancy_before"] <= 0.85).any() else None),
        } for et in ERROR_TYPES}
    bench.to_csv(RESULTS / "rq1_planted_errors.csv", index=False)
    print("5. thresholds"); out["threshold_sensitivity"] = threshold_sensitivity(cor)

    sample = review_sample(cor)
    RESULTS.mkdir(exist_ok=True)
    sample.to_csv(RESULTS / "rq1_review_sample.csv", index=False)
    out["review_sample"] = {"file": "results/rq1_review_sample.csv", "rows": int(len(sample))}
    out["runtime_s"] = round(time.perf_counter() - t0, 1)
    print("wrote", write_json("rq1_trust_audit.json", out))

    p, ch, hl = out["prevalence"], out["chance"], out["hhs_labels"]
    print(f"\nlevels: {p['level_share']}")
    print(f"hospitals with any RED: {p['hospitals_with_any_red']} / {p['hospitals']}")
    print(f"frozen flags observed {ch['frozen_flags_observed']:,}, expected by chance "
          f"{ch['frozen_flags_expected_by_chance']:.0f}")
    print(f"HHS changed {hl['rows_hhs_changed']:,} rows; recall(RED|MISSING) "
          f"{hl['recall_red_or_missing']:.3f}; share of RAW RED that HHS changed "
          f"{hl['share_of_raw_red_that_hhs_changed']:.3f}")
    for k, v in out["planted"].items():
        print(f"  {k:16} caught {v['caught']:.2f}  collateral {v['collateral_alarms_per_episode']:.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
