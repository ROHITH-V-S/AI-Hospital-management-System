"""Controlled error injection: how well does the Data Steward catch known errors?

Real data has no complete answer key (nobody knows every wrong report), so
detection is measured the standard way: take report sequences the Steward
already considers clean, plant one error of a known type, and see whether it
is caught. Each error type corresponds to a real-world failure mode.

Two fairness rules, both of which make the measured detection rates *lower*
rather than higher:

1. When a weekly average is corrupted, the matching weekly sum is corrupted
   consistently (``sum = average * days``). Otherwise the arithmetic check would
   catch every planted error for free, which a real typo would not allow.
2. Only RED counts as a detection. An AMBER warning does not.

Subtle errors (a 10% drift) are included on purpose: the expected answer is
"mostly not caught", and reporting that is part of the result.
"""

from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Callable

import numpy as np
import pandas as pd

from .checks import assess, reasons

#: Rows before and after the corrupted week that must be clean and consecutive.
PAD_BEFORE, PAD_AFTER = 4, 4
MIN_CENSUS = 20.0


@dataclass(frozen=True)
class ErrorType:
    code: str
    description: str          # real-world cause, for the paper's table
    weeks: int                # how many consecutive weeks are corrupted
    apply: Callable[[pd.DataFrame, list[int]], None]


def _set(df: pd.DataFrame, rows: list[int], col: str, values) -> None:
    df.loc[rows, col] = values
    cov = df.loc[rows, f"{col}_cov"].fillna(7).to_numpy()
    df.loc[rows, f"{col}_sum"] = np.asarray(df.loc[rows, col], dtype=float) * cov


def _scale(col: str, k: float):
    def f(df, rows):
        _set(df, rows, col, df.loc[rows, col].to_numpy() * k)
    return f


def _stale(df, rows):
    # The feed stops updating: the last good value is repeated.
    first = rows[0] - 1
    _set(df, rows, "used", [df.at[first, "used"]] * len(rows))


def _swap(df, rows):
    u = df.loc[rows, "used"].to_numpy().copy()
    b = df.loc[rows, "beds"].to_numpy().copy()
    _set(df, rows, "used", b)
    _set(df, rows, "beds", u)


def _zero(df, rows):
    _set(df, rows, "used", [0.0] * len(rows))


ERROR_TYPES: list[ErrorType] = [
    ErrorType("STALE_FEED", "Reporting feed stopped updating; last value repeated "
              "for 3 more weeks", 3, _stale),
    ErrorType("EXTRA_ZERO", "Census typed with an extra zero (x10)", 1, _scale("used", 10)),
    ErrorType("LOST_DECIMAL", "Census typed missing a digit (/10)", 1, _scale("used", 0.1)),
    ErrorType("SUM_AS_AVERAGE", "Weekly total entered as the daily average (x7)", 1,
              _scale("used", 7)),
    ErrorType("FIELD_SWAP", "Beds and patients entered in each other's field", 1, _swap),
    ErrorType("ZERO_ENTRY", "Blank submission recorded as zero patients", 1, _zero),
    ErrorType("BEDS_EXTRA_ZERO", "Bed count typed with an extra zero (x10)", 1,
              _scale("beds", 10)),
    ErrorType("DRIFT_25", "Census overstated by 25% for one week", 1, _scale("used", 1.25)),
    ErrorType("DRIFT_10", "Census overstated by 10% for 4 weeks", 4, _scale("used", 1.10)),
]


def eligible_anchors(df: pd.DataFrame, levels: pd.Series, weeks: int) -> list[int]:
    """Row positions where a clean, consecutive window surrounds ``weeks`` rows."""
    n = len(df)
    pk = df["hospital_pk"].to_numpy()
    wk = df["week"].to_numpy().astype("datetime64[D]").astype(np.int64)
    green = levels.to_numpy() == "GREEN"
    used = df["used"].to_numpy()
    span = PAD_BEFORE + weeks + PAD_AFTER
    # A window is valid if every row is GREEN, the same hospital, 7 days apart.
    ok_step = np.zeros(n, dtype=bool)
    ok_step[1:] = (pk[1:] == pk[:-1]) & (wk[1:] - wk[:-1] == 7) & green[1:] & green[:-1]
    # run[i] = number of consecutive ok steps ending at i
    run = np.zeros(n, dtype=np.int64)
    for i in range(1, n):
        run[i] = run[i - 1] + 1 if ok_step[i] else 0
    anchors = []
    for end in np.nonzero(run >= span - 1)[0]:
        start = end - (span - 1)
        a = start + PAD_BEFORE
        if np.nanmin(used[a: a + weeks]) >= MIN_CENSUS:
            anchors.append(int(a))
    return anchors


def run_benchmark(df: pd.DataFrame, levels: pd.Series, per_type: int = 500,
                  seed: int = 2026) -> pd.DataFrame:
    """One row per planted error: type, hospital, week, caught?, collateral alarms."""
    rng = random.Random(seed)
    rows = []
    by_pk = {pk: idx for pk, idx in df.groupby("hospital_pk", sort=False).indices.items()}
    for et in ERROR_TYPES:
        anchors = eligible_anchors(df, levels, et.weeks)
        picks = rng.sample(anchors, min(per_type, len(anchors)))
        for a in picks:
            pk = df.at[a, "hospital_pk"]
            idx = by_pk[pk]
            series = df.iloc[idx].copy().reset_index(drop=True)
            local = a - idx[0]
            target = list(range(local, local + et.weeks))
            before = assess(series)["level"].to_numpy()
            et.apply(series, target)
            after = assess(series)
            lv = after["level"].to_numpy()
            caught = bool(np.isin(lv[target], ["RED", "MISSING"]).any())
            first = next((i - local for i in target if lv[i] in ("RED", "MISSING")), None)
            window = range(max(0, local - PAD_BEFORE),
                           min(len(series), local + et.weeks + PAD_AFTER))
            collateral = sum(1 for i in window if i not in target
                             and before[i] == "GREEN" and lv[i] in ("RED", "MISSING"))
            fired = sorted({c for i in target for c in reasons(int(after["flags"].iloc[i]))})
            rows.append({
                "error": et.code, "hospital_pk": pk,
                "week": series.at[local, "week"], "caught": caught,
                "weeks_to_catch": first, "collateral_alarms": collateral,
                "rules_fired": ",".join(fired),
                "occupancy_before": float(series.at[local - 1, "used"] / series.at[local - 1, "beds"]),
            })
    return pd.DataFrame(rows)
