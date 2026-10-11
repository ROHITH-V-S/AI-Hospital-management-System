"""MAHROS dashboard server.

    python -m mahros.server          # then open http://127.0.0.1:8000

Read-only. Serves the page and the precomputed result files in
``results/ui/`` (built by ``experiments/build_ui_data.py``). One thing is done
live: at startup the audit chain is rebuilt from its raw entries and checked
against the published block hashes, and the tamper demo edits an in-memory
copy to show exactly where verification breaks.
"""

from __future__ import annotations

import copy
from contextlib import asynccontextmanager
import json
import re
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse

from ..ledger.chain import AuditLedger

try:   # the platform database (PostgreSQL in Docker, SQLite file otherwise)
    from ..db.session import get_engine
    from ..ledger.store import DbLedger
    DB = get_engine()
    BOOK = DbLedger(DB)
except ImportError:                                # pragma: no cover
    DB = BOOK = None

try:   # live mode needs the experiment stack; the hosted evidence pages do not
    from .live import LiveEngine
except ImportError as _exc:                       # pragma: no cover
    _LIVE_IMPORT_ERROR = str(_exc)

    class LiveEngine:                              # type: ignore[no-redef]
        ready, loading = False, False
        error = (f"Live mode is not available here ({_LIVE_IMPORT_ERROR}). "
                 "Run it on a computer with the full install and data.")

        def start_loading(self):
            pass

        def status(self):
            return {"ready": False, "loading": False, "error": self.error}

ROOT = Path(__file__).resolve().parents[2]
UI = ROOT / "results" / "ui"
STATIC = Path(__file__).resolve().parent / "static"
SAFE_NAME = re.compile(r"^[A-Za-z0-9_\-]+\.json$")

try:
    LIVE = LiveEngine(DB, BOOK)
except TypeError:                                  # stub without database support
    LIVE = LiveEngine()

try:
    from ..emergency.live import EmergencyLive
    EMERGENCY = EmergencyLive(DB, BOOK)
except ImportError as _exc:                        # pragma: no cover
    EMERGENCY = None


def _ensure_tables() -> str | None:
    """Create/upgrade tables if needed (the Docker loader normally did this already)."""
    if DB is None:
        return "database libraries not installed"
    try:
        from ..db.load import migrate
        migrate(DB)
        return None
    except Exception as exc:                       # shown on the Audit tab, never fatal
        return f"{exc.__class__.__name__}: {exc}"


DB_ERROR: str | None = None


@asynccontextmanager
async def _lifespan(_app):
    global DB_ERROR
    DB_ERROR = _ensure_tables()
    LIVE.start_loading()          # ~15 s in a background thread; the page shows progress
    if EMERGENCY is not None:
        EMERGENCY.start_loading()
    yield


app = FastAPI(title="MAHROS", docs_url="/api/docs", lifespan=_lifespan)


def _load_entries():
    p = UI / "ledger_entries.json"
    return json.loads(p.read_text()) if p.exists() else []


class _LedgerState:
    def __init__(self) -> None:
        self.source = _load_entries()
        self.reset()

    def reset(self) -> None:
        self.ledger = AuditLedger()
        for blk in copy.deepcopy(self.source):
            for e in blk["entries"]:
                self.ledger.append(e)
            self.ledger.seal(blk["label"])
        self.tampered: dict | None = None


LEDGER = _LedgerState()


def _published_head() -> str | None:
    p = UI / "index.json"
    if not p.exists():
        return None
    blocks = json.loads(p.read_text()).get("ledger", {}).get("blocks", [])
    return blocks[-1]["hash"] if blocks else None


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html")


SAFE_STATIC = re.compile(r"^[a-z_]+\.js$")


@app.get("/static/{name}")
def static_file(name: str):
    if not SAFE_STATIC.match(name) or not (STATIC / name).exists():
        raise HTTPException(404, "not found")
    return FileResponse(STATIC / name, media_type="text/javascript")


@app.get("/healthz")
def healthz():
    return {"ok": True, "ui_files": UI.exists(),
            "database": None if DB is None else DB.dialect.name, "database_error": DB_ERROR}


# --------------------------------------------------------------------------- #
# The record book (audit ledger in the database)
# --------------------------------------------------------------------------- #

TAMPER: dict = {}


def _book():
    if BOOK is None or DB_ERROR:
        raise HTTPException(503, DB_ERROR or "database not available")
    return BOOK


@app.get("/api/book")
def book_status(limit: int = 40):
    b = _book()
    return JSONResponse({"summary": b.summary(), "verify": b.verify(),
                         "recent": b.recent(max(1, min(limit, 200))), "blocks": b.blocks(30),
                         "demo_tamper": TAMPER or None,
                         "database": DB.dialect.name})


@app.post("/api/book/verify")
def book_verify():
    return JSONResponse(_book().verify())


@app.get("/api/book/block/{block_id}")
def book_block(block_id: int):
    return JSONResponse(_book().recent(block_id=block_id))


@app.post("/api/book/tamper")
def book_tamper():
    """One click = what a person could do by hand in pgAdmin: edit a logged bid."""
    b = _book()
    try:
        TAMPER.clear()
        TAMPER.update(b.tamper_demo())
    except ValueError as exc:
        raise HTTPException(400, str(exc))
    return JSONResponse({"tampered": TAMPER, "verify": b.verify()})


@app.post("/api/book/undo")
def book_undo():
    b = _book()
    if TAMPER:
        b.undo_tamper(TAMPER)
        TAMPER.clear()
    return JSONResponse({"verify": b.verify()})


