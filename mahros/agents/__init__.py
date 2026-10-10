"""The multi-agent layer of MAHROS.

Four kinds of agent, each owning one responsibility and talking to the others
only through messages that are written to the audit ledger:

=========================== ===================================================
HospitalAgent (one each)    Submits its weekly report. Checks any proposal
                            against its own real situation before accepting.
DataStewardAgent            Judges every report GREEN / AMBER / RED / MISSING
                            and says why.
ForecastAgent               Predicts next week's occupancy, with a 90% range.
RegionalCoordinatorAgent    One per state. Proposes transfers. Cannot force
(one per state)             any hospital to accept.
=========================== ===================================================

Why agents and not one program: authority is split the way it is split in
real life. The state coordinator plans but cannot see inside a hospital this
week; the hospital knows its own situation but not the region's. A proposal
only becomes a transfer when both sides agree, and every step is on the record.
"""

from .messages import Message
from .hospital import HospitalAgent
from .steward import DataStewardAgent
from .forecaster import ForecastAgent
from .coordinator import RegionalCoordinatorAgent
from .platform import Platform

__all__ = ["Message", "HospitalAgent", "DataStewardAgent", "ForecastAgent",
           "RegionalCoordinatorAgent", "Platform"]
