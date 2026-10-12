# MAHROS

**Multi-Agent Hospital Resource Optimization System** — a working prototype of
the hospital-coordination service a state health department could run, built
and evaluated on real U.S. federal hospital reports (HHS, 4,712 general and
critical-access hospitals, 2020–2024).

> New to the project? Read [docs/REVIEW_GUIDE.md](docs/REVIEW_GUIDE.md) first:
> plain language, the 3-minute demo, the findings, the weak points, and the
> questions a reviewer will ask.

## What it does

| Timescale | What MAHROS does | Data |
|---|---|---|
| **Minutes** — emergency transfer | A patient needs an ICU bed, a cath lab or a trauma team now. MAHROS asks every capable hospital in reach **at once**; each hospital agent answers by itself from its own beds, nurses and equipment; the Data Steward checks the bids; the best bed is confirmed with one call. | Real hospitals, capability, road times and weekly reports; minute-by-minute beds **simulated** |
| **Weeks** — planning | The Data Steward marks every weekly report GREEN / AMBER / RED / MISSING and says why; the Forecaster predicts next week; the regional coordinator plans patient moves, nurse loans and equipment moves. | Real |
| **1–2 weeks ahead** — surge early warning | Warns which areas are about to pass 85% full. Not a pandemic predictor. | Real |
| **Always** — record book | Every request, answer and decision is written into a hash-chained log in PostgreSQL. Editing any row afterwards — even by hand in pgAdmin — is caught and named. | — |

Agents: one **hospital agent** per hospital (private state, decides for
itself), a **Data Steward**, a **Forecaster**, an **emergency coordinator**
and a **regional coordinator** per state. They talk only through messages.

## Start everything (Docker)

```bash
docker compose up            # first run: builds, loads ~1 million real reports into PostgreSQL
```

| Open | What |
|---|---|
| http://localhost:8080 | the MAHROS dashboard (opens on the Emergency tab) |
| http://localhost:5050 | pgAdmin: browse every table (no login; server "MAHROS database") |

What starts: `db` (PostgreSQL 16), `loader` (one-shot: downloads the data if
`data/cache/` is empty, runs the pipeline, fills the database; re-running it
does nothing if the inputs are unchanged; `docker compose run --rm loader
python -m mahros.db.load --force` reloads), `app` (the dashboard) and
`pgadmin`. Passwords: copy `.env.example` to `.env` and change them; without a
`.env` the local-demo defaults are used. The app uses port **8080** (change
`APP_PORT` in `.env`). Stop with `docker compose down` (add `-v` to delete the
database too).

The research experiments read the Parquet cache, so their results stay
byte-reproducible; the running platform reads and writes PostgreSQL (tested
to give identical numbers: `tests/test_db_equivalence.py`).

## Findings

Every number below is produced by the script named and checked against the
result files by `experiments/check_doc_numbers.py`.

### Emergency transfer — simulation grounded in real data (`experiments/emergency_eval.py`)

Arizona (71 hospitals) and Massachusetts (58), real OSRM road times, CMS
capability, each hospital's real weekly report; 16 real weeks × 10 runs; the
same simulated patients face every method.

| | MAHROS (ask all at once) | Phone, nearest first | Phone, report-informed order |
|---|---|---|---|
| Mean time to a confirmed bed | **13.2 min** | 19.9 min | 16.5 min |
| Slowest 10% of patients | **13.0 min** | 37.1 min | 29.0 min |
| Reached care inside the clinical window | 95.7% | 94.4% | 94.8% |
| Bed found at all | 97.6% | 97.9% | 97.9% |

MAHROS minus phoning nearest-first: -6.7 min on average (95% CI -7.2 to -6.2),
-24.1 min for the slowest 10%. Across every one-at-a-time change of an
assumption the mean difference ranges from -2.0 min (5-minute calls) to
-12.1 min (more requests). Simulated ICUs average 100.2% of their reported
census (calibration, not validation).

### Surge early warning — real data (`experiments/surge_warning.py`)

Will an area (a hospital and every hospital within 50 km; 4,705 areas) still
below 85% full reach 85% within 2 weeks? Tested on 2023–24, never seen in
training.

| | Warnings that came true | Surges caught | F1 | Surges warned ≥ 1 week ahead |
|---|---|---|---|---|
| **MAHROS model** | 40% | 58% | **0.47** | 48% |
| Simple rule: already near 85% | 37% | 44% | 0.40 | 47% |
| Simple rule: neighbours rising together | 6% | 40% | 0.11 | 69% |

Model minus best simple rule: +7.1 F1 points (95% CI 6.0 to 8.3). ED visits
add nothing (CDC made them optional on 2023-06-11).

### Staff estimates vs real shortage reports (`experiments/staffing_check.py`)

Staff per hospital is not public, so it is estimated. In 2020–22 the estimate
and the real state-level shortage reports moved together only weakly (median
within-state correlation 0.24, positive in 35 of 47 states); in 2023–24, when
few hospitals answered, not at all (0.03). Levels differ: 13.9% of hospitals
really reported a shortage in an average week, the estimate flagged 2.1%.

