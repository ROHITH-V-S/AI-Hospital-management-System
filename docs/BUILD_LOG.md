# Build log

Chronological record of the trust-aware rebuild. Every step says what was
done, why, and how to verify it. If something breaks, find the step here, then
the matching commit on branch `trust-aware-rebuild`.

The previous design (simulated negotiation, argumentation, strategic hospitals)
is preserved unchanged at git tag **`v0.1-negotiation`**:

```
git checkout v0.1-negotiation      # inspect the old version
git checkout trust-aware-rebuild   # come back
```

---

## 2026-10-10 — Step 0: why the rebuild

An audit of v0.1 found:

1. "Zero false accusations" held by construction: a challenged hospital's
   defence read the simulator's ground-truth `misreported` flag
   (`mahros/hospital/behaviours.py`, `BiddingPolicy.defend`).
2. The occupancy "validation" (R^2 = 0.95) was circular: arrival rates were
   solved from each hospital's observed occupancy, then compared against that
   same occupancy.
3. Transfer demand and hospital behaviour were entirely simulated.
4. The reference week contained frozen bed reports (Memorial Hermann: 1472.0
   beds for 43 consecutive weeks).

Decision (with the team): keep the title **Multi-Agent Hospital Resource
Optimization System**, drop the simulated negotiation, and rebuild around real
federal data with three research questions:

- **RQ1** How reliable is self-reported hospital capacity data, and can an
  agent detect unreliable reports?
- **RQ2** Can next-week occupancy be forecast, and does trust filtering help?
- **RQ3** How much overload could regional coordination have absorbed, and how
  much do unreliable reports distort the plan?

## 2026-10-10 — Step 0b: data availability verified before building

Queried live, not assumed:

| Dataset | Id | Rows | Hospitals | Weeks |
|---|---|---|---|---|
| HHS facility capacity (corrected) | `anag-cw7u` | 1,045,406 | 5,172 | 2019-12-29 .. 2024-04-21 |
| HHS facility capacity (RAW) | `uqq2-txqb` | 964,632 | 5,143 | 2020-08-02 .. 2024-04-21 |
| Rows HHS marked `is_corrected = true` | `anag-cw7u` | 39,492 | | |

Both share the same column schema (except `is_corrected`), so RAW and
corrected rows can be compared field by field.

Preliminary national scan (inpatient census >= 10, >= 20 reported weeks,
4,194 hospitals): weekly-average patient census repeated *exactly* for
>= 4 consecutive weeks at 530 hospitals (12.6%), >= 8 weeks at 347 (8.3%),
>= 26 weeks at 85 (2.0%). HHS documents only up to 4 days of forward-fill.

Not available (stated as limitations, not worked around):
- No public record of which hospital transferred which patient to which.
- No public facility-level capacity data after 2024-04-21 (NHSN releases
  since then are state-level).

Git: tagged `v0.1-negotiation`, created branch `trust-aware-rebuild`.
Environment: Python 3.13.3, numpy 2.2.6, pandas 2.2.3, scipy 1.17.1,
scikit-learn 1.8.0, pyarrow 23.0.1. LightGBM is not installed; scikit-learn's
`HistGradientBoostingRegressor` is used instead (same algorithm family, no
extra dependency).

## 2026-10-10 — Step 1: national data pipeline

- `mahros/data/hhs.py`: fetches both HHS datasets (paged on Socrata row id),
  stores Parquet in `data/cache/` (git-ignored), records row count, fetch time
  and SHA-256 in `data/manifest.json` (committed).
- `-999999` (CDC suppression of counts < 4) is stored as missing **and**
  flagged per measure (`used_suppressed`, `beds_suppressed`).
- Tidy cache file name carries `SCHEMA_VERSION` so a stale cache is never
  reused after the canonical schema changes.
- Verified: corrected 1,045,406 rows / 5,172 hospitals; RAW 964,632 rows /
  5,143 hospitals; **0 duplicate (hospital, week) keys** in either.
- Verify: `python experiments/fetch_national.py`

## 2026-10-10 — Step 2: Data Steward rules (`mahros/trust/`)

- Rules: frozen census / ICU (3 identical weeks, census >= 10), census > beds,
  ICU census > ICU beds, ICU beds > all beds, spikes (> 2.5x vs median of
  previous 3 reports), partial week, sum/average mismatch, not reported,
  CDC-withheld small count.
