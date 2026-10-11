"""The audit ledger, stored in the database: a record book written in pen.

In plain words
--------------
Every line in the book carries a fingerprint of the line before it. Change any
old line -- even one digit -- and its fingerprint no longer matches, and every
line after it is out of step. So after a bad outcome nobody can claim "we were
never asked": the book shows the request at 10:42 and the refusal at 10:44, and
proves those lines have not been touched since.

How it works
------------
* ``ledger_entries``: one row per message. ``hash = SHA-256(content + prev_hash)``
  where content is the sequence number, time, kind, sender, receiver, the row
  it refers to, and the body. Sequence numbers have no gaps.
* ``ledger_blocks``: pages. A page groups the lines of one emergency case or
  one state-week, and stores a Merkle root of its lines and the previous
  page's hash.
* **Records cross-check.** When an operational row is written (a bid, a
  transfer, a plan line), the entry that announces it copies the row's key
  fields into ``body["record"]``. Verification re-reads the row and compares.
  So a person who edits a *bid* in pgAdmin is caught too, not only one who
  edits the log.

What it cannot do: tell whether a line was true when it was written. That is
the Data Steward's job. It only proves nothing was changed afterwards.
"""

from __future__ import annotations

import hashlib
import json
import threading
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import func, select, text, update
from sqlalchemy.engine import Engine

from ..db.models import LedgerBlock, LedgerEntry
from ..db.session import is_postgres, session_scope

GENESIS = "0" * 64
_LOCK = threading.Lock()


def _h(s: str) -> str:
    return hashlib.sha256(s.encode()).hexdigest()


def canonical(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str,
                      ensure_ascii=False)


def entry_hash(seq, block_id, recorded_at, kind, sender, receiver, ref_table, ref_id,
               body, prev_hash) -> str:
    content = canonical({"seq": seq, "block": block_id, "at": recorded_at, "kind": kind,
                         "from": sender, "to": receiver, "ref": [ref_table, ref_id],
                         "body": body})
    return _h(content + prev_hash)


