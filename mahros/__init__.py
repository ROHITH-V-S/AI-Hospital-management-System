"""MAHROS -- Multi-Agent Hospital Resource Optimization System.

A government-side coordination platform, built and evaluated on real federal
hospital capacity reports (HHS, 5,172 US hospitals, 2020-2024). Four kinds of
agent work together each week:

* Hospital agents report their numbers and decide whether to accept proposals.
* A Data Steward agent decides which reports can be trusted, and says why.
* A Forecast agent predicts next week's occupancy with a 90% range.
* A Regional Coordinator agent per state proposes patient load balancing.

Every message is written to a tamper-evident audit ledger.
"""

__version__ = "0.2.0"
