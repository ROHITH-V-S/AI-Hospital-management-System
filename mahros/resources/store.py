"""Resources in the database, and the combined weekly orchestration plan.

The plan for one state-week has three parts, each line with a plain reason:

1. Patients  -- the regional coordinator's transfer proposals (RQ3 planner).
2. Staff     -- nurse loans from hospitals with spare nurses to hospitals short
                of them, within 60 km; lenders keep what their own patients
                need plus one; hospitals in a surge-warned area go first.
3. Equipment -- units moved from hospitals with spares to hospitals that will
                need more, within 100 km; same priority rule.

Staff numbers are ESTIMATED and equipment counts are ENTERED; both are
labelled on screen. Pressing "Make this week's plan" writes the lines to
patient_moves / staff_loans / equipment_moves and seals them as one page of the
record book.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timezone

import numpy as np
import pandas as pd
from sqlalchemy import func, select

from ..db.io import read_frame, truncate, write_frame
from ..db.models import EquipmentItem, EquipmentMove, PatientMove, StaffLoan
from ..db.session import session_scope
from . import equipment as EQ
from .optimize import plan as transport
from .staff import pools

STAFF_FROM = pd.Timestamp("2022-06-26")
STAFF_RADIUS_KM = 60.0
EQUIP_RADIUS_KM = 100.0
PRIORITY = 1.5          # weight for hospitals in a surge-warned area


# --------------------------------------------------------------------------- #
# Loader steps
# --------------------------------------------------------------------------- #

def load_staff(engine, df: pd.DataFrame) -> str:
    p = pools(df)
    p = p[p["week"] >= STAFF_FROM].copy()
    p["source"] = "mahros.resources.staff (Title 22 ratios x usual staffed beds)"
    p["provenance"] = "estimated"
    truncate(engine, "staff_pools")
    write_frame(engine, "staff_pools", p)
    return f"{len(p):,} hospital-weeks"


def seed_equipment(engine, df: pd.DataFrame) -> str:
    """Seed ONLY when the table is empty: a presenter's entries are never overwritten."""
    with session_scope(engine) as s:
        if (s.execute(select(func.count()).select_from(EquipmentItem)).scalar() or 0) > 0:
            return "inventory already present -- left as entered"
    d = df[df["level"].isin(["GREEN", "AMBER"]) & (df["week"] >= STAFF_FROM)]
    usual = d.groupby("hospital_pk").agg(icu=("icu_beds", "median"), beds=("beds", "median"))
    caps = read_frame(engine, "SELECT hospital_pk, capability FROM hospitals WHERE capability IS NOT NULL")
    cardiac = set()
    for r in caps.itertuples():
        # SQLite returns JSON text, PostgreSQL (via COPY) text or a blank (NaN) for no value.
        c = r.capability if isinstance(r.capability, dict) else             json.loads(r.capability) if isinstance(r.capability, str) and r.capability else None
        if c and (c.get("OPEN_HRT_SRGRY_SRVC_CD") or "").strip() in ("1", "3"):
            cardiac.add(str(r.hospital_pk))
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    rows = []
    for pk, r in usual.iterrows():
        for item, units in EQ.seed(r["icu"], r["beds"], pk in cardiac).items():
            rows.append({"hospital_pk": pk, "item": item, "units": units, "in_use": 0,
                         "updated_at": now, "updated_by": "seed estimate",
                         "source": f"seed estimate: {EQ.ITEMS[item]['seed']} (not public data)",
                         "provenance": "entered"})
    out = pd.DataFrame(rows)
    out["updated_at"] = out["updated_at"].astype(str)
    write_frame(engine, "equipment_inventory", out)
    return f"{len(out):,} inventory rows seeded (labelled estimates)"


# --------------------------------------------------------------------------- #
# The weekly orchestration plan
# --------------------------------------------------------------------------- #

