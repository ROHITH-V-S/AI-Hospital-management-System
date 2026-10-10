"""Reproduce every result, in order.

    python experiments/run_all.py            # uses the cached data if present
    python experiments/run_all.py --refetch  # re-download the federal data first

Each step is an ordinary script that can also be run on its own. Takes roughly
30-40 minutes on a laptop, most of it in the RQ3 planted-error runs.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ["fetch_national.py"],
    ["rq1_trust_audit.py"],
    ["rq2_forecast.py"],
    ["rq3_coordination.py"],
    ["houston_case_study.py"],
    ["build_ui_data.py"],
]


def main() -> int:
    if "--refetch" in sys.argv:
        STEPS[0] = ["fetch_national.py", "--refetch"]
    for step in STEPS:
        t0 = time.perf_counter()
        print(f"\n=== {' '.join(step)}", flush=True)
        rc = subprocess.call([sys.executable, "-u", str(HERE / step[0]), *step[1:]])
        if rc:
            print(f"!!! {step[0]} failed with exit code {rc}; stopping.")
            return rc
        print(f"=== done in {time.perf_counter() - t0:.0f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