- Fix during build: 83% of "missing" rows were CDC suppression of counts < 4,
  not absent reports. Split into `SUPPRESSED_SMALL` so small rural hospitals
  are not described as failing to report.
- Fix during build: spike reference changed from "last week" to "median of
  last 3 reports" so the correct week after a typo is not flagged too.
- Fix during build: `assess()` now rejects frames whose hospitals are not
  contiguous (a week-sorted frame would otherwise compare different hospitals).
- Tests: `tests/test_trust.py` (18), including a causality test (appending
  future weeks never changes earlier verdicts).

## 2026-10-10 — Step 3: RQ1 results (`experiments/rq1_trust_audit.py`)

Scope: Short Term + Critical Access hospitals, corrected data.

| | |
|---|---|
| Reports GREEN / AMBER / RED / MISSING | 82.3% / 4.8% / 1.6% / 11.4% |
| Hospitals with >= 1 RED week | 2,079 of 4,712 (44%) |
| Frozen-census flags observed vs expected by chance | 8,325 vs 81 (~1% explainable) |
| Honest exact week-to-week repeat rate | 1.11% (alt. estimate 1.45%) |
| HHS later changed a RED report vs a GREEN report | 30.5% vs 2.6% (11.6x enrichment) |
| Recall vs HHS corrections, by size: <5% / 5-25% / 25-100% / >2x | 0.26 / 0.18 / 0.23 / 0.58 |
| Planted errors caught (400 each): stale, x10, /10, x7, zero, beds x10 | 100% |
| Field swap / +25% one week / +10% four weeks | 91% / 33% / 15% |
| Collateral false alarms on neighbouring clean weeks | 0.00 per episode |

Notes recorded for the paper:
- Drift is caught only via "census > beds" when already above 85% occupancy
  (89% vs 8%). Subtle drift is mostly undetectable; stated, not hidden.
- Most HHS corrections are ~1% adjustments; flat recall against them is not a
  meaningful target, so recall is reported by correction size.
- `ARITHMETIC` never fires: HHS averages always equal sum / days. Kept and
  reported as a null.

## 2026-10-10 — Step 4: RQ2 results (`experiments/rq2_forecast.py`)

MAE in occupancy points on trusted test targets (2023-01 .. 2024-04),
~269k hospital-weeks, ~4,400 hospitals; CIs from 1,000 hospital bootstraps.

| Horizon | Persistence | 4-wk mean | Model (trust-masked) | Model (raw) | 90% PI coverage |
|---|---|---|---|---|---|
| 1 wk | 4.89 | 4.82 | 4.72 | 4.62 | 0.889 |
| 2 wk | 5.88 | 5.28 | 5.21 | 5.19 | 0.901 |
| 4 wk | 6.36 | 5.71 | 5.85 | 5.80 | 0.903 |

Honest findings, kept as found (no tuning on the test window):
- The model beats persistence at every horizon (h=1: -0.17 pts, CI
  [-0.20, -0.15]) but **at h=4 a plain 4-week mean beats it**.
- **Masking untrusted inputs does not improve average forecast accuracy**
  (+0.10 pts worse at h=1). The Steward's value must therefore be shown on
  decisions under large errors (RQ3), not on average accuracy.

## 2026-10-10 — Step 5: agents and coordination (`mahros/agents/`, `mahros/coordination/`)

- Agents: HospitalAgent (one per hospital, final say over its own beds),
  DataStewardAgent, ForecastAgent, RegionalCoordinatorAgent (one per state,
  proposes only). Weekly cycle REPORT -> VERDICT -> FORECAST -> PROPOSAL ->
  RESPONSE -> OUTCOME, one ledger block per state-week (`platform.py`).
- Planner: transportation LP (HiGHS) per state; receivers judged on the upper
  90% forecast bound; plan checked against the next week's real reports.
- Fix during build: `execute()` used to drop arcs to untrusted receivers before
  senders decided, which a real hospital could not know. Changed to the agent
  order (senders decide, then receivers). `tests/test_agents.py` pins the
  agent path equal to the fast path in three trust configurations.
- Fix during build: platform held an unused half-built steward object; removed.
- New audit ledger (`mahros/ledger/chain.py`): deterministic (content + week
  label only), Merkle root per block, `verify()` names the first bad block.

## 2026-10-10 — Step 6: removal of v0.1

