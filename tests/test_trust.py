"""Unit tests for the Data Steward rules.

These use tiny hand-built frames to pin each rule's logic. They test code, not
findings: no number from these frames appears in any result.
"""

import numpy as np
import pandas as pd
import pytest

from mahros.trust import BIT, assess, explain, repeat_base_rate
from mahros.trust.checks import FROZEN_RUN


def frame(used, beds=None, pk="H1", start="2021-01-03", icu_used=None, icu_beds=None,
          cov=7):
    n = len(used)
    beds = beds if beds is not None else [100.0] * n
    weeks = pd.date_range(start, periods=n, freq="7D")
    used = [np.nan if u is None else float(u) for u in used]
    beds = [np.nan if b is None else float(b) for b in beds]
    df = pd.DataFrame({
        "hospital_pk": pk, "week": weeks,
        "used": used, "beds": beds,
        "used_sum": [u * cov if u == u else np.nan for u in used],
        "beds_sum": [b * cov if b == b else np.nan for b in beds],
        "used_cov": cov, "beds_cov": cov,
        "icu_used": icu_used if icu_used is not None else [5.0] * n,
        "icu_beds": icu_beds if icu_beds is not None else [10.0] * n,
    })
    return df


def has(out, i, code):
    return bool(out["flags"].iloc[i] & BIT[code])


def test_clean_series_is_green():
    out = assess(frame([60, 62, 59, 64, 61, 63]))
    assert (out["level"] == "GREEN").all()


def test_frozen_fires_on_third_identical_week_not_before():
    out = assess(frame([60, 55, 55, 55, 55, 58]))
    assert not has(out, 1, "FROZEN_CENSUS")
    assert not has(out, 2, "FROZEN_CENSUS")          # two identical: allowed
    assert has(out, 3, "FROZEN_CENSUS")              # third identical: flagged
    assert has(out, 4, "FROZEN_CENSUS")
    assert not has(out, 5, "FROZEN_CENSUS")          # value changed: run over
    assert FROZEN_RUN == 3


def test_frozen_ignores_small_census():
    out = assess(frame([4, 4, 4, 4, 4]))
    assert not any(has(out, i, "FROZEN_CENSUS") for i in range(5))


def test_frozen_run_breaks_on_skipped_week():
    df = frame([55, 55, 55, 55])
    df.loc[2:, "week"] = df.loc[2:, "week"] + pd.Timedelta(days=7)   # a gap
    out = assess(df)
    assert not has(out, 2, "FROZEN_CENSUS")
    assert not has(out, 3, "FROZEN_CENSUS")


def test_frozen_does_not_carry_across_hospitals():
    a = frame([55, 55], pk="A")
    b = frame([55, 55], pk="B")
    out = assess(pd.concat([a, b], ignore_index=True))
    assert not out["flags"].apply(lambda f: bool(f & BIT["FROZEN_CENSUS"])).any()


def test_more_patients_than_beds_is_red():
    out = assess(frame([60, 120], beds=[100, 100]))
    assert has(out, 1, "CENSUS_OVER_BEDS")
    assert out["level"].iloc[1] == "RED"


def test_rounding_tolerance_on_capacity():
    out = assess(frame([60, 104], beds=[100, 100]))   # within 5%
    assert not has(out, 1, "CENSUS_OVER_BEDS")


def test_decimal_shift_spike_flags_the_typo_but_not_the_recovery():
    out = assess(frame([60, 62, 61, 610, 63, 62]))
    assert has(out, 3, "CENSUS_SPIKE")
    assert not has(out, 4, "CENSUS_SPIKE")            # median reference absorbs the typo


def test_icu_rules():
    out = assess(frame([60, 60.5], icu_used=[5, 15], icu_beds=[10, 10]))
    assert has(out, 1, "ICU_OVER_BEDS")
    out = assess(frame([60, 61], beds=[100, 100], icu_beds=[10, 150]))
    assert has(out, 1, "ICU_BEDS_OVER_TOTAL")


def test_missing_is_its_own_level():
    out = assess(frame([60, None, 61]))
    assert out["level"].iloc[1] == "MISSING"


def test_suppressed_small_count_is_not_called_unreported():
    df = frame([60, None, 61])
    df["used_suppressed"] = [False, True, False]
    out = assess(df)
    assert out["level"].iloc[1] == "MISSING"
    assert has(out, 1, "SUPPRESSED_SMALL")
    assert not has(out, 1, "NOT_REPORTED")


def test_partial_week_is_amber():
    df = frame([60, 61])
    df.loc[1, "used_cov"] = 5
    df.loc[1, "used_sum"] = 61 * 5
    out = assess(df)
    assert out["level"].iloc[1] == "AMBER"
    assert has(out, 1, "PARTIAL_WEEK")


def test_arithmetic_mismatch_is_amber():
    df = frame([60, 61])
    df.loc[1, "used_sum"] = 61 * 7 + 30      # sum disagrees with average
    out = assess(df)
    assert has(out, 1, "ARITHMETIC")


def test_rules_are_causal():
    """Appending future weeks must never change the verdict on earlier weeks."""
    base = frame([60, 55, 55, 70, 610, 62])
    longer = frame([60, 55, 55, 70, 610, 62, 62, 62, 62, 1000])
    a = assess(base)
    b = assess(longer).iloc[: len(base)]
    assert (a["flags"].to_numpy() == b["flags"].to_numpy()).all()


def test_every_flag_has_an_explanation():
    out = assess(frame([60, 55, 55, 55, 610]))
    for f in out["flags"]:
        for item in explain(int(f)):
            assert item["explain"] and item["title"]


def test_repeat_base_rate_excludes_frozen_hospitals():
    honest = frame([60, 61, 61, 62, 63], pk="A")      # one honest repeat
    frozen = frame([50, 50, 50, 50, 50], pk="B")      # excluded entirely
    r = repeat_base_rate(pd.concat([honest, frozen], ignore_index=True))
    assert r["pairs"] == 4
    assert r["exact_repeats"] == 1
    assert r["p_repeat"] == pytest.approx(0.25)


def test_unsorted_input_is_rejected():
    df = frame([60, 61, 62]).iloc[::-1].reset_index(drop=True)
    with pytest.raises(ValueError):
        assess(df)


def test_week_major_order_is_rejected():
    """Interleaved hospitals would make every rule compare the wrong rows."""
    a, b = frame([55, 55, 55], pk="A"), frame([55, 55, 55], pk="B")
    df = pd.concat([a, b]).sort_values(["week", "hospital_pk"]).reset_index(drop=True)
    with pytest.raises(ValueError):
        assess(df)
