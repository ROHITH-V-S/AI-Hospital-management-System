"""Emergency module: agents decide from their own state; baselines are fair; runs are reproducible.

Uses a small synthetic network (no data cache needed) so every expectation is exact.
"""

import numpy as np
import pandas as pd
import pytest

from mahros.emergency.agents import HospitalAgent, steward_check
from mahros.emergency.network import Network, Site
from mahros.emergency.params import Params
from mahros.emergency.world import World, erlang_b, offered_load

ALL = {"icu": True, "cath_lab": True, "cardiac_surgery": False, "neurosurgery": False,
       "trauma": False, "burns": False, "picu": False}


def site(pk, icu_beds, icu_used, caps=None, ed=0.0, level="GREEN"):
    return Site(pk=pk, ccn=pk, name=f"H{pk}", city="", lat=0, lon=0, caps=dict(caps or ALL),
                cap_source="test", cath_rooms=1, beds=100, used=50, icu_beds=icu_beds,
                icu_used=icu_used, ed_visits_week=ed, level=level)


def net(sites, minutes):
    return Network("AZ", pd.Timestamp("2023-01-01"), sites, np.array(minutes, float),
                   np.array(minutes, float), 0.0)


def quiet(**kw):
    """No random background traffic: only the cases a test creates."""
    return Params(transfer_rate=0.0, **kw)


def frozen_world(n, prm, policy):
    w = World(n, prm, seed=1, policy=policy, horizon=0.0)   # horizon 0: no background events
    return w


# ------------------------------------------------------------------ agents
def test_full_icu_declines_with_a_reason():
    a = HospitalAgent(site("A", 10, 10), 0, quiet(reserve_beds=0), False, None, 0)
    yes, d = a.decide("icu", 0)
    assert not yes and "ICU full (10 of 10" in d["reason"]


def test_reserve_policy_is_private_and_own_patients_may_use_it():
    a = HospitalAgent(site("A", 12, 11), 0, quiet(reserve_beds=1), False, None, 0)
    yes, d = a.decide("icu", 0)
    assert not yes and d["code"] == "reserve"
    assert a.decide("icu", 0, own_patient=True)[0]


def test_short_staffed_hospital_says_so():
    a = HospitalAgent(site("A", 20, 17), 0, quiet(reserve_beds=0, short_staff_cut=0.2), True, None, 0)
    yes, d = a.decide("icu", 0)
    assert not yes and d["code"] == "staff" and "nurses" in d["reason"]


def test_missing_capability_declines():
    caps = dict(ALL, cath_lab=False)
    a = HospitalAgent(site("A", 10, 0, caps), 0, quiet(), False, None, 0)
    yes, d = a.decide("cath_lab", 0)
    assert not yes and d["code"] == "capability"


def test_steward_uses_only_the_public_report():
    assert steward_check(site("A", 10, 10), "icu")              # report says 100% full
    assert steward_check(site("A", 10, 5, level="RED"), "icu")  # report unverified
    assert steward_check(site("A", 10, 5), "icu") is None


# ------------------------------------------------------------------ coordinators
def _three():
    # Origin O; A nearest but full; B further with room; C furthest with room.
    s = [site("O", 0, 0, dict(ALL, icu=False)), site("A", 10, 10), site("B", 10, 3), site("C", 10, 2)]
    m = [[0, 10, 30, 50], [10, 0, 20, 40], [30, 20, 0, 20], [50, 40, 20, 0]]
    return net(s, m)


def test_phone_stops_at_first_yes_and_never_discards_one():
    prm = quiet(reserve_beds=0, call_min=10)
    w = frozen_world(_three(), prm, "phone_nearest")
    c = w.on_need(0, "icu", stay=1e9, vent=False, n=1)
    w.run(until=1e6)
    assert c.status == "placed" and w.net.sites[c.chosen].pk == "B"
    assert [w.net.sites[x[0]].pk for x in c.calls] == ["A", "B"]     # A said no, B said yes: stop
    assert c.t_placed - c.t0 == pytest.approx(20.0)                 # two calls of 10 min


def test_mahros_asks_everyone_at_once_and_makes_one_acceptance_call():
    prm = quiet(reserve_beds=0, call_min=10, bid_window_min=3)
    w = frozen_world(_three(), prm, "mahros")
    c = w.on_need(0, "icu", stay=1e9, vent=False, n=1)
    w.run(until=1e6)
    assert sorted(w.net.sites[j].pk for j in c.asked) == ["A", "B", "C"]
    assert c.replies[1]["yes"] is False and c.replies[2]["yes"] and c.replies[3]["yes"]
    assert w.net.sites[c.chosen].pk == "B"                          # fastest definitive care
    assert c.t_placed - c.t0 == pytest.approx(13.0)                 # 3 min bids + 1 call
    assert len(c.calls) == 1