@app.get("/ui/{name}")
def ui_file(name: str):
    if not SAFE_NAME.match(name) or not (UI / name).exists():
        raise HTTPException(404, f"{name} not found -- run experiments/build_ui_data.py")
    return FileResponse(UI / name, media_type="application/json")


@app.get("/api/ledger")
def ledger_status():
    v = LEDGER.ledger.verify()
    pub = _published_head()
    return JSONResponse({
        "verify": v,
        "published_head": pub,
        "rebuilt_matches_published": (v.get("head") == pub) if v["ok"] else False,
        "tampered": LEDGER.tampered,
        "blocks": [{"index": b.index, "label": b.label, "hash": b.hash,
                    "entries": len(b.entries)} for b in LEDGER.ledger.blocks],
    })


@app.post("/api/ledger/tamper")
def ledger_tamper(block: int = 0):
    """Quietly change one hospital's reported patient count in a past block."""
    blocks = LEDGER.ledger.blocks
    if not blocks:
        raise HTTPException(400, "ledger is empty")
    block = max(0, min(block, len(blocks) - 1))
    for e in blocks[block].entries:
        if e.get("kind") == "REPORT" and e["body"].get("used") is not None:
            before = e["body"]["used"]
            e["body"]["used"] = round(before * 0.5, 2)
            LEDGER.tampered = {"block": block, "label": blocks[block].label,
                               "hospital": e["sender"], "field": "used",
                               "before": before, "after": e["body"]["used"]}
            break
    return ledger_status()


@app.post("/api/ledger/reset")
def ledger_reset():
    LEDGER.reset()
    return ledger_status()


# --------------------------------------------------------------------------- #
# Live operations: the agents replay real weeks (needs the local data cache).
# --------------------------------------------------------------------------- #

def _live_ready():
    if not LIVE.ready:
        raise HTTPException(503, LIVE.error or "live engine is still loading")


@app.get("/api/live/status")
def live_status():
    return JSONResponse(LIVE.status())


@app.get("/api/live/hospitals")
def live_hospitals():
    _live_ready()
    return JSONResponse(LIVE.hospitals())


@app.get("/api/live/demo_pick")
def live_demo_pick(mistake: str = "lost_digit"):
    _live_ready()
    return JSONResponse(LIVE.demo_pick(mistake))


@app.post("/api/live/reset")
def live_reset(state: str, week_idx: int = 0):
    _live_ready()
    if state not in {s["state"] for s in LIVE.states}:
        raise HTTPException(400, f"unknown state {state}")
    return JSONResponse(LIVE.reset(state, week_idx))


@app.post("/api/live/step")
def live_step():
    _live_ready()
    return JSONResponse(LIVE.step())


@app.post("/api/live/inject")
def live_inject(hospital_id: str, mistake: str):
    _live_ready()
    try:
        return JSONResponse(LIVE.inject(hospital_id, mistake))
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.post("/api/live/tamper")
def live_tamper():
    _live_ready()
    try:
        return JSONResponse(LIVE.tamper())
    except ValueError as exc:
        raise HTTPException(400, str(exc))


# --------------------------------------------------------------------------- #
# Emergency transfer (simulation grounded in real data)
# --------------------------------------------------------------------------- #

def _em(state: str | None = None):
    if EMERGENCY is None:
        raise HTTPException(503, "emergency module not available")
    if not EMERGENCY.ready:
        raise HTTPException(503, EMERGENCY.error or "emergency module is still loading")
    if state is not None and state not in EMERGENCY.sessions:
        raise HTTPException(400, f"unknown state {state}")
    return EMERGENCY


@app.get("/api/emergency/status")
def emergency_status(state: str = "AZ"):
    if EMERGENCY is None or not EMERGENCY.ready:
        return JSONResponse(EMERGENCY.status() if EMERGENCY else {"ready": False, "error": "not installed"})
    return JSONResponse(_em(state).status(state))


@app.get("/api/emergency/hospitals")
def emergency_hospitals(state: str = "AZ"):
    return JSONResponse(_em(state).hospitals(state))


@app.post("/api/emergency/reset")
def emergency_reset(state: str = "AZ", week: str | None = None):
    em = _em(state)
    week = week or em.sessions[state]["week"]
    if week not in {w["week"] for w in em.weeks[state]}:
        raise HTTPException(400, f"no trusted reports for week {week}")
    with em.lock:
        return JSONResponse(em.reset(state, week))


@app.post("/api/emergency/advance")
def emergency_advance(state: str = "AZ", minutes: float = 60):
    return JSONResponse(_em(state).advance(state, minutes))


@app.post("/api/emergency/find")
def emergency_find(state: str, origin: str, need: str, acuity: str = "critical"):
    em = _em(state)
    try:
        return JSONResponse(em.find_bed(state, origin, need, acuity))
    except (ValueError, StopIteration) as exc:
        raise HTTPException(400, str(exc) or "unknown hospital")


# --------------------------------------------------------------------------- #
# Surge early warning (real weekly reports)
# --------------------------------------------------------------------------- #

def _db():
    if DB is None or DB_ERROR:
        raise HTTPException(503, DB_ERROR or "database not available")
    return DB


@app.get("/api/warning/weeks")
def warning_weeks(state: str = "AZ"):
    from ..surge import store
    try:
        return JSONResponse({"state": state, "weeks": store.weeks(_db(), state)})
    except ValueError as exc:
        raise HTTPException(400, str(exc))


@app.get("/api/warning")
def warning_week(state: str = "AZ", week: str = "2023-12-17"):
    from ..surge import store
    try:
        return JSONResponse(store.week_view(_db(), state, week))
    except ValueError as exc:
        raise HTTPException(400, str(exc))
