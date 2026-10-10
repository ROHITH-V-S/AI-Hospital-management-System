# Review guide

Plain language first, then the questions a panel or journal reviewer is most
likely to ask, each with an honest answer and where the evidence is. If you
can say these things in your own words, you can defend the project.

---

## 1. The project in four sentences

> During a surge, some hospitals are overflowing while others nearby have empty
> beds, and today nobody is checking whether the bed numbers hospitals report
> are even right. MAHROS is a platform a state health department could run: it
> checks every hospital's weekly report, predicts next week, and proposes
> moving patients from too-full hospitals to nearby ones with room. Each
> hospital agent decides for itself whether to accept, and everything is
> written to a record nobody can quietly change. We built and tested it on
> **real federal reports from 4,712 US hospitals (2020–2024)** — nothing is
> simulated.

## 2. Each part, explained simply

| Part | Like... |
|---|---|
| **Data Steward agent** | A teacher checking homework. If a kid writes "I have exactly 87 marbles" every day for a month while playing marbles every day, he stopped counting. |
| **Forecast agent** | A weather forecast, but for hospital beds — with a "probably between" range, not just one number. |
| **State coordinator agent** | Moving kids from a classroom with 40 kids and 30 chairs to the room next door with empty chairs. |
| **Hospital agents** | The other teacher can still say "actually, two new kids just arrived — I can only take three." |
| **Audit ledger** | A notebook written in pen, where each page includes a fingerprint of the page before. Change one word anywhere and every page after it stops matching. |
| **Planted errors** | Hiding known mistakes in a clean exam to check the marker finds them. |
| **Train / test split** | You don't grade a student using the exam they practised on. The model learned on 2020–2022 and was tested on 2023–2024. |

## 3. What we found (say it exactly like this)

1. **Reports are not always right.** 1.6% of weekly reports cannot be right,
   and 44% of hospitals sent at least one. The most common problem is a
   patient count frozen for weeks. Chance explains only about 1% of those
   (81 expected vs 8,325 seen). Reports we flagged were **11.6 times** more
   likely to be corrected later by the government itself.
2. **Next week can be forecast, modestly better than "same as this week".**
   Average error 4.72 vs 4.89 occupancy points one week ahead; larger gains
   two weeks ahead (5.21 vs 5.88). The 90% ranges held 89–90% of the time.
3. **Coordination could have absorbed about half of the overload.** Of all
   patient-days hospitals spent above 90% full in 2023–2024, about **50%**
   could have gone to a hospital within 80 km that really had room the
   following week. With perfect foresight, 66%. In a crowded metro like
   Houston, only about 13%.
4. **Checking reports keeps the plan safe when reports go wrong.** We planted
   mistakes into 2%, 5% and 10% of real reports. A planner that believes every
   report proposed 73k, 137k and 253k patient-days into hospitals that were
   actually over the safe level; with the Data Steward it stayed at about 26k
   each time. The share of the plan that was really possible stayed at 84%
   with MAHROS and fell to 74%, 67% and 58% without it.

> 🧒 If one classroom wrongly says "we have 30 empty chairs", a teacher who
> believes it sends 30 kids into a full room. The checker notices the number
> looks wrong and sends them somewhere else.

## 4. Say the weak points before you are asked

- **The forecaster barely matters for the decisions.** Planning with "next
  week = this week" absorbed 51.4% vs MAHROS's 50.2%. Almost all of the gain
  comes from coordinating at all. We report this; we did not tune it away.
- **Removing bad reports did not improve average forecast accuracy** (slightly
  worse: +0.10 points). Bad reports are rare (1.6%). The trust layer's job is
  to stop *large* errors from steering decisions — see the planted-error test.
- **A 4-week average beats our model four weeks ahead.**
- **Absorption is an upper estimate.** It ignores specialty (an ICU patient
  cannot use any free bed), ambulance availability and patient choice.
- **The data ends in April 2024** and is weekly and self-reported.

Volunteering these is what a panel is testing for. None of them is hidden in
the code or the results.

## 5. Questions you will be asked

