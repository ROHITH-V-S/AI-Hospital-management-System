"""Download the v0.3 inputs: extra facility fields and the state staffing series.

    python experiments/fetch_extra.py            # skips files already cached
    python experiments/fetch_extra.py --refetch

Both go to data/cache/ (git-ignored) and are fingerprinted in
data/manifest.json. The RQ1-RQ3 input file is not touched.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from mahros.data import hhs  # noqa: E402


def main() -> int:
    refetch = "--refetch" in sys.argv
    extra = hhs.CACHE / "hhs_corrected_extra_source.parquet"
    staff = hhs.CACHE / "hhs_state_staffing_source.parquet"
    if refetch or not extra.exists():
        hhs.fetch_extra()
    if refetch or not staff.exists():
        hhs.fetch_state_staffing()
    e, s = hhs.load_extra(), hhs.load_state_staffing()
    dup = e.duplicated(["hospital_pk", "week"]).sum()
    print(f"extra fields: {len(e):,} rows, {e['hospital_pk'].nunique():,} hospitals, "
          f"{e['week'].min().date()} .. {e['week'].max().date()}, duplicate keys {dup}")
    print(f"state staffing: {len(s):,} rows, {s['state'].nunique()} states, "
          f"{s['date'].min().date()} .. {s['date'].max().date()}")
    return 0 if dup == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
