"""Database connection.

``DATABASE_URL`` decides where data lives:

* Docker (``docker compose up``): ``postgresql+psycopg://mahros:...@db:5432/mahros``
* Local, no Docker: falls back to a SQLite file ``data/mahros.sqlite``
* Unit tests: an in-memory or temporary SQLite database

PostgreSQL is the platform's database. SQLite exists only so the unit tests and
a quick local run do not need a server; anything Postgres-specific (bulk COPY)
has a portable fallback.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

ROOT = Path(__file__).resolve().parents[2]
DEFAULT_SQLITE = ROOT / "data" / "mahros.sqlite"

_engines: dict[str, Engine] = {}


def database_url() -> str:
    url = os.environ.get("DATABASE_URL", "").strip()
    return url or f"sqlite:///{DEFAULT_SQLITE.as_posix()}"


def is_postgres(engine: Engine) -> bool:
    return engine.dialect.name == "postgresql"


def get_engine(url: str | None = None) -> Engine:
    url = url or database_url()
    if url not in _engines:
        kw = {"future": True, "pool_pre_ping": True}
        if url.startswith("sqlite"):
            Path(DEFAULT_SQLITE.parent).mkdir(parents=True, exist_ok=True)
            kw["connect_args"] = {"check_same_thread": False}
        eng = create_engine(url, **kw)
        if url.startswith("sqlite"):
            @event.listens_for(eng, "connect")
            def _fk_on(dbapi_conn, _):          # SQLite ignores foreign keys by default
                cur = dbapi_conn.cursor()
                cur.execute("PRAGMA foreign_keys=ON")
                cur.close()
        _engines[url] = eng
    return _engines[url]


@contextmanager
def session_scope(engine: Engine | None = None):
    """A transaction: commits on success, rolls back on any error."""
    factory = sessionmaker(bind=engine or get_engine(), expire_on_commit=False)
    s: Session = factory()
    try:
        yield s
        s.commit()
    except Exception:
        s.rollback()
        raise
    finally:
        s.close()