def _warned(engine, state: str, week: str, thr: float) -> set:
    w = read_frame(engine, f"SELECT hospital_pk FROM surge_signals WHERE state = '{state}' "
                           f"AND week = '{week}' AND probability >= {thr}")
    return set(w["hospital_pk"].astype(str)) if len(w) else set()


def build_plan(engine, platform, state: str, week: str, surge_threshold: float) -> dict:
    from ..agents.coordinator import RegionalCoordinatorAgent
    from ..server.live import nice_name
    wk = str(pd.Timestamp(week).date())
    warned = _warned(engine, state, wk, surge_threshold)
    hosp = read_frame(engine, f"SELECT hospital_pk, name, city, lat, lon FROM hospitals WHERE state = '{state}'")
    hosp["hospital_pk"] = hosp["hospital_pk"].astype(str)
    H = hosp.set_index("hospital_pk")
    nm = lambda pk: nice_name(H.loc[pk, "name"]) if pk in H.index else pk

    # 1. Patients (the same planner as RQ3 and "This week").
    g = platform.week_frame(state, pd.Timestamp(wk))
    coord = RegionalCoordinatorAgent(state, platform.params)
    plan_p, msgs = coord.propose(wk, g["hospital_pk"].astype(str).to_numpy(), g["name"].astype(str).to_numpy(),
                                 g["lat"].to_numpy(float), g["lon"].to_numpy(float), g["pred"].to_numpy(float),
                                 g["hi"].to_numpy(float), g["beds"].to_numpy(float),
                                 g["can_receive"].to_numpy(bool))
    patients = [{"from": m.body["from"], "to": m.body["to"], "from_name": nm(m.body["from"]),
                 "to_name": nm(m.body["to"]), "amount": m.body["patients_per_day"], "km": m.body["km"],
                 "reason": m.body["why"]} for m in msgs]

    # 2. Staff.
    sp = read_frame(engine, f"""SELECT s.hospital_pk, s.nurses_per_shift, s.nurses_needed, s.nurse_gap,
                                h.lat, h.lon FROM staff_pools s JOIN hospitals h ON h.hospital_pk = s.hospital_pk
                                WHERE s.state = '{state}' AND s.week = '{wk}'""")
    staff = []
    if len(sp):
        sp["hospital_pk"] = sp["hospital_pk"].astype(str)
        surplus = np.floor(np.maximum(0, sp["nurses_per_shift"] - sp["nurses_needed"] - 1)).to_numpy()
        short = np.ceil(np.maximum(0, sp["nurse_gap"])).to_numpy()
        wgt = np.where(sp["hospital_pk"].isin(warned), PRIORITY, 1.0)
        mv = transport(sp["lat"], sp["lon"], surplus, short, STAFF_RADIUS_KM, wgt, integer=True)
        for k in range(len(mv.amount)):
            a, b = sp.iloc[mv.src[k]], sp.iloc[mv.dst[k]]
            staff.append({"from": a.hospital_pk, "to": b.hospital_pk, "from_name": nm(a.hospital_pk),
                          "to_name": nm(b.hospital_pk), "amount": int(mv.amount[k]), "km": round(float(mv.km[k]), 1),
                          "warned": b.hospital_pk in warned,
                          "reason": (f"{nm(b.hospital_pk)} needs about {b.nurses_needed:.0f} nurses per shift for this "
                                     f"week's patients but usually has {b.nurses_per_shift:.0f}; {nm(a.hospital_pk)} "
                                     f"usually has {a.nurses_per_shift:.0f} and needs {a.nurses_needed:.0f}, so it can "
                                     f"lend and still keep one spare."
                                     + (" Priority: in a surge-warned area." if b.hospital_pk in warned else ""))})
    staff_summary = {"short_hospitals": int((sp["nurse_gap"] > 0).sum()) if len(sp) else 0,
                     "nurses_short": float(np.ceil(np.maximum(0, sp["nurse_gap"])).sum()) if len(sp) else 0.0,
                     "nurses_lent": int(sum(x["amount"] for x in staff))}

    # 3. Equipment.
    rep = read_frame(engine, f"""SELECT r.hospital_pk, r.used, r.icu_used, h.lat, h.lon
                                 FROM weekly_reports r JOIN hospitals h ON h.hospital_pk = r.hospital_pk
                                 JOIN trust_verdicts v ON v.hospital_pk = r.hospital_pk AND v.week = r.week
                                 WHERE h.state = '{state}' AND r.week = '{wk}' AND v.level IN ('GREEN','AMBER')""")
    inv = read_frame(engine, f"""SELECT e.hospital_pk, e.item, e.units FROM equipment_inventory e
                                 JOIN hospitals h ON h.hospital_pk = e.hospital_pk WHERE h.state = '{state}'""")
    equipment, eq_summary = [], {}
    if len(rep) and len(inv):
        rep["hospital_pk"] = rep["hospital_pk"].astype(str)
        inv["hospital_pk"] = inv["hospital_pk"].astype(str)
        for item, meta in EQ.ITEMS.items():
            u = inv[inv["item"] == item].set_index("hospital_pk")["units"]
            r = rep[rep["hospital_pk"].isin(u.index)].reset_index(drop=True)
            if r.empty:
                continue
            units = r["hospital_pk"].map(u).fillna(0).astype(int).to_numpy()
            need = np.array([EQ.need(item, a, b, n > 0) for a, b, n in zip(r["icu_used"], r["used"], units)])
            warn = r["hospital_pk"].isin(warned).to_numpy()
            ss = [EQ.shortfall_surplus(int(n), float(q), bool(w)) for n, q, w in zip(units, need, warn)]
            short = np.array([x[0] for x in ss], float)
            surplus = np.array([x[1] for x in ss], float)
            mv = transport(r["lat"], r["lon"], surplus, short, EQUIP_RADIUS_KM,
                           np.where(warn, PRIORITY, 1.0), integer=True)
            eq_summary[item] = {"label": meta["label"], "hospitals_short": int((short > 0).sum()),
                                "units_short": int(short.sum()), "units_moved": int(mv.amount.sum())}
            for k in range(len(mv.amount)):
                i, j = mv.src[k], mv.dst[k]
                a, b = r.iloc[i], r.iloc[j]
                equipment.append({"item": item, "label": meta["label"], "from": a.hospital_pk, "to": b.hospital_pk,
                                  "from_name": nm(a.hospital_pk), "to_name": nm(b.hospital_pk),
                                  "amount": int(mv.amount[k]), "km": round(float(mv.km[k]), 1), "warned": bool(warn[j]),
                                  "reason": (f"{nm(b.hospital_pk)} has {units[j]} and is expected to need "
                                             f"{units[j] + int(short[j])} ({meta['use']}"
                                             + ("; +15% because its area has a surge warning" if warn[j] else "")
                                             + f"); {nm(a.hospital_pk)} has {units[i]}, needs {units[i] - int(surplus[i]) - EQ.KEEP_SPARE} "
                                             f"and keeps one spare.")})
    hospitals = [{"id": pk, "name": nm(pk), "city": H.loc[pk, "city"].title() if isinstance(H.loc[pk, "city"], str) else "", "lat": H.loc[pk, "lat"],
                  "lon": H.loc[pk, "lon"], "warned": pk in warned} for pk in H.index]
    return {"state": state, "week": wk, "warned_hospitals": len(warned), "patients": patients,
            "staff": staff, "staff_summary": staff_summary, "equipment": equipment,
            "equipment_summary": eq_summary, "hospitals": hospitals,
            "params": {"staff_radius_km": STAFF_RADIUS_KM, "equipment_radius_km": EQUIP_RADIUS_KM,
                       "priority_weight": PRIORITY, "surge_buffer": EQ.SURGE_BUFFER,
                       "items": EQ.ITEMS}}