**"Your first review said your data was simulated. Is any of this simulated?"**
No. Every hospital, bed count and patient count is an official federal report
(`data/manifest.json` has the download fingerprint). The only artificial step
is the planted-error test, which is labelled as such and always scored against
the real, unmodified reports.

**"Where is the AI?"**
Four places: (1) autonomous agents with divided authority — the hospital agent
can refuse the coordinator; (2) a machine-learned forecaster (gradient-boosted
trees) with calibrated uncertainty (conformal prediction); (3) a rule-based
expert system for data trust, every rule explainable; (4) mathematical
optimisation (linear programming) for the plan. Be honest that the learned
forecaster adds little to the decisions (Section 4).

**"Why is the 'A' — agents — needed? Isn't this one program?"**
Because authority is split the way it is in real life. The state coordinator
can see the whole region but not inside a hospital this week; each hospital
knows its own situation. A proposal becomes a transfer only when both
hospitals' real numbers allow it. That local veto is what stops a bad forecast
from overfilling a hospital — and it is why the evaluation is conservative.

**"How do you know a RED flag is really an error? You have no answer key."**
Three independent checks, plus a human one: (1) chance explains ~1% of frozen
flags; (2) the government's own later corrections hit RED reports 11.6× more
often than GREEN ones; (3) planted errors of six common kinds are caught 100%
of the time; (4) a random sample of flags is exported for manual review
(`results/rq1_review_sample.csv`).

**"Isn't 'frozen' sometimes real? Small hospitals don't change much."**
Yes — which is why the rule ignores hospitals with fewer than 10 patients and
needs three identical weeks. We measured how often an honest count repeats
exactly (1.1% per week) and report the expected false alarms (81) next to the
observed flags (8,325).

**"Did the model see the test data?"**
No. Train 2020-08..2022-06, calibrate 2022-07..2022-12, test 2023-01..2024-04,
split by the week being predicted. A test (`tests/test_forecast.py`) rewrites
every future value and checks that no input changes.

**"Is 50% realistic?"**
It is an upper estimate of how much overload had real room nearby, checked
against what hospitals reported the next week. It ignores specialty and
transport, so real absorption would be lower. It also varies a lot by place:
Houston, where hospitals tend to be full together, only ~13%.

**"Why 90% / 80 km / 5%?"**
They are declared assumptions, and each is moved on its own in the
sensitivity table (`results/rq3_coordination.json`, "sensitivity"). The
conclusion — coordination absorbs a large share, below the ceiling — holds in
every setting (26% to 65%).

**"Straight-line distance is unrealistic."**
We checked it. For 27 Houston hospitals with real driving times, straight-line
distance and drive time correlate at 0.98; re-planning with a 60-minute drive
radius gives the same result (13.46% vs 13.48%) with 96% of the same transfers.

**"Is this a blockchain?"**
No, and it does not need to be. It is an append-only hash chain held by the
coordinating authority, verifiable by anyone with the entries. It proves the
record was not changed afterwards; it cannot prove a report was true when
written — that is the Data Steward's job.

**"The data is from COVID. Is it still relevant?"**
The test period is 2023–2024, after the acute pandemic. Since November 2024,
CMS again requires hospitals to report bed capacity to CDC every week, so the
same inputs exist today (though only state totals are public).

**"Could a hospital game the Data Steward?"**
A hospital deliberately adding small noise to a frozen number would evade the
frozen rule. The rules target accidental errors, which is what the evidence
shows they are. The ledger means any later change to a report is detectable.
Deliberate manipulation is listed as future work.

**"What is new compared to existing work?"**
Optimal patient redistribution has been studied (Parker et al. 2020, 2024)
and so has predict-then-optimise (Bertsimas et al. 2020); both assume the
reported numbers are right. GAO (2021) and HHS itself say the data needs
external validation. As far as our search found, this is the first national
measurement of how often facility-level capacity reports are unreliable,
validated against the government's own corrections, combined with a
coordination method that is scored against what hospitals actually reported
next. (Do a full systematic literature search before submission.)

## 6. If you get stuck

Say: *"That isn't something we measured."* Then say what you would measure.
Every number in this project comes from a script; you never need to guess.
