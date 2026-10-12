"""Surge signals and alerts: into the database, and back out for the dashboard.

Alerts from overlapping neighbourhoods are merged: in each state-week the
highest-probability neighbourhood is kept and every other alerted centre
within 50 km is folded into it, so the screen shows "the Phoenix area", not
twenty overlapping circles.
"""

from __future__ import annotations

import subprocess
import sys

import numpy as np
import pandas as pd

from ..data import hhs
from ..db.io import read_frame, truncate, write_frame
from .features import RADIUS_KM, THRESHOLD

SCORES = hhs.CACHE / "surge_scores.parquet"


def _km(lat1, lon1, lat2, lon2):
    from ..coordination import haversine_km
    return haversine_km(lat1, lon1, lat2, lon2)


def _growth_word(g) -> str:
    if g is None or not np.isfinite(g):
        return "not reported"
    pct = (np.exp(g) - 1) * 100
    if abs(pct) < 5:
        return "flat"
    return f"{'up' if pct > 0 else 'down'} {abs(pct):.0f}%"


def message(r) -> str:
    return (f"{r.area_occ:.0%} full now ({100 * (r.area_occ_d2 if np.isfinite(r.area_occ_d2) else 0):+.0f} "
            f"points in 2 weeks); new COVID-19 admissions {_growth_word(r.covid_adm_growth)}, "
            f"flu admissions {_growth_word(r.flu_adm_growth)}; {int(r.rising_neighbours)} of "
            f"{int(r.n_neighbours)} hospitals rising. Chance of reaching {THRESHOLD:.0%} within "
            f"2 weeks: {r.probability:.0%}.")


def merge_alerts(s: pd.DataFrame, info: pd.DataFrame, rule_col: str = "alert_model") -> pd.DataFrame:
    """One alert per area per state-week (greedy by probability, 50 km)."""
    a = s[s[rule_col]].join(info[["lat", "lon", "name", "city"]], on="hospital_pk")
    out = []
    for (_, _), g in a.groupby(["state", "week"], sort=False):
        g = g.sort_values("probability", ascending=False)
        lat, lon = g["lat"].to_numpy(), g["lon"].to_numpy()
        taken = np.zeros(len(g), bool)
        for i in range(len(g)):
            if taken[i]:
                continue
            d = _km(lat[i], lon[i], lat, lon)
            members = (~taken) & (d <= RADIUS_KM)
            taken |= members
            r = g.iloc[i]
            out.append({"hospital_pk": r.hospital_pk, "state": r.state, "week": r.week,
                        "probability": float(r.probability), "members": int(members.sum()),
                        "message": message(r)})
    return pd.DataFrame(out)


def load_surge(engine, df: pd.DataFrame) -> str:
    """Loader step: surge_signals (every neighbourhood-week) and merged surge_alerts."""
    if not SCORES.exists():
        rc = subprocess.call([sys.executable, "-u", str(hhs.ROOT / "experiments" / "surge_warning.py")])
        if rc:
            raise RuntimeError("surge_warning.py failed")
    s = pd.read_parquet(SCORES)
    info = df.sort_values("week").groupby("hospital_pk")[["lat", "lon", "name", "city"]].last()
    sig = pd.DataFrame({
        "hospital_pk": s["hospital_pk"], "week": s["week"], "state": s["state"],
        "n_neighbours": s["n_neighbours"].astype(int), "area_occ": s["area_occ"],
        "area_occ_d1": s["area_occ_d1"], "area_occ_d2": s["area_occ_d2"],
        "area_ed_growth": s["ed_growth"], "area_covid_adm_growth": s["covid_adm_growth"],
        "area_flu_adm_growth": s["flu_adm_growth"],
        "rising_neighbours": s["rising_neighbours"].astype(int), "probability": s["probability"],
        "source": "experiments/surge_warning.py", "provenance": "derived"})
    truncate(engine, "surge_signals", "surge_alerts")
    write_frame(engine, "surge_signals", sig)
    al = []
    for rule, col in (("model", "alert_model"), ("neighbours", "alert_neighbours")):
        m = merge_alerts(s, info, col)
        if len(m):
            m["rule"] = rule
            al.append(m)
    alerts = pd.concat(al, ignore_index=True)
    alerts = alerts[["hospital_pk", "state", "week", "rule", "probability", "message"]].assign(
        source="experiments/surge_warning.py", provenance="derived")
    write_frame(engine, "surge_alerts", alerts)
    return f"{len(sig):,} neighbourhood-weeks, {len(alerts):,} merged alerts"


