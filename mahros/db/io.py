"""Fast bulk transfer between pandas and the database.

PostgreSQL: COPY (a million rows in seconds). SQLite: pandas ``to_sql`` /
``read_sql`` (fine for tests and quick local runs).
"""

from __future__ import annotations

import io

import numpy as np
import pandas as pd
from sqlalchemy import text
from sqlalchemy.engine import Engine

from .session import is_postgres


def write_frame(engine: Engine, table: str, df: pd.DataFrame, chunk: int = 200_000) -> int:
    """Append ``df`` to an existing table. Column names must match the table."""
    if df.empty:
        return 0
    df = df.copy()
    for c in df.columns:
        if pd.api.types.is_datetime64_any_dtype(df[c]):
            df[c] = df[c].dt.strftime("%Y-%m-%d")
    if is_postgres(engine):
        cols = ",".join(f'"{c}"' for c in df.columns)
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                for start in range(0, len(df), chunk):
                    buf = io.StringIO()
                    df.iloc[start:start + chunk].to_csv(buf, index=False, header=False, na_rep="")
                    with cur.copy(f"COPY {table} ({cols}) FROM STDIN WITH (FORMAT csv, NULL '')") as cp:
                        cp.write(buf.getvalue())
            raw.commit()
        finally:
            raw.close()
    else:
        df = df.replace({np.nan: None})
        df.to_sql(table, engine, if_exists="append", index=False, chunksize=20_000)
    return len(df)


def read_frame(engine: Engine, sql: str) -> pd.DataFrame:
    """Run a SELECT and return a DataFrame (COPY on PostgreSQL for speed)."""
    if is_postgres(engine):
        raw = engine.raw_connection()
        try:
            with raw.cursor() as cur:
                buf = io.BytesIO()
                with cur.copy(f"COPY ({sql}) TO STDOUT WITH (FORMAT csv, HEADER true)") as cp:
                    for data in cp:
                        buf.write(data)
            buf.seek(0)
            return pd.read_csv(buf, dtype={"hospital_pk": str, "ccn": str, "zip": str,
                                           "fips": str, "from_pk": str, "to_pk": str})
        finally:
            raw.close()
    with engine.connect() as c:
        return pd.read_sql(text(sql), c)


def truncate(engine: Engine, *tables: str) -> None:
    with engine.begin() as c:
        for t in tables:
            if is_postgres(engine):
                c.execute(text(f"TRUNCATE {t} RESTART IDENTITY CASCADE"))
            else:
                c.execute(text(f"DELETE FROM {t}"))
