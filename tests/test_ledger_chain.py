"""Audit ledger: append-only, tamper-evident, deterministic."""

from mahros.ledger.chain import AuditLedger


def build():
    led = AuditLedger()
    for w in ("2023-01-01", "2023-01-08", "2023-01-15"):
        led.append({"kind": "report", "hospital": "A", "week": w, "used": 50})
        led.append({"kind": "plan", "from": "A", "to": "B", "week": w, "amount": 2.5})
        led.seal(w)
    return led


def test_clean_chain_verifies():
    v = build().verify()
    assert v["ok"] and v["blocks"] == 3 and v["entries"] == 6


def test_editing_a_past_entry_is_detected_at_that_block():
    led = build()
    led.blocks[1].entries[0]["used"] = 5          # quietly rewrite history
    v = led.verify()
    assert not v["ok"] and v["first_bad_block"] == 1


def test_deleting_an_entry_is_detected():
    led = build()
    led.blocks[0].entries.pop()
    assert led.verify()["first_bad_block"] == 0


def test_rehashing_one_block_still_breaks_the_next_link():
    led = build()
    b = led.blocks[1]
    b.entries[0]["used"] = 5
    b.seal()                                       # attacker recomputes that block
    v = led.verify()
    assert not v["ok"] and v["first_bad_block"] == 2


def test_deterministic():
    assert build().head == build().head


def test_filter_by_kind():
    assert len(list(build().entries("plan"))) == 3
