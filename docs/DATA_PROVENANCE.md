# Data provenance

Every input to MAHROS, where it comes from, and its status. The same labels
appear in the database (`provenance` column on every row) and on screen.

| Status | Meaning |
|---|---|
| **observed** | read from an official dataset (HHS, CMS, OSRM) |
| **derived** | computed from observed values by a stated rule or model |
| **estimated** | a per-hospital figure no public dataset reports, built from observed values and a published ratio |
| **simulated** | produced by the emergency simulation (grounded in observed values) |
| **entered** | typed in by a person (equipment inventory; seeded with labelled estimates) |
| **assumption** | a choice we made, swept in a sensitivity analysis |

The research questions RQ1–RQ3 and the surge warning use **no simulated
data**. Only the emergency module's minute-level dynamics are simulated.

## 1. Datasets

| Dataset | Publisher | Use | Scope | Licence |
|---|---|---|---|---|
| COVID-19 Reported Patient Impact and Hospital Capacity by Facility (`anag-cw7u`, corrected) | U.S. HHS | Everything | 1,045,406 hospital-weeks, 5,172 hospitals, 2019-12-29 .. 2024-04-21 | Public domain |
| Same dataset, extra fields (ED visits, COVID / flu admissions, paediatric ICU) — own cache file | U.S. HHS | Surge warning, emergency request rates, paediatric ICU | same rows (1,045,406) | Public domain |
| Same dataset, RAW version (`uqq2-txqb`) | U.S. HHS | RQ1: comparison with the government's own corrections | 964,632 hospital-weeks | Public domain |
| COVID-19 Reported Patient Impact and Hospital Capacity by State Timeseries (RAW) (`g62h-syeh`) | U.S. HHS | Real state share of hospitals with a critical staffing shortage | 81,713 state-days, 54 jurisdictions, 2020-01-01 .. 2024-04-27 | Public domain |
| CMS Provider of Services file, Q3 2022 (NBER mirror) | CMS | What each Arizona / Massachusetts hospital can treat (cath lab, cardiac surgery, neurosurgery, trauma, burns, paediatric ICU, ICU) | 68 of 71 AZ and 58 of 58 MA hospitals matched on CCN | Public domain |
| OSRM routed driving times over OpenStreetMap | OSRM / OpenStreetMap contributors | Emergency travel times (AZ 71×71, MA 58×58, 0 unroutable); Houston case study (27×27) | — | ODbL |

Download time, row counts and SHA-256 fingerprints: [`data/manifest.json`](../data/manifest.json).
Vendored inputs (networks, routes, capability): `mahros/calibration/data/`,
re-built by `experiments/fetch_emergency_network.py`.

**No patient-level data is used anywhere.**

## 2. Fields used

All bed and census figures are **7-day averages**; admissions and ED visits
are **7-day sums**.