Removed (recoverable at tag `v0.1-negotiation`): `core, eval, fairness,
hospital, llm, negotiation, privacy, sim`, old ledger interface and Solidity
contract, old server console, CLI, 13 old experiment scripts, 7 old test
files, old dashboard, `vercel.json` (static-only hosting cannot serve the
ledger API), old docs (PANEL_GUIDE, DEMO, MODEL_ASSUMPTIONS, old
DATA_PROVENANCE). Kept: Houston OSRM route data and fetch scripts.

## 2026-10-10 — Step 7: Houston case study (`experiments/houston_case_study.py`)

27 hospitals with OSRM driving times. Straight-line vs drive time correlation
0.98; road / straight median 1.20 (p90 1.35). Re-planning every test week with
a 60-min drive radius vs 80 km straight line: 13.46% vs 13.48% absorbed, 96%
of transferred load identical. Finding: Houston absorbs ~13% vs ~50%
nationally -> per-state results added to RQ3.

## 2026-10-10 — Step 8: dashboard

- `mahros/server/app.py`: read-only; serves `results/ui/*.json` (name
  whitelist regex), rebuilds the ledger from raw entries at startup and checks
  it matches the published head; tamper/reset demo on an in-memory copy.
- `mahros/server/static/index.html`: one question per tab with a one-sentence
  answer, evidence, and a "what this does not show" box. No external
  libraries; light/dark.
- `tests/test_server.py` (path traversal blocked, tamper detected at the right
  block, reset restores). `tests/ui_smoke.js` runs every render function
  against the real result files with a fake DOM and fails on any
  undefined/NaN shown.

## 2026-10-10 — Step 9: verification

- 51 tests pass (`python -m pytest`).
- `tests/test_forecast.py`: rewriting every future value leaves all inputs at
  or before the cut-off unchanged (no leakage); splits do not overlap.
- RQ1 re-run produced byte-identical results (excluding runtime).
- RQ2 re-run produced identical MAEs.
- Full end-to-end reproduction (`python experiments/run_all.py`, 26 min from
  cached data): RQ1, RQ2, RQ3 and the Houston case study were identical to
  the committed results apart from runtime fields.

## 2026-10-11 — Step 10: live operations console

Requested by the team: a dashboard that shows the system working live, not a
report.

- `mahros/server/live.py`: `LiveEngine` loads the real data at server start
  (~15 s, background thread), keeps one session (state, week, live ledger),
  and steps one real week at a time through the same `Platform.run_week` the
  experiments are pinned to. Each step becomes a readable feed: reports,
  Steward verdicts (with reasons), forecasts, proposals (with reasons),
  hospital answers, ledger seal, result.
- Inject a mistake: one hospital's report for the next week is corrupted
  (x10, /10, x7, zero, swap), re-judged by the Steward on that hospital's real
  history; if caught it is excluded, if not it is believed and the feed says
  so. The feed also shows what the coordinator would have proposed had the
  mistake been believed.
- `Platform.week_frame/run_week(overrides=...)`: optional, live-only; the
  experiments never pass it, and the equivalence tests are unchanged.
- Live tamper on the session ledger; restart for a clean log.
- UI: new first tab (map + newest-first feed + counters + inject + week-by-week
  + audit log). Checked with real headless-Chrome screenshots; fixed oversized
  arrowheads, overflowing selects, a broken bold word, feed order.
- Hosted deployments without pandas/data show a clear "live mode not
  available here" message; evidence tabs unaffected.
- FastAPI `on_event` replaced with `lifespan` (deprecation warning).
- `tests/test_live.py` (5, skipped without the data cache): week runs and is
  sealed; lost digit at a >95%-full hospital is caught, excluded and the
  prevented harm reported; injection lasts one week; tamper detected at the
  right block. Total 56 tests pass.

## 2026-10-11 — Step 11: live console made understandable

Team feedback: the live feed (~150 messages per week) was impossible to
follow, and the state dropdown (postal codes + hospital counts) was unclear.

- Each week is now six steps (report, check, forecast, plan, answer, result),
  advanced with **Next step ›**; one plain sentence per step, big numbers, a
  few named examples, and the map recoloured per step (this week / expected /
  real next week). Built server-side in `LiveEngine._stages` from the same run
  as the ledger, so the words cannot disagree with the numbers (test pins the
  result total).
- Map: numbered badges matching the text instead of overlapping names; zooms
  to the hospitals involved from step 4 on.
- Worked example per week (largest real move), using forecast figures so it
  matches step 4.
