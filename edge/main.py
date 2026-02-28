"""
Edge FastAPI service.
Endpoints: GET /decision, GET /status, GET /audit_log
Background tasks: decision_loop, sync_loop
"""
import asyncio
import logging
import os
from collections import deque
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Literal

import httpx
from fastapi import Body, FastAPI
from fastapi.middleware.cors import CORSMiddleware

from audit import init_db, write_decision, get_unsynced, mark_synced, get_audit_log, get_unsynced_count
from envelope import compute_envelope
from models import EnvelopeDecision, SensorReading, SyncPayload
from qc import run_qc
from sensor_adapter import SensorAdapter

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

REPLAY_SPEED_X = float(os.getenv("REPLAY_SPEED_X", "60"))
CLOUD_SYNC_URL = os.getenv("CLOUD_SYNC_URL", "http://cloud:8002/sync")
DECISION_INTERVAL = 60.0 / REPLAY_SPEED_X  # real seconds between decisions
SYNC_INTERVAL = 30.0  # seconds

adapter: SensorAdapter | None = None
latest_decision: EnvelopeDecision | None = None
is_running = False
reading_history: deque = deque(maxlen=60)

FaultMode = Literal["normal", "ph_flatline", "ph_spike"]
fault_mode: FaultMode = "normal"


def _apply_fault(reading: SensorReading, mode: FaultMode) -> SensorReading:
    """Inject a simulated sensor fault for demo purposes."""
    if mode == "ph_flatline":
        # pH stuck at constant — triggers STUCK_PH after history fills
        return reading.model_copy(update={"pH": 7.800})
    elif mode == "ph_spike":
        # pH extreme outlier — triggers OOR_PH + IMPLAUSIBLE_PH_PCO2 + Ω crash
        return reading.model_copy(update={"pH": 6.20})
    return reading


async def decision_loop():
    global latest_decision
    logger.info("Decision loop starting (interval=%.1fs)", DECISION_INTERVAL)
    while True:
        try:
            reading = adapter.next_reading()
            reading = _apply_fault(reading, fault_mode)
            tidal_amp = adapter.get_tidal_amplitude()
            reading_history.append(reading)
            qc = run_qc(reading, history=list(reading_history))
            decision = compute_envelope(qc, tidal_amp)
            decision = await write_decision(decision)
            latest_decision = decision
            logger.info(
                "Decision #%d: mid=%.1f t/day, omega=%.3f, conf=%.2f, source=%s",
                decision.decision_id or 0,
                decision.cap_mid,
                decision.aragonite_saturation,
                decision.confidence,
                decision.source,
            )
        except Exception as e:
            logger.error("Decision loop error: %s", e, exc_info=True)
        await asyncio.sleep(DECISION_INTERVAL)


async def sync_loop():
    logger.info("Sync loop starting (interval=%.1fs, target=%s)", SYNC_INTERVAL, CLOUD_SYNC_URL)
    while True:
        await asyncio.sleep(SYNC_INTERVAL)
        try:
            unsynced = await get_unsynced()
            if not unsynced:
                continue
            payload = SyncPayload(decisions=unsynced)
            async with httpx.AsyncClient(timeout=10.0) as client:
                response = await client.post(CLOUD_SYNC_URL, content=payload.model_dump_json(), headers={"Content-Type": "application/json"})
            if response.status_code == 200:
                synced_ids = response.json().get("synced_ids", [])
                await mark_synced(synced_ids)
                logger.info("Synced %d decisions to cloud", len(synced_ids))
            else:
                logger.warning("Cloud sync returned %d", response.status_code)
        except Exception as e:
            logger.warning("Sync failed (cloud may be offline): %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    global adapter, is_running
    logger.info("Initializing edge service...")
    await init_db()
    adapter = SensorAdapter()
    is_running = True
    dl_task = asyncio.create_task(decision_loop())
    sl_task = asyncio.create_task(sync_loop())
    yield
    dl_task.cancel()
    sl_task.cancel()
    await asyncio.gather(dl_task, sl_task, return_exceptions=True)
    is_running = False


app = FastAPI(title="OAE Edge MRV", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/fault")
async def get_fault_mode():
    return {"mode": fault_mode}


@app.post("/fault")
async def set_fault_mode(mode: str = Body(..., embed=True)):
    global fault_mode
    if mode not in ("normal", "ph_flatline", "ph_spike"):
        return {"error": f"unknown mode: {mode}"}
    if mode == "normal":
        reading_history.clear()  # flush history so anomaly flags clear quickly
    fault_mode = mode  # type: ignore[assignment]
    logger.info("Fault mode set to: %s", mode)
    return {"mode": fault_mode}


@app.get("/decision")
async def get_decision():
    if latest_decision is None:
        return {"status": "initializing", "message": "First decision pending"}
    return latest_decision.model_dump()


@app.get("/status")
async def get_status():
    unsynced = await get_unsynced_count()
    return {
        "status": "running" if is_running else "stopped",
        "replay_index": adapter.replay_index if adapter else 0,
        "total_rows": adapter.total_rows if adapter else 0,
        "unsynced_decisions": unsynced,
        "decision_interval_s": DECISION_INTERVAL,
        "sync_url": CLOUD_SYNC_URL,
        "timestamp": datetime.now(tz=timezone.utc).isoformat(),
        "data_source": adapter.mbari_source if adapter else "unknown",
    }


@app.get("/audit_log")
async def get_audit(limit: int = 50):
    log = await get_audit_log(limit=limit)
    return {"count": len(log), "entries": log}


@app.get("/health")
async def health():
    return {"ok": True}