| MAHROS name | Source field | Used by |
|---|---|---|
| `beds`, `used` | `inpatient_beds_7_day_avg`, `inpatient_beds_used_7_day_avg` | everything |
| `icu_beds`, `icu_used` | `total_staffed_adult_icu_beds_7_day_avg`, `staffed_adult_icu_bed_occupancy_7_day_avg` | everything |
| `covid_used` | `inpatient_beds_used_covid_7_day_avg` | forecaster |
| `ed_visits` | `previous_day_total_ed_visits_7_day_sum` | emergency request rate; surge signal |
| `covid_ed_visits` | `previous_day_covid_ed_visits_7_day_sum` | stored |
| `covid_adm_adult`, `covid_adm_peds` | `previous_day_admission_{adult,pediatric}_covid_confirmed_7_day_sum` | surge signal |
| `flu_adm` | `previous_day_admission_influenza_confirmed_7_day_sum` | surge signal |
| `flu_used`, `flu_icu`, `covid_icu` | influenza / COVID inpatient and ICU 7-day averages | stored |
| `picu_beds`, `picu_used` | `total_staffed_pediatric_icu_beds_7_day_avg`, `staffed_pediatric_icu_bed_occupancy_7_day_avg` | emergency (children's ICU) |
| `shortage_today_yes/no/not_reported` | `critical_staffing_shortage_today_*` (state, daily) | staffing check; short-staffed share in the simulation |
| capability flags | POS `*_SRVC_CD` codes 1 or 3 (on site) | emergency |

`-999999` means CDC withheld a count below 4. It is stored as missing **and**
flagged; in surge-warning area totals a withheld admission count enters as 2
(derived).

**Reporting change, 2023-06-11:** CDC's NHSN guidance made "previous day's ED
visits" and COVID ED visits **optional**. ED reporting then fell to ~46% of
facility reports nationally and almost none in Massachusetts. The surge
warning works without ED visits (tested); the emergency simulation uses the
hospital's own median of its last 8 reported weeks, labelled "carried forward".

## 3. Classification of every quantity

| Quantity | Status | Source or rule |
|---|---|---|
| Beds, census, ICU, admissions, ED visits, location, type | **observed** | HHS fields above |
| State share of hospitals with a staffing shortage | **observed** | HHS `g62h-syeh` |
| Hospital capability (AZ, MA) | **observed** | CMS POS Q3 2022; unmatched hospitals use only their observed ICU / paediatric ICU beds |
| Driving times | **observed** | OSRM free-flow (no traffic, no emergency-vehicle privilege) |
| Trust verdict | **derived** | `mahros/trust/checks.py`, causal |
| Forecast and 90% range | **derived** | fitted 2020-08..2022-06, calibrated 2022-07..2022-12 |
| Weekly plan lines (patients) | **derived** | RQ3 linear program |
| Surge signals, chance of crossing, alerts | **derived** | `mahros/surge/`, model trained 2020-08..2022-06 |
| Nurse and physician pools / need per hospital | **estimated** | usual staffed beds × Title 22 ratios (ICU 1:2, ward 1:5); intensivists 1:14 (Ward et al. 2013); ward physicians 1:15 (assumption) |
| Nurse loans, equipment moves | **derived** | weighted transportation LP over estimated / entered inputs |
| Equipment inventory | **entered** | seeded once: ventilators 1 per usual ICU bed; ECMO 2 at cardiac-surgery or ≥ 50-ICU-bed hospitals; ICU dialysis 1 per 6 ICU beds; monitors 1 per 10 beds |
| Equipment use ratios | **assumption** | ventilators 40% of ICU patients, ECMO 2%, dialysis 10%, monitors 1 per 12 inpatients, +15% in surge-warned areas |
| Minute-level ICU arrivals / discharges, transfer requests, bids, transfers | **simulated** | `mahros/emergency/world.py`, calibrated to each hospital's reported census |
| Mean ICU stay 3.4 days | cited | Moitra et al., Crit Care Med 2016 (PMID 26571190) |
| ICU nurse ratio 1:2 | cited | California Code of Regulations, Title 22, §70217 |
| Transfer-request rate (1.0% of ED visits; swept 0.5–1.5%) | **assumption** | anchor: 1.5% of ED encounters end in transfer (Kindermann et al., Acad Emerg Med 2015) |
| Phone call length (10 min; swept 5–15) | **assumption** | anchor: 4.7 calls / 56.7 min per accepted transfer (one regional ED study, 2003) |
| Bid window (3 min; swept 1–5), reserve beds (1; swept 0–2), short-staff cut (15%; swept 0–30%), cath-lab use and call-in, surgery readiness, ventilator share | **assumption** | `mahros/emergency/params.py` (every one listed with its reason on Evidence → 4) |
| Clinical windows (cath lab 120 min, trauma / neurosurgery 120, ICU / ventilator / paediatric ICU / burns 240; ×0.5 / ×2 swept) | **assumption** | cath lab anchored on ACC/AHA 2013 (first contact to device ≤ 120 min when transferring) |
| Need mix (ICU 40%, ventilator 15%, cath lab 15%, trauma 10%, neurosurgery 10%, paediatric ICU 5%, burns 5%) | **assumption** | not published |
| Frozen-run length, spike ratio, minimum census, capacity tolerance | **assumption** | swept in `rq1_trust_audit.py` |
| Safe occupancy 90%, radius 80 km, weekly cap 5% | **assumption** | swept in RQ3 |
| Surge line 85%, area radius 50 km | **assumption** | 80% / 90% swept |
| Planted error types and rates | **assumption** | `mahros/trust/inject.py`, `rq3_coordination.py` |

## 4. What this data cannot establish

1. **Self-reported, weekly, ending 2024-04-21.** Within-week peaks are
   invisible; public facility-level data stopped when the federal mandate
   lapsed (NHSN releases since November 2024 are state-level).
2. **No record of actual transfers.** Weekly proposals are scored against next
   week's real reports; emergency results come from the simulation.
3. **Bed totals, not specialties** (except POS capability codes, which say a
   service exists, not how many beds or teams are free).
4. **Staff per hospital is not public** — estimated, and agrees only weakly
   with real shortage reports. **Equipment is not public** — entered.
5. **Minute-level dynamics are simulated**; road times are free-flow.
6. **Excludes** VA, Indian Health Service and Department of Defense hospitals
   (not in the dataset), and children's, long-term and psychiatric hospitals.
