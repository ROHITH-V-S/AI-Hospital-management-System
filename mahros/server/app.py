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

LIVE = LiveEngine()


@asynccontextmanager
async def _lifespan(_app):
    LIVE.start_loading()          # ~15 s in a background thread; the page shows progress
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


@app.get("/healthz")
def healthz():
    return {"ok": True, "ui_files": UI.exists()}


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
