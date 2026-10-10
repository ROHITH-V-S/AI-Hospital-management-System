"""Live console engine, on the real data. Skipped where the data cache is absent."""

import pytest

from mahros.data import hhs

pytestmark = pytest.mark.skipif(
    not (hhs.CACHE / "forecasts_h1.parquet").exists(),
    reason="needs the national data cache (experiments/fetch_national.py, rq2_forecast.py)")


@pytest.fixture(scope="module")
def engine():
    from mahros.server.live import LiveEngine
    e = LiveEngine()
    e._load()
    assert e.ready, e.error
    return e


def test_a_week_runs_and_is_sealed(engine):
    engine.reset("TX", 10)
    d = engine.step()
    assert d["run"]["state"] == "TX" and d["feed"]
    assert d["ledger"]["ok"] and d["ledger"]["blocks"] == 1
    assert d["week_idx"] == 11


def test_lost_digit_at_a_full_hospital_is_caught_and_prevention_reported(engine):
    engine.reset("TX", 10)
    g = engine.platform.week_frame("TX", engine.weeks[10])
    full = g[(g.level == "GREEN") & (g.used / g.beds > 0.95) & (g.used > 60)].iloc[0]
    engine.inject(str(full.hospital_pk), "lost_digit")
    d = engine.step()
    inj = d["injected"][0]
    assert inj["level"] == "RED"
    assert any(r["code"] == "CENSUS_SPIKE" for r in inj["reasons"])
    # The hospital is not offered patients this week.
    assert all(p["to"] != str(full.hospital_pk) for p in d["run"]["proposals"])
    assert any(ev.get("level") == "SAVED" for ev in d["feed"])


def test_injection_only_lasts_one_week(engine):
    engine.reset("TX", 10)
    hid = str(engine.platform.week_frame("TX", engine.weeks[10]).hospital_pk.iloc[0])
    engine.inject(hid, "extra_zero")
    assert engine.step()["injected"]
    assert engine.step()["injected"] == []


def test_tamper_breaks_the_live_log(engine):
    engine.reset("TX", 10)
    engine.step(); engine.step(); engine.step()
    d = engine.tamper()
    assert not d["ledger"]["ok"]
    assert d["ledger"]["first_bad_block"] == d["block"]


def test_unknown_mistake_rejected(engine):
    with pytest.raises(ValueError):
        engine.inject("x", "made_up")
