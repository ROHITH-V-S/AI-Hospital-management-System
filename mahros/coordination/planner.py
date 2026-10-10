"""The Regional Coordinator's plan: who should send patients where next week.

The decision, in one sentence
-----------------------------
For each state and week, move patient load from hospitals forecast to be above
a safe occupancy level to nearby hospitals forecast to stay below it, as much
as possible, preferring shorter distances.

This is *tactical weekly load balancing* -- what the state Medical Operations
Coordination Centers (Washington, Minnesota, Arizona) did during COVID-19 --
not routing of an individual patient. Quantities are average census
("beds-worth of patients over the week"); multiplied by 7 they are
patient-days. No length-of-stay assumption is needed for either.

The linear program (solved per state per week with HiGHS)
---------------------------------------------------------
    maximise    sum_ij x_ij  -  eps * sum_ij (d_ij / R) x_ij
    subject to  sum_j x_ij <= send_cap_i      (each sender)
                sum_i x_ij <= spare_j         (each receiver)
                x_ij >= 0, and x_ij exists only if d_ij <= R

    send_cap_i = min( (p_i - theta) * B_i ,  kappa * p_i * B_i )   if p_i > theta
    spare_j    = (theta - hi_j) * B_j                              if hi_j < theta

where p is the point forecast, hi the upper end of the 90% interval, B staffed
beds, d straight-line distance. Using ``hi`` for receivers is the safety
margin: a hospital is only offered patients if it stays below the safe level
even when its forecast is too optimistic.

Declared parameters (all swept in experiments/rq3_coordination.py)
------------------------------------------------------------------
theta  safe occupancy level, 0.90. Occupancy above ~85-90% is widely used as a
       strain threshold; 0.85 and 0.95 are also run.
R      transfer radius, 80 km straight line (~1 h by road at the 1.20 road /
       straight-line ratio measured for Houston). 40 and 150 also run.
kappa  at most 5% of a hospital's census moved per week. 2% and 10% also run.
eps    0.1: distance only breaks ties; it never reduces how much is moved.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

THETA = 0.90
RADIUS_KM = 80.0
KAPPA = 0.05
EPS = 0.1


@dataclass(frozen=True)
class Params:
    theta: float = THETA
    radius_km: float = RADIUS_KM
    kappa: float = KAPPA
    eps: float = EPS


def haversine_km(lat1, lon1, lat2, lon2) -> np.ndarray:
    lat1, lon1, lat2, lon2 = map(np.radians, (lat1, lon1, lat2, lon2))
    a = (np.sin((lat2 - lat1) / 2) ** 2
         + np.cos(lat1) * np.cos(lat2) * np.sin((lon2 - lon1) / 2) ** 2)
    return 6371.0 * 2 * np.arcsin(np.sqrt(np.clip(a, 0, 1)))


def send_capacity(p, beds, prm: Params) -> np.ndarray:
    excess = (p - prm.theta) * beds
    cap = np.minimum(excess, prm.kappa * p * beds)
    return np.where(np.isfinite(cap) & (cap > 0), cap, 0.0)


def spare_capacity(hi, beds, eligible, prm: Params) -> np.ndarray:
    spare = (prm.theta - hi) * beds
    return np.where(eligible & np.isfinite(spare) & (spare > 0), spare, 0.0)


@dataclass
class Plan:
    senders: np.ndarray          # index into the hospital arrays
    receivers: np.ndarray
    amount: np.ndarray           # average census moved
    distance_km: np.ndarray


def _arcs(lat, lon, s_idx, r_idx, radius, distance=None):
    if len(s_idx) == 0 or len(r_idx) == 0:
        return np.empty(0, int), np.empty(0, int), np.empty(0)
    if distance is None:
        d = haversine_km(lat[s_idx][:, None], lon[s_idx][:, None],
                         lat[r_idx][None, :], lon[r_idx][None, :])
    else:
        d = np.asarray(distance)[np.ix_(s_idx, r_idx)]
    si, rj = np.nonzero(d <= radius)
    return s_idx[si], r_idx[rj], d[si, rj]


def solve_lp(lat, lon, cap, spare, prm: Params, distance=None) -> Plan:
    """Optimal transportation plan. Arrays are aligned per hospital.

    ``distance`` optionally replaces straight-line km with any n x n matrix in
    the same unit as ``prm.radius_km`` (the Houston case study passes routed
    driving minutes and a radius in minutes).
    """
    s_idx = np.nonzero(cap > 1e-9)[0]
    r_idx = np.nonzero(spare > 1e-9)[0]
    s, r, d = _arcs(lat, lon, s_idx, r_idx, prm.radius_km, distance)
    if len(s) == 0:
        return Plan(*(np.empty(0, int),) * 2, np.empty(0), np.empty(0))
    n = len(s)
    c = -1.0 + prm.eps * d / prm.radius_km
    s_pos = {h: k for k, h in enumerate(np.unique(s))}
    r_pos = {h: k for k, h in enumerate(np.unique(r))}
    rows = np.concatenate([[s_pos[h] for h in s],
                           [len(s_pos) + r_pos[h] for h in r]])
    cols = np.concatenate([np.arange(n), np.arange(n)])
    A = coo_matrix((np.ones(2 * n), (rows, cols)),
                   shape=(len(s_pos) + len(r_pos), n)).tocsr()
    b = np.concatenate([[cap[h] for h in s_pos], [spare[h] for h in r_pos]])
    res = linprog(c, A_ub=A, b_ub=b, bounds=(0, None), method="highs")
    if not res.success:
        raise RuntimeError(f"planner LP failed: {res.message}")
    x = res.x
    keep = x > 1e-6
    return Plan(s[keep], r[keep], x[keep], d[keep])


def solve_greedy(lat, lon, cap, spare, prm: Params) -> Plan:
    """Baseline: biggest excess first, each to its nearest hospital with room."""
    cap, spare = cap.copy(), spare.copy()
    s_idx = np.nonzero(cap > 1e-9)[0]
    r_idx = np.nonzero(spare > 1e-9)[0]
    out_s, out_r, out_x, out_d = [], [], [], []
    for i in s_idx[np.argsort(-cap[s_idx])]:
        if len(r_idx) == 0:
            break
        d = haversine_km(lat[i], lon[i], lat[r_idx], lon[r_idx])
        for k in np.argsort(d):
            if d[k] > prm.radius_km or cap[i] <= 1e-9:
                break
            j = r_idx[k]
            amt = min(cap[i], spare[j])
            if amt <= 1e-9:
                continue
            cap[i] -= amt
            spare[j] -= amt
            out_s.append(i), out_r.append(j), out_x.append(amt), out_d.append(d[k])
    return Plan(np.array(out_s, int), np.array(out_r, int),
                np.array(out_x), np.array(out_d))


@dataclass
class Execution:
    """What actually happened when hospitals checked the plan against reality."""
    executed: np.ndarray         # per arc, average census actually moved
    sender_factor: np.ndarray    # per arc, share the sender could really send
    receiver_factor: np.ndarray  # per arc, share the receiver could really take
    unverifiable: np.ndarray     # per arc, True if either side's next report is untrusted


def execute(plan: Plan, used_next, beds_next, trusted_next, prm: Params) -> Execution:
    """Each hospital agent accepts only what its actual next-week report allows.

    A sender sends no more than its real excess over the safe level; a receiver
    takes no more than its real spare room below it. A transfer touching a
    hospital whose next report is untrusted cannot be verified and is not
    credited. This is what keeps the evaluation honest: a plan built on a bad
    forecast earns nothing for the patients it could not actually move.
    """
    n = len(plan.amount)
    if n == 0:
        z = np.empty(0)
        return Execution(z, z, z, np.empty(0, bool))
    # Same order as the agents (mahros.agents.platform): every sender decides
    # first, knowing only its own situation; then every receiver decides on
    # what is actually coming. A hospital whose own report is untrusted moves
    # nothing on its own account. Pinned equal to the agent path by a test.
    n = len(beds_next)
    excess = np.nan_to_num(np.maximum(0.0, used_next - prm.theta * beds_next))
    room = np.nan_to_num(np.maximum(0.0, prm.theta * beds_next - used_next))
    unver = ~(trusted_next[plan.senders] & trusted_next[plan.receivers])

    planned_out = np.bincount(plan.senders, plan.amount, minlength=n)
    f_send = np.zeros(n)
    pos = planned_out > 0
    f_send[pos] = np.minimum(1.0, excess[pos] / planned_out[pos])
    f_send[~trusted_next] = 0.0
    after_send = plan.amount * f_send[plan.senders]

    planned_in = np.bincount(plan.receivers, after_send, minlength=n)
    f_recv = np.zeros(n)
    pos = planned_in > 0
    f_recv[pos] = np.minimum(1.0, room[pos] / planned_in[pos])
    f_recv[~trusted_next] = 0.0
    executed = after_send * f_recv[plan.receivers]
    return Execution(executed, f_send[plan.senders], f_recv[plan.receivers], unver)


def overload(used, beds, trusted, prm: Params) -> float:
    """Average census above the safe level, summed over trusted hospitals."""
    ex = np.maximum(0.0, used - prm.theta * beds)
    return float(np.nansum(np.where(trusted, ex, 0.0)))
