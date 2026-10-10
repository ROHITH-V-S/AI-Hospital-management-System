"""DataStewardAgent: decides which reports can be believed, and says why.

The rules (``mahros.trust``) are causal -- a verdict for week t uses only
weeks up to t -- so running them once over the whole history gives exactly the
verdicts the agent would have issued live, week by week. A test pins this.
"""

from __future__ import annotations

import pandas as pd

from ..trust import assess, explain
from .messages import Message


class DataStewardAgent:
    address = "steward"

    def __init__(self, reports: pd.DataFrame) -> None:
        verdicts = assess(reports)
        self._v = reports[["hospital_pk", "week"]].join(verdicts).set_index(
            ["hospital_pk", "week"])

    def verdict(self, hospital_id: str, week: pd.Timestamp) -> tuple[str, int]:
        try:
            row = self._v.loc[(hospital_id, week)]
        except KeyError:
            return "MISSING", 0
        return str(row["level"]), int(row["flags"])

    def judge(self, hospital_id: str, week: pd.Timestamp) -> Message:
        level, flags = self.verdict(hospital_id, week)
        return Message("VERDICT", self.address, "coordinator", str(week.date()),
                       {"hospital": hospital_id, "level": level,
                        "reasons": [r["title"] for r in explain(flags)]})
