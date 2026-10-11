# MAHROS

**Multi-Agent Hospital Resource Optimization System** — a trust-aware platform
for regional hospital load balancing, built and evaluated entirely on real
federal hospital capacity reports (U.S. HHS, 4,712 general and critical-access
hospitals, 2020–2024). Nothing is simulated.

> New to the project? Read [docs/REVIEW_GUIDE.md](docs/REVIEW_GUIDE.md) first:
> plain language, the findings, the weak points, and the questions a reviewer
> will ask.

## What it does

A state health department runs MAHROS. Every week:

1. **Hospital agents** submit their reports (beds, patients, ICU).
2. The **Data Steward agent** marks each report GREEN / AMBER / RED / MISSING
   and says why (frozen counts, more patients than beds, typo-sized jumps…).
3. The **Forecast agent** predicts next week's occupancy with a 90% range.
4. A **Regional Coordinator agent** per state proposes moving patient load from
   hospitals forecast above a safe level (90%) to nearby hospitals with room.
5. Each **hospital agent accepts only what its real numbers allow.** Every
   message is sealed into a tamper-evident audit ledger.

## Findings

All numbers below come from the scripts named, on the data fingerprinted in
[`data/manifest.json`](data/manifest.json).

**RQ1 — Can the reports be trusted?** (`experiments/rq1_trust_audit.py`)

| | |
|---|---|
| Weekly reports that cannot be right (RED) | 1.6% |
| Hospitals with at least one RED report | 2,079 of 4,712 (44%) |
| Frozen patient counts: seen vs expected by chance | 8,325 vs 81 |
| Government later corrected a RED vs a GREEN report | 30.5% vs 2.6% (11.6×) |
| Planted errors caught (stale feed, ×10, ÷10, ×7, zero, beds ×10) | 100% each |
| Planted subtle drift caught (+25% one week / +10% four weeks) | 33% / 15% |

**RQ2 — Can next week be forecast?** (`experiments/rq2_forecast.py`; test
period 2023–2024, never seen in training)

| Mean absolute error, occupancy points | 1 week | 2 weeks | 4 weeks |
|---|---|---|---|
| "Same as this week" | 4.89 | 5.88 | 6.36 |
| 4-week average | 4.82 | 5.28 | **5.71** |
| MAHROS forecaster | **4.72** | **5.21** | 5.85 |
| 90% range held the true value | 88.9% | 90.1% | 90.3% |

**RQ3 — Could hospitals have shared the load?** (`experiments/rq3_coordination.py`;
69 decision weeks, 2023–2024, every state; plans scored against what
hospitals actually reported the following week)

| Strategy | Share of above-90% patient-days absorbed |
|---|---|
| No coordination | 0% |
| Nearest hospital with room (no optimiser) | 49.9% |
| Optimised, "same as this week" forecast | 51.4% |
| Optimised, every report believed | 49.9% |
| **MAHROS** | **50.2%** |
| Perfect knowledge of next week (ceiling) | 66.5% |

Coordinating at all: +27,294 patient-days absorbed per week (95% CI 26,138 to
28,428). Effect varies by state (Texas 39%, Minnesota 18%, Massachusetts 69%).

**When some reports are wrong** (errors planted into real reports; plans
always scored against the real, uncorrupted next week):

| Reports corrupted | MAHROS absorbs | Every report believed | Share of plan that was actually possible (MAHROS vs believed) | Load planned into hospitals already over the safe level, had nobody checked |
|---|---|---|---|---|
| none (real data) | 50.2% | 49.9% | 84% vs 79% | 26.6k vs 28.3k patient-days |
| 2% | 49.4% | 48.3% | 84% vs 74% | 25.5k vs 72.9k |
| 5% | 48.2% | 46.6% | 84% vs 67% | 25.9k vs 136.8k |
| 10% | 46.0% | 43.3% | 84% vs 58% | 26.4k vs 252.5k |

