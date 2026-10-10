"""The Data Steward's rules: is this hospital's weekly report believable?

Every report gets a traffic-light verdict:

======== =====================================================================
GREEN    No rule fired. Use as reported.
AMBER    A minor issue (incomplete week, small arithmetic mismatch). Usable,
         with lower confidence.
RED      A rule says the number cannot be right, or is very unlikely to be a
         real measurement. Not used for planning.
MISSING  Nothing usable was reported this week.
======== =====================================================================

Three properties a reviewer will ask about, and why each holds
-------------------------------------------------------------
**Causal.** A report for week *t* is judged using week *t* and earlier weeks
only (``shift`` within a hospital, never a negative shift). The same code could
run live the moment a report arrives; no rule peeks at the future.

**Explainable.** A verdict is a list of named rules, each with a sentence a
non-specialist can read ("same patient count, 0.1 precision, 4 weeks running").
There is no opaque score.

**Thresholds are declared, and the frozen threshold is measured.** The
frozen-census rule fires at the third identical week in a row. How often an
honest, varying census repeats *exactly* is measured from the data by
:func:`repeat_base_rate`, and the expected number of false alarms that implies
is reported next to the result (``experiments/rq1_trust_audit.py``).

Why rules and not only a statistical detector: a frozen value sits inside the
hospital's normal range, so distribution-based detectors do not see it. This
is documented for stale-value errors in other domains (Peysakhovich &
Sieradzki 2026, arXiv:2606.20079, report 0% recall for six statistical
detectors on stale values). The learned check lives in
:mod:`mahros.forecast` (a report far outside the forecast interval) and is
reported separately, so each mechanism's contribution can be measured.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd

# --------------------------------------------------------------------------- #
# Declared thresholds. Changing any of these changes results; each is swept in
# experiments/rq1_trust_audit.py --sensitivity.
# --------------------------------------------------------------------------- #

#: Below this census a hospital's count can legitimately stay the same for
#: weeks (a 6-bed unit holding 4 patients), so frozen/spike rules are off.
MIN_LEVEL = 10.0
#: Identical weekly values needed for the frozen rule (3 = two zero changes).
FROZEN_RUN = 3
#: One-week ratio outside [1/SPIKE_RATIO, SPIKE_RATIO] is a spike.
#: 2.5 catches decimal-shift (x10) and sum-for-average (x7) keying errors while
#: staying well outside real week-to-week movement (checked in the audit).
SPIKE_RATIO = 2.5
#: Census above staffed beds by more than this fraction is impossible.
#: The 5% tolerance absorbs rounding of 7-day averages and same-day surge beds.
OVER_CAPACITY_TOL = 0.05
#: |average - sum/coverage| allowed before the arithmetic is called inconsistent.
ARITH_ABS_TOL = 0.15
ARITH_REL_TOL = 0.02


@dataclass(frozen=True)
class Rule:
    code: str
    level: str          # "RED" or "AMBER"
    title: str          # short label for the UI
    explain: str        # one sentence, readable by a non-specialist


RULES: dict[str, Rule] = {r.code: r for r in [
    Rule("FROZEN_CENSUS", "RED", "Frozen patient count",
         "The number of patients was reported as exactly the same value for "
         f"{FROZEN_RUN} or more weeks running. Real patient counts change daily."),
    Rule("FROZEN_ICU", "RED", "Frozen ICU count",
         f"The ICU patient count was exactly the same for {FROZEN_RUN} or more "
         "weeks running."),
    Rule("CENSUS_OVER_BEDS", "RED", "More patients than beds",
         "More patients were reported than staffed beds exist."),
    Rule("ICU_OVER_BEDS", "RED", "More ICU patients than ICU beds",
         "More ICU patients were reported than staffed ICU beds exist."),
    Rule("ICU_BEDS_OVER_TOTAL", "RED", "ICU beds exceed all beds",
         "More ICU beds were reported than inpatient beds in total, but ICU "
         "beds are part of the inpatient total."),
    Rule("CENSUS_SPIKE", "RED", "Implausible jump in patients",
         f"The patient count changed by more than {SPIKE_RATIO}x in one week, "
         "the size of a typing error (an extra zero, or a weekly total entered "
         "as a daily average)."),
    Rule("BEDS_SPIKE", "RED", "Implausible jump in beds",
         f"The number of staffed beds changed by more than {SPIKE_RATIO}x in "
         "one week."),
    Rule("PARTIAL_WEEK", "AMBER", "Incomplete week",
         "Fewer than 7 days were reported this week, so the weekly average "
         "rests on less data."),
    Rule("ARITHMETIC", "AMBER", "Totals do not add up",
         "The reported weekly average does not equal the reported weekly sum "
         "divided by the days reported."),
    Rule("NOT_REPORTED", "MISSING", "Not reported",
         "No usable patient or bed count was reported this week."),
    Rule("SUPPRESSED_SMALL", "MISSING", "Withheld (fewer than 4)",
         "The count was below 4, so CDC withheld the exact number to protect "
         "privacy. This is not an error, but the exact value is unknown."),
]}

#: Stable bit for each rule, so flags fit in one integer column.
BIT = {code: 1 << i for i, code in enumerate(RULES)}

LEVEL_ORDER = ["GREEN", "AMBER", "RED", "MISSING"]


def _require_sorted(df: pd.DataFrame) -> None:
    """Every rule compares a row with the row above it, so order is load-bearing.

    Each hospital's rows must be contiguous and in week order. Checked rather
    than assumed, because a frame sorted by week would otherwise run silently
    and compare different hospitals with each other.
    """
    pk = df["hospital_pk"]
    blocks = int(pk.ne(pk.shift(1)).sum())
    if blocks != pk.nunique():
        raise ValueError("assess() needs each hospital's rows to be contiguous")
    same = pk.eq(pk.shift(1))
    if (df["week"].diff().dt.days.le(0) & same).any():
        raise ValueError("assess() needs rows in week order within each hospital")


def _consecutive(df: pd.DataFrame) -> pd.Series:
    """True where this row's previous row is the same hospital, one week earlier."""
    same_h = df["hospital_pk"].eq(df["hospital_pk"].shift(1))
    gap = (df["week"] - df["week"].shift(1)).dt.days
    return same_h & gap.eq(7)


