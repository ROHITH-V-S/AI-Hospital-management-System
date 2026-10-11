"""The MAHROS database schema.

Every row says where it came from:

* ``source``      the dataset, script or person that produced it
* ``provenance``  one of PROVENANCE:

  ========== ================================================================
  observed   read from an official dataset (HHS, CMS, OSRM)
  derived    computed from observed values by a stated rule or model
  estimated  a per-hospital figure that no public dataset reports, built from
             observed values and a published ratio (staff pools)
  simulated  produced by the emergency simulation (grounded in real data)
  entered    typed in by a person (equipment inventory)
  ========== ================================================================

The dashboard shows these labels next to the numbers.
"""

from __future__ import annotations

from datetime import date, datetime

from sqlalchemy import (JSON, Boolean, CheckConstraint, Date, DateTime, Float,
                        ForeignKey, Index, Integer, String, Text, UniqueConstraint)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

PROVENANCE = ("observed", "derived", "estimated", "simulated", "entered")

JSONType = JSON().with_variant(JSONB(), "postgresql")


class Base(DeclarativeBase):
    pass


def _prov(default: str):
    return mapped_column(String(10), default=default, nullable=False)


def _prov_check(table: str):
    return CheckConstraint(
        "provenance IN (" + ",".join(f"'{p}'" for p in PROVENANCE) + ")",
        name=f"ck_{table}_provenance")


# --------------------------------------------------------------------------- #
# Real data
# --------------------------------------------------------------------------- #

class Hospital(Base):
    __tablename__ = "hospitals"
    __table_args__ = (_prov_check("hospitals"),)
    hospital_pk: Mapped[str] = mapped_column(String(80), primary_key=True)
    ccn: Mapped[str | None] = mapped_column(String(20))
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(4), index=True)
    zip: Mapped[str | None] = mapped_column(String(12))
    subtype: Mapped[str | None] = mapped_column(String(40))
    fips: Mapped[str | None] = mapped_column(String(8))
    metro: Mapped[bool | None] = mapped_column(Boolean)
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    #: CMS Provider of Services capability (observed where present, NULL otherwise).
    capability: Mapped[dict | None] = mapped_column(JSONType)
    capability_source: Mapped[str | None] = mapped_column(String(120))
    source: Mapped[str] = mapped_column(String(120), default="HHS anag-cw7u")
    provenance: Mapped[str] = _prov("observed")


