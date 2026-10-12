"""Check that the numbers quoted in the docs are the numbers in results/.

    python experiments/check_doc_numbers.py

Each claim below rebuilds a figure from a results file, formats it the way the
docs write it, and checks that exact text appears in every document listed.
If a result changes (or a doc is edited by hand), this fails and says which
claim and which document. It checks the headline figures listed here; it does
not parse every number in the prose.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
R = lambda name: json.loads((ROOT / "results" / f"{name}.json").read_text())

README, GUIDE, METHODS, PROV = "README.md", "docs/REVIEW_GUIDE.md", "docs/METHODS.md", "docs/DATA_PROVENANCE.md"


def p1(x):          # 0.957 -> "95.7%"
    return f"{100 * x:.1f}%"


def p0(x):          # 0.398 -> "40%"
    return f"{100 * x:.0f}%"


def m1(x):          # 13.23 -> "13.2"
    return f"{x:.1f}"


def signed(x):      # -6.67 -> "-6.7"
    return f"{x:.1f}"


def claims() -> list[tuple[str, str, list[str]]]:
    e, s, t = R("emergency_eval"), R("surge_warning"), R("staffing_check")
    r1, r2, r3 = R("rq1_trust_audit"), R("rq2_forecast"), R("rq3_coordination")
    S, cN, cI = e["summary"], e["comparisons"]["mahros_vs_phone_nearest"], e["comparisons"]["mahros_vs_phone_informed"]
    sens = [v["ttb_mean"] for v in e["sensitivity"].values()]
    M, cmp = s["methods"], s["comparisons"]["model_vs_near_threshold"]
    A, B = t["periods"]["2020-08..2022-12"], t["periods"]["2023-01..2024-04"]
    p, h1, h2 = r1["prevalence"], r2["horizons"]["1"], r2["horizons"]["2"]
    C = []
    add = lambda label, text, docs: C.append((label, text, docs))
    # ---------------- emergency
    add("AZ hospitals", f"{e['states']['AZ']['hospitals']}", [README, METHODS, PROV])
    add("MA hospitals", f"{e['states']['MA']['hospitals']}", [README, METHODS, PROV])
    add("POS matched AZ", f"{e['states']['AZ']['pos_matched']} of {e['states']['AZ']['hospitals']}", [METHODS, PROV])
    add("MAHROS mean time to bed", f"{m1(S['mahros']['ttb_mean'])} min", [README, METHODS, GUIDE])
    add("phone nearest mean", f"{m1(S['phone_nearest']['ttb_mean'])}", [README, METHODS, GUIDE])
    add("phone informed mean", f"{m1(S['phone_informed']['ttb_mean'])}", [README, METHODS, GUIDE])
    add("MAHROS p90", f"{m1(S['mahros']['ttb_p90'])}", [README, METHODS, GUIDE])
    add("phone nearest p90", f"{m1(S['phone_nearest']['ttb_p90'])}", [README, METHODS, GUIDE])
    add("phone informed p90", f"{m1(S['phone_informed']['ttb_p90'])}", [README, METHODS])
    add("in window MAHROS", p1(S["mahros"]["within_window"]), [README, METHODS, GUIDE])
    add("in window phone", p1(S["phone_nearest"]["within_window"]), [README, METHODS, GUIDE])
    add("placed MAHROS", p1(S["mahros"]["placed"]), [README, METHODS, GUIDE])
    add("placed phone", p1(S["phone_nearest"]["placed"]), [README, METHODS, GUIDE])
    add("diff vs nearest", f"{signed(cN['ttb_mean']['mean_diff'])} min", [README, METHODS])
    add("diff CI", f"{signed(cN['ttb_mean']['ci95'][0])} to {signed(cN['ttb_mean']['ci95'][1])}", [README, METHODS])
    add("p90 diff", f"{signed(cN['ttb_p90']['mean_diff'])}", [README, METHODS])
    add("diff vs informed", f"{signed(cI['ttb_mean']['mean_diff'])} min", [METHODS])
    add("sensitivity max", f"{signed(min(sens))}", [README, METHODS])
    add("sensitivity min", f"{signed(max(sens))}", [README, METHODS])
    add("sensitivity range (guide)", f"{abs(max(sens)):.1f} to {abs(min(sens)):.1f} minutes", [GUIDE])
    add("calibration", p1(e["calibration"]["total_simulated_over_reported"]), [README, METHODS, GUIDE])
    add("phone calls nearest", f"{S['phone_nearest']['calls_mean']:.2f}", [METHODS])
    # ---------------- surge
    add("areas", f"{s['rows']['neighbourhoods']:,}", [README, METHODS])
    add("model F1", f"{M['model']['test_onset']['f1']:.2f}", [README, METHODS, GUIDE])
    add("simple rule F1", f"{M['near_threshold']['test_onset']['f1']:.2f}", [README, METHODS, GUIDE])
    add("neighbours F1", f"{M['neighbours']['test_onset']['f1']:.2f}", [README, GUIDE])
    add("model precision", p0(M["model"]["test_onset"]["precision"]), [README, METHODS])
    add("model recall", p0(M["model"]["test_onset"]["recall"]), [README, METHODS])
    add("warned >=1 week", p0(M["model"]["lead"]["warned_1_week_or_more"]), [README, METHODS, GUIDE])
    add("F1 gain", f"+{100 * cmp['diff']:.1f} F1 points", [README, METHODS])
    add("F1 gain CI", f"{100 * cmp['ci95'][0]:.1f} to {100 * cmp['ci95'][1]:.1f}", [README, METHODS])
    add("onset base rate", p1(s["onset_base_rate_test"]), [METHODS])
    add("crossing events", f"{M['model']['lead']['events']:,}", [METHODS])
    # ---------------- staffing
    add("staff rho 2020-22", f"{A['within_state_spearman_median']:.2f}", [README, METHODS])
    add("states positive", f"{A['states_positive']} of {A['states_tested']}", [README, METHODS])
    add("staff rho 2023-24", f"{B['within_state_spearman_median']:.2f}", [README, METHODS])
    add("real share short", p1(A["mean_real_share"]), [README, METHODS])
    add("estimated share short", p1(A["mean_est_share"]), [README, METHODS])
    # ---------------- RQ1-RQ3 (headline)
    add("RED share", p1(p["level_share"]["RED"]), [README, GUIDE, METHODS])
    add("hospitals with RED", f"{p['hospitals_with_any_red']:,} of {p['hospitals']:,}", [README, METHODS])
    add("frozen observed", f"{r1['chance']['frozen_flags_observed']:,}", [README, GUIDE, METHODS])
    add("enrichment", f"{r1['hhs_labels']['enrichment_red_vs_green']:.1f}", [README, GUIDE, METHODS])
    add("MAE persistence h1", f"{h1['mae_points']['persistence']:.2f}", [README, GUIDE, METHODS])
    add("MAE model h1", f"{h1['mae_points']['model_trusted']:.2f}", [README, GUIDE, METHODS])
    add("MAE model h2", f"{h2['mae_points']['model_trusted']:.2f}", [README, METHODS])
    add("RQ3 MAHROS", p1(r3["arms"]["mahros"]["share_of_overload_absorbed"]), [README, GUIDE, METHODS])
    add("RQ3 oracle", p1(r3["arms"]["oracle"]["share_of_overload_absorbed"]), [README, GUIDE, METHODS])
    return C


def main() -> int:
    docs = {}
    bad = []
    C = claims()
    for label, text, files in C:
        for f in files:
            if f not in docs:
                docs[f] = (ROOT / f).read_text(encoding="utf-8")
            if text not in docs[f]:
                bad.append(f"  {f}: '{text}' ({label}) not found")
    checks = sum(len(f) for _, _, f in C)
    if bad:
        print(f"DOC NUMBER CHECK FAILED: {len(bad)} of {checks} checks")
        print("\n".join(bad))
        return 1
    print(f"Doc number check OK: {len(C)} figures, {checks} checks across {len(docs)} documents.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