def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return _h("")
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_h(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


def block_hash(block_id, label, prev_hash, merkle, first_seq, last_seq) -> str:
    return _h(canonical({"id": block_id, "label": label, "prev": prev_hash,
                         "merkle": merkle, "first": first_seq, "last": last_seq}))


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(tzinfo=None).isoformat(timespec="seconds")


def _norm(v):
    """Normalise a value for the record comparison (floats to 2 dp)."""
    if isinstance(v, float):
        return round(v, 2)
    if hasattr(v, "isoformat"):
        return v.isoformat()
    return v


#: Human names for the tables a log entry can vouch for.
TABLE_NAMES = {"bids": "bid", "transfers": "transfer", "transfer_requests": "transfer request",
               "patient_moves": "patient-move suggestion", "staff_loans": "staff loan",
               "equipment_moves": "equipment move", "equipment_inventory": "equipment count"}


class DbLedger:
    def __init__(self, engine: Engine) -> None:
        self.engine = engine

    # ------------------------------------------------------------- writing
    def open_block(self, label: str) -> int:
        with _LOCK, session_scope(self.engine) as s:
            self._serialise(s)
            last = s.execute(select(LedgerBlock).order_by(LedgerBlock.id.desc()).limit(1)).scalar()
            prev = (last.hash or GENESIS) if last else GENESIS
            b = LedgerBlock(label=label, prev_hash=prev)
            s.add(b)
            s.flush()
            return b.id

    def append(self, kind: str, sender: str, receiver: str, body: dict,
               block_id: int | None = None, recorded_at: str | None = None,
               ref: tuple[str, int] | None = None, record: dict | None = None,
               session=None) -> int:
        """Write one line. ``record`` = the referenced row's fields, copied for cross-checking."""
        body = dict(body)
        if record is not None:
            body["record"] = {k: _norm(v) for k, v in record.items()}
        body = json.loads(canonical(body))       # exactly what the database will store
        recorded_at = recorded_at or now_iso()
        ref_table, ref_id = ref if ref else (None, None)

        def _write(s):
            self._serialise(s)
            last = s.execute(select(LedgerEntry.seq, LedgerEntry.hash)
                             .order_by(LedgerEntry.seq.desc()).limit(1)).first()
            seq = (last[0] + 1) if last else 1
            prev = last[1] if last else GENESIS
            h = entry_hash(seq, block_id, recorded_at, kind, sender, receiver,
                           ref_table, ref_id, body, prev)
            s.add(LedgerEntry(seq=seq, block_id=block_id, recorded_at=recorded_at, kind=kind,
                              sender=sender, receiver=receiver, ref_table=ref_table,
                              ref_id=ref_id, body=body, prev_hash=prev, hash=h))
            s.flush()
            return seq

        with _LOCK:
            if session is not None:
                return _write(session)
            with session_scope(self.engine) as s:
                return _write(s)

    def append_many(self, rows: list[dict], block_id: int | None) -> list[int]:
        """Write several lines in one transaction (a weekly cycle has hundreds)."""
        out = []
        with _LOCK, session_scope(self.engine) as s:
            self._serialise(s)
            last = s.execute(select(LedgerEntry.seq, LedgerEntry.hash)
                             .order_by(LedgerEntry.seq.desc()).limit(1)).first()
            seq = last[0] if last else 0
            prev = last[1] if last else GENESIS
            objs = []
            for r in rows:
                seq += 1
                body = dict(r["body"])
                if r.get("record") is not None:
                    body["record"] = {k: _norm(v) for k, v in r["record"].items()}
                body = json.loads(canonical(body))
                at = r.get("recorded_at") or now_iso()
                ref_table, ref_id = r.get("ref") or (None, None)
                h = entry_hash(seq, block_id, at, r["kind"], r["sender"], r["receiver"],
                               ref_table, ref_id, body, prev)
                objs.append(LedgerEntry(seq=seq, block_id=block_id, recorded_at=at,
                                        kind=r["kind"], sender=r["sender"],
                                        receiver=r["receiver"], ref_table=ref_table,
                                        ref_id=ref_id, body=body, prev_hash=prev, hash=h))
                prev = h
                out.append(seq)
            s.add_all(objs)
        return out

    def seal_block(self, block_id: int) -> dict:
        with _LOCK, session_scope(self.engine) as s:
            self._serialise(s)
            b = s.get(LedgerBlock, block_id)
            rows = s.execute(select(LedgerEntry.seq, LedgerEntry.hash)
                             .where(LedgerEntry.block_id == block_id)
                             .order_by(LedgerEntry.seq)).all()
            b.first_seq = rows[0][0] if rows else None
            b.last_seq = rows[-1][0] if rows else None
            b.merkle = merkle_root([r[1] for r in rows])
            b.hash = block_hash(b.id, b.label, b.prev_hash, b.merkle, b.first_seq, b.last_seq)
            b.sealed_at = datetime.now(timezone.utc).replace(tzinfo=None)
            return {"id": b.id, "label": b.label, "hash": b.hash, "entries": len(rows),
                    "first_seq": b.first_seq, "last_seq": b.last_seq}

    def _serialise(self, s) -> None:
        """Only one writer at a time, even across processes (Postgres advisory lock)."""
        if is_postgres(self.engine):
            s.execute(text("SELECT pg_advisory_xact_lock(424242)"))

    # ------------------------------------------------------------- reading
    def summary(self) -> dict:
        with session_scope(self.engine) as s:
            n = s.execute(select(func.count()).select_from(LedgerEntry)).scalar() or 0
            nb = s.execute(select(func.count()).select_from(LedgerBlock)).scalar() or 0
            last = s.execute(select(LedgerEntry).order_by(LedgerEntry.seq.desc()).limit(1)).scalar()
            return {"entries": n, "blocks": nb, "head": last.hash if last else GENESIS,
                    "last_at": last.recorded_at if last else None}

    def recent(self, limit: int = 30, block_id: int | None = None) -> list[dict]:
        with session_scope(self.engine) as s:
            q = select(LedgerEntry).order_by(LedgerEntry.seq.desc()).limit(limit)
            if block_id is not None:
                q = (select(LedgerEntry).where(LedgerEntry.block_id == block_id)
                     .order_by(LedgerEntry.seq))
            return [self._row(e) for e in s.execute(q).scalars()]

    def blocks(self, limit: int = 20) -> list[dict]:
        with session_scope(self.engine) as s:
            q = select(LedgerBlock).order_by(LedgerBlock.id.desc()).limit(limit)
            return [{"id": b.id, "label": b.label, "hash": b.hash, "first_seq": b.first_seq,
                     "last_seq": b.last_seq, "sealed": b.hash is not None}
                    for b in s.execute(q).scalars()]

    @staticmethod
    def _row(e: LedgerEntry) -> dict:
        return {"seq": e.seq, "block_id": e.block_id, "recorded_at": e.recorded_at,
                "kind": e.kind, "sender": e.sender, "receiver": e.receiver,
                "ref_table": e.ref_table, "ref_id": e.ref_id, "body": e.body,
                "hash": e.hash, "prev_hash": e.prev_hash}

    # ------------------------------------------------------------- checking
    def verify(self) -> dict:
        """Recompute every fingerprint and re-check every referenced record.

        Returns ``ok`` and, if not, the FIRST problem found in book order with
        a plain sentence saying what no longer matches.
        """
        from ..db import models as M
        tables = {"bids": M.Bid, "transfers": M.Transfer, "transfer_requests": M.TransferRequest,
                  "patient_moves": M.PatientMove, "staff_loans": M.StaffLoan,
                  "equipment_moves": M.EquipmentMove, "equipment_inventory": M.EquipmentItem}
        problems: list[dict] = []
        with session_scope(self.engine) as s:
            prev, expect_seq, n = GENESIS, 1, 0
            hashes_by_block: dict[int, list[str]] = {}
            refs: list[tuple[LedgerEntry, dict]] = []
            for e in s.execute(select(LedgerEntry).order_by(LedgerEntry.seq)).scalars():
                n += 1
                if e.seq != expect_seq and not problems:
                    problems.append(self._problem("missing", expect_seq, None,
                                    f"Line #{expect_seq} of the record book is missing — "
                                    f"someone deleted it."))
                expect_seq = e.seq + 1
                h = entry_hash(e.seq, e.block_id, e.recorded_at, e.kind, e.sender, e.receiver,
                               e.ref_table, e.ref_id, e.body, e.prev_hash)
                if e.prev_hash != prev and not problems:
                    problems.append(self._problem("chain", e.seq, e,
                                    f"Line #{e.seq} no longer follows the line before it — "
                                    f"a line was inserted or removed just before it."))
                if h != e.hash and not problems:
                    problems.append(self._problem("entry", e.seq, e,
                                    f"Line #{e.seq} ({e.kind}, written {e.recorded_at}) was "
                                    f"changed after it was written: it no longer matches its "
                                    f"fingerprint."))
                prev = e.hash
                if e.block_id is not None:
                    hashes_by_block.setdefault(e.block_id, []).append(e.hash)
                rec = (e.body or {}).get("record") if isinstance(e.body, dict) else None
                if e.ref_table and e.ref_id is not None and rec:
                    refs.append((e, rec))
            # Records: does the operational row still say what the log says?
            for e, rec in refs:
                if problems:
                    break
                model = tables.get(e.ref_table)
                row = s.get(model, e.ref_id) if model else None
                what = TABLE_NAMES.get(e.ref_table, e.ref_table)
                if row is None:
                    problems.append(self._problem("record", e.seq, e,
                                    f"The {what} #{e.ref_id} written in line #{e.seq} "
                                    f"({e.recorded_at}) has been deleted from the database."))
                    break
                for k, logged in rec.items():
                    now = _norm(getattr(row, k, None))
                    if not _same(now, logged):
                        p = self._problem("record", e.seq, e,
                                          f"The {what} #{e.ref_id} was changed in the database: "
                                          f"'{k}' now says {now!r}, but the record book wrote "
                                          f"{logged!r} at {e.recorded_at} (line #{e.seq}).")
                        p.update({"table": e.ref_table, "row_id": e.ref_id, "field": k,
                                  "logged": logged, "now": now})
                        problems.append(p)
                        break
            # Pages.
            if not problems:
                bprev = GENESIS
                for b in s.execute(select(LedgerBlock).order_by(LedgerBlock.id)).scalars():
                    if b.hash is None:
                        continue                       # still being written
                    m = merkle_root(hashes_by_block.get(b.id, []))
                    bh = block_hash(b.id, b.label, b.prev_hash, m, b.first_seq, b.last_seq)
                    if m != b.merkle or bh != b.hash or b.prev_hash != bprev:
                        problems.append({"kind": "block", "seq": b.first_seq, "block": b.id,
                                         "message": f"Page {b.id} ({b.label}) no longer matches "
                                                    f"its seal."})
                        break
                    bprev = b.hash
        if problems:
            return {"ok": False, "entries": n, **problems[0]}
        return {"ok": True, "entries": n, "head": prev,
                "message": f"All {n:,} lines match their fingerprints, and every bid, transfer "
                           f"and plan in the database still says what the book recorded."}

    @staticmethod
    def _problem(kind, seq, e, message) -> dict:
        out = {"kind": kind, "seq": seq, "message": message}
        if e is not None:
            out.update({"recorded_at": e.recorded_at, "entry_kind": e.kind, "sender": e.sender,
                        "block": e.block_id})
        return out

    # ------------------------------------------------------------- demo
    def tamper_demo(self) -> dict:
        """One-click demo: quietly change one logged bid's travel time in the DATABASE ROW.

        Exactly what a person could do by hand in pgAdmin. Returns what was
        changed so the page can say it, and so ``undo_tamper`` can put it back.
        """
        from ..db.models import Bid
        with session_scope(self.engine) as s:
            b = s.execute(select(Bid).where(Bid.answer == "BID", Bid.ledger_seq.is_not(None))
                          .order_by(Bid.id.desc()).limit(1)).scalar()
            if b is None:
                raise ValueError("No bid in the record book yet — find a bed first.")
            before = b.travel_min
            after = round((before or 0) + 25.0, 2)
            s.execute(update(Bid).where(Bid.id == b.id).values(travel_min=after))
            return {"table": "bids", "row_id": b.id, "field": "travel_min",
                    "before": before, "after": after, "hospital_pk": b.hospital_pk}

    def undo_tamper(self, t: dict) -> None:
        from ..db.models import Bid
        with session_scope(self.engine) as s:
            s.execute(update(Bid).where(Bid.id == t["row_id"]).values(**{t["field"]: t["before"]}))


def _same(a, b) -> bool:
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool):
        return abs(float(a) - float(b)) < 1e-6
    return a == b
