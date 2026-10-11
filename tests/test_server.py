"""Dashboard server: file serving is locked down; the ledger demo behaves."""

import json

import pytest

fastapi = pytest.importorskip("fastapi")
from fastapi.testclient import TestClient  # noqa: E402

from mahros.ledger.chain import AuditLedger  # noqa: E402
from mahros.server import app as server  # noqa: E402


@pytest.fixture()
def client(tmp_path, monkeypatch):
    led = AuditLedger()
    blocks = []
    for w in range(5):
        entries = [{"kind": "REPORT", "sender": f"hospital:H{i}", "receiver": "steward",
                    "week": f"2023-01-{w + 1:02d}", "body": {"used": 50.0 + i, "beds": 100}}
                   for i in range(3)]
        for e in entries:
            led.append(e)
        b = led.seal(f"TX 2023-01-{w + 1:02d}")
        blocks.append({"label": b.label, "entries": entries})
    (tmp_path / "ledger_entries.json").write_text(json.dumps(blocks))
    (tmp_path / "index.json").write_text(json.dumps(
        {"ledger": {"blocks": [{"hash": led.head}]}}))
    (tmp_path / "rq1_trust_audit.json").write_text("{}")
    monkeypatch.setattr(server, "UI", tmp_path)
    server.LEDGER.__init__()
    return TestClient(server.app)


def test_index_and_health(client):
    assert client.get("/").status_code == 200
    assert client.get("/healthz").json()["ok"] is True


def test_serves_only_plain_json_names(client):
    assert client.get("/ui/rq1_trust_audit.json").status_code == 200
    for bad in ("..%2F..%2Fpyproject.toml", "rq1.txt", "a b.json", "missing.json"):
        assert client.get(f"/ui/{bad}").status_code == 404


def test_rebuilt_chain_matches_published_head(client):
    d = client.get("/api/ledger").json()
    assert d["verify"]["ok"] and d["rebuilt_matches_published"]


def test_tamper_is_detected_at_the_right_block_and_reset_restores(client):
    d = client.post("/api/ledger/tamper?block=3").json()
    assert not d["verify"]["ok"]
    assert d["verify"]["first_bad_block"] == 3
    assert d["tampered"]["before"] != d["tampered"]["after"]
    d = client.post("/api/ledger/reset").json()
    assert d["verify"]["ok"] and d["rebuilt_matches_published"]


# --------------------------------------------------------------------------- #
# Record book (database audit ledger) endpoints
# --------------------------------------------------------------------------- #

@pytest.fixture()
def book_client(tmp_path, monkeypatch):
    from sqlalchemy import create_engine
    from mahros.db.models import Base, Hospital
    from mahros.ledger.store import DbLedger
    from tests.test_db_ledger import _case
    eng = create_engine(f"sqlite:///{tmp_path / 'b.sqlite'}", future=True)
    Base.metadata.create_all(eng)
    with eng.begin() as c:
        c.execute(Hospital.__table__.insert(), [
            {"hospital_pk": h, "name": h, "state": "AZ", "source": "t", "provenance": "observed"}
            for h in ("A", "B")])
    book = DbLedger(eng)
    _case(eng, book)
    monkeypatch.setattr(server, "DB", eng)
    monkeypatch.setattr(server, "BOOK", book)
    monkeypatch.setattr(server, "DB_ERROR", None)
    server.TAMPER.clear()
    return TestClient(server.app), eng


def test_book_status_and_verify(book_client):
    c, _ = book_client
    d = c.get("/api/book").json()
    assert d["verify"]["ok"] and d["summary"]["entries"] == 3 and len(d["recent"]) == 3


def test_book_one_click_tamper_names_the_bid_and_undo_restores(book_client):
    c, _ = book_client
    d = c.post("/api/book/tamper").json()
    assert not d["verify"]["ok"] and d["verify"]["table"] == "bids"
    assert d["tampered"]["before"] == 14.0 and d["tampered"]["after"] == 39.0
    assert c.post("/api/book/undo").json()["verify"]["ok"]


def test_book_detects_a_hand_edit_like_pgadmin(book_client):
    from sqlalchemy import update
    from mahros.db.models import Bid
    c, eng = book_client
    with eng.begin() as conn:
        conn.execute(update(Bid).values(reason="no beds"))
    v = c.post("/api/book/verify").json()
    assert not v["ok"] and v["field"] == "reason" and v["now"] == "no beds"
