"""Vendor the real inputs of the emergency module for Arizona and Massachusetts.

    python experiments/fetch_emergency_network.py               # both states
    python experiments/fetch_emergency_network.py --state AZ
    python experiments/fetch_emergency_network.py --pos PATH    # use a downloaded POS csv

Writes, per state, into mahros/calibration/data/:

  us_<st>_network.json      the hospitals: every Short Term / Critical Access
                            hospital that reported in 2022-12-25..2024-04-21
                            (HHS anag-cw7u, observed)
  us_<st>_routes.json       OSRM driving times and distances between all of
                            them (free-flow, over OpenStreetMap; observed)
  us_<st>_capability.json   CMS Provider of Services service codes, joined on
                            CCN (observed where matched)

If OSRM is unreachable the script stops and says so. It never invents times.
"""

from __future__ import annotations

import argparse
import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import pandas as pd  # noqa: E402

from mahros.calibration.capability import (DATA_DIR, FIELDS, POS_BASE,  # noqa: E402
                                           download, extract, state_capability_path)
from mahros.calibration.routing import fetch_road_matrix  # noqa: E402
from mahros.data import hhs  # noqa: E402
from mahros.forecast.model import SUBTYPES  # noqa: E402

FIRST, LAST = "2022-12-25", "2024-04-21"
POS_QUARTER = "Q32022"       # newest quarter on the NBER mirror; nearest to the test period
NAMES = {"AZ": "Arizona", "MA": "Massachusetts"}


def network(state: str) -> list[dict]:
    d = hhs.load("corrected")
    d = d[d["subtype"].isin(SUBTYPES) & (d["state"] == state)
          & (d["week"] >= FIRST) & (d["week"] <= LAST)]
    last = d.sort_values("week").groupby("hospital_pk").tail(1)
    out = []
    for r in last.sort_values("hospital_pk").itertuples():
        out.append({"hospital_pk": r.hospital_pk, "ccn": str(r.ccn), "name": r.name,
                    "city": r.city, "subtype": r.subtype,
                    "lat": round(float(r.lat), 6), "lon": round(float(r.lon), 6)})
    return out


def write_network(state: str, hosp: list[dict]) -> None:
    p = DATA_DIR / f"us_{state.lower()}_network.json"
    p.write_text(json.dumps({
        "source": {"dataset": "HHS COVID-19 Reported Patient Impact and Hospital Capacity "
                              "by Facility (anag-cw7u)",
                   "selection": f"Short Term + Critical Access hospitals in {NAMES[state]} with "
                                f"at least one report {FIRST}..{LAST}",
                   "provenance": "observed"},
        "state": state, "n": len(hosp), "hospitals": hosp}, indent=1), encoding="utf-8")
    print(f"  wrote {p.relative_to(ROOT)}: {len(hosp)} hospitals")


def write_routes(state: str, hosp: list[dict]) -> None:
    payload = fetch_road_matrix(hosp)       # raises if OSRM fails -- never faked
    dur, dist = payload["durations"], payload.get("distances")
    missing = sum(1 for row in dur for v in row if v is None)
    p = DATA_DIR / f"us_{state.lower()}_routes.json"
    p.write_text(json.dumps({
        "source": {"router": "OSRM public demo server (router.project-osrm.org)",
                   "profile": "driving, free-flow (no live traffic, no emergency-vehicle privilege)",
                   "network": "OpenStreetMap contributors (ODbL)",
                   "fetched_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                   "provenance": "observed"},
        "state": state, "hospital_pks": [h["hospital_pk"] for h in hosp],
        "unroutable_pairs": missing, "durations_seconds": dur, "distances_metres": dist}),
        encoding="utf-8")
    print(f"  wrote {p.relative_to(ROOT)}: {len(hosp)}x{len(hosp)} pairs, {missing} unroutable")


def write_capability(state: str, hosp: list[dict], pos_csv: Path) -> None:
    ccns = {h["ccn"] for h in hosp}
    rows = extract(pos_csv, ccns)
    p = state_capability_path(state)
    p.write_text(json.dumps({
        "source": {"dataset": "CMS Provider of Services (POS), Other Facilities",
                   "quarter": POS_QUARTER, "mirror": POS_BASE,
                   "label": f"CMS Provider of Services {POS_QUARTER}",
                   "join_key": "PRVDR_NUM = HHS ccn (exact)",
                   "service_codes": {"0": "not provided", "1": "provided by staff",
                                     "2": "under arrangement", "3": "staff and arrangement"},
                   "onsite_codes": ["1", "3"], "fields": FIELDS, "provenance": "observed"},
        "state": state, "n_hospitals": len(hosp), "n_matched": len(rows),
        "unmatched": sorted(ccns - set(rows)), "facilities": rows}, indent=1), encoding="utf-8")
    print(f"  wrote {p.relative_to(ROOT)}: matched {len(rows)} of {len(ccns)} CCNs")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--state", choices=sorted(NAMES))
    ap.add_argument("--pos", help="path to an already-downloaded POS csv")
    args = ap.parse_args()
    pos = Path(args.pos) if args.pos else Path(tempfile.gettempdir()) / f"pos_other_{POS_QUARTER}.csv"
    if not pos.exists():
        print(f"downloading POS {POS_QUARTER} (~110 MB)...")
        download(POS_QUARTER, pos)
    for st in ([args.state] if args.state else sorted(NAMES)):
        print(f"{NAMES[st]}:")
        hosp = network(st)
        write_network(st, hosp)
        write_routes(st, hosp)
        write_capability(st, hosp, pos)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
