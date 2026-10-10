# Methods

This document is written to become the methods section of the paper. Every
number in it is produced by a script in `experiments/` and stored in
`results/`; the script is named next to each claim.

## 1. System

MAHROS is a multi-agent platform for a public authority (for example a state
health department) that coordinates hospital capacity week by week. Four kinds
of agent share the work; each owns one responsibility and communicates only
through messages written to an append-only, hash-chained audit ledger.

| Agent | Count | Responsibility | Authority |
|---|---|---|---|
| Hospital agent | one per hospital | Submits its weekly report; accepts, part-accepts or declines proposals using its own real numbers | Final say over its own beds |
| Data Steward | one | Classifies each report GREEN / AMBER / RED / MISSING with named reasons | Can exclude a report from planning |
| Forecast agent | one | Predicts next-week occupancy with a 90% interval | Advisory |
| Regional Coordinator | one per state | Proposes transfers by solving a linear program | Proposes only; cannot compel |

Weekly cycle (`mahros/agents/platform.py`): REPORT -> VERDICT -> FORECAST ->
PROPOSAL -> RESPONSE -> OUTCOME, sealed as one ledger block per state-week.

**Why agents.** Authority is divided the way it is in practice: the
coordinator sees the region but not inside a hospital this week; each hospital
knows its own state but not the region. A proposal becomes a transfer only if
both hospitals' real numbers allow it. This local check is what makes the
evaluation in RQ3 conservative (Section 4.3).

**Equivalence of the fast path.** The experiments use a vectorised
implementation of the same cycle. `tests/test_agents.py` asserts that the
agent-by-agent run and the fast path produce identical totals, including when
a sender's or a receiver's next report is untrusted.

## 2. Data

U.S. HHS facility-level hospital capacity reports, both the corrected and RAW
releases, downloaded in full (see `docs/DATA_PROVENANCE.md` and
`data/manifest.json` for fingerprints). Analyses use Short Term and Critical
Access hospitals (4,712 hospitals in the corrected release). No patient-level
data is used.

## 3. RQ1 — Report reliability (`experiments/rq1_trust_audit.py`)

### 3.1 Rules

Ten rules (`mahros/trust/checks.py`), each with a level and a plain-language
explanation. RED: frozen census or ICU census (same value for >= 3 consecutive
weeks, census >= 10), census above staffed beds (> 5% tolerance), ICU census
above ICU beds, ICU beds above all beds, census or bed spike (> 2.5x or
< 1/2.5x the median of the previous three reports). AMBER: partial week (< 7
days reported), weekly average inconsistent with sum / days. MISSING: not
reported, or withheld by CDC (count < 4).

All rules are **causal**: a verdict for week *t* uses only weeks <= *t*
(enforced by `test_rules_are_causal`). Rule-based detection is used because
stale values lie inside a series' normal range and are invisible to
distributional detectors (Peysakhovich & Sieradzki, 2026).

### 3.2 Evidence that flags are real

Because no complete answer key exists, three independent lines of evidence:

1. **Chance.** The honest week-to-week exact-repeat probability *p* is
   measured on hospitals that never froze; the expected number of chance
   frozen flags is (eligible weeks) x *p*^2.
2. **Government corrections.** RAW and corrected releases are joined on
   (hospital, week). A row counts as government-corrected if any of census,
   beds, ICU census or ICU beds changed by more than max(0.5, 1%). We report
   the enrichment (P(corrected | RED) / P(corrected | GREEN)) and recall by
   size of correction.
3. **Planted errors.** 400 errors of each of nine real-world types are planted
   into report sequences the Steward considers clean (four clean weeks either
   side, census >= 20). Weekly sums are corrupted consistently so the
   arithmetic rule cannot catch them for free; only RED counts as caught.
   Neighbouring clean weeks wrongly flagged are counted.

A random sample of 15 RED flags per rule is exported for manual review
(`results/rq1_review_sample.csv`).

### 3.3 Results

| | |
|---|---|
| Reports GREEN / AMBER / RED / MISSING | 82.3% / 4.8% / 1.6% / 11.4% |
| Hospitals with at least one RED week | 2,079 of 4,712 (44.1%) |
| Frozen-census flags: observed vs expected by chance | 8,325 vs 81 |
| Honest exact-repeat probability | 1.11% (alternative estimate 1.45%) |
| P(government-corrected) for RED vs GREEN reports | 30.5% vs 2.6% (11.6x) |
| Recall vs government corrections by size (<5% / 5-25% / 25-100% / >2x) | 26% / 18% / 23% / 58% |
| Planted: stale feed, x10, /10, x7, zero entry, beds x10 | 100% caught each |
| Planted: field swap / +25% one week / +10% four weeks | 91% / 33% / 15% |
| Clean neighbouring weeks wrongly flagged | 0 in 3,600 planted episodes |

Subtle drift is caught only through the capacity rule when a hospital is
already near full (+25%: 89% caught above 85% occupancy, 8% below). The
arithmetic rule never fired: HHS weekly averages always equal sum / days.

## 4. RQ2 — Forecasting (`experiments/rq2_forecast.py`)

**Target**: occupancy (census / staffed beds) 1, 2 and 4 weeks ahead.
**Model**: one gradient-boosted tree model across all hospitals
(scikit-learn `HistGradientBoostingRegressor`, absolute-error loss, 400
iterations, learning rate 0.05, 31 leaves, min 200 samples per leaf; fixed in
advance, not tuned on test data). **Inputs**: 21 features available at the
forecast week (`FEATURES` in `mahros/forecast/model.py`). **Split by target
week**: train 2020-08-02 .. 2022-06-26; calibrate 2022-07-03 .. 2022-12-25;
test 2023-01-01 .. 2024-04-21. **Intervals**: split-conformal 90%, by
bed-size quartile. **Scoring**: test hospital-weeks whose target report is
trusted and where persistence has a value (~269,000 rows, ~4,400 hospitals).
**Uncertainty**: 1,000 bootstrap resamples of hospitals.

