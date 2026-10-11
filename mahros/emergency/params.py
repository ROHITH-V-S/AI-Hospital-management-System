"""Every number the emergency simulation uses, with where it comes from.

Status of each parameter (shown on screen and in docs/DATA_PROVENANCE.md):

* ``cited``       a published figure (source given)
* ``assumption``  our choice; swept in ``experiments/emergency_eval.py``

Nothing here is fitted to make MAHROS look good. Where a published figure
exists it is used as the centre of the sweep; where none exists the sweep is
wide and the result is reported as a range.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, replace


@dataclass(frozen=True)
class P:
    value: float
    status: str           # cited | assumption
    source: str
    sweep: tuple = ()


#: name -> parameter. ``Params`` below holds the values actually used in a run.
REGISTRY: dict[str, P] = {
    "transfer_rate": P(0.010, "assumption",
        "Share of ED visits that become an emergency transfer request needing ICU-level or "
        "specialty care. Anchor: 1.5% of all US ED encounters end in transfer to another acute "
        "hospital (Kindermann et al., Acad Emerg Med 2015, HCUP NEDS 2009; 3.0% for rural "
        "patients). Not every transfer needs critical care, so 1.0% is the centre and 0.5%/1.5% "
        "the sweep.", (0.005, 0.010, 0.015)),
    "los_icu_days": P(3.4, "cited",
        "Mean ICU stay of 34,696 Medicare ICU survivors, 3.4 days (Moitra et al., Crit Care Med "
        "2016, PMID 26571190; 2005 data).", (2.5, 3.4, 4.5)),
    "call_min": P(10.0, "assumption",
        "Minutes per phone call to a hospital (reach the right person, present the patient, "
        "get an answer). Anchor: a regional ED needed a mean 4.7 calls and 56.7 min to get a "
        "transfer accepted (~12 min per call; Monash University study, 2003). Swept 5-15.",
        (5.0, 10.0, 15.0)),
    "bid_window_min": P(3.0, "assumption",
        "Minutes MAHROS waits for hospitals to answer the call-for-bids (the bed board answers "
        "at once; a charge nurse confirms). Swept 1-5.", (1.0, 3.0, 5.0)),
    "icu_vent_share": P(0.40, "assumption",
        "Share of ICU patients on a ventilator (used for ventilator availability).", (0.3, 0.4, 0.5)),
    "vents_per_icu_bed": P(1.0, "assumption",
        "Ventilators per staffed ICU bed (no public per-hospital data; same as the entered "
        "equipment seed).", (0.8, 1.0, 1.3)),
    "nurse_ratio_icu": P(2.0, "cited",
        "ICU patients per registered nurse: California Code of Regulations, Title 22, §70217 "
        "(1:2).", ()),
    "short_staff_cut": P(0.15, "assumption",
        "Share of ICU nurses missing at a hospital that is short-staffed this week. WHICH "
        "hospitals are short is drawn with the REAL state share of hospitals reporting a "
        "critical staffing shortage that week (HHS g62h-syeh).", (0.0, 0.15, 0.30)),
    "reserve_beds": P(1.0, "assumption",
        "ICU beds a hospital keeps back for its own emergency department (hospitals with >= 10 "
        "ICU beds). Hospital policy, private to each hospital agent.", (0.0, 1.0, 2.0)),
    "cath_day_util": P(0.5, "assumption",
        "Share of daytime (07-19 h) a cath-lab room is busy with other procedures.", (0.3, 0.5, 0.7)),
    "cath_callin_min": P(30.0, "assumption",
        "Minutes to bring the on-call cath team in at night.", (20.0, 30.0, 45.0)),
    "surgery_ready_min": P(15.0, "assumption",
        "Minutes for a trauma / neurosurgery / burns team to be ready once accepted.", ()),
    "window_scale": P(1.0, "assumption",
        "Multiplier on every clinical window below.", (0.5, 1.0, 2.0)),
}

#: What a patient can need, the clinical window (minutes from request to arrival
#: at definitive care), and the share of requests of that kind.
NEEDS = {
    "icu": {"label": "Intensive care bed", "window": 240, "share": 0.40,
            "why": "No fixed standard; assumption. Context: each hour of delay moving a ward "
                   "patient to the ICU was linked to ~3% higher odds of death (Churpek et al., "
                   "J Hosp Med 2016, PMID 27352032 -- within-hospital, not interhospital). "
                   "Interhospital critical-care transfers in 49 UK hospitals took a median 22 h, "
                   "driven by organisation, not distance (Crit Care 2015 meeting abstract, "
                   "PMC4472710)."},
    "ventilator": {"label": "ICU bed with ventilator", "window": 240, "share": 0.15,
                   "why": "As intensive care. Assumption."},
    "cath_lab": {"label": "Cath lab (heart attack)", "window": 120, "share": 0.15,
                 "why": "ACC/AHA 2013 STEMI guideline: first medical contact to device <= 120 "
                        "min when transferring (here measured from the request: generous)."},
    "trauma": {"label": "Trauma surgery", "window": 120, "share": 0.10,
               "why": "Assumption (the 'golden hour' has weak evidence; 120 min used)."},
    "neurosurgery": {"label": "Neurosurgery / stroke", "window": 120, "share": 0.10,
                     "why": "Assumption, informed by door-in-door-out targets for stroke transfer."},
    "picu": {"label": "Children's intensive care", "window": 240, "share": 0.05,
             "why": "Assumption."},
    "burns": {"label": "Burns unit", "window": 240, "share": 0.05,
              "why": "Assumption. The share of each need is an assumption too."},
}

ACUITY = {"critical": 1.0, "serious": 2.0}     # window multiplier


@dataclass(frozen=True)
class Params:
    transfer_rate: float = REGISTRY["transfer_rate"].value
    los_icu_days: float = REGISTRY["los_icu_days"].value
    call_min: float = REGISTRY["call_min"].value
    bid_window_min: float = REGISTRY["bid_window_min"].value
    icu_vent_share: float = REGISTRY["icu_vent_share"].value
    vents_per_icu_bed: float = REGISTRY["vents_per_icu_bed"].value
    nurse_ratio_icu: float = REGISTRY["nurse_ratio_icu"].value
    short_staff_cut: float = REGISTRY["short_staff_cut"].value
    reserve_beds: float = REGISTRY["reserve_beds"].value
    cath_day_util: float = REGISTRY["cath_day_util"].value
    cath_callin_min: float = REGISTRY["cath_callin_min"].value
    surgery_ready_min: float = REGISTRY["surgery_ready_min"].value
    window_scale: float = REGISTRY["window_scale"].value
    cath_proc_min: float = 60.0          # mean minutes per cath procedure (assumption)

    def with_(self, **kw) -> "Params":
        return replace(self, **kw)

    def as_dict(self) -> dict:
        return asdict(self)


def registry_table() -> list[dict]:
    return [{"name": k, "value": p.value, "status": p.status, "source": p.source,
             "sweep": list(p.sweep)} for k, p in REGISTRY.items()]
