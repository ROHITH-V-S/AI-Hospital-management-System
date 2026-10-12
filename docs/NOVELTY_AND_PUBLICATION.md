# Is MAHROS novel, and can it be published?

An honest assessment written on 2026-10-12 from a targeted literature search
(about 20 searches across PubMed, arXiv, INFORMS, CHEST, Frontiers, BMC and
government sources — **not** a systematic review; do one before submission).
Every paper named below was found and checked; nothing is cited from memory.

---

## 1. The short answer

- **As one big "system" paper: probably not novel enough for a good journal.**
  Each piece has close prior work, and a reviewer will say "parallel bed search,
  LP load balancing and occupancy forecasting all exist".
- **But one part is genuinely new and publishable:** measuring, nationally, how
  often hospitals' capacity reports are wrong — checked against the
  government's own corrections — and showing how much those wrong reports
  would misdirect a coordination plan. The search found **no paper that does
  either**.
- **The emergency module is a reasonable second contribution, not a lead
  one,** because its timings come from a simulation.
- **Realistic plan:** one focused journal paper (data trust → decisions), built
  on the multi-agent platform so the title stays true, plus optionally a second
  paper or conference paper on the emergency call-for-bids.

> 🧒 Lots of people have built ways to move kids between full and empty
> classrooms. Almost nobody checked whether the classrooms were counting their
> kids correctly — and what happens to the moving plan when they are not. That
> second question is ours.

## 2. Gap map: each part vs the closest existing work

| MAHROS part | Closest existing work (found) | What they did | What MAHROS adds | Novelty |
|---|---|---|---|---|
| **RQ1 — reliability of facility capacity reports** | GAO-21-600 (2021); HHS ASPE data-quality brief (2022) | Said HHS hospital data needs "external validation"; rated indicators qualitatively | First national, quantitative audit: 1.6% of reports cannot be right, 44% of hospitals sent at least one; frozen counts 8,325 vs 81 by chance; flagged reports 11.6× more likely to be corrected by HHS itself; planted-error benchmark | **Strong** — no peer-reviewed quantitative validation found |
| **Wrong reports → wrong decisions** (RQ3 planted errors) | Parker et al., arXiv 2011.03528 (LP redistribution, NJ/FL/TX); Chan, Park, Pogacar & Sarhangian, *M&SOM* 2026 (queueing network, 17 Ontario hospitals); Yaqin et al., *Syst. Sci. Control Eng.* 2025 (forecast + IP) | Optimise transfers assuming reported capacity is right; uncertainty only in demand | Quantifies harm of misreported capacity: with 2/5/10% errors, a believe-everything plan sends 72.9k/136.8k/252.5k patient-days toward really-full hospitals vs ~26k with the Data Steward | **Strong** — search found no study of misreported capacity |
| **Weekly coordination (RQ3 itself)** | Parker et al.; Chan et al. (up to 48.4% fewer patient-days above 95%); Carmichael et al., *J Hosp Med* 2025 (load-balancing protocol) | LP / queueing redistribution, some on real data | Scored against what hospitals **really reported next week**, with a hospital veto; every US state | **Moderate** — method is standard; the evaluation design is the contribution |
| **Real statewide transfer centres** | Villarroel et al., *Front Public Health* 2023 (Arizona Surge Line: 84% placed, **median 59 min**); Minnesota C4/MOCC, *CHEST* 2023 (36% of requests placed); Washington MOCC, *DMPHP*; Korea NEMSR, *BMC Emerg Med* 2023 (81% coordinated) | Descriptive evaluations of human-run centres, some on a software platform (Central Logic) | A testable agent design + honest comparison against serial phoning | Background, not competition — but it shows **centralised bed search already exists in practice** |
| **Emergency call-for-bids (Contract Net)** | Hsieh & Lin (CNP + Petri nets, patient scheduling *inside* a hospital); edge-based multi-agent bed model; 2026 conceptual multi-agent bed framework (simulation only); Korean pilot (2026, press) that "checks several hospitals at once" | Agents or parallel querying, but not evaluated on real interhospital networks against fair baselines | Real AZ/MA networks, CMS capability, OSRM road times, calibrated ICUs; fair baselines (stop at first yes; report-informed phoning); Data-Steward check of bids against the hospital's own report; results as ranges | **Moderate–weak** — idea not new; rigorous evaluation is, but it is simulated |
| **Surge early warning** | "Generating simple classification rules to predict local surges in COVID-19 hospitalizations", *Health Care Manag Sci* 2023 (PMID 36692583); county models (Bhowmik & Eluru, *Sci Rep* 2021); wastewater models | Local surge prediction, mostly COVID admissions | Facility-centred areas, capacity (85% full) target, fair baselines, named misses | **Weak** — modest gain (F1 0.47 vs 0.40) over a near-identical idea |
| **Staff estimates and loans** | Leuchter et al., *JAMA Netw Open* 2025 (HHS data: occupancy rising because staffed beds fell); "Dynamic Redeployment of Nurses Across Hospitals: A Sample Robust Optimization Approach", arXiv 2509.07387 | Nurse redeployment optimisation; staffing trend analysis | Direction check of bed-based staff estimates vs real shortage reports (weak: 0.24) | **Weak** — keep as a platform feature |
| **Equipment** | — | — | Demo only (entered data) | **None** (not a research claim) |
| **Tamper-evident record book** | MediTrail and similar blockchain audit logs for EHR access | Audit logs for record access | Applied to transfer decisions, with record cross-checks | **None as research** — good engineering and a strong demo |

