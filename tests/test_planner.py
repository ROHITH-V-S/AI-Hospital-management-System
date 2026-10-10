"""Planner and execution guarantees. Small hand-built networks; logic only."""

import numpy as np
import pytest

from mahros.coordination import (Params, execute, haversine_km, overload,
                                 send_capacity, solve_greedy, solve_lp,
                                 spare_capacity)

P = Params(theta=0.9, radius_km=80, kappa=0.05, eps=0.1)


def test_haversine_known_distance():
    # Houston TMC to Galveston is ~70 km straight line.
    d = haversine_km(29.708, -95.400, 29.301, -94.797)
    assert 65 < d < 78


def test_send_and_spare_capacity():
    beds = np.array([100.0, 100.0, 100.0])
    p = np.array([0.98, 0.80, 0.92])
    cap = send_capacity(p, beds, P)
    assert cap[0] == pytest.approx(min(8.0, 0.05 * 98))   # kappa binds: 4.9
    assert cap[1] == 0
    assert cap[2] == pytest.approx(2.0)
    hi = np.array([0.99, 0.85, 0.95])
    spare = spare_capacity(hi, beds, np.array([True, True, True]), P)
    assert spare.tolist() == pytest.approx([0, 5.0, 0])
    spare = spare_capacity(hi, beds, np.array([True, False, True]), P)
    assert spare[1] == 0                                   # untrusted receiver gets nothing


def net():
    lat = np.array([29.70, 29.75, 29.60, 31.5])     # last one is ~200 km away
    lon = np.array([-95.40, -95.35, -95.30, -95.4])
    cap = np.array([6.0, 0, 0, 0])
    spare = np.array([0, 2.0, 10.0, 50.0])
    return lat, lon, cap, spare


def test_lp_respects_caps_and_radius():
    lat, lon, cap, spare = net()
    plan = solve_lp(lat, lon, cap, spare, P)
    assert plan.amount.sum() == pytest.approx(6.0)
    assert 3 not in plan.receivers                       # out of radius
    for j in np.unique(plan.receivers):
        assert plan.amount[plan.receivers == j].sum() <= spare[j] + 1e-6
    assert (plan.distance_km <= P.radius_km).all()


def test_lp_never_moves_less_than_greedy():
    rng = np.random.default_rng(0)
    for _ in range(25):
        n = 12
        lat = 29.7 + rng.normal(0, 0.3, n)
        lon = -95.4 + rng.normal(0, 0.3, n)
        cap = np.where(rng.random(n) < 0.4, rng.uniform(0, 8, n), 0)
        spare = np.where(cap == 0, rng.uniform(0, 6, n), 0)
        lp = solve_lp(lat, lon, cap, spare, P).amount.sum()
        gr = solve_greedy(lat, lon, cap, spare, P).amount.sum()
        assert lp >= gr - 1e-6


def test_greedy_respects_caps():
    lat, lon, cap, spare = net()
    plan = solve_greedy(lat, lon, cap, spare, P)
    assert plan.amount.sum() <= 6.0 + 1e-9
    assert 3 not in plan.receivers


def test_no_senders_or_receivers_gives_empty_plan():
    lat, lon, _, spare = net()
    assert len(solve_lp(lat, lon, np.zeros(4), spare, P).amount) == 0
    assert len(solve_lp(lat, lon, np.array([5.0, 0, 0, 0]), np.zeros(4), P).amount) == 0


def test_execution_caps_to_reality():
    lat, lon, cap, spare = net()
    plan = solve_lp(lat, lon, cap, spare, P)
    beds = np.array([100.0, 100, 100, 100])
    # Reality: sender only 3 over the safe level; receiver 2 has only 1 spare bed.
    used = np.array([93.0, 80.0, 89.0, 50.0])
    ex = execute(plan, used, beds, np.ones(4, bool), P)
    moved_out = ex.executed.sum()
    assert moved_out <= 3.0 + 1e-9
    into = np.bincount(plan.receivers, ex.executed, minlength=4)
    room = np.maximum(0, 0.9 * beds - used)
    assert (into <= room + 1e-9).all()                   # nobody pushed past safe level


def test_untrusted_next_report_is_not_credited():
    lat, lon, cap, spare = net()
    plan = solve_lp(lat, lon, cap, spare, P)
    beds = np.full(4, 100.0)
    used = np.array([99.0, 50, 50, 50])
    trusted = np.array([False, True, True, True])        # sender's next report untrusted
    ex = execute(plan, used, beds, trusted, P)
    assert ex.executed.sum() == 0
    assert ex.unverifiable.all()


def test_overload_counts_only_trusted():
    used = np.array([95.0, 99.0, 50.0])
    beds = np.full(3, 100.0)
    assert overload(used, beds, np.array([True, False, True]), P) == pytest.approx(5.0)
