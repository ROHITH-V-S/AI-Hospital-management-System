"""Forecast inputs never use the future; targets and splits are what they claim."""

import numpy as np
import pandas as pd
import pytest

from mahros import forecast as F
from mahros.forecast.model import CALIB_END, START, TRAIN_END


def synthetic(seed=0, weeks=150):
    rng = np.random.default_rng(seed)
    rows = []
    for h, (state, beds) in enumerate([("TX", 200), ("TX", 120), ("CA", 300)]):
        for k, w in enumerate(pd.date_range(START, periods=weeks, freq="7D")):
            used = beds * (0.7 + 0.1 * np.sin(k / 8 + h) + rng.normal(0, 0.02))
            rows.append({"hospital_pk": f"H{h}", "week": w, "state": state,
                         "subtype": "Short Term", "metro": True, "lat": 30.0, "lon": -95.0,
                         "name": f"H{h}", "city": "X", "used": used, "beds": float(beds),
                         "icu_used": 10.0, "icu_beds": 20.0, "covid_used": used * 0.1})
    df = pd.DataFrame(rows)
    return df, pd.Series("GREEN", index=df.index)


def test_inputs_do_not_depend_on_the_future():
    df, lv = synthetic()
    cut = START + pd.Timedelta(weeks=100)
    fut = df.copy()
    fut.loc[fut["week"] > cut, ["used", "covid_used"]] *= 3.0      # rewrite the future
    for h in F.HORIZONS:
        a = F.features(F.build_panel(df, lv), h)
        b = F.features(F.build_panel(fut, lv), h)
        past = a["week"] <= cut
        cols = [c for c in F.FEATURES]
        pd.testing.assert_frame_equal(a.loc[past, cols], b.loc[past, cols])


def test_target_is_occupancy_h_weeks_later():
    df, lv = synthetic()
    fr = F.features(F.build_panel(df, lv), 2)
    row = fr[(fr["hospital_pk"] == "H1")].iloc[30]
    later = df[(df["hospital_pk"] == "H1") & (df["week"] == row["week"] + pd.Timedelta(weeks=2))]
    assert row["y"] == pytest.approx(float(later["used"].iloc[0] / later["beds"].iloc[0]))


def test_untrusted_reports_are_masked_not_guessed():
    df, lv = synthetic()
    lv.iloc[5] = "RED"
    p = F.build_panel(df, lv, trusted=True)
    r = df.iloc[5]
    assert np.isnan(p.occ.loc[r["week"], r["hospital_pk"]])
    assert not p.trusted.loc[r["week"], r["hospital_pk"]]
    raw = F.build_panel(df, lv, trusted=False)
    assert not np.isnan(raw.occ.loc[r["week"], r["hospital_pk"]])


def test_splits_do_not_overlap():
    df, lv = synthetic(weeks=190)
    parts = F.split(F.features(F.build_panel(df, lv), 1))
    assert parts["train"]["target_week"].max() <= TRAIN_END
    assert parts["calib"]["target_week"].min() > TRAIN_END
    assert parts["calib"]["target_week"].max() <= CALIB_END
    assert parts["test"]["target_week"].min() > CALIB_END