class WeeklyReport(Base):
    __tablename__ = "weekly_reports"
    __table_args__ = (UniqueConstraint("hospital_pk", "week", name="uq_report_hospital_week"),
                      Index("ix_report_week", "week"), _prov_check("weekly_reports"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    week: Mapped[date] = mapped_column(Date)
    # As written in THAT week's report (2 hospitals changed name/location over
    # time; keeping them per row makes the platform reproduce the experiments exactly).
    name: Mapped[str | None] = mapped_column(String(200))
    city: Mapped[str | None] = mapped_column(String(100))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    metro: Mapped[bool | None] = mapped_column(Boolean)
    beds: Mapped[float | None] = mapped_column(Float)
    used: Mapped[float | None] = mapped_column(Float)
    icu_beds: Mapped[float | None] = mapped_column(Float)
    icu_used: Mapped[float | None] = mapped_column(Float)
    beds_sum: Mapped[float | None] = mapped_column(Float)
    used_sum: Mapped[float | None] = mapped_column(Float)
    icu_beds_sum: Mapped[float | None] = mapped_column(Float)
    icu_used_sum: Mapped[float | None] = mapped_column(Float)
    beds_cov: Mapped[float | None] = mapped_column(Float)
    used_cov: Mapped[float | None] = mapped_column(Float)
    icu_beds_cov: Mapped[float | None] = mapped_column(Float)
    icu_used_cov: Mapped[float | None] = mapped_column(Float)
    total_beds: Mapped[float | None] = mapped_column(Float)
    covid_used: Mapped[float | None] = mapped_column(Float)
    beds_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    used_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    icu_beds_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    icu_used_suppressed: Mapped[bool] = mapped_column(Boolean, default=False)
    n_suppressed: Mapped[int] = mapped_column(Integer, default=0)
    is_corrected: Mapped[bool] = mapped_column(Boolean, default=False)
    # v0.3 extra fields (same dataset).
    ed_visits: Mapped[float | None] = mapped_column(Float)          # 7-day sum
    covid_ed_visits: Mapped[float | None] = mapped_column(Float)    # 7-day sum
    covid_adm_adult: Mapped[float | None] = mapped_column(Float)    # 7-day sum
    covid_adm_peds: Mapped[float | None] = mapped_column(Float)     # 7-day sum
    flu_adm: Mapped[float | None] = mapped_column(Float)            # 7-day sum
    flu_used: Mapped[float | None] = mapped_column(Float)           # 7-day avg
    flu_icu: Mapped[float | None] = mapped_column(Float)            # 7-day avg
    covid_icu: Mapped[float | None] = mapped_column(Float)          # 7-day avg
    picu_beds: Mapped[float | None] = mapped_column(Float)          # 7-day avg
    picu_used: Mapped[float | None] = mapped_column(Float)          # 7-day avg
    source: Mapped[str] = mapped_column(String(120), default="HHS anag-cw7u")
    provenance: Mapped[str] = _prov("observed")


class TrustVerdict(Base):
    __tablename__ = "trust_verdicts"
    __table_args__ = (UniqueConstraint("hospital_pk", "week", name="uq_verdict_hospital_week"),
                      Index("ix_verdict_week_level", "week", "level"), _prov_check("trust_verdicts"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    week: Mapped[date] = mapped_column(Date)
    level: Mapped[str] = mapped_column(String(8))
    flags: Mapped[int] = mapped_column(Integer, default=0)
    reasons: Mapped[str | None] = mapped_column(String(300))       # rule codes, comma-separated
    census_run: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.trust.checks")
    provenance: Mapped[str] = _prov("derived")


class Forecast(Base):
    __tablename__ = "forecasts"
    __table_args__ = (UniqueConstraint("hospital_pk", "week", name="uq_forecast_hospital_week"),
                      Index("ix_forecast_week", "week"), _prov_check("forecasts"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    week: Mapped[date] = mapped_column(Date)            # week the forecast is made
    target_week: Mapped[date] = mapped_column(Date)
    ml_pred: Mapped[float | None] = mapped_column(Float)
    ml_hi: Mapped[float | None] = mapped_column(Float)
    raw_pred: Mapped[float | None] = mapped_column(Float)
    raw_hi: Mapped[float | None] = mapped_column(Float)
    persist_pred: Mapped[float | None] = mapped_column(Float)
    persist_hi: Mapped[float | None] = mapped_column(Float)
    beds_0: Mapped[float | None] = mapped_column(Float)
    occ_0: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(120), default="experiments/rq2_forecast.py")
    provenance: Mapped[str] = _prov("derived")


class StateStaffing(Base):
    """Real state-level counts of hospitals reporting a critical staffing shortage."""
    __tablename__ = "state_staffing"
    __table_args__ = (UniqueConstraint("state", "date", name="uq_staffing_state_date"),
                      _prov_check("state_staffing"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(4))
    date: Mapped[date] = mapped_column(Date)
    shortage_today_yes: Mapped[float | None] = mapped_column(Float)
    shortage_today_no: Mapped[float | None] = mapped_column(Float)
    shortage_today_not_reported: Mapped[float | None] = mapped_column(Float)
    shortage_week_yes: Mapped[float | None] = mapped_column(Float)
    shortage_week_no: Mapped[float | None] = mapped_column(Float)
    shortage_week_not_reported: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(120), default="HHS g62h-syeh")
    provenance: Mapped[str] = _prov("observed")


class DataManifest(Base):
    __tablename__ = "data_manifest"
    key: Mapped[str] = mapped_column(String(40), primary_key=True)
    title: Mapped[str] = mapped_column(String(300))
    url: Mapped[str | None] = mapped_column(String(300))
    rows: Mapped[int | None] = mapped_column(Integer)
    sha256: Mapped[str | None] = mapped_column(String(64))
    fetched_at: Mapped[str | None] = mapped_column(String(40))
    loaded_at: Mapped[datetime] = mapped_column(DateTime)
    note: Mapped[str | None] = mapped_column(Text)


# --------------------------------------------------------------------------- #
# Surge early warning
# --------------------------------------------------------------------------- #

class SurgeSignal(Base):
    """Neighbourhood signals around one hospital for one week (all derived)."""
    __tablename__ = "surge_signals"
    __table_args__ = (UniqueConstraint("hospital_pk", "week", name="uq_signal_hospital_week"),
                      Index("ix_signal_week", "week"), _prov_check("surge_signals"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    week: Mapped[date] = mapped_column(Date)
    state: Mapped[str | None] = mapped_column(String(4))
    n_neighbours: Mapped[int | None] = mapped_column(Integer)
    area_occ: Mapped[float | None] = mapped_column(Float)
    area_occ_d1: Mapped[float | None] = mapped_column(Float)
    area_occ_d2: Mapped[float | None] = mapped_column(Float)
    area_ed_growth: Mapped[float | None] = mapped_column(Float)
    area_covid_adm_growth: Mapped[float | None] = mapped_column(Float)
    area_flu_adm_growth: Mapped[float | None] = mapped_column(Float)
    rising_neighbours: Mapped[int | None] = mapped_column(Integer)
    probability: Mapped[float | None] = mapped_column(Float)
    source: Mapped[str] = mapped_column(String(120), default="mahros.surge")
    provenance: Mapped[str] = _prov("derived")


class SurgeAlert(Base):
    __tablename__ = "surge_alerts"
    __table_args__ = (Index("ix_alert_state_week", "state", "week"), _prov_check("surge_alerts"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    state: Mapped[str] = mapped_column(String(4))
    week: Mapped[date] = mapped_column(Date)
    rule: Mapped[str] = mapped_column(String(20))           # model | neighbours
    probability: Mapped[float | None] = mapped_column(Float)
    message: Mapped[str] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(120), default="mahros.surge")
    provenance: Mapped[str] = _prov("derived")


# --------------------------------------------------------------------------- #
# Emergency transfers (simulation grounded in real data)
# --------------------------------------------------------------------------- #

class TransferRequest(Base):
    __tablename__ = "transfer_requests"
    __table_args__ = (_prov_check("transfer_requests"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(4))
    origin_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    need: Mapped[str] = mapped_column(String(30))
    acuity: Mapped[str] = mapped_column(String(20))
    window_min: Mapped[float] = mapped_column(Float)
    sim_week: Mapped[date] = mapped_column(Date)
    sim_time: Mapped[str] = mapped_column(String(32))          # simulated clock, ISO
    status: Mapped[str] = mapped_column(String(20))            # placed | not_placed
    chosen_pk: Mapped[str | None] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    contacted: Mapped[int] = mapped_column(Integer, default=0)
    time_to_bed_s: Mapped[float | None] = mapped_column(Float)
    phone_low_min: Mapped[float | None] = mapped_column(Float)
    phone_high_min: Mapped[float | None] = mapped_column(Float)
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.emergency")
    provenance: Mapped[str] = _prov("simulated")


class Bid(Base):
    __tablename__ = "bids"
    __table_args__ = (Index("ix_bid_request", "request_id"), _prov_check("bids"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("transfer_requests.id", ondelete="CASCADE"))
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    answer: Mapped[str] = mapped_column(String(10))            # BID | DECLINE
    travel_min: Mapped[float | None] = mapped_column(Float)
    ready_min: Mapped[float | None] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    steward_flag: Mapped[bool] = mapped_column(Boolean, default=False)
    steward_note: Mapped[str | None] = mapped_column(Text)
    chosen: Mapped[bool] = mapped_column(Boolean, default=False)
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.emergency")
    provenance: Mapped[str] = _prov("simulated")


class Transfer(Base):
    __tablename__ = "transfers"
    __table_args__ = (_prov_check("transfers"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    request_id: Mapped[int] = mapped_column(ForeignKey("transfer_requests.id", ondelete="CASCADE"))
    from_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    to_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    travel_min: Mapped[float] = mapped_column(Float)
    confirmed_at: Mapped[str] = mapped_column(String(32))      # simulated clock, ISO
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.emergency")
    provenance: Mapped[str] = _prov("simulated")


# --------------------------------------------------------------------------- #
# Resources: weekly patient plan, staff, equipment
# --------------------------------------------------------------------------- #

class PatientMove(Base):
    """One line of the weekly patient plan (the RQ3 coordinator's proposal)."""
    __tablename__ = "patient_moves"
    __table_args__ = (Index("ix_pmove_state_week", "state", "week"), _prov_check("patient_moves"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(4))
    week: Mapped[date] = mapped_column(Date)
    from_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    to_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    patients: Mapped[float] = mapped_column(Float)
    km: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.coordination")
    provenance: Mapped[str] = _prov("derived")


class StaffPool(Base):
    __tablename__ = "staff_pools"
    __table_args__ = (UniqueConstraint("hospital_pk", "week", name="uq_staff_hospital_week"),
                      Index("ix_staff_week", "week"), _prov_check("staff_pools"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    week: Mapped[date] = mapped_column(Date)
    state: Mapped[str | None] = mapped_column(String(4))
    nurses_per_shift: Mapped[float | None] = mapped_column(Float)    # pool (estimated)
    nurses_needed: Mapped[float | None] = mapped_column(Float)       # at safe ratios for this census
    physicians_per_shift: Mapped[float | None] = mapped_column(Float)
    physicians_needed: Mapped[float | None] = mapped_column(Float)
    nurse_gap: Mapped[float | None] = mapped_column(Float)           # needed - pool (>0 = short)
    source: Mapped[str] = mapped_column(String(120), default="mahros.resources.staff")
    provenance: Mapped[str] = _prov("estimated")


class StaffLoan(Base):
    __tablename__ = "staff_loans"
    __table_args__ = (Index("ix_loan_state_week", "state", "week"), _prov_check("staff_loans"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(4))
    week: Mapped[date] = mapped_column(Date)
    from_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    to_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    nurses: Mapped[float] = mapped_column(Float)
    km: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.resources.staff")
    provenance: Mapped[str] = _prov("estimated")


class EquipmentItem(Base):
    __tablename__ = "equipment_inventory"
    __table_args__ = (UniqueConstraint("hospital_pk", "item", name="uq_equipment_hospital_item"),
                      _prov_check("equipment_inventory"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    hospital_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    item: Mapped[str] = mapped_column(String(30))
    units: Mapped[int] = mapped_column(Integer)
    in_use: Mapped[int] = mapped_column(Integer, default=0)
    updated_at: Mapped[datetime] = mapped_column(DateTime)
    updated_by: Mapped[str] = mapped_column(String(60), default="seed estimate")
    source: Mapped[str] = mapped_column(String(120), default="seed estimate (not public data)")
    provenance: Mapped[str] = _prov("entered")


class EquipmentMove(Base):
    __tablename__ = "equipment_moves"
    __table_args__ = (Index("ix_emove_state_week", "state", "week"), _prov_check("equipment_moves"))
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    state: Mapped[str] = mapped_column(String(4))
    week: Mapped[date] = mapped_column(Date)
    item: Mapped[str] = mapped_column(String(30))
    from_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    to_pk: Mapped[str] = mapped_column(ForeignKey("hospitals.hospital_pk"))
    units: Mapped[int] = mapped_column(Integer)
    km: Mapped[float] = mapped_column(Float)
    reason: Mapped[str] = mapped_column(Text)
    ledger_seq: Mapped[int | None] = mapped_column(Integer)
    source: Mapped[str] = mapped_column(String(120), default="mahros.resources.equipment")
    provenance: Mapped[str] = _prov("derived")


# --------------------------------------------------------------------------- #
# Audit ledger (hash chain)
# --------------------------------------------------------------------------- #

class LedgerBlock(Base):
    """A page of the record book: one emergency case, or one state-week."""
    __tablename__ = "ledger_blocks"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    label: Mapped[str] = mapped_column(String(200))
    first_seq: Mapped[int | None] = mapped_column(Integer)
    last_seq: Mapped[int | None] = mapped_column(Integer)
    prev_hash: Mapped[str] = mapped_column(String(64))
    merkle: Mapped[str | None] = mapped_column(String(64))
    hash: Mapped[str | None] = mapped_column(String(64))
    sealed_at: Mapped[datetime | None] = mapped_column(DateTime)


class LedgerEntry(Base):
    """One line in the record book. ``hash`` covers this line AND the previous hash."""
    __tablename__ = "ledger_entries"
    __table_args__ = (Index("ix_entry_block", "block_id"),)
    seq: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=False)
    block_id: Mapped[int | None] = mapped_column(ForeignKey("ledger_blocks.id"))
    recorded_at: Mapped[str] = mapped_column(String(32))       # ISO, seconds, UTC or sim clock
    kind: Mapped[str] = mapped_column(String(30))
    sender: Mapped[str] = mapped_column(String(80))
    receiver: Mapped[str] = mapped_column(String(80))
    ref_table: Mapped[str | None] = mapped_column(String(40))
    ref_id: Mapped[int | None] = mapped_column(Integer)
    body: Mapped[dict] = mapped_column(JSONType)
    prev_hash: Mapped[str] = mapped_column(String(64))
    hash: Mapped[str] = mapped_column(String(64))