- Default state Arizona (74 hospitals; ran a real statewide transfer line).
  States listed by full name; counts removed (they counted all-time hospitals,
  which disagreed with the weekly map).
- `demo_pick`: for every nearly full hospital, actually re-plans as if a
  "digit missing" typo were believed and pre-selects the one where it would
  misdirect the most patients (AZ week 1: Mercy Gilbert, ~24 patients).
  Found because the first choice (Abrazo Central) honestly changed nothing.
- Corrected wording: flagged hospitals are not *sent* patients but can still
  be helped based on earlier trusted reports (the old caption said they were
  left out entirely, which contradicted step 4).
- Full message feed kept under "For experts".
- 59 tests pass; UI smoke passes; checked with headless-Chrome screenshots.

---

# v0.3 revision (spec: `docs/NEXT_SESSION_PROMPT.md`)

## 2026-10-11 — Step 12 (Phase 1): Docker + PostgreSQL

**Why.** Team flaw #3: no real database; the live audit log was lost on
restart.

**Checked before building (live, not assumed).** Dataset metadata for
`anag-cw7u` lists `previous_day_total_ed_visits_7_day_sum`, COVID ED visits,
adult/paediatric COVID admissions, flu admissions, flu inpatients/ICU and
paediatric ICU beds. `g62h-syeh` has the six `critical_staffing_shortage_*`
columns; note its title is the **RAW** state timeseries. OSRM table API and the
NBER POS mirror are reachable.

**What.**
- `experiments/fetch_extra.py` + `hhs.fetch_extra / fetch_state_staffing`:
  the extra fields go into their **own** cache file
  (`hhs_corrected_extra_source.parquet`, 1,045,406 rows, 0 duplicate keys —
  same row count as the main file) and the state series into
  `hhs_state_staffing_source.parquet` (81,713 rows, 54 jurisdictions,
  2020-01-01..2024-04-27). The RQ1–3 input file is untouched, so those results
  stay byte-reproducible. Paged downloads now resume after a network failure
  (fix: the first attempt died on a DNS error at page 2).
- `mahros/db/`: SQLAlchemy 2 models for all spec tables (+ `patient_moves`
  for the weekly plan lines); every row has `source` and `provenance`
  (observed / derived / estimated / simulated / entered, enforced by a CHECK
  constraint). Alembic migration `0001`. Bulk COPY on Postgres, `to_sql` on
  SQLite (`mahros/db/io.py`).
- `python -m mahros.db.load`: migrate → ensure data → skip if fingerprints
  unchanged → hospitals (upsert, never deleted: operational rows point at
  them), weekly_reports (+extra fields), trust_verdicts, forecasts,
  state_staffing → derived steps. Never touches the ledger, emergency cases or
  entered equipment.
- `docker-compose.yml`: db (postgres:16, healthcheck, volume), loader
  (one-shot), app, pgAdmin (desktop mode, pre-registered server, password file
  from the env via a compose `config`). Library versions pinned to the ones
  that produced the committed results (`requirements-docker.txt`).
- App reads its frames from the database (`mahros/db/frames.py`) and writes
  every weekly cycle into the database record book with cross-referenced
  `patient_moves` rows.

**Fixes found by running on real PostgreSQL** (SQLite had silently allowed them):
- Some HHS `hospital_pk` values are 64-character hashes → key column widened
  from 20 to 80.
- pgAdmin refused to start with a `.local` e-mail → `reviewer@example.com`.
- Port 8000 is used by another project on this machine → the Docker app
  publishes on **8080** (`APP_PORT` in `.env` changes it).
- Weekly reports keep name/city/coordinates as written that week: 2 hospitals
  change name or location over time, and the platform must reproduce the
  experiments exactly.

**Verified.**
- Loader on Postgres: 5,172 hospitals, 1,045,406 reports, 160 s; second run:
  "inputs unchanged — nothing to do".
- `tests/test_db_equivalence.py`: the agents give **identical** totals,
  proposals and verdicts from Postgres and from the Parquet files
  (AZ ×2, MA, TX weeks); also passes on SQLite.