def commit_plan(engine, book, plan: dict) -> dict:
    """Write the plan lines and seal them as one page of the record book."""
    wk = date.fromisoformat(plan["week"])
    blk = book.open_block(f"Weekly orchestration plan · {plan['state']} · week of {plan['week']}")
    n = 0
    with session_scope(engine) as s:
        for p in plan["patients"]:
            r = PatientMove(state=plan["state"], week=wk, from_pk=p["from"], to_pk=p["to"],
                            patients=round(float(p["amount"]), 2), km=float(p["km"]), reason=p["reason"])
            s.add(r); s.flush()
            r.ledger_seq = book.append("PATIENT_MOVE", f"coordinator:{plan['state']}", f"hospital:{p['to']}",
                                       {"reason": p["reason"]}, block_id=blk, ref=("patient_moves", r.id),
                                       record={"from_pk": r.from_pk, "to_pk": r.to_pk, "patients": r.patients},
                                       session=s)
            n += 1
        for p in plan["staff"]:
            r = StaffLoan(state=plan["state"], week=wk, from_pk=p["from"], to_pk=p["to"],
                          nurses=float(p["amount"]), km=float(p["km"]), reason=p["reason"])
            s.add(r); s.flush()
            r.ledger_seq = book.append("STAFF_LOAN", f"coordinator:{plan['state']}", f"hospital:{p['to']}",
                                       {"reason": p["reason"]}, block_id=blk, ref=("staff_loans", r.id),
                                       record={"from_pk": r.from_pk, "to_pk": r.to_pk, "nurses": r.nurses},
                                       session=s)
            n += 1
        for p in plan["equipment"]:
            r = EquipmentMove(state=plan["state"], week=wk, item=p["item"], from_pk=p["from"], to_pk=p["to"],
                              units=int(p["amount"]), km=float(p["km"]), reason=p["reason"])
            s.add(r); s.flush()
            r.ledger_seq = book.append("EQUIPMENT_MOVE", f"coordinator:{plan['state']}", f"hospital:{p['to']}",
                                       {"reason": p["reason"]}, block_id=blk, ref=("equipment_moves", r.id),
                                       record={"item": r.item, "from_pk": r.from_pk, "to_pk": r.to_pk,
                                               "units": r.units}, session=s)
            n += 1
    sealed = book.seal_block(blk)
    sealed["lines"] = n
    return sealed