### RQ1 — Can the reports be trusted? (`experiments/rq1_trust_audit.py`)

| | |
|---|---|
| Weekly reports that cannot be right (RED) | 1.6% |
| Hospitals with at least one RED report | 2,079 of 4,712 (44%) |
| Frozen patient counts: seen vs expected by chance | 8,325 vs 81 |
| Government later corrected a RED vs a GREEN report | 30.5% vs 2.6% (11.6×) |
| Planted errors caught (stale feed, ×10, ÷10, ×7, zero, beds ×10) | 100% each |
| Planted subtle drift caught (+25% one week / +10% four weeks) | 33% / 15% |

### RQ2 — Can next week be forecast? (`experiments/rq2_forecast.py`; test 2023–2024)

| Mean absolute error, occupancy points | 1 week | 2 weeks | 4 weeks |
|---|---|---|---|
| "Same as this week" | 4.89 | 5.88 | 6.36 |
| 4-week average | 4.82 | 5.28 | **5.71** |
| MAHROS forecaster | **4.72** | **5.21** | 5.85 |
| 90% range held the true value | 88.9% | 90.1% | 90.3% |

### RQ3 — Could hospitals have shared the load? (`experiments/rq3_coordination.py`)

69 decision weeks, 2023–2024, every state; plans scored against what hospitals
actually reported the following week.

| Strategy | Share of above-90% patient-days absorbed |
|---|---|
| No coordination | 0% |
| Nearest hospital with room (no optimiser) | 49.9% |
| Optimised, "same as this week" forecast | 51.4% |
| Optimised, every report believed | 49.9% |
| **MAHROS** | **50.2%** |
| Perfect knowledge of next week (ceiling) | 66.5% |

With errors planted into 2%, 5% and 10% of reports, a planner that believes
every report plans 72.9k, 136.8k and 252.5k patient-days into hospitals already
over the safe level; with the Data Steward it stays near 26k. Houston (real
driving times) absorbs only about 13%.

### Read these honestly

- **Emergency:** the gain is in the slow tail and in staff phone time. When the
  nearest hospital has room, one phone call is as fast or faster. MAHROS finds
  a bed slightly less often (phone callers keep calling while beds free up).
  Minute-level dynamics are simulated.
- **Surge warning:** modest. About half of real surges came with no warning.
- **Staff:** estimates only; agreement with real shortage reports is weak.
  **Equipment** is an entered inventory; no research claim rests on it.
- **RQ3:** almost all of the gain comes from coordinating at all; the trust
  filter's value is safety, not volume. Absorption is an upper estimate.

## Run it (without Docker)

```bash
pip install -e ".[dev,demo]"
python experiments/run_all.py           # download data + every result (~50 min)
python -m mahros.db.load                # fill a local SQLite database (data/mahros.sqlite)
python -m mahros.server                 # dashboard -> http://127.0.0.1:8000
python -m pytest                        # 106 tests (10 need PostgreSQL, see below)
node tests/ui_smoke.js                  # dashboard renders every result
```

PostgreSQL tests (with Docker running):
`MAHROS_TEST_PG_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/postgres`
`MAHROS_TEST_DATABASE_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/mahros python -m pytest`.

## Layout

```
mahros/
  data/          HHS downloads (facility data, extra fields, state staffing), manifest
  trust/         Data Steward rules; planted-error benchmark
  forecast/      gradient-boosted forecaster with conformal intervals
  coordination/  weekly linear-program planner and execution check
  agents/        weekly agents (hospital, steward, forecaster, coordinator) and cycle
  emergency/     emergency transfer: hospital agents, Steward bid check, coordinators,
                 discrete-event world, live service, parameters with sources
  surge/         surge early warning: area signals, alerts
  resources/     staff estimates, equipment inventory, loan/move optimiser, weekly plan
  ledger/        chain.py (research log), store.py (record book in the database)
  db/            SQLAlchemy models, session, loader, bulk COPY, frame readers
  server/        FastAPI app + dashboard (static/index.html + one .js per tab)
  calibration/   vendored real inputs: AZ/MA/Houston networks, OSRM routes, CMS capability
experiments/     every result: run_all.py runs them in order
migrations/      Alembic (0001: full schema)
tests/           pytest suite + ui_smoke.js
docs/            REVIEW_GUIDE, METHODS, DATA_PROVENANCE, BUILD_LOG, STATUS
results/         every result as JSON/CSV; results/ui/ feeds the dashboard
docker-compose.yml, Dockerfile, .env.example, docker/pgadmin/
```

## History

v0.1 (git tag `v0.1-negotiation`) simulated hospitals negotiating transfers.
An audit found its headline results depended on the simulator's own ground
truth; it was replaced by the real-data v0.2, and v0.3 added the emergency
module, PostgreSQL, the surge warning, staff and equipment. The full record is
in [docs/BUILD_LOG.md](docs/BUILD_LOG.md).

## Licence

MIT. Data: U.S. HHS (public domain); CMS Provider of Services (public domain);
OpenStreetMap via OSRM (ODbL).
