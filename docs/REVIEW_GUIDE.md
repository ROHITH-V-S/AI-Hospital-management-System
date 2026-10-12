# Review guide

Plain language first, then the demo, the findings, the weak points, and the
questions a panel or journal reviewer is most likely to ask — each with an
honest answer and where the evidence is. If you can say these things in your
own words, you can defend the project.

---

## 1. The project in five sentences

> When a hospital has a patient it cannot treat — no ICU bed, no cath lab —
> staff today phone other hospitals one by one; in one study of 49 UK
> hospitals, critically ill patients moved between hospitals waited a median
> of 22 hours. MAHROS is a working prototype of the service a
> state health department could run: it asks every capable hospital at once,
> each hospital's own agent answers from its own beds, nurses and equipment,
> and the best bed is confirmed in minutes. Every week it also checks which
> hospital reports can be believed, warns where hospitals are about to fill
> up, and plans where patients, nurses and equipment should go. Everything is
> written into a record book in a real database that nobody can quietly
> change. The weekly parts run on **real federal reports from 4,712 US
> hospitals (2020–2024)**; the emergency timings are a **simulation grounded
> in that real data**, and we say so on every screen.

## 2. Each part, explained simply

| Part | Like... |
|---|---|
| **Emergency call-for-bids** | Instead of phoning restaurants one by one to find a table for six, you send one message to every restaurant nearby and pick the best "yes". |
| **Hospital agent** | Each restaurant decides for itself — only it knows how many tables are free and whether the chef is in. |
| **Data Steward agent** | A teacher checking homework. If a kid writes "exactly 87 marbles" every day for a month, he stopped counting. In an emergency: a restaurant that says "table free" while its own sign says "full" gets a quick phone check. |
| **Forecaster** | A weather forecast, but for hospital beds — with a "probably between" range. |
| **Surge early warning** | A smoke alarm for a neighbourhood's hospitals: rings when they are filling up fast. Not a crystal ball for epidemics. |
| **Regional coordinator** | Moving kids from a classroom with 40 kids and 30 chairs to the room next door — and lending a teacher too. |
| **Record book (audit ledger)** | A notebook written in pen, where each line carries a fingerprint of the line before. Change one word anywhere and the fingerprints stop matching. |
| **Train / test split** | You don't grade a student using the exam they practised on. |

## 3. The live demo (3 minutes)

Before the review: `docker compose up` (wait until http://localhost:8080
loads; first run takes a few minutes), and open http://localhost:5050
(pgAdmin) in a second tab.

1. **Emergency (first tab, ~60 s).** "This is Arizona's hospitals in a real
   busy week (January 2024). The yellow banner says what is real and what is
   simulated." The patient is already placed at a small hospital (or click any
   dot). Choose **Cath lab (heart attack)** → **Find a bed** → press
   **Next step ›** four times, reading the big sentence each time:
   1. "The request goes to every hospital that can treat this, at the same moment."
   2. "Each hospital's agent answers by itself, with a reason" — point at a
      "No — ICU full (26 of 26 beds)".
   3. "The Data Steward checks each yes against that hospital's own report."
   4. "The best bed: soonest to definitive care."
   5. "Compared with phoning one by one" — read the bars. **If phoning would
      have been as fast, say so:** "Here the nearest hospital had room, so one
      call was enough. MAHROS helps most when the nearest ones are full."
2. **Early warning (~30 s).** Opens on a test week with warnings. "These areas
   were still below 85% full; the model warned they would cross within 2
   weeks." Tick **Show what really happened** — "3 of 4 came true; this one did
   not. Across 2023–24, about half of surges came with no warning."
3. **Staff & equipment (~30 s).** "One weekly plan: patients, nurse loans,
   equipment. Read the labels: staff numbers are estimates, equipment is
   entered by the state." Click a nurse-loan line to see it on the map.