def inventory(engine, state: str) -> list[dict]:
    from ..server.live import nice_name
    d = read_frame(engine, f"""SELECT e.id, e.hospital_pk, h.name, e.item, e.units, e.updated_by, e.updated_at
                               FROM equipment_inventory e JOIN hospitals h ON h.hospital_pk = e.hospital_pk
                               WHERE h.state = '{state}' ORDER BY h.name, e.item""")
    return [{"id": int(r.id), "hospital": str(r.hospital_pk), "name": nice_name(r.name), "item": r.item,
             "units": int(r.units), "updated_by": r.updated_by} for r in d.itertuples()]


def set_units(engine, book, row_id: int, units: int, who: str = "presenter") -> dict:
    if not (0 <= units <= 10000):
        raise ValueError("units must be between 0 and 10000")
    with session_scope(engine) as s:
        e = s.get(EquipmentItem, row_id)
        if e is None:
            raise ValueError("no such inventory row")
        before = e.units
        e.units, e.updated_by = int(units), who
        e.updated_at = datetime.now(timezone.utc).replace(tzinfo=None)
        e.source, e.provenance = f"entered on screen by {who}", "entered"
        pk, item = e.hospital_pk, e.item
    # Logged, but not as a vouched record: an inventory count is MEANT to change.
    book.append("INVENTORY_EDIT", who, f"hospital:{pk}", {"item": item, "before": before, "after": int(units)})
    return {"id": row_id, "before": before, "after": int(units)}