def _run_length(values: pd.Series, consecutive: pd.Series) -> pd.Series:
    """Length of the current run of identical values, counting this row.

    A run breaks on any change, any missing value, a new hospital, or a
    skipped week. Only past rows are used.
    """
    same = consecutive & values.notna() & values.eq(values.shift(1))
    run_id = (~same).cumsum()
    return same.groupby(run_id).cumsum() + 1


#: Reports used as the spike reference, and how stale that reference may be.
SPIKE_WINDOW = 3
SPIKE_MAX_GAP_DAYS = 28


def _trailing_median(df: pd.DataFrame, col: str) -> pd.Series:
    """Median of the hospital's previous ``SPIKE_WINDOW`` reported values (past only)."""
    prev = df.groupby("hospital_pk", sort=False)[col].shift(1)
    return (prev.groupby(df["hospital_pk"], sort=False)
            .rolling(SPIKE_WINDOW, min_periods=1).median()
            .reset_index(level=0, drop=True)
            .reindex(df.index))


def _recent_report(df: pd.DataFrame) -> pd.Series:
    """True where the hospital's previous report is at most 4 weeks old."""
    same_h = df["hospital_pk"].eq(df["hospital_pk"].shift(1))
    gap = (df["week"] - df["week"].shift(1)).dt.days
    return same_h & gap.le(SPIKE_MAX_GAP_DAYS)


def _ratio(cur: pd.Series, prev: pd.Series) -> pd.Series:
    with np.errstate(divide="ignore", invalid="ignore"):
        return cur / prev


