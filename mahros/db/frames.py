"""Read the platform's working frames back out of the database.

``assessed_frame`` returns exactly the columns ``mahros.pipeline.assessed``
returns (plus the v0.3 extra fields), so the agents run unchanged on database
data. ``tests/test_postgres.py`` checks a full state-week gives identical
numbers from both sources.
"""

from __future__ import annotations

import pandas as pd

from ..data import hhs
from .io import read_frame

_BOOL = ["metro", "beds_suppressed", "used_suppressed", "icu_beds_suppressed",
         "icu_used_suppressed", "is_corrected"]


def _bool(s: pd.Series) -> pd.Series:
    if s.dtype == bool:
        return s
    return s.map({True: True, False: False, "t": True, "f": False, "True": True,
                  "False": False, 1: True, 0: False}).fillna(False).astype(bool)


def assessed_frame(engine, states: list[str] | None = None) -> pd.DataFrame:
    where = ""
    if states:
        where = "WHERE h.state IN (" + ",".join(f"'{s}'" for s in states) + ")"
    extra = ", ".join(f"r.{c}" for c in hhs.EXTRA_FIELDS)
    sql = f"""
      SELECT r.hospital_pk, h.ccn, r.week, h.state, r.name, r.city, h.zip, h.subtype, h.fips,
             r.metro, r.lat, r.lon,
             r.beds, r.beds_suppressed, r.beds_sum, r.beds_cov,
             r.used, r.used_suppressed, r.used_sum, r.used_cov,
             r.icu_beds, r.icu_beds_suppressed, r.icu_beds_sum, r.icu_beds_cov,
             r.icu_used, r.icu_used_suppressed, r.icu_used_sum, r.icu_used_cov,
             r.total_beds, r.covid_used, r.n_suppressed, r.is_corrected, {extra},
             v.flags, v.level, v.census_run
      FROM weekly_reports r
      JOIN hospitals h ON h.hospital_pk = r.hospital_pk
      JOIN trust_verdicts v ON v.hospital_pk = r.hospital_pk AND v.week = r.week
      {where}
      ORDER BY r.hospital_pk, r.week"""
    df = read_frame(engine, sql)
    df["hospital_pk"] = df["hospital_pk"].astype(str)
    df["week"] = pd.to_datetime(df["week"])
    for c in _BOOL:
        df[c] = _bool(df[c])
    df["flags"] = df["flags"].astype("int64")
    df["n_suppressed"] = df["n_suppressed"].astype("int16")
    df["census_run"] = df["census_run"].astype("Int64")
    return df.reset_index(drop=True)


def forecasts_frame(engine) -> pd.DataFrame:
    df = read_frame(engine, """
      SELECT hospital_pk, week, target_week, ml_pred, ml_hi, raw_pred, raw_hi,
             persist_pred, persist_hi, beds_0, occ_0 FROM forecasts ORDER BY id""")
    df["hospital_pk"] = df["hospital_pk"].astype(str)
    df["week"] = pd.to_datetime(df["week"])
    df["target_week"] = pd.to_datetime(df["target_week"])
    return df


def loaded(engine) -> bool:
    """True once the loader has filled the database at least once."""
    try:
        d = read_frame(engine, "SELECT key FROM data_manifest WHERE key = '_pipeline'")
        return len(d) > 0
    except Exception:
        return False
