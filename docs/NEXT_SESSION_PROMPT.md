# MAHROS — handoff prompt for a fresh session

Copy everything below the line into a new chat, opened in
`C:\Users\Rohith\Desktop\mahros`.

---

You are continuing work on **MAHROS — Multi-Agent Hospital Resource
Optimization System**, a student team's AI project (Windows, VS Code, repo at
`C:\Users\Rohith\Desktop\mahros`, branch `trust-aware-rebuild`). It will be
shown to a review panel and later written up as a journal paper. The registered
title is fixed: **"Multi-Agent"** must stay and must be genuinely true.

## 0. How to work with me

- I want blunt honesty. No sugarcoating, no false positives. If something is
  weak, say so and say why.
- Explain things so a five-year-old could follow (short analogy + one plain
  sentence), then give the technical detail.
- **First** read the repo (README.md, docs/REVIEW_GUIDE.md, docs/METHODS.md,
  docs/DATA_PROVENANCE.md, docs/BUILD_LOG.md, this file), then give me a short
  confirmation of the build order below and start building. Don't re-ask
  decisions that are already made here.
- Log every step in `docs/BUILD_LOG.md` (what, why, how to verify, any fix
  made). Commit after each phase on branch `trust-aware-rebuild` with a clear
  message. Never push. The old version is at git tag `v0.1-negotiation`.
- "Make no mistakes": write tests before relying on code, re-check numbers you
  put in docs against the result files, check the UI with real headless-Chrome
  screenshots (`C:\Program Files\Google\Chrome\Application\chrome.exe
  --headless=new --screenshot=... --virtual-time-budget=...`) and look at them.
  Fix what looks wrong before saying it's done.
- Every number shown anywhere must come from a script or the database, never
  typed by hand.

## 1. Where the project stands (already built and committed)

**History.** v0.1 simulated hospitals negotiating transfers, with "liar"
hospitals and argumentation. The audit found its key results were produced by
the simulator's own hidden truth (a challenged hospital's defence read a
`misreported` flag; struck-out refusals were replaced by an oracle "truthful
bid"), its occupancy "validation" was circular (arrival rates fitted to the
same occupancy they were then "validated" against), all demand was simulated,
and its reference week contained frozen bed reports. The first review panel
attacked it for using simulated data. v0.1 was replaced.

**Current version (v0.2), all on real federal data:**
- `mahros/data/hhs.py` — downloads both HHS releases of *COVID-19 Reported
  Patient Impact and Hospital Capacity by Facility* (corrected `anag-cw7u`:
  1,045,406 rows, 5,172 hospitals, 2019-12-29..2024-04-21; RAW `uqq2-txqb`:
  964,632 rows), Parquet cache in `data/cache/` (git-ignored), SHA-256 in
  `data/manifest.json`. `-999999` = CDC suppression (<4), kept as missing AND
  flagged `*_suppressed`.
- `mahros/trust/` — **Data Steward** rules (causal, explainable): frozen
  census/ICU (3 identical weeks, census>=10), census>beds, ICU>ICU beds, ICU
  beds>all beds, spike >2.5x vs median of previous 3 reports, partial week,
  sum/avg mismatch, not reported, CDC-withheld. Planted-error benchmark.
- `mahros/forecast/` — global HistGradientBoosting occupancy forecaster,
  split-conformal 90% intervals; train 2020-08..2022-06, calibrate
  2022-07..2022-12, test 2023-01..2024-04.
- `mahros/coordination/` — per-state transportation LP (HiGHS): move load from
  hospitals forecast >90% to hospitals within 80 km forecast below 90% (upper
  bound), cap 5% of census/week; scored against the next week's real reports;
  receivers never pushed over 90%.
- `mahros/agents/` — HospitalAgent, DataStewardAgent, ForecastAgent,
  RegionalCoordinatorAgent; weekly cycle sealed into `mahros/ledger/chain.py`
  (deterministic hash chain, Merkle root per block, `verify()` names the first
  bad block).
- `mahros/server/` — FastAPI + one static page. Tabs: **Live operations**
  (six-step walkthrough of a real week: report, check, forecast, plan, answer,
  result; Next step button; numbered map badges; zoom; "add a mistake" with
  `demo_pick` that pre-selects the hospital where a believed typo would really
  misdirect patients; tamper demo), About, three Evidence tabs, Audit log,
  Limits. Live mode needs the data cache (~15 s load).
