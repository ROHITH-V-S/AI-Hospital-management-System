"""Reproduce every result, in order.

    python experiments/run_all.py            # uses the cached data if present
    python experiments/run_all.py --refetch  # re-download the federal data first

Each step is an ordinary script that can also be run on its own. Takes roughly
45-55 minutes on a laptop, most of it in the RQ3 planted-error runs.
"""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
STEPS = [
    ["fetch_national.py"],          # HHS facility data (skipped if cached)
    ["fetch_extra.py"],             # v0.3: ER / COVID / flu fields + state staffing (skipped if cached)
    ["rq1_trust_audit.py"],
    ["rq2_forecast.py"],
    ["rq3_coordination.py"],
    ["houston_case_study.py"],
    ["emergency_eval.py"],          # v0.3: emergency transfer simulation (uses vendored AZ/MA inputs)
    ["surge_warning.py"],           # v0.3: surge early warning
    ["staffing_check.py"],          # v0.3: staff estimate vs real shortage reports
    ["build_ui_data.py"],
    ["check_doc_numbers.py"],       # every number in the docs matches results/
]
# The AZ/MA hospital networks, OSRM road times and CMS capability are vendored
# in mahros/calibration/data/. Re-fetch them with:
#     python experiments/fetch_emergency_network.py


def main() -> int:
    if "--refetch" in sys.argv:
        STEPS[0] = ["fetch_national.py", "--refetch"]
        STEPS[1] = ["fetch_extra.py", "--refetch"]
    if "--no-check" in sys.argv:
        STEPS.remove(["check_doc_numbers.py"])
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
