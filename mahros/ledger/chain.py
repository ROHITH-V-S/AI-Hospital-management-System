"""Tamper-evident audit log: every report, verdict, forecast and plan, in pen.

A *permissioned* append-only hash chain held by the coordinating authority and
checkable by any participant. Deliberately not a blockchain: there is no
mining, no token and no public network. What the platform needs is narrower,
and this provides exactly it:

* **Append-only.** Entries are grouped into blocks; each block stores the hash
  of the previous block, so editing any past entry changes every later hash.
* **Independently verifiable.** :meth:`AuditLedger.verify` recomputes the chain
  from scratch and names the first block that no longer matches.
* **Deterministic.** Hashes depend only on content and the reporting week, not
  on wall-clock time, so the same inputs always produce the same chain and a
  reviewer can regenerate it bit for bit.

What it does **not** do: it cannot tell whether an entry was true when written.
That is the Data Steward's job. The ledger only guarantees that what was
written, and what was decided because of it, cannot be quietly changed later.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from typing import Any


def _h(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()


def canonical_json(obj: Any) -> str:
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), default=str)


def merkle_root(leaves: list[str]) -> str:
    if not leaves:
        return _h("")
    level = list(leaves)
    while len(level) > 1:
        if len(level) % 2:
            level.append(level[-1])
        level = [_h(level[i] + level[i + 1]) for i in range(0, len(level), 2)]
    return level[0]


@dataclass
class Block:
    index: int
    label: str                       # e.g. "2023-01-08" -- the reporting week
    prev_hash: str
    entries: list[dict[str, Any]] = field(default_factory=list)
    merkle: str = ""
    hash: str = ""

    def leaf_hashes(self) -> list[str]:
        return [_h(canonical_json(e)) for e in self.entries]

    def compute_hash(self) -> str:
        return _h(canonical_json({"index": self.index, "label": self.label,
                                  "prev": self.prev_hash, "merkle": self.merkle,
                                  "n": len(self.entries)}))

    def seal(self) -> None:
        self.merkle = merkle_root(self.leaf_hashes())
        self.hash = self.compute_hash()


GENESIS = "0" * 64


class AuditLedger:
    """Append entries, seal them into a block per reporting week, verify any time."""

    def __init__(self) -> None:
        self.blocks: list[Block] = []
        self._pending: list[dict[str, Any]] = []

    def append(self, entry: dict[str, Any]) -> str:
        """Add one entry. Returns its content hash (its receipt)."""
        self._pending.append(dict(entry))
        return _h(canonical_json(entry))

    def seal(self, label: str) -> Block:
        prev = self.blocks[-1].hash if self.blocks else GENESIS
        block = Block(index=len(self.blocks), label=label, prev_hash=prev,
                      entries=self._pending)
        block.seal()
        self.blocks.append(block)
        self._pending = []
        return block

    @property
    def head(self) -> str:
        return self.blocks[-1].hash if self.blocks else GENESIS

    def verify(self) -> dict[str, Any]:
        """Recompute everything. ``ok`` is False at the first block that disagrees."""
        prev = GENESIS
        for b in self.blocks:
            merkle = merkle_root(b.leaf_hashes())
            expect = Block(b.index, b.label, prev, b.entries, merkle).compute_hash()
            if b.prev_hash != prev or merkle != b.merkle or expect != b.hash:
                return {"ok": False, "first_bad_block": b.index, "label": b.label,
                        "blocks": len(self.blocks)}
            prev = b.hash
        return {"ok": True, "first_bad_block": None, "blocks": len(self.blocks),
                "entries": sum(len(b.entries) for b in self.blocks), "head": prev}

    def entries(self, kind: str | None = None):
        for b in self.blocks:
            for e in b.entries:
                if kind is None or e.get("kind") == kind:
                    yield b.label, e
