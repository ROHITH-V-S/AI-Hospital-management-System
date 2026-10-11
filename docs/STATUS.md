# Where we stopped (2026-10-11)

Spec: `docs/NEXT_SESSION_PROMPT.md`. Full history: `docs/BUILD_LOG.md`.
Branch `trust-aware-rebuild`. Nothing pushed.

| Phase | State | Commit |
|---|---|---|
| 1 Docker + PostgreSQL | done | 7d19a36 |
| 2 Ledger in DB | done (UI in Phase 6 — done) | 6892bb8 |
| 3 Emergency transfer | done | 8dd12ed |
| 4 Surge early warning | done | a5c5d9a, 165ef20 |
| 5 Staff + equipment | done | 692d170 |
| 6 Command-centre UI | **mostly done**, see below | (WIP commit) |
| 7 Docs, tests, verification | **not started** | |

## To finish Phase 6
1. Look at the 400-px screenshot of the Emergency tab after the `minmax(0,1fr)` fix; fix any remaining overflow.
2. Screenshot "This week" (`?tab=live&steps=6&inject=lost_digit`), Evidence 1–3, Limits.
3. Check the resources map click-to-zoom (lines in `static/resources.js`).
4. Rebuild Docker (`docker compose build && docker compose run --rm loader --force`? — loader has `--force`; the derived steps surge/staff/equipment have NOT yet been run against Postgres) and check every tab on http://localhost:8080, plus the real pgAdmin tamper demo (edit `bids.travel_min`, press Verify log).
5. Commit Phase 6.

## Phase 7 (all to do)
- README (Docker quick start already in; update findings with emergency/surge/staff numbers), REVIEW_GUIDE (3-minute demo: Emergency → Early warning → Staff & equipment → pgAdmin tamper; Q&A: why not just phone, where is the multi-agent part, is it real-time, what is simulated), METHODS (sections for emergency, surge, staffing), DATA_PROVENANCE (every new field: ED/COVID/flu fields, OSRM AZ/MA, POS Q3 2022, state staffing, estimated staff, entered equipment, every emergency parameter from `mahros/emergency/params.py`).
- `experiments/run_all.py`: add fetch_extra, fetch_emergency_network (optional, vendored), emergency_eval, surge_warning, staffing_check, build_ui_data.
- Script that cross-checks every number in the docs against `results/*.json`.
- Full `pytest` (currently 96 pass, 10 skip = Postgres-only; run with
  `MAHROS_TEST_PG_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/postgres`
  `MAHROS_TEST_DATABASE_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/mahros`) + `node tests/ui_smoke.js` (check its exit code — do not pipe into tail).
- Fix the `alembic` migration if any model changed since 0001 (none so far).

## Headline results so far (all from results/*.json)
- Emergency (simulation grounded in real data, AZ 71 + MA 58 hospitals, 16 weeks × 10 runs): time to bed MAHROS 13.2 min vs 19.9 phone nearest-first vs 16.5 phone report-informed; slowest 10%: 13.0 vs 37.1 vs 29.0; in-window 95.7% vs 94.4%; bed found 97.6% vs 97.9%; sensitivity range −2.0 to −12.1 min.
- Surge warning (real, test 2023–24): model F1 0.47 vs 0.40 best simple rule (+7.1 pts, CI 6.0–8.3); 48% of surges warned ≥ 1 week ahead; ED visits add nothing.
- Staffing check: weak agreement in direction 2020–22 (median ρ 0.24, 35/47 states), none 2023–24; estimate flags 2.1% vs 13.9% real.

## Local notes
- Port 8000 is used by another project on this machine; Docker app is on **8080**.
- A pre-existing `python -m mahros.server` (port 8000) was stopped during this session; restart it if needed.
- Scratch SQLite DB with data loaded was used for local screenshots (not in repo).