def test_phone_is_faster_when_the_nearest_hospital_has_room():
    """The baseline is not rigged: one lucky call beats the bid window."""
    s = [site("O", 0, 0, dict(ALL, icu=False)), site("A", 10, 2), site("B", 10, 2)]
    m = [[0, 10, 30], [10, 0, 20], [30, 20, 0]]
    prm = quiet(reserve_beds=0, call_min=10, bid_window_min=3)
    t = {}
    for pol in ("mahros", "phone_nearest"):
        w = frozen_world(net(s, m), prm, pol)
        c = w.on_need(0, "icu", stay=1e9, vent=False, n=1)
        w.run(until=1e6)
        t[pol] = c.t_placed - c.t0
    assert t["phone_nearest"] < t["mahros"]


def test_flagged_bid_costs_a_confirmation_call_in_the_ranking():
    s = [site("O", 0, 0, dict(ALL, icu=False)), site("A", 10, 3, level="RED"), site("B", 10, 3)]
    m = [[0, 10, 18], [10, 0, 8], [18, 8, 0]]
    w = frozen_world(net(s, m), quiet(reserve_beds=0, call_min=10), "mahros")
    c = w.on_need(0, "icu", stay=1e9, vent=False, n=1)
    w.run(until=1e6)
    assert 1 in c.flags and w.net.sites[c.chosen].pk == "B"          # 10+10 > 18


# ------------------------------------------------------------------ the week
def _busy_net():
    rng = np.random.default_rng(0)
    sites = [site(str(i), int(b), float(u), ed=4000.0)
             for i, (b, u) in enumerate(zip(rng.integers(8, 40, 12), rng.uniform(5, 30, 12)))]
    for s in sites:
        s.icu_used = min(s.icu_used, s.icu_beds)
    m = rng.uniform(5, 90, (12, 12))
    m = (m + m.T) / 2
    np.fill_diagonal(m, 0)
    return net(sites, m)


def test_same_seed_same_week_same_answers():
    n = _busy_net()
    a = World(n, Params(), 3, "mahros"); a.run()
    b = World(n, Params(), 3, "mahros"); b.run()
    assert a.results() == b.results()


def test_policies_face_the_same_patients():
    n = _busy_net()
    totals = []
    for pol in ("mahros", "phone_nearest", "phone_informed"):
        w = World(n, Params(), 5, pol); w.run()
        totals.append(w.local + len(w.cases))
    assert totals[0] == totals[1] == totals[2]


def test_calibration_starts_from_the_reported_census():
    n = _busy_net()
    rows = []
    for seed in range(4):
        w = World(n, Params(transfer_rate=0.0), seed, "mahros")
        w.run(7 * 1440)
        rows += w.calibration()
    c = pd.DataFrame(rows)
    assert c["simulated"].sum() / c["reported"].sum() == pytest.approx(1.0, abs=0.04)


def test_offered_load_solves_the_capped_census():
    a = offered_load(9.0, 10)
    assert a * (1 - erlang_b(10, a)) == pytest.approx(9.0, rel=1e-6)
    assert offered_load(0, 10) == 0.0


def test_odd_bed_count_does_not_invent_a_staff_shortage():
    """Found in a screenshot: floor(105/2) nurses lost a bed and claimed to be short-staffed."""
    a = HospitalAgent(site("A", 105, 104), 0, quiet(reserve_beds=0), False, None, 0)
    assert a._icu_usable == 105
    yes, d = a.decide("icu", 0)
    assert yes
    a.take("icu", 0, False)
    yes, d = a.decide("icu", 0)
    assert not yes and d["code"] == "full"


def test_coordinators_never_read_a_hospitals_private_state():
    """The coordinator (MAHROS and phone) may only ASK a hospital agent (decide / take /
    messages); it must never read the agent's private fields directly."""
    import inspect
    import re
    from mahros.emergency import world as W
    private = re.compile(r"\._(icu|vent|picu|nurses|reserve|cath|short|prm)")
    coordinator_methods = [m for n, m in inspect.getmembers(W.World, inspect.isfunction)
                           if n.startswith(("_mahros", "_phone", "_reach", "on_need", "on_hospital"))]
    assert len(coordinator_methods) >= 7
    for m in coordinator_methods:
        src = inspect.getsource(m)
        assert not private.search(src), f"{m.__name__} reads private hospital state"


def test_hospital_with_no_staffed_icu_says_so_plainly():
    """Found in the seeded record book: 'ICU full (0 of 0 beds in use)'."""
    a = HospitalAgent(site("A", 0, 0), 0, quiet(), False, None, 0)
    yes, d = a.decide("icu", 0)
    assert not yes and d["reason"] == "no staffed ICU beds reported this week"
