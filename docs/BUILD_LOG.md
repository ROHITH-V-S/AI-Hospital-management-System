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