4. **Audit log + pgAdmin (~60 s).** Press **Verify log** (green). Switch to
   pgAdmin → MAHROS database → Schemas → public → Tables → `bids` → right-click
   → View/Edit Data → All Rows. Change one `travel_min`, press Save (F6).
   Back in MAHROS press **Verify log**: it turns red and names the exact bid,
   the old and new value and the time it was written. Change it back → green.
   "After a bad outcome nobody can say 'we were never asked' — and nobody can
   quietly rewrite what was said."

Backup if pgAdmin misbehaves: the **Try it: secretly change a bid** button does
the same edit in the database with one click; **Undo my change** restores it.

## 4. What we found (say it exactly like this)

1. **Asking everyone at once finds beds faster, mostly for the patients who
   wait longest.** In the simulation (16 real weeks, Arizona and
   Massachusetts, 10 runs each): 13.2 minutes on average to a confirmed bed vs
   19.9 phoning nearest-first and 16.5 phoning first the hospitals whose report
   shows room. For the slowest 1 in 10 patients: 13.0 vs 37.1 minutes. The
   gain ranges from 2.0 to 12.1 minutes depending on our assumptions.
2. **Reports are not always right.** 1.6% of weekly reports cannot be right;
   44% of hospitals sent at least one. Reports we flagged were **11.6 times**
   more likely to be corrected later by the government itself.
3. **Next week can be forecast, modestly better than "same as this week"**
   (4.72 vs 4.89 occupancy points of error).
4. **Weekly coordination could have absorbed about half of the overload**
   (50.2%; perfect foresight 66.5%), and checking reports keeps the plan safe
   when reports are wrong.
5. **The surge warning is modest:** F1 0.47 vs 0.40 for the best simple rule;
   48% of surges warned at least a week ahead.

## 5. Say the weak points before you are asked

- **Emergency timings are simulated.** Hospitals, capability, road times and
  weekly numbers are real; the minute-by-minute beds and the patients are not.
  There is no public record of real transfers to compare against.
- **When the nearest hospital has room, phoning is as fast or faster.**
  MAHROS waits ~3 minutes for answers, then still needs the same
  doctor-to-doctor call. Its gain is in the slow tail and in staff phone time.
- **MAHROS found a bed slightly less often** (97.6% vs 97.9%): a phone caller
  keeps calling while beds free up.
- **The share reaching care inside the clinical window barely moves**
  (95.7% vs 94.4%): the windows (2–4 hours) are long compared with the minutes
  saved. We do not claim lives saved.
- **The phone-call length comes from one old study** (2003, ~12 min per call);
  we sweep 5–15 minutes and always report a range.
- **The surge warning misses about half of surges**, and the
  "neighbours rising together" rule in our plan turned out weak (F1 0.11).
- **Staff per hospital is an estimate** that agrees only weakly with real
  shortage reports and flags far fewer shortages. **Equipment** is an entered
  inventory: no research claim rests on it.
- **The weekly forecaster barely changes the decisions**; almost all of RQ3's
  gain comes from coordinating at all. **The data ends in April 2024.**

## 6. Questions you will be asked

**"Why not just phone the hospitals?"**
That is today's practice, and it is our baseline — built fairly: the same
honest hospitals, the same final call, phoning stops at the first yes, and a
stronger version phones the hospitals whose report shows room first. Phoning
wins when the nearest hospital has room. It loses when the nearest ones are
full: the slowest 10% wait 37.1 minutes vs 13.0. It also costs staff time —
about 20 minutes on the phone per patient vs 10. And the weekly side cannot
be done by phone at all: checking 4,712 hospitals' reports, forecasting and
planning across a state.

**"Where is the multi-agent part?"**
Hospital agents hold private state no one else can read (beds in use, nurses
on shift, ventilators, cath-lab rooms, their own reserve policy) and decide by
themselves, with reasons, to bid or decline. The coordinator knows only public
facts and cannot see inside a hospital; it can only ask. The Data Steward
checks other agents' claims. They communicate only by messages, sent in
parallel, and every message is in the record book. A test pins that the
coordinators never read a hospital's private state (`mahros/emergency/`,
`tests/test_emergency.py`).

