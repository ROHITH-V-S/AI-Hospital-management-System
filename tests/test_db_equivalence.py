"""The platform gives the SAME numbers from the database as from the research Parquet files.

Needs a database the loader has filled. Set MAHROS_TEST_DATABASE_URL to it
(Docker: postgresql+psycopg://mahros:mahros-local@localhost:5432/mahros).
Skipped otherwise.
"""

import os

import pytest

URL = os.environ.get("MAHROS_TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="set MAHROS_TEST_DATABASE_URL to a loaded database")


@pytest.fixture(scope="module")
def both():
    import pandas as pd
    from mahros.agents import Platform
    from mahros.data import hhs
    from mahros.db.frames import assessed_frame, forecasts_frame
    from mahros.db.session import get_engine
    from mahros.pipeline import assessed
    eng = get_engine(URL)
    db = Platform(assessed_frame(eng, ["AZ", "MA", "TX"]), forecasts_frame(eng))
    pq_df = assessed()
    pq = Platform(pq_df[pq_df.state.isin(["AZ", "MA", "TX"])],
                  pd.read_parquet(hhs.CACHE / "forecasts_h1.parquet"))
    return db, pq


@pytest.mark.parametrize("state,wk", [("AZ", 0), ("AZ", 30), ("MA", 5), ("TX", 50)])
def test_same_week_same_numbers(both, state, wk):
    db, pq = both
    week = pq.weeks()[wk]
    a, b = db.run_week(state, week), pq.run_week(state, week)
    assert a.totals == b.totals
    assert a.proposals == b.proposals
    assert [h["level"] for h in a.hospitals] == [h["level"] for h in b.hospitals]
