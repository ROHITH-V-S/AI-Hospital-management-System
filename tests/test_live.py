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


def test_week_is_told_in_six_plain_steps(engine):
    engine.reset("AZ", 0)
    d = engine.step()
    keys = [s["key"] for s in d["stages"]]
    assert keys == ["report", "check", "forecast", "plan", "answer", "result"]
    for s in d["stages"]:
        assert s["title"] and s["caption"] and s["numbers"]
        assert s["map"]["color"] in ("now", "forecast", "next")
    # The result step's numbers are the run's own totals, not separate arithmetic.
    t = d["run"]["totals"]
    assert d["stages"][5]["numbers"][0]["value"] == f"{t['overload_patient_days'] / 7:.0f}"


def test_demo_pick_finds_a_case_where_the_typo_would_misdirect_patients(engine):
    engine.reset("AZ", 0)
    pick = engine.demo_pick()
    assert pick["id"] and pick["would_receive"] > 0
    engine.inject(pick["id"], "lost_digit")
    d = engine.step()
    assert d["injected"][0]["level"] == "RED"
    saved = [i for i in d["stages"][5]["items"] if i.get("tone") == "saved"]
    assert saved and pick["id"] in saved[0]["focus"]


def test_state_names_are_spelled_out(engine):
    names = {s["state"]: s["name"] for s in engine.states}
    assert names["AZ"] == "Arizona" and names["TX"] == "Texas"