## 3. What exactly is new (say it this way)

1. **The first national measurement of how often facility-level hospital
   capacity reports are unreliable**, validated three independent ways (chance
   baseline, the government's own corrections, planted errors) — answering the
   external validation GAO and HHS asked for.
2. **The first quantification of how unreliable capacity reports distort
   coordination decisions**, and evidence that an explainable, causal trust
   layer contains the damage (safety, not volume).
3. **A conservative evaluation design for coordination plans**: proposals are
   scored against what hospitals actually reported the following week, and
   each hospital agent can decline — so a bad forecast earns nothing.
4. **A multi-agent emergency transfer design evaluated on real hospital
   networks** against fair serial-phone baselines, with an agent that checks
   bids against the bidder's own public report. (Simulation; supporting
   contribution.)

## 4. Can it be published? Where?

**Yes — as a focused paper. Not as "a platform that does everything".**

| Paper | Core | Fits (examples, check scope and impact before choosing) | Chance |
|---|---|---|---|
| **A (recommended first)** "How reliable are hospital capacity reports, and does it matter for coordination? A multi-agent, trust-aware analysis of 4,712 US hospitals" | RQ1 + RQ3 planted errors (+ RQ2 briefly) | *JAMIA*, *Journal of Biomedical Informatics*, *JMIR Public Health and Surveillance*, *Health Care Management Science*, *BMJ Health & Care Informatics*; *PLOS ONE* as a safer option | **Good**, if the manual review and literature review below are done |
| **B (optional)** "Parallel call-for-bids for emergency interhospital transfer: an agent-based evaluation on real hospital networks" | Emergency module | *Health Care Management Science*, *Simulation Modelling Practice and Theory*, *Journal of Simulation*, health-informatics or multi-agent conferences (e.g. an AAMAS workshop) | **Moderate**; much stronger with real transfer-centre data |
| Systems paper (everything) | The whole platform | Applied venues (e.g. *IEEE Access*, MDPI *Healthcare*) | Achievable but lower impact; reviewers will see it as engineering |

Keep the registered title true in every option: the agents (hospital agents
with a veto, Data Steward, coordinator) are what turn "wrong numbers" into
"safe decisions".

## 5. What reviewers will attack — fix these before submitting (in order)

1. **No systematic literature review.** Do a PRISMA-style search (PubMed,
   Scopus, IEEE, INFORMS) on hospital capacity data quality, patient load
   balancing, transfer centres and multi-agent bed allocation. This document is
   a starting map, not that review.
