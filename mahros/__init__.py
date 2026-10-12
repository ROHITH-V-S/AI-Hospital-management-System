"""MAHROS -- Multi-Agent Hospital Resource Optimization System.

A working prototype of a state hospital-coordination service, built and
evaluated on real federal hospital reports (HHS, 5,172 US hospitals,
2020-2024):

* Emergency transfer: hospital agents with private state answer a parallel
  call-for-bids; a Data Steward checks bids; a coordinator picks the best bed
  (minute-level dynamics simulated, grounded in real data).
* Weekly: Data Steward verdicts, forecasts, a regional plan for patients,
  nurses and equipment; surge early warning.
* Every message is written to a hash-chained record book in PostgreSQL.
"""

__version__ = "0.3.0"