MAHROS minus "believe every report", patient-days absorbed per week: +172 on
real data (CI −93 to +416, not significant); +586 (279 to 931), +881
(550 to 1,239) and +1,478 (1,019 to 1,871) at 2%, 5% and 10% corruption.

**Houston check** (`experiments/houston_case_study.py`): with real driving
times instead of straight-line distance, the plan is the same (13.46% vs
13.48% absorbed, 96% identical transfers). Houston absorbs far less than the
national average because its hospitals are often full together.

### Read these honestly

- Almost all of RQ3's gain comes from **coordinating at all**. The forecaster,
  the optimiser and the trust filter each change the volume absorbed by about
  a point; "same as this week" even does slightly better.
- The Data Steward's value is **safety, not volume**: it keeps a plan from
  sending patients toward hospitals whose numbers are wrong (table above).
- Absorption is an **upper estimate**: it ignores specialty, transport and
  patient choice. See [docs/DATA_PROVENANCE.md](docs/DATA_PROVENANCE.md) §4.

## Start everything (Docker)

```bash
docker compose up            # first run: builds, loads ~1 million real reports into PostgreSQL
```

| Open | What |
|---|---|
| http://localhost:8080 | the MAHROS dashboard |
| http://localhost:5050 | pgAdmin: browse every table (no login; server "MAHROS database") |

What starts: `db` (PostgreSQL 16), `loader` (one-shot: downloads the data if
`data/cache/` is empty, runs the pipeline, fills the database; re-running it
does nothing if the inputs are unchanged), `app` (the dashboard) and
`pgadmin`. Passwords: copy `.env.example` to `.env` and change them; without
a `.env` the local-demo defaults are used. Stop with `docker compose down`
(add `-v` to delete the database too).

The research experiments still read the Parquet cache, so their results stay
byte-reproducible; the running platform reads and writes PostgreSQL.

## Run it (without Docker)

```bash
pip install -e ".[dev,demo]"
python experiments/run_all.py           # first time: download data + all results (~30 min)
python -m mahros.server                 # dashboard -> http://127.0.0.1:8000
python -m pytest                        # 56 tests
node tests/ui_smoke.js                  # dashboard renders every result
```

**Live operations** (the first tab) replays real weeks with the real agents:
pick a state, press Play, and watch hospitals report, the Data Steward flag
bad reports, the forecaster predict, the coordinator propose transfers and the
hospitals accept or decline — each week sealed into the audit log. You can
inject a typo into a hospital's report and watch it get caught, or tamper with
the log and watch verification fail. It needs the downloaded data in
`data/cache/` (about 15 s to load when the server starts). The other tabs
(the evidence) need only the committed files in `results/ui/` and also work
when deployed.

Hands-free: `http://127.0.0.1:8000/?autoplay=3&speed=450&inject=lost_digit`.

## Layout

```
mahros/
  data/          HHS download, manifest, canonical frame
  trust/         Data Steward rules; planted-error benchmark
  forecast/      gradient-boosted forecaster with conformal intervals
  coordination/  linear-program planner, execution check, decision frames
  agents/        hospital, steward, forecaster, coordinator agents; weekly cycle
  ledger/        hash-chained audit ledger
  server/        dashboard + live operations console (FastAPI + one page)
  calibration/   Houston road-time data for the case study
experiments/     fetch_national, rq1_trust_audit, rq2_forecast,
                 rq3_coordination, houston_case_study, build_ui_data, run_all
tests/           56 tests + ui_smoke.js
docs/            REVIEW_GUIDE, METHODS, DATA_PROVENANCE, BUILD_LOG
results/         every result as JSON/CSV; results/ui/ feeds the dashboard
```

## History

v0.1 (git tag `v0.1-negotiation`) simulated hospitals negotiating transfers.
An audit found its headline results depended on the simulator's own ground
truth and on simulated demand; it was replaced by this version. The full
record is in [docs/BUILD_LOG.md](docs/BUILD_LOG.md).

## Licence

MIT. Data: U.S. HHS (public domain); OpenStreetMap via OSRM (ODbL).