- Record book survives an app restart (256 lines, still valid).
- Editing a plan row by hand (psql, same as pgAdmin) is caught and named:
  "patient-move suggestion #1 … 'patients' now says 11.19, but the record
  book wrote 1.19 … (line #208)"; undoing it turns verification green.
- `tests/test_db_ledger.py`: 6 checks × {SQLite, Postgres} pass.
- Verify on Postgres: `MAHROS_TEST_PG_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/postgres`
  and `MAHROS_TEST_DATABASE_URL=postgresql+psycopg://mahros:mahros-local@localhost:5432/mahros`
  then `python -m pytest`.

## 2026-10-11 — Step 13 (Phase 2): audit ledger in the database

**Why.** Team flaw #4: "what does secretly change a past report mean?" — the
old demo edited an in-memory copy, so it proved nothing a reviewer could touch.

**What.** `mahros/ledger/store.py` (`DbLedger`), tables `ledger_entries` and
`ledger_blocks`.
- Each line: `hash = SHA-256(seq, block, time, kind, sender, receiver, referenced row, body + previous hash)`.
  Sequence numbers have no gaps; a page (block) per emergency case or
  state-week stores a Merkle root and the previous page's hash. Postgres
  advisory lock: one writer at a time.
- **Records cross-check:** an entry that announces a bid / transfer / plan
  line copies the row's key fields into `body.record`; `verify()` re-reads the
  row. So editing a **bid in pgAdmin** is caught, not only editing the log.
- `verify()` returns the FIRST problem with a plain sentence: edited line,
  deleted line, inserted line, edited/deleted record, broken page seal.
- API: `GET /api/book`, `POST /api/book/verify`, `POST /api/book/tamper`
  (one-click: changes the newest logged bid's travel time in the database row,
  exactly what a person could do in pgAdmin), `POST /api/book/undo`,
  `GET /api/book/block/{id}`.

**Fix during build.** A test edited a bid's *reason* by hand and verification
still passed: the reason was not a vouched field, so a decline reason could
be rewritten unnoticed. Bids now vouch for hospital, answer, travel time,
ready time **and reason**; the test requires the change to be named.

**Verified.** `tests/test_db_ledger.py` (6 checks, SQLite + Postgres) and
`tests/test_server.py` (one-click tamper names the bid, undo restores, hand
edit of the reason is named). pgAdmin's password file connects without a
prompt (`psql -w` inside the pgAdmin container read 1,045,406 rows).
The plain-language explanation on screen is built with the Phase 6 UI.

## 2026-10-11 — Step 14 (Phase 3): emergency transfer module (the core)

**Why.** Team flaws #1 and #2: weekly planning alone is weak (a government
could phone every hospital weekly); the life-saving problem is the acute
transfer found today by serial phone calls; and the multi-agent part was thin.

**Real inputs vendored** (`experiments/fetch_emergency_network.py`,
`mahros/calibration/data/us_{az,ma}_*.json`):
- Hospitals: every Short Term / Critical Access hospital reporting in
  2022-12-25..2024-04-21 — **71 Arizona, 58 Massachusetts** (the spec's 74/59
  were all-time counts).
- OSRM driving times, all pairs: AZ 71×71, MA 58×58, **0 unroutable** (AZ
  median 142 min, MA 73 min between hospitals).
- CMS POS **Q3 2022** (newest quarter on the NBER mirror), joined on CCN:
  matched **68/71** AZ and **58/58** MA. Unmatched hospitals use only their
  observed HHS ICU / paediatric ICU beds; no capability is guessed.

**Citations checked** (abstracts fetched, not remembered):
- 1.5% of US ED encounters end in transfer to another acute hospital
  (Kindermann et al., Acad Emerg Med 2015; HCUP NEDS 2009) — anchor for the
  swept request rate 0.5/1.0/1.5%.
- Mean ICU stay of Medicare survivors 3.4 d (Moitra et al., Crit Care Med 2016, PMID 26571190).
- The spec's "3% per hour" (PMID 27352032) is Churpek et al., J Hosp Med
  2016 — **ward-to-ICU delay within a hospital**, not interhospital; cited
  with that caveat. PMC4472710 is a Crit Care 2015 **meeting abstract**: 151
  interhospital critical-care transfers in 49 UK hospitals, median delay 22 h,
  driven by organisation not distance.
- ~12 min per transfer phone call: one regional ED study (2003), 4.7 calls,
  56.7 min — old, so call length is swept 5/10/15.
