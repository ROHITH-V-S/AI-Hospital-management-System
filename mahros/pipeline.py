"""One place that turns downloaded data into what every experiment uses.

Every experiment calls :func:`assessed`, so all of them see the same reports
with the same trust verdicts. Nothing is recomputed differently in two places.
"""

from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from .data import hhs
from .trust import assess

ROOT = Path(__file__).resolve().parents[1]
RESULTS = ROOT / "results"


def assessed(key: str = "corrected") -> pd.DataFrame:
    """Canonical frame plus ``flags``, ``level`` and ``census_run`` columns."""
    df = hhs.load(key)
    return df.join(assess(df))


def write_json(name: str, payload: dict) -> Path:
    RESULTS.mkdir(exist_ok=True)
    path = RESULTS / name
    path.write_text(json.dumps(payload, indent=2, default=_jsonable) + "\n")
    return path


def _jsonable(o):
    if hasattr(o, "isoformat"):
        return o.isoformat()
    if hasattr(o, "item"):
        return o.item()
    return str(o)


def data_stamp() -> dict:
    """Which exact data a result came from (copied from the manifest)."""
    if not hhs.MANIFEST.exists():
        return {}
    m = json.loads(hhs.MANIFEST.read_text())
    return {k: {"sha256": v["sha256"], "rows": v["rows"], "fetched_at": v["fetched_at"]}
            for k, v in m.items()}