def assess(df: pd.DataFrame) -> pd.DataFrame:
    """Return a frame aligned with ``df``: ``flags`` (bitmask), ``level``, ``reasons``.

    ``df`` must be the canonical frame from :mod:`mahros.data.hhs`, sorted by
    hospital and week (``load`` guarantees this; it is re-checked here).
    """
    _require_sorted(df)

    cons = _consecutive(df)
    flags = np.zeros(len(df), dtype=np.int64)

    def mark(code: str, mask: pd.Series) -> None:
        nonlocal flags
        flags |= np.where(mask.fillna(False).to_numpy(), BIT[code], 0)

    used, beds = df["used"], df["beds"]
    icu_used, icu_beds = df["icu_used"], df["icu_beds"]

    # Missing: nothing to plan with. A CDC-withheld small count is told apart
    # from a report that never arrived -- the first is not the hospital's fault.
    suppressed = pd.Series(False, index=df.index)
    for m in ("used", "beds"):
        if f"{m}_suppressed" in df:
            suppressed |= df[f"{m}_suppressed"].fillna(False).astype(bool)
    missing = used.isna() | beds.isna() | beds.le(0)
    mark("SUPPRESSED_SMALL", missing & suppressed)
    mark("NOT_REPORTED", missing & ~suppressed)

    # Frozen values.
    run = _run_length(used, cons)
    mark("FROZEN_CENSUS", run.ge(FROZEN_RUN) & used.ge(MIN_LEVEL))
    icu_run = _run_length(icu_used, cons)
    mark("FROZEN_ICU", icu_run.ge(FROZEN_RUN) & icu_used.ge(MIN_LEVEL))

    # Impossible combinations.
    mark("CENSUS_OVER_BEDS", used.gt(beds * (1 + OVER_CAPACITY_TOL)) & beds.gt(0))
    mark("ICU_OVER_BEDS", icu_used.gt(icu_beds * (1 + OVER_CAPACITY_TOL))
         & icu_beds.gt(0) & icu_used.ge(1))
    mark("ICU_BEDS_OVER_TOTAL", icu_beds.gt(beds * (1 + OVER_CAPACITY_TOL)) & beds.gt(0))

    # Spikes: compared with the median of this hospital's previous 3 reports,
    # not with last week alone -- otherwise the correct value that follows a
    # one-week typo would itself look like a jump and be wrongly flagged.
    recent = _recent_report(df)
    for col, code in (("used", "CENSUS_SPIKE"), ("beds", "BEDS_SPIKE")):
        ref = _trailing_median(df, col).where(recent)
        ratio = _ratio(df[col], ref)
        big = df[col].ge(MIN_LEVEL) | ref.ge(MIN_LEVEL)
        mark(code, big & (ratio.gt(SPIKE_RATIO) | ratio.lt(1 / SPIKE_RATIO)))

    # Minor issues.
    mark("PARTIAL_WEEK", df["used_cov"].lt(7) | df["beds_cov"].lt(7))
    arith = pd.Series(False, index=df.index)
    for m in ("used", "beds"):
        avg, tot, cov = df[m], df[f"{m}_sum"], df[f"{m}_cov"]
        with np.errstate(divide="ignore", invalid="ignore"):
            implied = tot / cov
        gap = (avg - implied).abs()
        tol = np.maximum(ARITH_ABS_TOL, ARITH_REL_TOL * avg.abs())
        arith |= cov.gt(0) & avg.notna() & tot.notna() & gap.gt(tol)
    mark("ARITHMETIC", arith)

    level = np.full(len(df), "GREEN", dtype=object)
    amber = sum(BIT[c] for c, r in RULES.items() if r.level == "AMBER")
    red = sum(BIT[c] for c, r in RULES.items() if r.level == "RED")
    level[(flags & amber) > 0] = "AMBER"
    level[(flags & red) > 0] = "RED"
    level[(flags & (BIT["NOT_REPORTED"] | BIT["SUPPRESSED_SMALL"])) > 0] = "MISSING"

    out = pd.DataFrame({"flags": flags, "level": level,
                        "census_run": run.to_numpy()}, index=df.index)
    return out


def reasons(flags: int) -> list[str]:
    """Rule codes set in one bitmask, in declaration order."""
    return [code for code in RULES if flags & BIT[code]]


def explain(flags: int) -> list[dict[str, str]]:
    """Human-readable reasons for one report, for the UI and the audit log."""
    return [{"code": c, "level": RULES[c].level, "title": RULES[c].title,
             "explain": RULES[c].explain} for c in reasons(flags)]


def repeat_base_rate(df: pd.DataFrame, min_level: float = MIN_LEVEL) -> dict:
    """How often does an honest census repeat exactly from one week to the next?

    Measured on hospitals that never have a run of 3+, so the estimate is not
    inflated by the frozen series the rule is meant to catch. If an honest
    week-to-week repeat has probability ``p``, a run of ``FROZEN_RUN`` identical
    weeks happens by chance with probability about ``p ** (FROZEN_RUN - 1)``
    per eligible week -- the expected false-alarm rate of the rule.
    """
    cons = _consecutive(df)
    run = _run_length(df["used"], cons)
    ever_frozen = run.ge(FROZEN_RUN).groupby(df["hospital_pk"]).transform("any")
    prev = df["used"].shift(1).where(cons)
    ok = (~ever_frozen) & cons & df["used"].ge(min_level) & prev.ge(min_level)
    pairs = int(ok.sum())
    repeats = int((ok & df["used"].eq(prev)).sum())
    p = repeats / pairs if pairs else float("nan")
    return {
        "pairs": pairs,
        "exact_repeats": repeats,
        "p_repeat": p,
        "expected_false_alarm_per_week": p ** (FROZEN_RUN - 1) if pairs else float("nan"),
    }
