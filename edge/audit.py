"""
SQLite audit log with HMAC-SHA256 hash chain.
Each row is hashed against the previous row's hash — tamper-evident.
"""
import hashlib
import hmac
import json
import logging
import os
import aiosqlite
from datetime import datetime
from models import EnvelopeDecision

logger = logging.getLogger(__name__)

DB_PATH = "/app/data/edge_audit.db"
HMAC_KEY = os.getenv("HMAC_KEY", "oae_mrv_dev_key_change_in_prod").encode()

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,
    cap_low REAL,
    cap_mid REAL,
    cap_high REAL,
    reason_codes TEXT,
    confidence REAL,
    aragonite_saturation REAL,
    source TEXT,
    row_hash TEXT,
    synced INTEGER DEFAULT 0
);
"""


def _compute_hash(decision: EnvelopeDecision, prev_hash: str) -> str:
    payload = json.dumps({
        "timestamp": decision.timestamp.isoformat(),
        "cap_low": decision.cap_low,
        "cap_mid": decision.cap_mid,
        "cap_high": decision.cap_high,
        "reason_codes": decision.reason_codes,
        "confidence": decision.confidence,
        "aragonite_saturation": decision.aragonite_saturation,
        "source": decision.source,
        "prev_hash": prev_hash,
    }, sort_keys=True)
    return hmac.new(HMAC_KEY, payload.encode(), hashlib.sha256).hexdigest()


async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE)
        await db.commit()
    logger.info("Edge audit DB initialized at %s", DB_PATH)


async def write_decision(decision: EnvelopeDecision) -> EnvelopeDecision:
    """Write decision to audit log, computing hash chain. Returns decision with hash + id."""
    async with aiosqlite.connect(DB_PATH) as db:
        # Get last hash for chain
        async with db.execute("SELECT row_hash FROM decisions ORDER BY id DESC LIMIT 1") as cursor:
            row = await cursor.fetchone()
        prev_hash = row[0] if row else "genesis"

        row_hash = _compute_hash(decision, prev_hash)
        decision = decision.model_copy(update={"row_hash": row_hash})

        cursor = await db.execute(
            """INSERT INTO decisions
               (timestamp, cap_low, cap_mid, cap_high, reason_codes, confidence,
                aragonite_saturation, source, row_hash, synced)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)""",
            (
                decision.timestamp.isoformat(),
                decision.cap_low,
                decision.cap_mid,
                decision.cap_high,
                json.dumps(decision.reason_codes),
                decision.confidence,
                decision.aragonite_saturation,
                decision.source,
                row_hash,
            ),
        )
        await db.commit()
        decision = decision.model_copy(update={"decision_id": cursor.lastrowid})

    return decision


async def get_unsynced() -> list[EnvelopeDecision]:
    """Return all decisions not yet synced to cloud."""
    decisions = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, timestamp, cap_low, cap_mid, cap_high, reason_codes, "
            "confidence, aragonite_saturation, source, row_hash FROM decisions WHERE synced=0 ORDER BY id"
        ) as cursor:
            rows = await cursor.fetchall()
    for row in rows:
        decisions.append(EnvelopeDecision(
            decision_id=row[0],
            timestamp=datetime.fromisoformat(row[1]),
            cap_low=row[2],
            cap_mid=row[3],
            cap_high=row[4],
            reason_codes=json.loads(row[5]),
            confidence=row[6],
            aragonite_saturation=row[7],
            source=row[8],
            row_hash=row[9],
        ))
    return decisions


async def mark_synced(ids: list[int]):
    """Mark decisions as synced by ID."""
    if not ids:
        return
    async with aiosqlite.connect(DB_PATH) as db:
        placeholders = ",".join("?" for _ in ids)
        await db.execute(f"UPDATE decisions SET synced=1 WHERE id IN ({placeholders})", ids)
        await db.commit()


async def get_audit_log(limit: int = 50) -> list[dict]:
    """Return recent audit log entries for API."""
    rows_out = []
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            "SELECT id, timestamp, cap_low, cap_mid, cap_high, confidence, "
            "aragonite_saturation, source, row_hash, synced FROM decisions ORDER BY id DESC LIMIT ?",
            (limit,),
        ) as cursor:
            rows = await cursor.fetchall()
    for row in rows:
        rows_out.append({
            "id": row[0],
            "timestamp": row[1],
            "cap_low": row[2],
            "cap_mid": row[3],
            "cap_high": row[4],
            "confidence": row[5],
            "aragonite_saturation": row[6],
            "source": row[7],
            "row_hash": row[8],
            "synced": bool(row[9]),
        })
    return rows_out


async def get_unsynced_count() -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM decisions WHERE synced=0") as cursor:
            row = await cursor.fetchone()
    return row[0] if row else 0