# --------------------------------------------------------------------------- #
# Reading for the dashboard
# --------------------------------------------------------------------------- #

def weeks(engine, state: str) -> list[dict]:
    """Every week with signals, and how many real WARNINGS (area still below the line) it had."""
    st = _st(state)
    d = read_frame(engine, f"SELECT DISTINCT week FROM surge_signals WHERE state = '{st}' ORDER BY week")
    w = read_frame(engine, f"""
        SELECT a.week, COUNT(*) AS n FROM surge_alerts a
        JOIN surge_signals s ON s.hospital_pk = a.hospital_pk AND s.week = a.week
        WHERE a.state = '{st}' AND a.rule = 'model' AND s.area_occ < {THRESHOLD}
        GROUP BY a.week""")
    n = {str(pd.Timestamp(x).date()): int(c) for x, c in zip(w["week"], w["n"])} if len(w) else {}
    return [{"week": str(pd.Timestamp(x).date()), "warnings": n.get(str(pd.Timestamp(x).date()), 0)}
            for x in d["week"]]


def week_view(engine, state: str, week: str) -> dict:
    st, wk = _st(state), str(pd.Timestamp(week).date())
    sig = read_frame(engine, f"""
        SELECT s.hospital_pk, s.area_occ, s.area_occ_d2, s.probability, s.n_neighbours,
               s.rising_neighbours, h.name, h.city, h.lat, h.lon
        FROM surge_signals s JOIN hospitals h ON h.hospital_pk = s.hospital_pk
        WHERE s.state = '{st}' AND s.week = '{wk}'""")
    nxt = read_frame(engine, f"""
        SELECT hospital_pk, area_occ FROM surge_signals
        WHERE state = '{st}' AND week IN (DATE '{wk}' + 7, DATE '{wk}' + 14)""") \
        if engine.dialect.name == "postgresql" else read_frame(engine, f"""
        SELECT hospital_pk, area_occ FROM surge_signals WHERE state = '{st}'
        AND week IN (date('{wk}', '+7 day'), date('{wk}', '+14 day'))""")
    peak = nxt.groupby("hospital_pk")["area_occ"].max() if len(nxt) else pd.Series(dtype=float)
    al = read_frame(engine, f"""
        SELECT a.hospital_pk, a.rule, a.probability, a.message, h.name, h.city
        FROM surge_alerts a JOIN hospitals h ON h.hospital_pk = a.hospital_pk
        WHERE a.state = '{st}' AND a.week = '{wk}' ORDER BY a.probability DESC""")
    hs = []
    for r in sig.itertuples():
        nx = peak.get(r.hospital_pk)
        hs.append({"id": r.hospital_pk, "name": _s(r.name), "city": _s(r.city), "lat": _f(r.lat), "lon": _f(r.lon),
                   "area_occ": _f(r.area_occ), "d2": _f(r.area_occ_d2), "p": _f(r.probability),
                   "n": int(r.n_neighbours), "rising": int(r.rising_neighbours),
                   "next_peak": _f(nx)})
    occ_now = {h["id"]: h["area_occ"] for h in hs}
    alerts = []
    for r in al.itertuples():
        now = occ_now.get(r.hospital_pk)
        alerts.append({
            "id": r.hospital_pk, "rule": r.rule, "p": _f(r.probability), "name": _s(r.name),
            "city": _s(r.city), "area": f"{_s(r.city).title()} area" if _s(r.city) else _s(r.name),
            "message": r.message, "area_occ": now,
            # A WARNING is about an area still below the threshold; above it is status.
            "kind": "already" if now is not None and now >= THRESHOLD else "warning",
            "happened": (lambda v: None if v is None else bool(v >= THRESHOLD))(_f(peak.get(r.hospital_pk)))})
    return {"state": state, "week": wk, "threshold": THRESHOLD, "radius_km": RADIUS_KM,
            "hospitals": hs, "alerts": alerts}


def _st(s: str) -> str:
    if not (isinstance(s, str) and len(s) == 2 and s.isalpha()):
        raise ValueError("bad state")
    return s.upper()


def _s(v) -> str:
    """Text or "" -- PostgreSQL COPY returns a blank (NaN) for a missing string."""
    return v if isinstance(v, str) else ""


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if not np.isfinite(f) else round(f, 4)