**"Is it real-time?"**
It is a working prototype of a real-time service, run on a simulated clock.
The emergency module answers in about half a second per request on a laptop
and writes everything to PostgreSQL. It is not deployed and connects to no
real hospital system; live bed data would come from hospitals' own systems.

**"What exactly is simulated?"**
Only the emergency module's minute-by-minute part: when patients arrive and
leave each ICU, and when transfer requests happen. Both are calibrated to each
hospital's real weekly report (simulated ICUs average 100.2% of the reported
census) and real ED volume. The weekly trust audit, forecasts, plans and surge
warning use real reports only. Staff numbers are estimated, equipment is
entered. Every screen labels which is which.

**"Your first review said the data was simulated."**
The research questions (trust, forecasting, coordination, surge warning) use
no simulation. The emergency module needs minute-level data that does not
exist publicly, so it is a simulation grounded in real data and labelled as
such; its result is reported as a range over every swept assumption.

**"Did the hospitals lie? Does the Steward catch liars?"**
No and no. Hospitals answer honestly in the model. The Steward catches
reports that cannot be right (mostly technical: frozen feeds, typos) and asks
for a phone check when a bid contradicts the hospital's own report. Deliberate
manipulation is future work.

**"Where is the AI?"**
Autonomous agents with divided authority; machine-learned forecasting and surge
warning (gradient-boosted trees, calibrated uncertainty); a rule-based expert
system for data trust; mathematical optimisation (linear programming) for
weekly plans and loans. Be honest that the learned parts add modestly.

**"How do you know a RED flag is really an error?"**
Chance explains ~1% of frozen flags (81 expected vs 8,325 seen); the
government's own later corrections hit RED reports 11.6× more often; planted
errors of six kinds are caught 100%; a sample is exported for manual review.

**"Did the models see the test data?"**
No. Split by week: train 2020–22, calibrate late 2022, test 2023–24, for both
the forecaster and the surge warning. Tests rewrite future values and check no
input changes.

**"Why these numbers — 90%, 85%, 80 km, 3 minutes, 10-minute calls?"**
Declared assumptions, each moved on its own in a sensitivity table (RQ3 in
`results/rq3_coordination.json`; emergency in
`results/emergency_eval.json` → "sensitivity"; surge 80/85/90% sweep). Every
emergency parameter and its source is listed on Evidence → 4 and in
`mahros/emergency/params.py`.

**"Is the database real? What happens if someone edits it?"**
PostgreSQL 16 in Docker, browsable in pgAdmin. Each record-book line's hash
covers its content and the previous hash; bids, transfers and plan lines are
cross-checked against the line that recorded them. Demonstrate it (Section 3).

**"Is this a blockchain?"**
No, and it does not need to be: an append-only hash chain held by the
coordinating authority, verifiable by anyone with database access.

**"The data is from COVID. Is it still relevant?"**
The test period is 2023–2024, after the acute pandemic. Since November 2024
CMS again requires hospitals to report bed capacity weekly (public releases
are state-level only).

**"What is new?"**
Optimal patient redistribution (Parker et al.) and predict-then-optimise
(Bertsimas et al.) assume reported numbers are right. As far as our search
found, this is the first national measurement of how often facility capacity
reports are unreliable, validated against the government's own corrections,
combined with coordination scored against what hospitals reported next, and
an agent-based call-for-bids for transfers evaluated on real hospital
networks. (Do a full systematic literature search before submission.)

## 7. If you get stuck

Say: *"That isn't something we measured."* Then say what you would measure.
Every number in this project comes from a script; `python
experiments/check_doc_numbers.py` confirms the numbers in these documents
match the result files.
