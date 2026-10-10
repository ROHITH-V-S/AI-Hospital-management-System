"""Messages between agents. Every message is also a ledger entry."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

#: The only message kinds the platform uses, in the order they occur each week.
KINDS = ("REPORT", "VERDICT", "FORECAST", "PROPOSAL", "RESPONSE", "OUTCOME")


@dataclass
class Message:
    kind: str
    sender: str
    receiver: str
    week: str
    body: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown message kind {self.kind!r}")

    def entry(self) -> dict[str, Any]:
        return asdict(self)
