"""Who lends what to whom: a weighted transportation LP (HiGHS), shared by staff and equipment.

    maximise   sum_ij w_j x_ij  -  eps * sum_ij (d_ij / R) x_ij
    s.t.       sum_j x_ij <= surplus_i     (a lender never goes below what it needs itself)
               sum_i x_ij <= shortfall_j
               x_ij >= 0, only if d_ij <= R

``w_j`` = 1, or ``priority`` for hospitals in an area with a surge warning, so
warned areas are served first when there is not enough to go round.
Integer items (equipment) are rounded down and the remainder is filled
greedily by the largest fractional parts, never exceeding either side.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import linprog
from scipy.sparse import coo_matrix

from ..coordination import haversine_km


@dataclass
class Moves:
    src: np.ndarray
    dst: np.ndarray
    amount: np.ndarray
    km: np.ndarray


def plan(lat, lon, surplus, shortfall, radius_km: float, weight=None, eps: float = 0.05,
         integer: bool = False) -> Moves:
    lat, lon = np.asarray(lat, float), np.asarray(lon, float)
    surplus, shortfall = np.asarray(surplus, float), np.asarray(shortfall, float)
    w = np.ones(len(lat)) if weight is None else np.asarray(weight, float)
    s_idx = np.flatnonzero(surplus > 1e-9)
    r_idx = np.flatnonzero(shortfall > 1e-9)
    empty = Moves(np.empty(0, int), np.empty(0, int), np.empty(0), np.empty(0))
    if not len(s_idx) or not len(r_idx):
        return empty
    d = haversine_km(lat[s_idx][:, None], lon[s_idx][:, None], lat[r_idx][None, :], lon[r_idx][None, :])
    si, rj = np.nonzero((d <= radius_km) & (s_idx[:, None] != r_idx[None, :]))
    if not len(si):
        return empty
    s, r, dk = s_idx[si], r_idx[rj], d[si, rj]
    n = len(s)
    c = -w[r] + eps * dk / radius_km
    sp = {h: k for k, h in enumerate(np.unique(s))}
    rp = {h: k for k, h in enumerate(np.unique(r))}
    rows = np.concatenate([[sp[h] for h in s], [len(sp) + rp[h] for h in r]])
    A = coo_matrix((np.ones(2 * n), (rows, np.r_[np.arange(n), np.arange(n)])),
                   shape=(len(sp) + len(rp), n)).tocsr()
    b = np.r_[[surplus[h] for h in sp], [shortfall[h] for h in rp]]
    res = linprog(c, A_ub=A, b_ub=b, bounds=(0, None), method="highs")
    if not res.success:
        raise RuntimeError(res.message)
    x = res.x
    if integer:
        x = _round(x, s, r, surplus, shortfall)
    keep = x > (0.5 if integer else 1e-6)
    return Moves(s[keep], r[keep], x[keep], dk[keep])


def _round(x, s, r, surplus, shortfall):
    base = np.floor(x + 1e-9)
    left_s = {h: surplus[h] - base[s == h].sum() for h in np.unique(s)}
    left_r = {h: shortfall[h] - base[r == h].sum() for h in np.unique(r)}
    for k in np.argsort(-(x - base)):
        if x[k] - base[k] < 1e-6:
            break
        if left_s[s[k]] >= 1 and left_r[r[k]] >= 1:
            base[k] += 1
            left_s[s[k]] -= 1
            left_r[r[k]] -= 1
    return base