2. **"Is a RED flag really an error?"** Two people independently review the
   exported sample (`results/rq1_review_sample.csv`) and report agreement
   (Cohen's kappa). This turns the strongest result into a defensible one.
3. **Emergency timings do not match real ones.** The Arizona Surge Line
   reported a real **median of 59 minutes** to transfer; our simulated
   phone baseline averages 19.9 minutes. Our timeline ends at "bed confirmed",
   theirs probably includes more steps — but say so, treat our numbers as a
   lower bound on delays, and do not compare them directly.
4. **Simulation validity.** The best fix is real data: ask the Arizona Surge
   Line authors (Villarroel et al.) or a state transfer centre for anonymised
   request logs (time, origin, need, hospitals called, outcome). Even a small
   sample would let you check the simulation's decline rates.
5. **"Multi-agent" must be more than vocabulary.** We have private state,
   independent decisions, a veto and message passing (tested). Add a short
   comparison: what a single centralised optimiser with *full* information
   would do (the "oracle"), to show what decentralisation costs and buys.
6. **Clinical outcomes.** Do not claim lives saved; the in-window share barely
   changes. If you want outcome language, link minutes saved to published
   delay–mortality estimates only as a clearly labelled illustration.
7. **Data period.** Facility data ends April 2024; argue relevance through the
   reinstated CMS/NHSN reporting (Nov 2024) and the method's portability.

## 6. One-paragraph abstract you could start from (Paper A)

> Regional coordination of hospital capacity relies on self-reported bed
> counts that are rarely validated. Using all 1,045,406 weekly facility
> reports to the US Department of Health and Human Services (2020–2024), we
> built a multi-agent platform in which a Data Steward agent applies causal,
> explainable rules to every report, a forecaster predicts next-week
> occupancy, a regional coordinator proposes transfers, and hospital agents
> accept only what their next real report allows. 1.6% of reports could not be
> right and 44% of hospitals filed at least one; flagged reports were 11.6
> times more likely than unflagged ones to be corrected later by HHS. When
> errors were planted into 2–10% of reports, a coordinator that believed every
> report planned 2.9–9.6 times more patient-days into hospitals already over
> the safe level than the trust-aware platform. Coordination itself could have
> absorbed about half of above-safe occupancy. Capacity data quality is
> therefore a first-order safety issue for regional coordination.

(Checked against `results/rq3_coordination.json`: 72,855 / 25,542 = 2.85 at 2%
errors; 252,547 / 26,383 = 9.57 at 10%.)

## 7. Sources checked

- GAO-21-600, *COVID-19: HHS's Collection of Hospital Capacity Data* (2021) — https://www.gao.gov/products/gao-21-600
- HHS ASPE, *Quality of Federal COVID-19 Data* (2022) — https://aspe.hhs.gov/sites/default/files/documents/20a7d309c9f4daa54b47cf2f83fb7b0d/covid-data-quality-ib.pdf
- Villarroel et al., *Arizona Surge Line*, Front Public Health 2023 — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9907843/
- Minnesota MOCC, CHEST 2023 — https://www.sciencedirect.com/science/article/abs/pii/S0012369223052777
- Washington MOCC, Disaster Med Public Health Prep — https://www.cambridge.org/core/journals/disaster-medicine-and-public-health-preparedness/article/statewide-patient-load-balancing-work-of-washington-states-medical-operations-coordination-center/73C062A9473899199746E802F34B610E
- Korea NEMSR, BMC Emerg Med 2023 — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC9913013/
- Parker et al., arXiv 2011.03528 — https://arxiv.org/abs/2011.03528
- Chan, Park, Pogacar & Sarhangian, *M&SOM* 2026, doi:10.1287/msom.2025.0497
- Carmichael et al., *J Hosp Med* 2025, doi:10.1002/jhm.70174
- Yaqin et al., *Syst Sci Control Eng* 2025, doi:10.1080/21642583.2025.2602209
- *Generating simple classification rules to predict local surges in COVID-19 hospitalizations*, Health Care Manag Sci 2023, PMID 36692583
- Bhowmik & Eluru, Sci Rep 2021 — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC8630121/
- *Dynamic Redeployment of Nurses Across Hospitals*, arXiv 2509.07387
- Leuchter et al., JAMA Netw Open 2025 (summary: https://epocrates.com/online/article/u-s-hospital-occupancy-could-hit-critical-85-by-2032-due-to-staffing)
- *Declining Interhospital Transfers — A Symptom of Strained Hospital Capacity* — https://www.ncbi.nlm.nih.gov/pmc/articles/PMC12120653/
- Multi-agent bed allocation: https://link.springer.com/chapter/10.1007/978-3-032-16632-6_31 ; https://link.springer.com/article/10.1007/s10489-017-0935-y
- Peysakhovich & Sieradzki, arXiv 2606.20079 (verified; cited in the trust rules)
