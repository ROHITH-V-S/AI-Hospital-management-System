"""The national HHS facility-level hospital capacity data -- fetch, store, load.

Source
------
*COVID-19 Reported Patient Impact and Hospital Capacity by Facility*,
U.S. Department of Health & Human Services, published on healthdata.gov.
Public domain. Facility-level weekly operational reporting; no patient-level
data. Collection ended 2024-04-21 (the federal mandate lapsed 2024-04-30).

Two versions are published, and this module keeps both:

``corrected`` (``anag-cw7u``)
    The version HHS recommends. Since 2021-05-08 HHS "smooths out keyed-in data
    errors" and marks the rows it changed with ``is_corrected``.
``raw`` (``uqq2-txqb``)
    The same reports before that correction.

Keeping both is deliberate: the rows HHS itself corrected are the closest thing
to a government-labelled error set that exists, and the trust agent is
evaluated against them (``experiments/rq1_trust_audit.py``).

Conventions -- every one of these is a decision a reviewer may ask about
------------------------------------------------------------------------
* ``-999999`` is CDC small-number suppression (a true value below 4). It is
  stored as **missing**, never as zero, and counted in ``n_suppressed``.
* Bed and census figures are **7-day averages** of daily reports. ``*_sum`` and
  ``*_cov`` (days reported) are kept because ``avg == sum / cov`` is an
  internal consistency check the trust agent uses.
* A row is one hospital-week, keyed by ``(hospital_pk, week)``. ``hospital_pk``
  is HHS's facility key; it equals the CMS Certification Number for most
  hospitals but not all, so ``ccn`` is kept separately.

Nothing in this module changes a reported value. Cleaning decisions live in
:mod:`mahros.trust`, where they are visible and testable.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[2]
#: Large downloaded files. Git-ignored; reproducible from the manifest.
CACHE = ROOT / "data" / "cache"
#: Small, committed record of exactly which data every result was built from.
MANIFEST = ROOT / "data" / "manifest.json"

BASE = "https://healthdata.gov/resource"


@dataclass(frozen=True)
class Dataset:
    key: str
    socrata_id: str
    title: str


DATASETS = {
    "corrected": Dataset(
        "corrected", "anag-cw7u",
        "COVID-19 Reported Patient Impact and Hospital Capacity by Facility"),
    "raw": Dataset(
        "raw", "uqq2-txqb",
        "COVID-19 Reported Patient Impact and Hospital Capacity by Facility -- RAW"),
}

#: Source field -> short name used everywhere in MAHROS.
ID_FIELDS = {
    "hospital_pk": "hospital_pk",
    "ccn": "ccn",
    "collection_week": "week",
    "state": "state",
    "hospital_name": "name",
    "city": "city",
    "zip": "zip",
    "hospital_subtype": "subtype",
    "fips_code": "fips",
    "is_metro_micro": "metro",
    "geocoded_hospital_address": "geo",
}

#: Each measure is published as a 7-day average, a 7-day sum and a coverage
#: count (days reported). Short name -> source stem.
MEASURES = {
    "beds": "inpatient_beds",                          # staffed inpatient beds
    "used": "inpatient_beds_used",                     # inpatient census
    "icu_beds": "total_staffed_adult_icu_beds",        # staffed adult ICU beds
    "icu_used": "staffed_adult_icu_bed_occupancy",     # adult ICU census
}
#: Extra averages used only as forecasting features.
EXTRA_AVG = {
    "total_beds": "total_beds_7_day_avg",
    "covid_used": "inpatient_beds_used_covid_7_day_avg",
}

SUPPRESSED = -999999.0

#: Bump whenever `canonical` changes, so a stale tidy cache is never reused.
SCHEMA_VERSION = 2


def _source_fields(dataset: Dataset) -> list[str]:
    fields = list(ID_FIELDS)
    for stem in MEASURES.values():
        fields += [f"{stem}_7_day_avg", f"{stem}_7_day_sum", f"{stem}_7_day_coverage"]
    fields += list(EXTRA_AVG.values())
    if dataset.key == "corrected":
        fields.append("is_corrected")
    return fields


def value_columns() -> list[str]:
    """Every numeric column in the canonical frame, in a stable order."""
    cols = []
    for short in MEASURES:
        cols += [short, f"{short}_sum", f"{short}_cov"]
    return cols + list(EXTRA_AVG)


# --------------------------------------------------------------------------- #
# Fetch
# --------------------------------------------------------------------------- #

def _get(url: str, retries: int = 4) -> bytes:
    last = None
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(url, timeout=600) as resp:
                return resp.read()
        except Exception as exc:  # network hiccups are retried, then raised
            last = exc
            time.sleep(5 * (attempt + 1))
    raise RuntimeError(f"failed to fetch {url}: {last}")


def fetch(key: str, page: int = 50_000, log=print) -> Path:
    """Download one dataset in full and store it as Parquet. Returns the path.

    Paged on Socrata's internal row id so pages never overlap or skip rows
    even if the server orders ties differently between requests.
    """
    ds = DATASETS[key]
    CACHE.mkdir(parents=True, exist_ok=True)
    fields = _source_fields(ds)
    frames, offset = [], 0
    while True:
        query = urllib.parse.urlencode({
            "$select": ",".join(fields),
            "$order": ":id",
            "$limit": page,
            "$offset": offset,
        })
        raw = _get(f"{BASE}/{ds.socrata_id}.csv?{query}")
        chunk = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
        frames.append(chunk)
        log(f"  {key}: {offset + len(chunk):,} rows")
        if len(chunk) < page:
            break
        offset += page
    df = pd.concat(frames, ignore_index=True)
    out = CACHE / f"hhs_{key}_source.parquet"
    df.to_parquet(out, index=False)
    _record_manifest(ds, out, len(df))
    return out


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def _record_manifest(ds: Dataset, path: Path, rows: int) -> None:
    meta_url = f"https://healthdata.gov/api/views/{ds.socrata_id}.json"
    try:
        meta = json.loads(_get(meta_url))
        updated = datetime.fromtimestamp(meta.get("rowsUpdatedAt", 0), timezone.utc)
        updated = updated.isoformat()
    except Exception:
        updated = "unknown"
    manifest = json.loads(MANIFEST.read_text()) if MANIFEST.exists() else {}
    manifest[ds.key] = {
        "title": ds.title,
        "socrata_id": ds.socrata_id,
        "url": f"https://healthdata.gov/d/{ds.socrata_id}",
        "publisher": "U.S. Department of Health & Human Services",
        "licence": "U.S. Public Domain",
        "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source_rows_updated_at": updated,
        "rows": rows,
        "file": path.name,
        "sha256": _sha256(path),
    }
    MANIFEST.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST.write_text(json.dumps(manifest, indent=2) + "\n")


# --------------------------------------------------------------------------- #
# Load
# --------------------------------------------------------------------------- #

def _parse_point(text: str) -> tuple[float, float]:
    """``POINT (lon lat)`` -> (lat, lon). Missing or malformed -> NaN."""
    if not isinstance(text, str) or "(" not in text:
        return (np.nan, np.nan)
    try:
        lon, lat = text[text.index("(") + 1: text.index(")")].split()
        return (float(lat), float(lon))
    except ValueError:
        return (np.nan, np.nan)


def canonical(source: pd.DataFrame, key: str) -> pd.DataFrame:
    """Rename, type and tidy one source frame. Values are never altered."""
    ds = DATASETS[key]
    df = pd.DataFrame({short: source[src] for src, short in ID_FIELDS.items()})
    df["week"] = pd.to_datetime(df["week"].str.slice(0, 10))
    df["metro"] = df["metro"].str.lower().eq("true")
    latlon = df.pop("geo").map(_parse_point)
    df["lat"] = [p[0] for p in latlon]
    df["lon"] = [p[1] for p in latlon]

    n_suppressed = np.zeros(len(df), dtype=np.int16)
    for short, stem in MEASURES.items():
        for suffix, col in (("_7_day_avg", short), ("_7_day_sum", f"{short}_sum"),
                            ("_7_day_coverage", f"{short}_cov")):
            vals = pd.to_numeric(source[stem + suffix], errors="coerce")
            sup = vals.eq(SUPPRESSED)
            n_suppressed += sup.to_numpy(dtype=np.int16)
            df[col] = vals.mask(sup)
            if suffix == "_7_day_avg":
                # Kept per measure: a withheld small count is a real value
                # below 4, not a missing report, and the Steward says so.
                df[f"{short}_suppressed"] = sup.to_numpy()
    for short, src in EXTRA_AVG.items():
        vals = pd.to_numeric(source[src], errors="coerce")
        sup = vals.eq(SUPPRESSED)
        n_suppressed += sup.to_numpy(dtype=np.int16)
        df[short] = vals.mask(sup)
    df["n_suppressed"] = n_suppressed

    if ds.key == "corrected":
        df["is_corrected"] = source["is_corrected"].str.lower().eq("true")
    else:
        df["is_corrected"] = False

    df = df.sort_values(["hospital_pk", "week"], kind="stable").reset_index(drop=True)
    return df


def load(key: str = "corrected") -> pd.DataFrame:
    """The canonical frame for one dataset, from the local cache.

    Raises with the exact command to run if the data has not been fetched.
    """
    tidy = CACHE / f"hhs_{key}_v{SCHEMA_VERSION}.parquet"
    source = CACHE / f"hhs_{key}_source.parquet"
    if tidy.exists() and source.exists() and tidy.stat().st_mtime >= source.stat().st_mtime:
        return pd.read_parquet(tidy)
    if not source.exists():
        raise FileNotFoundError(
            f"{source} not found. Run:  python experiments/fetch_national.py")
    df = canonical(pd.read_parquet(source), key)
    df.to_parquet(tidy, index=False)
    return df


def duplicate_keys(df: pd.DataFrame) -> pd.DataFrame:
    """Rows sharing a (hospital_pk, week) key. Should be empty; checked, not assumed."""
    return df[df.duplicated(["hospital_pk", "week"], keep=False)]


# --------------------------------------------------------------------------- #
# v0.3 additions: extra facility fields and the state staffing series.
#
# Kept in their OWN cache files with their own fingerprints, so the file the
# RQ1-RQ3 results were built from (hhs_corrected_source.parquet) is untouched
# and those results stay byte-reproducible.
# --------------------------------------------------------------------------- #

#: Extra per-hospital weekly fields from the same corrected dataset
#: (``anag-cw7u``). Short name -> source field. Checked against the live
#: dataset metadata on 2026-10-11 before use.
EXTRA_FIELDS = {
    "ed_visits": "previous_day_total_ed_visits_7_day_sum",
    "covid_ed_visits": "previous_day_covid_ed_visits_7_day_sum",
    "covid_adm_adult": "previous_day_admission_adult_covid_confirmed_7_day_sum",
    "covid_adm_peds": "previous_day_admission_pediatric_covid_confirmed_7_day_sum",
    "flu_adm": "previous_day_admission_influenza_confirmed_7_day_sum",
    "flu_used": "total_patients_hospitalized_confirmed_influenza_7_day_avg",
    "flu_icu": "icu_patients_confirmed_influenza_7_day_avg",
    "covid_icu": "staffed_icu_adult_patients_confirmed_covid_7_day_avg",
    "picu_beds": "total_staffed_pediatric_icu_beds_7_day_avg",
    "picu_used": "staffed_pediatric_icu_bed_occupancy_7_day_avg",
}

#: State-level daily series (``g62h-syeh``, "COVID-19 Reported Patient Impact
#: and Hospital Capacity by State Timeseries (RAW)"). Counts of hospitals.
STATE_STAFFING = Dataset(
    "state_staffing", "g62h-syeh",
    "COVID-19 Reported Patient Impact and Hospital Capacity by State Timeseries (RAW)")
STAFFING_FIELDS = {
    "shortage_today_yes": "critical_staffing_shortage_today_yes",
    "shortage_today_no": "critical_staffing_shortage_today_no",
    "shortage_today_not_reported": "critical_staffing_shortage_today_not_reported",
    "shortage_week_yes": "critical_staffing_shortage_anticipated_within_week_yes",
    "shortage_week_no": "critical_staffing_shortage_anticipated_within_week_no",
    "shortage_week_not_reported": "critical_staffing_shortage_anticipated_within_week_not_reported",
}
EXTRA = Dataset("corrected_extra", "anag-cw7u",
                "COVID-19 Reported Patient Impact and Hospital Capacity by Facility "
                "-- extra fields (ER visits, COVID/flu admissions, paediatric ICU)")


def _fetch_paged(socrata_id: str, fields: list[str], page: int, log, label: str,
                 order: str = ":id") -> pd.DataFrame:
    # Each page is kept on disk until the whole download finishes, so a
    # network failure resumes where it stopped instead of starting over.
    parts = CACHE / f"_parts_{label}"
    parts.mkdir(parents=True, exist_ok=True)
    frames, offset = [], 0
    while True:
        part = parts / f"{offset:09d}.parquet"
        if part.exists():
            chunk = pd.read_parquet(part)
        else:
            query = urllib.parse.urlencode({
                "$select": ",".join(fields), "$order": order,
                "$limit": page, "$offset": offset})
            raw = _get(f"{BASE}/{socrata_id}.csv?{query}", retries=8)
            chunk = pd.read_csv(io.BytesIO(raw), dtype=str, keep_default_na=False)
            chunk.to_parquet(part, index=False)
        frames.append(chunk)
        log(f"  {label}: {offset + len(chunk):,} rows")
        if len(chunk) < page:
            break
        offset += page
    df = pd.concat(frames, ignore_index=True)
    for p in parts.glob("*.parquet"):
        p.unlink()
    parts.rmdir()
    return df


def fetch_extra(page: int = 50_000, log=print) -> Path:
    """Download the extra facility fields (same dataset, same row keys)."""
    CACHE.mkdir(parents=True, exist_ok=True)
    fields = ["hospital_pk", "collection_week", *EXTRA_FIELDS.values()]
    df = _fetch_paged(EXTRA.socrata_id, fields, page, log, EXTRA.key)
    out = CACHE / "hhs_corrected_extra_source.parquet"
    df.to_parquet(out, index=False)
    _record_manifest(EXTRA, out, len(df))
    return out


def fetch_state_staffing(page: int = 50_000, log=print) -> Path:
    CACHE.mkdir(parents=True, exist_ok=True)
    fields = ["state", "date", *STAFFING_FIELDS.values()]
    df = _fetch_paged(STATE_STAFFING.socrata_id, fields, page, log, STATE_STAFFING.key)
    out = CACHE / "hhs_state_staffing_source.parquet"
    df.to_parquet(out, index=False)
    _record_manifest(STATE_STAFFING, out, len(df))
    return out


def load_extra() -> pd.DataFrame:
    """Extra fields keyed by (hospital_pk, week). -999999 -> missing + flag."""
    src = CACHE / "hhs_corrected_extra_source.parquet"
    if not src.exists():
        raise FileNotFoundError(f"{src} not found. Run:  python experiments/fetch_extra.py")
    s = pd.read_parquet(src)
    df = pd.DataFrame({"hospital_pk": s["hospital_pk"],
                       "week": pd.to_datetime(s["collection_week"].str.slice(0, 10))})
    for short, field in EXTRA_FIELDS.items():
        vals = pd.to_numeric(s[field], errors="coerce")
        sup = vals.eq(SUPPRESSED)
        df[short] = vals.mask(sup)
        df[f"{short}_suppressed"] = sup.to_numpy()
    return df.sort_values(["hospital_pk", "week"], kind="stable").reset_index(drop=True)


def load_state_staffing() -> pd.DataFrame:
    """Daily state series: counts of hospitals reporting a critical staffing shortage."""
    src = CACHE / "hhs_state_staffing_source.parquet"
    if not src.exists():
        raise FileNotFoundError(f"{src} not found. Run:  python experiments/fetch_extra.py")
    s = pd.read_parquet(src)
    df = pd.DataFrame({"state": s["state"],
                       "date": pd.to_datetime(s["date"].str.slice(0, 10))})
    for short, field in STAFFING_FIELDS.items():
        df[short] = pd.to_numeric(s[field], errors="coerce")
    return df.sort_values(["state", "date"]).reset_index(drop=True)
