"""One-shot loader: real data -> pipeline -> database.  Safe to run again.

    python -m mahros.db.load              # DATABASE_URL decides the database
    python -m mahros.db.load --force      # reload even if nothing changed

What it does, in order
----------------------
1. ``alembic upgrade head`` (create or update the tables).
2. Makes sure the data is on disk (``data/cache/``); downloads it if not.
   The forecasts come from ``experiments/rq2_forecast.py`` (run if missing).
3. If the input fingerprints are the same as last time, stops (idempotent).
4. Otherwise reloads the REAL and DERIVED tables: hospitals (upsert),
   weekly_reports, trust_verdicts, forecasts, state_staffing, then each
   derived step (surge early warning, staff pools, equipment seed).

Never touched by a reload: the audit ledger, emergency cases, plans and the
equipment inventory a person has entered. Equipment is seeded only when the
table is empty. A small demo set (6 emergency cases, 1 weekly plan;
``mahros/db/seed.py``) is added only when there are no cases yet; skip it with
``--no-seed``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, select, text

from ..data import hhs
from .io import truncate, write_frame
from .models import DataManifest, Hospital
from .session import ROOT, database_url, get_engine, session_scope

#: Bump when what the loader writes changes, so the next run reloads.
LOADER_VERSION = "0.3.1"

FORECASTS = hhs.CACHE / "forecasts_h1.parquet"


def log(msg: str) -> None:
    print(f"[loader {datetime.now():%H:%M:%S}] {msg}", flush=True)


def migrate(engine=None) -> None:
    from alembic import command
    from alembic.config import Config
    cfg = Config(str(ROOT / "alembic.ini"))
    cfg.set_main_option("script_location", str(ROOT / "migrations"))
    cfg.attributes["engine"] = engine or get_engine()
    command.upgrade(cfg, "head")


def ensure_data() -> None:
    if not (hhs.CACHE / "hhs_corrected_source.parquet").exists():
        log("downloading the HHS facility data (about 3 minutes)...")
        hhs.fetch("corrected", log=log)
    if not (hhs.CACHE / "hhs_corrected_extra_source.parquet").exists():
        log("downloading the extra HHS fields...")
        hhs.fetch_extra(log=log)
    if not (hhs.CACHE / "hhs_state_staffing_source.parquet").exists():
        log("downloading the state staffing series...")
        hhs.fetch_state_staffing(log=log)
    if not FORECASTS.exists():
        log("forecasts missing -- running experiments/rq2_forecast.py (several minutes)...")
        rc = subprocess.call([sys.executable, "-u", str(ROOT / "experiments" / "rq2_forecast.py")])
        if rc:
            raise SystemExit(f"rq2_forecast.py failed ({rc})")


def _sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def fingerprint() -> str:
    parts = [LOADER_VERSION]
    for name in ("hhs_corrected_source.parquet", "hhs_corrected_extra_source.parquet",
                 "hhs_state_staffing_source.parquet", "forecasts_h1.parquet"):
        p = hhs.CACHE / name
        parts.append(f"{name}:{p.stat().st_size}:{int(p.stat().st_mtime)}")
    for p in sorted((ROOT / "mahros" / "calibration" / "data").glob("*.json")):
        parts.append(f"{p.name}:{p.stat().st_size}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()


# --------------------------------------------------------------------------- #
# Real tables
# --------------------------------------------------------------------------- #

def reports_frame() -> pd.DataFrame:
    """The canonical frame + extra fields + Steward verdicts (same as the experiments)."""
    from ..pipeline import assessed
    df = assessed("corrected")
    extra = hhs.load_extra()
    keep = ["hospital_pk", "week"] + list(hhs.EXTRA_FIELDS)
    df = df.merge(extra[keep], on=["hospital_pk", "week"], how="left", validate="one_to_one")
    return df


def load_hospitals(engine, df: pd.DataFrame) -> int:
    from ..calibration.capability import load_state_capability
    last = df.sort_values("week").groupby("hospital_pk").tail(1)
    caps = {}
    for st in ("AZ", "MA"):
        payload = load_state_capability(st)
        if payload:
            for ccn, row in payload["facilities"].items():
                caps[ccn] = (row, payload["source"]["label"])
    with session_scope(engine) as s:
        have = {h.hospital_pk: h for h in s.execute(select(Hospital)).scalars()}
        n_new = 0
        for r in last.itertuples():
            cap = caps.get(str(r.ccn))
            vals = dict(ccn=_s(r.ccn), name=_s(r.name), city=_s(r.city), state=_s(r.state),
                        zip=_s(r.zip), subtype=_s(r.subtype), fips=_s(r.fips),
                        metro=bool(r.metro), lat=_f(r.lat), lon=_f(r.lon),
                        capability=cap[0] if cap else None,
                        capability_source=cap[1] if cap else None)
            h = have.get(r.hospital_pk)
            if h is None:
                s.add(Hospital(hospital_pk=r.hospital_pk, source="HHS anag-cw7u",
                               provenance="observed", **vals))
                n_new += 1
            else:
                for k, v in vals.items():
                    setattr(h, k, v)
    return n_new


def load_reports(engine, df: pd.DataFrame) -> None:
    cols = ["hospital_pk", "week", "name", "city", "lat", "lon", "metro",
            "beds", "used", "icu_beds", "icu_used",
            "beds_sum", "used_sum", "icu_beds_sum", "icu_used_sum",
            "beds_cov", "used_cov", "icu_beds_cov", "icu_used_cov", "total_beds", "covid_used",
            "beds_suppressed", "used_suppressed", "icu_beds_suppressed", "icu_used_suppressed",
            "n_suppressed", "is_corrected", *hhs.EXTRA_FIELDS]
    out = df[cols].copy()
    out["source"] = "HHS anag-cw7u"
    out["provenance"] = "observed"
    truncate(engine, "weekly_reports")
    write_frame(engine, "weekly_reports", out)

    from ..trust import RULES, BIT
    codes = list(RULES)
    flags = df["flags"].to_numpy(np.int64)
    reasons = np.full(len(df), "", dtype=object)
    for c in codes:
        hit = (flags & BIT[c]) > 0
        reasons[hit] = [f"{x},{c}" if x else c for x in reasons[hit]]
    v = pd.DataFrame({"hospital_pk": df["hospital_pk"], "week": df["week"],
                      "level": df["level"], "flags": flags, "reasons": reasons,
                      "census_run": df["census_run"].astype("Int64"),
                      "source": "mahros.trust.checks", "provenance": "derived"})
    truncate(engine, "trust_verdicts")
    write_frame(engine, "trust_verdicts", v)


def load_forecasts(engine) -> None:
    f = pd.read_parquet(FORECASTS)
    f["source"] = "experiments/rq2_forecast.py"
    f["provenance"] = "derived"
    truncate(engine, "forecasts")
    write_frame(engine, "forecasts", f)


def load_staffing(engine) -> None:
    s = hhs.load_state_staffing()
    s["source"] = "HHS g62h-syeh"
    s["provenance"] = "observed"
    truncate(engine, "state_staffing")
    write_frame(engine, "state_staffing", s)


def record_manifest(engine, fp: str) -> None:
    man = json.loads(hhs.MANIFEST.read_text()) if hhs.MANIFEST.exists() else {}
    now = datetime.now(timezone.utc).replace(tzinfo=None)
    with session_scope(engine) as s:
        for key, m in man.items():
            row = s.get(DataManifest, key) or DataManifest(key=key)
            row.title, row.url, row.rows = m.get("title"), m.get("url"), m.get("rows")
            row.sha256, row.fetched_at, row.loaded_at = m.get("sha256"), m.get("fetched_at"), now
            s.merge(row)
        fc = s.get(DataManifest, "forecasts") or DataManifest(key="forecasts")
        fc.title = "Next-week occupancy forecasts (experiments/rq2_forecast.py)"
        fc.sha256, fc.loaded_at = _sha(FORECASTS), now
        s.merge(fc)
        p = s.get(DataManifest, "_pipeline") or DataManifest(key="_pipeline")
        p.title, p.note, p.loaded_at = f"MAHROS loader {LOADER_VERSION}", fp, now
        s.merge(p)


def already_loaded(engine, fp: str) -> bool:
    with session_scope(engine) as s:
        row = s.get(DataManifest, "_pipeline")
        return bool(row and row.note == fp)


# --------------------------------------------------------------------------- #
# Derived steps (registered by the modules that own them)
# --------------------------------------------------------------------------- #

def derived_steps():
    """(name, function(engine, reports_df)) in order. Imported lazily."""
    steps = []
    try:
        from ..surge.store import load_surge
        steps.append(("surge early warning", load_surge))
    except ImportError:
        pass
    try:
        from ..resources.store import load_staff, seed_equipment
        steps.append(("staff pools", load_staff))
        steps.append(("equipment seed (only if empty)", seed_equipment))
    except ImportError:
        pass
    return steps


def run(force: bool = False) -> int:
    t0 = time.perf_counter()
    engine = get_engine()
    log(f"database: {engine.url.render_as_string(hide_password=True)}")
    for attempt in range(30):                 # the database may still be starting
        try:
            with engine.connect() as c:
                c.execute(text("SELECT 1"))
            break
        except Exception as exc:
            if attempt == 29:
                raise
            log(f"waiting for the database ({exc.__class__.__name__})...")
            time.sleep(2)
    migrate(engine)
    log("tables up to date (alembic head)")
    ensure_data()
    fp = fingerprint()
    if not force and already_loaded(engine, fp):
        log("inputs unchanged since the last load -- nothing to do")
        seed(engine)
        return 0
    log("building reports + Data Steward verdicts...")
    df = reports_frame()
    n_new = load_hospitals(engine, df)
    log(f"hospitals: {df['hospital_pk'].nunique():,} ({n_new:,} new)")
    load_reports(engine, df)
    log(f"weekly_reports + trust_verdicts: {len(df):,} rows")
    load_forecasts(engine)
    log("forecasts loaded")
    load_staffing(engine)
    log("state_staffing loaded")
    for name, fn in derived_steps():
        t = time.perf_counter()
        msg = fn(engine, df)
        log(f"{name}: {msg or 'done'} ({time.perf_counter() - t:.0f}s)")
    record_manifest(engine, fp)
    seed(engine)
    log(f"finished in {time.perf_counter() - t0:.0f}s")
    return 0


def seed(engine) -> None:
    """Demo cases + one weekly plan, only into an empty database (see mahros/db/seed.py)."""
    if "--no-seed" in sys.argv:
        return
    try:
        from ..agents import Platform
        from ..ledger.store import DbLedger
        from .frames import assessed_frame, forecasts_frame
        from .seed import seed_demo
        from .models import TransferRequest
        with session_scope(engine) as s:
            if (s.execute(select(func.count()).select_from(TransferRequest)).scalar() or 0) > 0:
                log("demo seed: cases already present -- nothing seeded")
                return
        plat = Platform(assessed_frame(engine, ["AZ"]), forecasts_frame(engine))
        log("demo seed: " + seed_demo(engine, DbLedger(engine), plat))
    except Exception as exc:                       # a demo seed must never break the load
        log(f"demo seed skipped: {exc.__class__.__name__}: {exc}")


def _s(v):
    if v is None or (isinstance(v, float) and np.isnan(v)):
        return None
    return str(v)


def _f(v):
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return None if np.isnan(f) else f


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true", help="reload even if inputs are unchanged")
    ap.add_argument("--no-seed", action="store_true", help="do not add the demo cases to an empty database")
    args = ap.parse_args()
    print(f"MAHROS loader -> {database_url().split('@')[-1]}")
    return run(args.force)


if __name__ == "__main__":
    raise SystemExit(main())
