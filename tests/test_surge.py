"""Surge early warning: signals are causal, areas are right, alerts merge, warnings != status."""

import numpy as np
import pandas as pd
import pytest

from mahros.surge import features as F
from mahros.surge.store import merge_alerts


def synth(n_weeks=12, seed=0):
    """Three hospitals close together (one area) and one far away."""
    rng = np.random.default_rng(seed)
    pos = {"A": (33.45, -112.07), "B": (33.50, -112.00), "C": (33.40, -111.95), "Z": (35.20, -111.65)}
    rows = []
    for k, w in enumerate(pd.date_range("2023-01-01", periods=n_weeks, freq="7D")):
        for h, (lat, lon) in pos.items():
            beds = 100.0
            rows.append({"hospital_pk": h, "week": w, "state": "AZ", "subtype": "Short Term",
                         "lat": lat, "lon": lon, "name": h, "city": "X", "level": "GREEN",
                         "used": 60 + 3 * k + rng.normal(0, 1), "beds": beds,
                         "icu_used": 8.0, "icu_beds": 10.0,
                         "covid_adm_adult": 10.0 + k, "covid_adm_peds": 0.0, "flu_adm": 5.0,
                         "ed_visits": 500.0, "covid_adm_adult_suppressed": False,
                         "covid_adm_peds_suppressed": False, "flu_adm_suppressed": False,
                         "ed_visits_suppressed": False})
    return pd.DataFrame(rows)


def test_neighbourhoods_use_the_radius():
    f = F.build(synth())
    n = f.groupby("hospital_pk")["n_neighbours"].first()
    assert n["A"] == 3 and n["Z"] == 1


def test_signals_never_use_future_weeks():
    d = synth(12)
    f1 = F.build(d)
    d2 = d.copy()
    d2.loc[d2["week"] > d2["week"].unique()[8], "used"] = 5.0       # rewrite the future
    f2 = F.build(d2)
    cut = d["week"].unique()[8]
    cols = [c for c in F.FEATURES]
    a = f1[f1["week"] <= cut].set_index(["hospital_pk", "week"])[cols]
    b = f2[f2["week"] <= cut].set_index(["hospital_pk", "week"])[cols]
    pd.testing.assert_frame_equal(a, b)


def test_untrusted_reports_are_left_out_of_area_occupancy():
    d = synth(6)
    d.loc[(d["hospital_pk"] == "B"), "level"] = "RED"
    d.loc[(d["hospital_pk"] == "B"), "used"] = 1000.0               # impossible, flagged
    f = F.build(d)
    assert f[f["hospital_pk"] == "A"]["area_occ"].max() < 1.0


def test_target_is_reaching_the_line_in_one_or_two_weeks():
    f = F.build(synth(12))
    r = f.dropna(subset=["exceed_1_2"]).iloc[0]
    assert r["exceed_1_2"] == float(max(r["occ_next1"], r["occ_next2"]) >= F.THRESHOLD)


def test_overlapping_alerts_merge_into_one_area():
    s = pd.DataFrame({"hospital_pk": ["A", "B", "C", "Z"], "state": "AZ",
                      "week": pd.Timestamp("2023-02-05"), "alert_model": True,
                      "probability": [0.5, 0.9, 0.4, 0.3], "area_occ": 0.8, "area_occ_d2": 0.02,
                      "covid_adm_growth": 0.1, "flu_adm_growth": 0.0, "rising_neighbours": 2,
                      "n_neighbours": 3})
    info = synth(1).set_index("hospital_pk")[["lat", "lon", "name", "city"]]
    m = merge_alerts(s, info)
    assert sorted(m["hospital_pk"]) == ["B", "Z"]                      # B leads the city area
    assert m.set_index("hospital_pk").loc["B", "members"] == 3
