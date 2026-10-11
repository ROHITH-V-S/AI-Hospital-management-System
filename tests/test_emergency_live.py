"""The live Emergency screen on the real Arizona data, writing to a throwaway database.

Skipped where the data cache is absent.
"""

import json

import pytest
from sqlalchemy import create_engine, func, select, update

from mahros.data import hhs

pytestmark = pytest.mark.skipif(
    not (hhs.CACHE / "hhs_corrected_extra_source.parquet").exists(),
    reason="needs the data cache (experiments/fetch_national.py, fetch_extra.py)")


@pytest.fixture(scope="module")
def live(tmp_path_factory):
    from mahros.db.models import Base, Hospital
    from mahros.emergency.live import EmergencyLive
    from mahros.ledger.store import DbLedger
    path = tmp_path_factory.mktemp("em") / "e.sqlite"
    eng = create_engine(f"sqlite:///{path}", future=True)
    Base.metadata.create_all(eng)
    rows = []
    for st in ("az", "ma"):
        net = json.loads((hhs.ROOT / "mahros" / "calibration" / "data" / f"us_{st}_network.json").read_text())
        rows += [{"hospital_pk": h["hospital_pk"], "name": h["name"], "state": st.upper(),
                  "source": "test", "provenance": "observed"} for h in net["hospitals"]]
    with eng.begin() as c:
        c.execute(Hospital.__table__.insert(), rows)
    em = EmergencyLive(eng, DbLedger(eng))
    em._load()                      # no engine data loaded -> reads the research files
    assert em.ready, em.error
    return em, eng


def _small_sender(em, state="AZ"):
    return next(h for h in em.hospitals(state) if h["ed_visits_week"] and not h["can"]["cath_lab"])


def test_find_a_bed_explains_every_step_and_logs_it(live):
    em, eng = live
    o = _small_sender(em)
    r = em.find_bed("AZ", o["id"], "cath_lab")
    assert r["asked_count"] >= 1 and len(r["asked"]) == r["asked_count"]
    assert all(a["reason"] for a in r["asked"])                       # every answer has a reason
    assert r["phone"]["5"] is not None and r["phone"]["15"] is not None
    if r["placed"]:
        assert r["time_to_bed_min"] >= em.prm.bid_window_min + em.prm.call_min - 1e-6
    lo, hi = r["phone_range_min"]
    if lo is not None:
        assert lo <= hi
    from mahros.db.models import Bid, TransferRequest
    with eng.connect() as c:
        assert c.execute(select(func.count()).select_from(Bid)).scalar() == r["asked_count"]
        assert c.execute(select(func.count()).select_from(TransferRequest)).scalar() >= 1
    assert em.book.verify()["ok"]


def test_editing_a_logged_bid_in_the_database_is_caught(live):
    em, eng = live
    o = _small_sender(em)
    em.find_bed("AZ", o["id"], "icu")
    from mahros.db.models import Bid
    with eng.begin() as c:
        bid_id = c.execute(select(func.max(Bid.id))).scalar()
        c.execute(update(Bid).where(Bid.id == bid_id).values(travel_min=999.0))
    v = em.book.verify()
    assert not v["ok"] and v["table"] == "bids" and v["row_id"] == bid_id and v["now"] == 999.0


def test_phone_what_if_does_not_change_the_live_world(live):
    """The phone comparison runs on copies; the real (simulated) world sees only MAHROS."""
    em, _ = live
    s = em.sessions["MA"]
    o = _small_sender(em, "MA")
    before = len(s["world"].cases)
    em.find_bed("MA", o["id"], "icu")
    after = s["world"].cases
    mine = [c for c in after if c.id < 0]
    assert all(c.policy == "mahros" for c in mine) and len(after) >= before + 1
