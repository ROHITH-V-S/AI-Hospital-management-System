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
| 6 Command-centre UI | done (checked in Docker) | see git log |
| 7 Docs, tests, verification | done (BUILD_LOG Step 19) | see git log |

## Phase 6
Done 2026-10-12 — see BUILD_LOG Step 18. Not verified: layouts narrower than 500 px; clicking through pgAdmin's own GUI.

## Phase 7
Done 2026-10-12. The v0.3 revision in docs/NEXT_SESSION_PROMPT.md is complete.

## Still open (not part of the spec, worth doing before submission)
- Systematic literature search (REVIEW_GUIDE §6 says so).
- Check the dashboard on a real phone (screenshots only verified down to 500 px).
- Click through pgAdmin's GUI once yourself before the review (the SQL it runs was verified).

## Headline results so far (all from results/*.json)
- Emergency (simulation grounded in real data, AZ 71 + MA 58 hospitals, 16 weeks × 10 runs): time to bed MAHROS 13.2 min vs 19.9 phone nearest-first vs 16.5 phone report-informed; slowest 10%: 13.0 vs 37.1 vs 29.0; in-window 95.7% vs 94.4%; bed found 97.6% vs 97.9%; sensitivity range −2.0 to −12.1 min.
- Surge warning (real, test 2023–24): model F1 0.47 vs 0.40 best simple rule (+7.1 pts, CI 6.0–8.3); 48% of surges warned ≥ 1 week ahead; ED visits add nothing.
- Staffing check: weak agreement in direction 2020–22 (median ρ 0.24, 35/47 states), none 2023–24; estimate flags 2.1% vs 13.9% real.

## Local notes
- Port 8000 is used by another project on this machine; Docker app is on **8080**.
- A pre-existing `python -m mahros.server` (port 8000) was stopped during this session; restart it if needed.
- Scratch SQLite DB with data loaded was used for local screenshots (not in repo).
