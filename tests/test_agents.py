"""The agents: decisions, messages, ledger, and equality with the fast path."""

import numpy as np
import pandas as pd
import pytest

from mahros.agents import DataStewardAgent, HospitalAgent, Message, Platform
from mahros.coordination import Params
from mahros.coordination.evaluate import plan_week
from mahros.coordination.frames import arm_frame, base_frame
from mahros.trust import assess

WEEKS = pd.date_range("2023-03-05", periods=3, freq="7D")
FIRST, LAST = WEEKS[0], WEEKS[1]


def network(next_untrusted: str | None = None):
    """Six hospitals in one state around Houston, three weeks of reports."""
    spec = [  # id, lat, lon, beds, used per week
        ("A", 29.70, -95.40, 200, [196, 197, 198]),   # over the safe level
        ("B", 29.75, -95.35, 150, [148, 149, 147]),   # over the safe level
        ("C", 29.65, -95.30, 120, [80, 82, 81]),      # room
        ("D", 29.80, -95.45, 100, [60, 65, 92]),      # room now, fills up next week
        ("E", 29.60, -95.50, 90, [40, 41, 39]),       # room
        ("F", 31.50, -95.40, 300, [100, 100, 100]),   # far away
    ]
    rows = []
    for pk, lat, lon, beds, used in spec:
        for w, u in zip(WEEKS, used):
            rows.append({"hospital_pk": pk, "name": f"Hosp {pk}", "city": "X",
                         "week": w, "state": "TX", "lat": lat, "lon": lon,
                         "subtype": "Short Term", "used": float(u), "beds": float(beds),
                         "icu_used": 5.0, "icu_beds": 10.0,
                         "used_sum": u * 7.0, "beds_sum": beds * 7.0,
                         "used_cov": 7, "beds_cov": 7})
    df = pd.DataFrame(rows).sort_values(["hospital_pk", "week"]).reset_index(drop=True)
    df = df.join(assess(df))
    if next_untrusted:
        m = (df.hospital_pk == next_untrusted) & (df.week == WEEKS[1])
        df.loc[m, "level"] = "RED"
    # Forecasts: next week's truth, slightly off, with a 5-point upper margin.
    occ = df["used"] / df["beds"]
    nxt = df.assign(occ=occ).groupby("hospital_pk")["occ"].shift(-1)
    fc = pd.DataFrame({"hospital_pk": df.hospital_pk, "week": df.week,
                       "ml_pred": nxt * 1.01, "ml_hi": nxt + 0.05,
                       "raw_pred": nxt, "raw_hi": nxt + 0.05,
                       "persist_pred": occ, "persist_hi": occ + 0.05}).dropna()
    return df, fc


@pytest.mark.parametrize("untrusted", [None, "C", "A"])
def test_agent_cycle_equals_fast_path(untrusted):
    df, fc = network(untrusted)
    prm = Params()
    plat = Platform(df, fc, prm, first=FIRST, last=LAST)
    run = plat.run_week("TX", FIRST)
    frame = arm_frame(base_frame(df, FIRST, LAST), fc, "mahros")
    fast = plan_week(frame[frame.week == FIRST], prm)
    assert run.totals["moved_patient_days"] == pytest.approx(7 * fast.executed, abs=0.05)
    assert run.totals["planned_patient_days"] == pytest.approx(7 * fast.planned, abs=0.05)
    assert run.totals["overload_patient_days"] == pytest.approx(7 * fast.overload, abs=0.05)


def test_far_hospital_is_never_proposed():
    df, fc = network()
    run = Platform(df, fc, first=FIRST, last=LAST).run_week("TX", FIRST)
    assert run.proposals, "expected some proposals"
    assert all(p["to"] != "F" and p["from"] != "F" for p in run.proposals)
    assert all(p["km"] <= Params().radius_km for p in run.proposals)


def test_every_proposal_has_a_reason():
    df, fc = network()
    run = Platform(df, fc, first=FIRST, last=LAST).run_week("TX", FIRST)
    assert all(p["why"] for p in run.proposals)
    assert all(r["why"] for r in run.responses)


def test_no_receiver_ends_above_safe_level():
    df, fc = network()
    prm = Params()
    run = Platform(df, fc, prm, first=FIRST, last=LAST).run_week("TX", FIRST)
    into = {}
    for p in run.proposals:
        into[p["to"]] = into.get(p["to"], 0) + p["executed"]
    for h in run.hospitals:
        if h["id"] in into:
            assert h["used_next"] + into[h["id"]] <= prm.theta * h["beds_next"] + 1e-6


def test_week_is_sealed_and_chain_verifies():
    df, fc = network()
    plat = Platform(df, fc, first=FIRST, last=LAST)
    plat.run_week("TX", FIRST)
    plat.run_week("TX", LAST)
    v = plat.ledger.verify()
    assert v["ok"] and v["blocks"] == 2
    kinds = {e["kind"] for _, e in plat.ledger.entries()}
    assert {"REPORT", "VERDICT", "FORECAST", "PROPOSAL", "RESPONSE", "OUTCOME"} <= kinds


def test_hospital_agent_rules():
    h = HospitalAgent("A", "A", "TX", 0, 0)
    acc, m = h.respond("w", "send", 10, used=95, beds=100, theta=0.9, trusted=True)
    assert acc == pytest.approx(5) and m.body["verdict"] == "PARTIAL"
    acc, m = h.respond("w", "receive", 3, used=80, beds=100, theta=0.9, trusted=True)
    assert acc == pytest.approx(3) and m.body["verdict"] == "ACCEPT"
    acc, m = h.respond("w", "receive", 3, used=95, beds=100, theta=0.9, trusted=True)
    assert acc == 0 and m.body["verdict"] == "DECLINE"
    acc, m = h.respond("w", "send", 3, used=99, beds=100, theta=0.9, trusted=False)
    assert acc == 0 and m.body["verdict"] == "DECLINE"


def test_steward_agent_matches_rules():
    df, _ = network()
    base = df.drop(columns=["flags", "level", "census_run"])
    st = DataStewardAgent(base)
    for r in df.itertuples():
        assert st.verdict(r.hospital_pk, r.week)[0] == r.level
    assert st.verdict("nope", WEEKS[0])[0] == "MISSING"


def test_unknown_message_kind_rejected():
    with pytest.raises(ValueError):
        Message("ORDER", "a", "b", "w")
