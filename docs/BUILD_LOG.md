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
