"""PostgreSQL storage for the MAHROS platform (SQLite fallback for unit tests).

The research experiments keep reading Parquet (``data/cache/``) so their
results stay byte-reproducible. The running platform -- dashboard, agents,
audit ledger -- reads and writes this database.
"""

from .session import get_engine, session_scope, database_url, is_postgres  # noqa: F401