- ACC/AHA 2013 STEMI: FMC-to-device ≤ 120 min when transferring.
- **CDC NHSN guidance effective 2023-06-11 made "previous day's ED visits"
  (element 19) and COVID ED visits (20) OPTIONAL** (read in the PDF). ED
  reporting then fell to ~0 in Massachusetts and ~2/3 in Arizona. ED volume
  only sets the request rate, so a missing week uses the hospital's own
  median of its last 8 reports, labelled "carried forward" with the date.

**Design** (`mahros/emergency/`):
- `HospitalAgent`: private state (ICU census, nurses on shift from the
  Title 22 1:2 ratio, short-staffed or not, ventilators, cath rooms,
  paediatric ICU, its own reserve-bed policy). Answers call-for-bids, awards
  and phone calls by itself with the SAME rule and a reason. Honest — no lying
  hospitals, no argumentation, no oracle reads.
- `steward_check`: bid vs the hospital's own public weekly report (ICU ≥ 100%
  or report RED/MISSING) → confirm by phone (costs one call in the ranking).
- Coordinator (MAHROS): broadcast to all capable hospitals within the clinical
  window at once, 3-min bid window, rank by time to definitive care → capability
  → free beds, one doctor-to-doctor acceptance call.
- Phone baselines: nearest first; and **report-informed** (hospitals whose
  report shows ICU room first). Stop at the FIRST yes (v0.1's discard bug
  pinned by a test). Both arms end with the same acceptance call, so **phoning
  wins when the nearest hospital has room** (pinned by a test).
- `World`: discrete-event week; common random numbers across policies.

**Fixes during build.**
1. Calibration check found simulated ICUs 4–16% emptier than reported at
   near-full hospitals (a full ICU turns patients away). Arrival rates now come
   from the Erlang loss formula so the CAPPED census equals the report:
   total 100.2%, median hospital 99.8% (calibration, not validation).
2. Python's `hash()` of a string changes between runs → cath-lab draws used
   it → replaced by `zlib.crc32` (results were not reproducible).
3. Screenshot showed "short-staffed" in a week with 0% real shortage: nurses
   were rounded down (105-bed ICU → 52 nurses → 104 usable). Rounded up; the
   message now appears only for hospitals drawn short-staffed. Test added.
4. Copying the world for the phone what-if failed (kernel held a module;
   message bus held closures) → plain imports and bound methods.
5. SQLite fallback: "database is locked" while the app read 1M rows → WAL +
   30 s timeout (Postgres unaffected).
6. 4 state-weeks produced no requests (ED not reported) → carry-forward above.
7. The headline sentence on the evidence page was hard-coded "yes" → now
   chosen from the confidence interval.

**Results** (`experiments/emergency_eval.py`, 16 real weeks × 10 runs, 480 runs
+ 3,680 sensitivity runs, `results/emergency_eval.json`):

| | MAHROS | Phone, nearest | Phone, report-informed |
|---|---|---|---|
| Mean time to confirmed bed | 13.2 min | 19.9 | 16.5 |
| Slowest 10% | 13.0 | 37.1 | 29.0 |
| Reached care inside window | 95.7% | 94.4% | 94.8% |
| Bed found | 97.6% | 97.9% | 97.9% |
| Phone calls per patient | 1.00 | 1.99 | 1.66 |

MAHROS − phone nearest: −6.7 min (95% CI −7.2 to −6.2); slowest 10% −24.1
(−25.3 to −22.9); inside window +1.3 pts. One-at-a-time sensitivity range:
−2.0 (5-min calls) to −12.1 min (1.5% request rate). Honest reading: the gain
is in the slow tail and staff phone time; the in-window share barely moves
because the windows are long; MAHROS finds a bed slightly LESS often (phone
callers keep calling while beds free up).

**UI.** New first tab "Emergency": pick a hospital (map, zoom "around the
patient", or list), the need and urgency, "Find a bed", then five steps (ask
all at once → answers with reasons → Steward check → choice with reason →
MAHROS vs phone at 5/10/15-min calls). Every case is written to
`transfer_requests`, `bids`, `transfers` and sealed as a record-book page.
Page split into `static/*.js`; `tests/ui_smoke.js` loads them all.
Screenshot fixes: tiny overlapping Phoenix dots (zoom + list), legend text
leaking into the panel, staffing sentence now gives answered/not-answered
counts, red-but-bidding hospitals explained (weekly average vs now).

**Tests.** `tests/test_emergency.py` (14), `tests/test_emergency_live.py` (3:
every answer has a reason, bids logged, editing a logged bid is caught, the
phone what-if never touches the live world).
