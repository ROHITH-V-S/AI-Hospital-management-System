"""Call every dashboard API for every state against a RUNNING app and fail on any error.

    python tests/api_sweep.py                       # http://localhost:8080
    python tests/api_sweep.py http://localhost:8089

Written after three bugs appeared only on PostgreSQL (a missing text value
comes back as NaN): run it against the Docker app after any change.
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8080").rstrip("/")


def get(path: str):
    try:
        with urllib.request.urlopen(BASE + path, timeout=120) as r:
            body = r.read().decode()
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"HTTP {e.code}: {e.read().decode()[:200]}")
    def no_nan(x):
        raise ValueError(f"non-JSON number {x}")
    return json.loads(body, parse_constant=no_nan)


def main() -> int:
    bad, n = [], 0

    def check(path):
        nonlocal n
        n += 1
        try:
            return get(path)
        except Exception as exc:
            bad.append(f"{path}: {exc}")
            return None

    rw = check("/api/resources/weeks") or {"weeks": [], "states": []}
    states = [s["state"] for s in rw["states"]]
    weeks = rw["weeks"]
    pick = sorted({weeks[0], weeks[len(weeks) // 2], weeks[-1], "2023-11-19"} & set(weeks))
    for p in ("/healthz", "/api/live/status", "/api/live/hospitals", "/api/book", "/api/trust/bids",
              "/api/emergency/status?state=AZ", "/api/emergency/status?state=MA",
              "/api/emergency/hospitals?state=AZ", "/api/emergency/hospitals?state=MA", "/api/ledger"):
        check(p)
    for st in states:
        ww = check(f"/api/warning/weeks?state={st}")
        wks = [w["week"] for w in (ww or {}).get("weeks", [])]
        for w in sorted(set(wks[:1] + wks[len(wks) // 2: len(wks) // 2 + 1] + wks[-1:] + [x for x in pick if x in wks])):
            check(f"/api/warning?state={st}&week={w}")
        check(f"/api/resources/inventory?state={st}")
        for w in pick:
            check(f"/api/trust?state={st}&week={w}")
        check(f"/api/resources/plan?state={st}&week=2023-11-19")
    if bad:
        print(f"API SWEEP FAILED: {len(bad)} of {n} calls")
        print("\n".join(bad[:30]))
        return 1
    print(f"API sweep OK: {n} calls, {len(states)} states, no errors and no NaN.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
