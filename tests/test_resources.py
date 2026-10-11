"""Staff and equipment: estimates are causal, lenders keep enough, integers never overshoot,
entered inventory is never overwritten."""

import numpy as np
import pandas as pd
import pytest
from sqlalchemy import create_engine, func, select

from mahros.resources import equipment as EQ
from mahros.resources.optimize import plan
from mahros.resources.staff import pools


def frame(n=20):
    rows = []
    for k, w in enumerate(pd.date_range("2023-01-01", periods=n, freq="7D")):
        rows.append({"hospital_pk": "A", "week": w, "state": "AZ", "level": "GREEN",
                     "beds": 100.0, "used": 80.0 + (20 if k == n - 1 else 0), "icu_beds": 20.0, "icu_used": 16.0})
    return pd.DataFrame(rows)


def test_staff_need_uses_title22_ratios_and_pool_uses_usual_beds():
    p = pools(frame()).set_index("week")
    last = p.iloc[-1]
    assert last["nurses_per_shift"] == 10 + 16            # 20 ICU /2 + 80 ward /5
    assert last["nurses_needed"] == 8 + 17                # 16/2 + ceil(84/5)
    assert last["nurse_gap"] == last["nurses_needed"] - last["nurses_per_shift"]


def test_pool_does_not_look_at_this_week_or_later():
    a = pools(frame(20))
    f = frame(20)
    f.loc[f.index[-1], "beds"] = 500.0                     # this week's beds change...
    b = pools(f)
    assert a["nurses_per_shift"].iloc[-1] == b["nurses_per_shift"].iloc[-1]   # ...pool unchanged


def test_lenders_never_give_more_than_their_surplus_and_integers_never_overshoot():
    rng = np.random.default_rng(1)
    lat, lon = 33 + rng.uniform(0, .5, 30), -112 + rng.uniform(0, .5, 30)
    surplus = rng.integers(0, 4, 30).astype(float)
    short = np.where(surplus == 0, rng.integers(0, 5, 30), 0).astype(float)
    mv = plan(lat, lon, surplus, short, 100.0, integer=True)
    give = np.bincount(mv.src, mv.amount, minlength=30)
    get = np.bincount(mv.dst, mv.amount, minlength=30)
    assert (give <= surplus + 1e-9).all() and (get <= short + 1e-9).all()
    assert np.allclose(mv.amount, np.round(mv.amount))


def test_warned_hospitals_are_served_first_when_there_is_not_enough():
    lat, lon = np.array([33.0, 33.01, 33.02]), np.array([-112.0, -112.0, -112.0])
    mv = plan(lat, lon, [1, 0, 0], [0, 1, 1], 50.0, weight=[1, 1, 1.5], integer=True)
    assert list(mv.dst) == [2]


def test_equipment_shortfall_keeps_a_spare_and_adds_the_surge_buffer():
    assert EQ.shortfall_surplus(10, 10.0, warned=False) == (0, 0)
    assert EQ.shortfall_surplus(10, 10.0, warned=True) == (2, 0)      # ceil(11.5) = 12
    assert EQ.shortfall_surplus(10, 5.0, warned=False) == (0, 4)


def test_seed_never_overwrites_entered_inventory(tmp_path):
    from mahros.db.models import Base, EquipmentItem, Hospital
    from mahros.resources.store import seed_equipment
    eng = create_engine(f"sqlite:///{tmp_path / 'r.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(Hospital.__table__.insert(), [{"hospital_pk": "A", "name": "A", "state": "AZ",
                                                 "source": "t", "provenance": "observed"}])
    df = frame().assign(week=pd.date_range("2023-01-01", periods=20, freq="7D"))
    assert "seeded" in seed_equipment(eng, df)
    with eng.connect() as c:
        n = c.execute(select(func.count()).select_from(EquipmentItem)).scalar()
    assert n == 4
    assert "left as entered" in seed_equipment(eng, df)
