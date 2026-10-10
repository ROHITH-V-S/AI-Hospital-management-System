"""Download both national HHS facility datasets and print a data profile.

    python experiments/fetch_national.py            # fetch if missing, then profile
    python experiments/fetch_national.py --refetch  # force a fresh download

Writes ``data/cache/hhs_{corrected,raw}*.parquet`` (git-ignored, ~1M rows each)
and ``data/manifest.json`` (committed: row counts, fetch time, SHA-256), so any
result can be traced to the exact bytes it was computed from.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.data import hhs  # noqa: E402


def main(refetch: bool = False) -> int:
    for key in ("corrected", "raw"):
        src = hhs.CACHE / f"hhs_{key}_source.parquet"
        if refetch or not src.exists():
            print(f"fetching {key} ...")
            hhs.fetch(key)
        df = hhs.load(key)
        dups = hhs.duplicate_keys(df)
        print(f"\n[{key}] rows={len(df):,} hospitals={df.hospital_pk.nunique():,} "
              f"weeks={df.week.nunique()} ({df.week.min().date()} .. {df.week.max().date()})")
        print(f"  duplicate (hospital, week) keys: {len(dups):,}")
        print(f"  rows with any suppressed field: {(df.n_suppressed > 0).sum():,}")
        print(f"  rows missing census: {df.used.isna().sum():,}   "
              f"missing beds: {df.beds.isna().sum():,}")
        print(f"  rows missing coordinates: {df.lat.isna().sum():,}")
        if key == "corrected":
            print(f"  is_corrected rows: {df.is_corrected.sum():,}")
        print("  subtypes:", df.drop_duplicates("hospital_pk").subtype.value_counts().to_dict())
    return 0


if __name__ == "__main__":
    raise SystemExit(main("--refetch" in sys.argv))