- Experiments: `experiments/run_all.py` reproduces everything (~26 min);
  verified byte-identical on rerun. 59 tests (`python -m pytest`) +
  `node tests/ui_smoke.js`.

**Real findings so far (keep them; they're the honest core of the paper):**
- RQ1: 1.6% of weekly reports RED; 2,079/4,712 hospitals (44%) had >=1 RED
  week; 8,325 frozen-census flags vs 81 expected by chance; RED reports 11.6x
  more likely than GREEN to be later corrected by HHS (30.5% vs 2.6%);
  planted errors (stale, x10, /10, x7, zero, beds x10) caught 100%; field swap
  91%; +25% drift 33%; +10% drift 15%; 0 collateral false alarms.
- RQ2: MAE (occupancy points) 1 wk: persistence 4.89, model 4.72; 2 wk 5.88 vs
  5.21; 4 wk a plain 4-week mean (5.71) beats the model (5.85). Masking
  untrusted inputs did NOT improve average accuracy (+0.10 worse). Coverage
  ~89-90%.
- RQ3 (69 weeks, all states): coordination absorbs 50.2% of above-90%
  patient-days (oracle ceiling 66.5%); "same as this week" forecast does
  slightly better (51.4%, significant); trust vs no-trust not significant on
  real data, but with planted errors (2/5/10%) the no-trust plan pushes
  73k/137k/253k patient-days toward really-full hospitals vs ~26k with MAHROS;
  plan realisable 84% vs 74/67/58%. Houston absorbs only ~13%; by state TX 39%,
  MN 18%, MA 69%. Houston road-time check: straight line vs 60-min drive radius
  gives the same result (13.46% vs 13.48%, 96% same transfers).

## 2. Flaws the team raised that this revision must fix

1. **Weekly planning alone is weak in real life**: a government could phone
   every hospital weekly. The life-saving problem is the **acute emergency
   transfer** (a deteriorating patient needs an ICU/cath-lab/trauma bed *now*;
   today found by serial phone calls; literature: median 22 h delay to
   critical care in 49 UK hospitals [PMC4472710]; ~3% higher odds of death
   per hour of ICU-transfer delay [PubMed 27352032]).
2. **The multi-agent part is thin**: today one LP decides and hospital agents
   only apply a fixed accept rule. Make agents genuinely autonomous (private
   state, own decisions, parallel messaging).
3. **No real database**: data lives in Parquet/JSON and the live ledger is lost
   on restart.
4. **The audit ledger demo is not understood** ("what does secretly change a
   past report mean?").
5. **Resource optimisation is only patient transfer**: staff and equipment
   must be included (for the review; the paper may later drop equipment).
6. **Outbreak idea**: the team wants an early warning. Symptom-level data is
   NOT public (CDC syndromic surveillance is restricted), so do **not** claim
   "pandemic prediction". Build a **surge early-warning** system on real data
   instead (below).

## 3. Decisions already made by the team

1. **Dockerize everything**: `docker compose up` must start PostgreSQL, pgAdmin,
   the app, and a one-shot loader. (Docker 29.3.1 + Compose v5.1.1 are
   installed.)
2. **Emergency module may simulate from static data**: real hospitals, real
   weekly capacity as the baseline, real road times, real ER volumes; minute-
   by-minute bed changes and the emergency requests are simulated from those.
   Always labelled "simulation grounded in real data".
3. **Implement staff AND equipment** for the review. Equipment has no public
   per-hospital data, so it is an inventory the state enters (seeded with
   clearly-labelled estimates). No research claims rest on equipment.
4. **Two states** for the emergency module with real road times: use
   **Arizona** (74 hospitals; ran the real Arizona Surge Line transfer
   service) and **Massachusetts** (59 hospitals, dense). Fetch OSRM driving
   time matrices for both (public OSRM table API; <=100 points per request is
   fine; vendor the result in `mahros/calibration/data/`, as already done for
   Houston, with provenance). If OSRM is unavailable, say so; don't fake it.

## 4. Verified data facts (checked against healthdata.gov metadata)

Facility-level (`anag-cw7u`), weekly, per hospital — **available**:
`previous_day_total_ed_visits_7_day_sum`, `previous_day_covid_ed_visits_7_day_sum`,
`previous_day_admission_adult_covid_confirmed_7_day_sum` (+ age bands,
paediatric), `total_patients_hospitalized_confirmed_influenza_7_day_avg/sum`,
`icu_patients_confirmed_influenza_*`, beds/census/ICU fields already used.
**Not available per hospital**: staffing shortages, ventilators, PPE/supplies.
State-level daily (`g62h-syeh`, "by State Timeseries"): **available**:
`critical_staffing_shortage_today_yes/no/not_reported`,
`critical_staffing_shortage_anticipated_within_week_yes/...` (counts of
hospitals). Check for any other field before using it; never assume.
NHSN mandatory reporting resumed 2024-11-01 but public data is state-level
only.

## 5. What to build (in this order)

### Phase 1 — Docker + PostgreSQL
- `docker-compose.yml`: `db` (postgres:16, volume, healthcheck), `pgadmin`
  (pre-configured server entry so the reviewer can browse tables), `loader`
  (one-shot: downloads/reads data, runs the pipeline, fills the DB, idempotent),
  `app` (FastAPI). `.env.example`; no secrets in git. One-command start and a
  README section "Start everything".
- Use SQLAlchemy 2 + psycopg; migrations with Alembic. Keep the experiments'
  Parquet path working (research reproducibility) but make the **app read and
  write PostgreSQL**.
- Schema (at least): `hospitals`, `weekly_reports` (all real fields incl. ER
  visits, COVID/flu), `trust_verdicts`, `forecasts`, `surge_signals`,
  `surge_alerts`, `transfer_requests`, `bids`, `transfers`, `staff_pools`,
  `staff_loans`, `equipment_inventory`, `equipment_moves`, `state_staffing`
  (real state shortage series), `ledger_blocks`, `ledger_entries`,
  `data_manifest`. Every row carries provenance (`source`, `observed|derived|
  simulated|entered`).
- Tests run against a throwaway Postgres (docker) or SQLite fallback for unit
  tests; say which.

### Phase 2 — Audit ledger in the database, explained
- Store the hash chain in Postgres. Each entry's hash covers its content and
  the previous hash.
- Plain explanation in the UI: "a record book in pen; each page carries a
  fingerprint of the page before; after a bad outcome nobody can claim 'we were
  never asked' — the log shows the request at 10:42 and the refusal at 10:44".
- **Tamper demo for real**: the reviewer edits a row in pgAdmin by hand (e.g.
  changes a hospital's bid), presses "Verify log" in the dashboard, and it turns
  red naming the exact entry. Keep the one-click demo too. Test it.

### Phase 3 — Emergency transfer module (the core; minutes timescale)
- A genuine multi-agent **parallel call-for-bids** (Contract Net style):
  1. Origin hospital raises a request: patient needs (ICU bed, ventilator,
     cath lab, trauma/neuro surgery, burns, paediatric ICU) + acuity + clinical
     time window.
  2. Emergency coordinator broadcasts to hospitals within reach (real road
     times).
  3. Each **hospital agent decides by itself** from its **private** live state
     (beds by type, staff on shift, equipment, its own reserve policy and
     capability): bid (ETA, readiness) or decline with a reason.
  4. Data Steward checks bids that contradict the hospital's own recent
     reports (e.g. bidding an ICU bed while reporting 100% ICU full).
  5. Coordinator picks the best bid (time to definitive care first, then
     capability, then load balance); receiver confirms; bed is reserved;
     everything goes to the ledger.
- **Do NOT reintroduce v0.1's flaws**: no "lying hospital" policies, no
  argumentation, no oracle/ground-truth reads in any decision, no claims of
  "zero false accusations". Hospitals bid honestly from their simulated state;
  the contribution is speed + coverage + data checks, not deceit detection.
- Live state simulation: start each hospital at its **real reported** occupancy
  for the chosen week; within-week admissions/discharges as a stochastic
  process whose weekly average matches the real report (this is calibration,
  NOT validation — never call it validation); emergency requests generated
  from real `previous_day_total_ed_visits` x a published interhospital
  transfer rate (cite source; sweep it). Capability: CMS Provider of Services
  service codes (`mahros/calibration/capability.py` already joins on CCN —
  extend to AZ and MA), labelled observed; anything not in POS is labelled
  estimated.
- Baseline: serial phone calls (one hospital at a time). Every timing
  parameter (call duration, coordinator availability) must have a cited
  source or be swept in sensitivity; report results as a range, not a single
  flattering number. Avoid the v0.1 bug where the phone baseline discarded a
  hospital that said yes.
- Metrics: time to bed (request -> confirmed bed), share placed within the
  clinical window, travel time, number of hospitals contacted, coordinator
  minutes; seeds + paired comparisons; sensitivity table.
- Live UI tab **"Emergency"** (make it the first tab): pick state (AZ/MA),
  click a hospital on the map, choose what the patient needs, press "Find a
  bed". Show, step by step like the current walkthrough: request sent to N
  hospitals at once -> each answers (bid/decline with reason, on the map) ->
  Steward check -> best bed chosen with reason -> timeline comparison "MAHROS:
  40 seconds vs phone calls: ~X minutes (range)". Plain sentences, numbered
  badges, no message flood (expert drawer for raw messages).

### Phase 4 — Surge early warning (real data)
- Signals per hospital and per neighbourhood (hospitals within R km): weekly
  ER visits, new COVID admissions, flu inpatients, occupancy trend.
- Model: predict "this area will exceed X% occupancy within 1-2 weeks"; plus a
  transparent spatial anomaly rule ("k neighbouring hospitals rising together").
  Train/calibrate/test by time like RQ2; baselines (persistence, trend);
  report precision/recall/lead time on real 2022-24 waves; honest about misses.
- Alerts feed the planner (pre-position staff/beds) and show on the map.
- Name it "surge early warning", never "pandemic prediction".

### Phase 5 — Resource orchestration: staff and equipment
- **Beds/ICU**: existing weekly LP (keep).
- **Staff**: per-hospital nurse/physician pools **estimated** from staffed
  beds x published nurse-to-patient ratios (cite; label `estimated`); a
  staff-loan optimiser (who lends nurses to whom, within travel limits, without
  dropping the lender below its own safe ratio). Validate the *direction* of
  shortages against the **real** state-level `critical_staffing_shortage_*`
  series (correlation / timing), and say clearly that per-hospital staff
  numbers are estimates.
- **Equipment** (ventilators, ECMO, dialysis, portable monitors): state-entered
  inventory table, seeded with labelled estimates; optimiser moves units to
  hospitals with alerts or emergencies; UI lets the presenter edit inventory.
  Clearly marked "entered / not from public data".
- One combined weekly "orchestration plan" (patients, staff, equipment), each
  line with a plain reason.

### Phase 6 — One command-centre UI
- Tabs: Emergency (minutes) · This week (planning walkthrough, existing) ·
  Early warning · Resources (staff/equipment) · Data trust · Audit log ·
  Evidence (RQ1-3) · Limits.
- Keep the current clarity rules: one question per screen, one plain-sentence
  answer, step-by-step with Next step, numbered badges matching text, full
  state names, "What this does not show" box on every screen, data provenance
  labels (observed / estimated / simulated / entered) visible on the screen.
- Check every screen with headless-Chrome screenshots and `ui_smoke.js`.

### Phase 7 — Docs, tests, verification
- Update README (docker quick start), REVIEW_GUIDE (new 3-minute demo script
  incl. emergency, early warning, resources, pgAdmin tamper; reviewer Q&A incl.
  "why not just phone hospitals", "where is the multi-agent part", "is it
  real-time", "what is simulated"), METHODS, DATA_PROVENANCE (every new field
  classified), BUILD_LOG.
- Full test suite + UI smoke + reproduce run; cross-check every doc number
  against result files with a script.

## 6. Honest framing to keep everywhere

- Real-time claim: "a working prototype of a state transfer-coordination
  service; emergency timing is a simulation grounded in real hospital data;
  weekly planning and early warning run on real reports". It is not deployed
  and moves no real patients.
- Paper focus (later): trust audit + emergency allocation; early warning and
  resources are platform features. Equipment results are not research claims.
- If something does not work or a result is unflattering, report it as found.

## 7. Known limitations to state, not hide

Weekly self-reported data ending 2024-04-21; no public record of real
transfers; bed totals not specialties (except POS capability codes); staff per
hospital estimated; equipment entered; emergency minute-level dynamics
simulated; OSRM free-flow times (no traffic).
