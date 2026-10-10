# Data provenance

Every input to MAHROS is listed here with where it comes from, and whether it
is **observed** (read from an official dataset), **derived** (computed from
observed values by a stated rule), or an **assumption** (a choice we made,
swept in sensitivity analysis). Nothing in the analysis is simulated.

## 1. Datasets

| Dataset | Publisher | Use | Rows / scope | Licence |
|---|---|---|---|---|
| COVID-19 Reported Patient Impact and Hospital Capacity by Facility (`anag-cw7u`, corrected) | U.S. Dept. of Health & Human Services | All analyses | 1,045,406 hospital-weeks, 5,172 hospitals, 2019-12-29 .. 2024-04-21 | Public domain |
| Same dataset, RAW version (`uqq2-txqb`) | U.S. Dept. of Health & Human Services | RQ1: comparison with the government's own corrections | 964,632 hospital-weeks, 5,143 hospitals, 2020-08-02 .. 2024-04-21 | Public domain |
| OSRM routed driving times over OpenStreetMap | OSRM project / OpenStreetMap contributors | Houston case study only | 27 x 27 hospitals | ODbL (OpenStreetMap) |
| CMS Provider of Services file, Q1 2021 | Centers for Medicare & Medicaid Services | **Not used in the current analyses.** Kept (`mahros/calibration/data/`) for the specialty-aware extension listed in the limitations | 27 Houston hospitals | Public domain |

Exact download time, row counts and SHA-256 fingerprints are in
[`data/manifest.json`](../data/manifest.json). Re-download with
`python experiments/fetch_national.py --refetch`; if the fingerprint differs,
the source has changed and results may differ.

**No patient-level data is used anywhere.** Every number is a weekly total for
a whole hospital.

## 2. Fields used

All bed and census figures are **7-day averages** of daily reports.

| MAHROS name | Source field | Meaning |
|---|---|---|
| `beds` | `inpatient_beds_7_day_avg` | Staffed inpatient beds (includes ICU) |
| `used` | `inpatient_beds_used_7_day_avg` | Inpatients (census) |
| `icu_beds` | `total_staffed_adult_icu_beds_7_day_avg` | Staffed adult ICU beds |
| `icu_used` | `staffed_adult_icu_bed_occupancy_7_day_avg` | Adult ICU patients |
| `covid_used` | `inpatient_beds_used_covid_7_day_avg` | Inpatients with COVID-19 (forecast input only) |
| `*_sum`, `*_cov` | `*_7_day_sum`, `*_7_day_coverage` | Weekly sum and days reported (consistency check) |
| `lat`, `lon` | `geocoded_hospital_address` | Hospital location |
| `subtype` | `hospital_subtype` | Analyses use Short Term and Critical Access hospitals |

`-999999` in the source means CDC withheld a count below 4 for privacy. It is
stored as missing **and** marked as withheld, so a small hospital is never
described as failing to report.

## 3. Classification of every quantity

| Quantity | Status | Source or rule |
|---|---|---|
| Beds, census, ICU beds, ICU census | **observed** | HHS fields above |
| Hospital location, type | **observed** | HHS fields above |
| Trust verdict (GREEN/AMBER/RED/MISSING) | **derived** | Rules in `mahros/trust/checks.py`, applied causally |
| Occupancy | **derived** | census / staffed beds |
| Forecast and 90% range | **derived** | Model fitted on 2020-08 .. 2022-06, calibrated on 2022-07 .. 2022-12 |
| Straight-line distance | **derived** | Haversine from observed coordinates |
| Houston driving times | **observed** | OSRM over OpenStreetMap (free-flow) |
| Frozen-run length (3), spike ratio (2.5x), minimum census (10), capacity tolerance (5%) | **assumption** | Swept in `rq1_trust_audit.py` |
| Safe occupancy level (90%) | **assumption** | Swept: 85%, 95% |
| Transfer radius (80 km) | **assumption** | Swept: 40, 150 km; checked against driving times in Houston |
| Weekly transfer cap (5% of census) | **assumption** | Swept: 2%, 10% |
| Planted error types and rates | **assumption** | Stated in `mahros/trust/inject.py` and `rq3_coordination.py` |

## 4. What this data cannot establish

1. **Self-reported, weekly.** Hospitals reported to HHS directly or through
   their state. Within-week peaks are invisible.
2. **Ends 2024-04-21.** The federal mandate lapsed on 2024-04-30. Since
   2024-11-01, CMS again requires hospitals to report bed capacity to CDC NHSN
   (12 bed fields), but public releases are state-level only.
3. **No record of actual transfers.** The dataset does not say which hospital
   sent patients where. MAHROS's transfers are proposals scored against the
   next week's real reports, never claims about transfers that happened.
4. **Bed totals, not specialties.** A free general bed cannot take every
   patient. Absorption figures are therefore upper estimates.
5. **Excludes** VA, Indian Health Service and Department of Defense hospitals
   (not in this dataset), and children's, long-term and psychiatric hospitals
   (excluded by us as not interchangeable with general acute beds).
