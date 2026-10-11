"""The database audit ledger: edits to the log OR to a logged record are caught and named.

Runs on a temporary SQLite database (no server needed), and ALSO on a
throwaway PostgreSQL database when MAHROS_TEST_PG_URL is set (Docker).
"""

import os

import pytest
from sqlalchemy import create_engine, delete, text, update

from mahros.db.models import Base, Bid, Hospital, LedgerEntry, TransferRequest
from mahros.ledger.store import DbLedger


PG = os.environ.get("MAHROS_TEST_PG_URL")   # e.g. postgresql+psycopg://mahros:mahros-local@localhost:5432/postgres


def _pg_engine():
    """A throwaway database on the Docker PostgreSQL server."""
    admin = create_engine(PG, isolation_level="AUTOCOMMIT", future=True)
    with admin.connect() as c:
        c.execute(text("DROP DATABASE IF EXISTS mahros_test WITH (FORCE)"))
        c.execute(text("CREATE DATABASE mahros_test"))
    admin.dispose()
    return create_engine(PG.rsplit("/", 1)[0] + "/mahros_test", future=True)


@pytest.fixture(params=["sqlite", "postgres"])
def engine(request, tmp_path):
    if request.param == "postgres":
        if not PG:
            pytest.skip("set MAHROS_TEST_PG_URL to run on PostgreSQL")
        eng = _pg_engine()
    else:
        eng = create_engine(f"sqlite:///{tmp_path / 't.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(Hospital.__table__.insert(), [
            {"hospital_pk": "A", "name": "Alpha", "state": "AZ", "source": "test", "provenance": "observed"},
            {"hospital_pk": "B", "name": "Beta", "state": "AZ", "source": "test", "provenance": "observed"}])
    return eng


def _case(engine, led):
    """One emergency case: request, one bid, award -- each row cross-referenced in the log."""
    from mahros.db.session import session_scope
    blk = led.open_block("AZ case 1")
    with session_scope(engine) as s:
        r = TransferRequest(state="AZ", origin_pk="A", need="icu", acuity="critical",
                            window_min=240, sim_week=__import__("datetime").date(2023, 1, 1),
                            sim_time="2023-01-02T10:42:00", status="placed")
        s.add(r)
        s.flush()
        led.append("REQUEST", "hospital:A", "coordinator", {"need": "icu"}, block_id=blk,
                   recorded_at="2023-01-02T10:42:00", ref=("transfer_requests", r.id),
                   record={"origin_pk": "A", "need": "icu"}, session=s)
        b = Bid(request_id=r.id, hospital_pk="B", answer="BID", travel_min=14.0,
                ready_min=10.0, reason="ICU bed free")
        s.add(b)
        s.flush()
        b.ledger_seq = led.append("BID", "hospital:B", "coordinator", {"travel_min": 14.0},
                                  block_id=blk, recorded_at="2023-01-02T10:42:20",
                                  ref=("bids", b.id),
                                  record={"hospital_pk": "B", "answer": "BID",
                                          "travel_min": 14.0, "ready_min": 10.0,
                                          "reason": "ICU bed free"}, session=s)
    led.append("AWARD", "coordinator", "hospital:B", {"to": "B"}, block_id=blk,
               recorded_at="2023-01-02T10:44:00")
    led.seal_block(blk)
    return blk


def test_clean_book_verifies(engine):
    led = DbLedger(engine)
    _case(engine, led)
    _case(engine, led)
    v = led.verify()
    assert v["ok"], v
    assert v["entries"] == 6


def test_editing_a_bid_row_is_caught_and_named(engine):
    """What a reviewer does in pgAdmin: change a hospital's bid."""
    led = DbLedger(engine)
    _case(engine, led)
    with engine.begin() as c:
        c.execute(update(Bid).values(travel_min=40.0))
    v = led.verify()
    assert not v["ok"]
    assert v["kind"] == "record" and v["table"] == "bids" and v["field"] == "travel_min"
    assert v["logged"] == 14.0 and v["now"] == 40.0
    assert "10:42:20" in v["message"]


def test_editing_a_log_line_is_caught_at_that_line(engine):
    led = DbLedger(engine)
    _case(engine, led)
    _case(engine, led)
    with engine.begin() as c:
        c.execute(update(LedgerEntry).where(LedgerEntry.seq == 5)
                  .values(body={"travel_min": 1.0}))
    v = led.verify()
    assert not v["ok"] and v["kind"] == "entry" and v["seq"] == 5


def test_deleting_a_line_is_caught(engine):
    led = DbLedger(engine)
    _case(engine, led)
    with engine.begin() as c:
        c.execute(delete(LedgerEntry).where(LedgerEntry.seq == 2))
    v = led.verify()
    assert not v["ok"] and v["seq"] == 2


def test_one_click_demo_and_undo(engine):
    led = DbLedger(engine)
    _case(engine, led)
    t = led.tamper_demo()
    v = led.verify()
    assert not v["ok"] and v["field"] == "travel_min"
    led.undo_tamper(t)
    assert led.verify()["ok"]


def test_append_many_chains_onto_existing_lines(engine):
    led = DbLedger(engine)
    _case(engine, led)
    blk = led.open_block("AZ 2023-01-01")
    seqs = led.append_many([{"kind": "REPORT", "sender": f"hospital:{i}", "receiver": "steward",
                             "body": {"used": i}} for i in range(50)], blk)
    led.seal_block(blk)
    assert seqs == list(range(4, 54))
    assert led.verify()["ok"]
