"""Demo seed: a few emergency cases and one weekly plan, so a fresh install is not empty.

Runs from the loader ONLY when the database has no emergency cases yet (it
never adds to, or overwrites, what someone has done on the dashboard). Every
seeded case is an ordinary run of the emergency module -- simulated, grounded
in real data, labelled as such -- and every line goes into the record book, so
the Audit log, the Data trust tab and the pgAdmin tables (bids, transfers,
staff_loans, ...) have something to show and to edit.
"""

from __future__ import annotations

import json

from sqlalchemy import func, select

from .models import TransferRequest
from .session import ROOT, session_scope

#: (state, need) for the seeded cases; the origin is a busy hospital without
#: that capability (a typical sender), chosen by rule, not by hand.
CASES = [("AZ", "cath_lab"), ("AZ", "icu"), ("AZ", "trauma"),
         ("MA", "icu"), ("MA", "neurosurgery"), ("MA", "cath_lab")]
PLAN = ("AZ", "2023-11-19")


def seed_demo(engine, book, platform=None, log=print) -> str:
    with session_scope(engine) as s:
        if (s.execute(select(func.count()).select_from(TransferRequest)).scalar() or 0) > 0:
            return "cases already present -- nothing seeded"
    from ..emergency.live import EmergencyLive
    em = EmergencyLive(engine, book)
    em._load()
    if not em.ready:
        return f"emergency module not ready ({em.error}) -- nothing seeded"
    done = 0
    for state, need in CASES:
        hs = em.hospitals(state)
        senders = sorted((h for h in hs if h["ed_visits_week"] and not h["can"][need]),
                         key=lambda h: -(h["ed_visits_week"] or 0))
        if not senders:
            continue
        em.find_bed(state, senders[done % min(3, len(senders))]["id"], need)
        done += 1
    plan_msg = ""
    if platform is not None:
        from ..resources.store import build_plan, commit_plan
        p = ROOT / "results" / "surge_warning.json"
        thr = json.loads(p.read_text())["methods"]["model"]["threshold"] if p.exists() else 1.01
        sealed = commit_plan(engine, book, build_plan(engine, platform, PLAN[0], PLAN[1], thr))
        plan_msg = f", 1 weekly plan ({sealed['lines']} lines)"
    return f"{done} demo emergency cases{plan_msg} (simulated, labelled)"