| MAE (occupancy points) | 1 week | 2 weeks | 4 weeks |
|---|---|---|---|
| Persistence | 4.89 | 5.88 | 6.36 |
| 4-week mean | 4.82 | 5.28 | 5.71 |
| Model, raw reports | 4.62 | 5.19 | 5.80 |
| Model, untrusted reports masked | 4.72 | 5.21 | 5.85 |
| 90% interval coverage (masked model) | 88.9% | 90.1% | 90.3% |

Model minus persistence at 1 week: -0.17 points (95% CI -0.20 to -0.15).
Masked minus raw model at 1 week: +0.10 points (CI +0.09 to +0.11), i.e.
masking untrusted inputs made average accuracy slightly **worse**. At 4 weeks
the 4-week mean outperforms the model.

## 5. RQ3 — Coordination (`experiments/rq3_coordination.py`)

### 5.1 Decision

For each state and decision week *t* (2022-12-25 .. 2024-04-14; 69 weeks), a
transportation linear program moves load from hospitals forecast above a safe
occupancy level theta to hospitals within radius R forecast below it:

    maximise   sum x_ij - eps * sum (d_ij / R) x_ij
    s.t.       sum_j x_ij <= min((p_i - theta) B_i, kappa p_i B_i)
               sum_i x_ij <= (theta - hi_j) B_j      (only if j's report is trusted)
               x_ij >= 0,  d_ij <= R

with p the point forecast, hi the upper 90% bound, B the last trusted staffed
beds (<= 4 weeks old). Defaults theta = 0.90, R = 80 km straight line,
kappa = 0.05, eps = 0.1; solved with HiGHS. Quantities are average census;
x 7 gives patient-days (no length-of-stay assumption needed).

### 5.2 Scoring against what happened

At week *t+1*, each hospital agent applies its real report: senders send at
most their real excess over theta; receivers accept at most their real room
below theta; a hospital whose *t+1* report is untrusted moves nothing. The
outcome is the share of trusted *t+1* above-theta patient-days that could have
been absorbed. Receivers can therefore never be pushed above theta, and a
plan built on a wrong forecast earns nothing for load it could not move.

### 5.3 Comparison arms

none; greedy (biggest excess to nearest with room); persistence forecast +
optimiser; no-trust (model trained on raw reports, every report believed);
MAHROS (masked model + Steward + optimiser); oracle (perfect knowledge of
*t+1*, ceiling). Weekly differences use a moving-block bootstrap over weeks
(block 4, 2,000 resamples).

### 5.4 Planted errors

Errors of six types (x10, /10, x7, zero, field swap, stale value) are planted
into 2%, 5% and 10% of clean decision-period reports with census >= 20. The
Steward, both forecasters and the planner are re-run on the corrupted
reports; plans are scored against the **uncorrupted** next-week reports.
"Overfill if unchecked" is the load the plan would have placed into hospitals
above theta had receivers not checked their real numbers.

### 5.5 Results

| Arm | Absorbed | Plan realised | Overfill if unchecked (patient-days) |
|---|---|---|---|
| none | 0% | — | 0 |
| greedy | 49.9% | 84.6% | 26,356 |
| persistence | 51.4% | 80.9% | 29,023 |
| no_trust | 49.9% | 79.5% | 28,286 |
| MAHROS | 50.2% | 84.4% | 26,555 |
| oracle | 66.5% | 100% | 0 |

Total above-theta load: 3,752,019 patient-days over 69 weeks. Weekly paired
differences in absorbed patient-days (95% block-bootstrap CI): MAHROS - none
+27,294 (26,138 to 28,428); MAHROS - greedy +136 (89 to 181); MAHROS -
persistence -634 (-1,235 to -131); MAHROS - no_trust +172 (-93 to +416, n.s.);
oracle - MAHROS +8,870 (7,633 to 9,987).

| Planted | Absorbed MAHROS / no_trust | Plan realised MAHROS / no_trust | Overfill MAHROS / no_trust | MAHROS - no_trust per week (CI) |
|---|---|---|---|---|
| 2% | 49.4% / 48.3% | 84% / 74% | 25,542 / 72,855 | +586 (279 to 931) |
| 5% | 48.2% / 46.6% | 84% / 67% | 25,868 / 136,832 | +881 (550 to 1,239) |
| 10% | 46.0% / 43.3% | 84% / 58% | 26,383 / 252,547 | +1,478 (1,019 to 1,871) |

Sensitivity (MAHROS / ceiling): theta 0.85: 37.6% / 48.8%; theta 0.95:
65.1% / 95.7%; R 40 km: 42.0% / 58.7%; R 150 km: 55.5% / 70.1%; kappa 2%:
26.2% / 33.2%; kappa 10%: 62.8% / 88.8%.

## 6. Houston case study (`experiments/houston_case_study.py`)

For 27 Houston hospitals with OSRM driving times, every test week is
re-planned with a 60-minute driving radius instead of 80 km straight line.
Straight-line distance and driving time correlate at 0.98 (road / straight
median 1.20, 90th percentile 1.35); the two plans absorb 13.46% vs 13.48% of
overload and share 96% of transferred load.

## 7. Reproducibility

`python experiments/run_all.py` re-runs everything. All randomness is seeded.
The trust rules, forecaster and planner are deterministic given the data
fingerprint in `data/manifest.json`. 51 unit tests (`pytest`) plus a headless
dashboard check (`node tests/ui_smoke.js`).
