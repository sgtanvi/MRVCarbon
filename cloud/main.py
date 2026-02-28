"""
Cloud FastAPI service.
Endpoints: POST /sync, GET /mrv_note, GET /export, GET /health, GET /verify_chain
"""
import hashlib
import hmac
import json
import logging
import os
import re
import statistics
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from typing import Optional

import aiosqlite
from fastapi import FastAPI, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
logger = logging.getLogger(__name__)

DB_PATH = "/app/data/cloud_audit.db"
HMAC_KEY = os.getenv("HMAC_KEY", "oae_mrv_dev_key_change_in_prod").encode()

# YYYY-MM-DD only
DATE_STR_REGEX = re.compile(r"^\d{4}-\d{2}-\d{2}$")

CREATE_TABLE = """
CREATE TABLE IF NOT EXISTS decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    edge_id TEXT,
    edge_decision_id INTEGER,
    timestamp TEXT NOT NULL,
    cap_low REAL,
    cap_mid REAL,
    cap_high REAL,
    reason_codes TEXT,
    confidence REAL,
    aragonite_saturation REAL,
    source TEXT,
    row_hash TEXT,
    received_at TEXT
);
"""

MRV_NOTE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Daily MRV Note — {date}</title>
<style>
  body {{ font-family: 'Segoe UI', system-ui, sans-serif; max-width: 900px; margin: 0 auto; padding: 2rem; background: #f8fafc; color: #1e293b; }}
  h1 {{ color: #0f172a; border-bottom: 3px solid #3b82f6; padding-bottom: .5rem; }}
  h2 {{ color: #1d4ed8; margin-top: 2rem; }}
  .badge {{ display: inline-block; padding: .25rem .6rem; border-radius: 9999px; font-size: .75rem; font-weight: 600; margin: .15rem; }}
  .badge-blue {{ background: #dbeafe; color: #1e40af; }}
  .badge-amber {{ background: #fef3c7; color: #92400e; }}
  .badge-red {{ background: #fee2e2; color: #991b1b; }}
  .badge-green {{ background: #dcfce7; color: #166534; }}
  .envelope {{ display: flex; gap: 2rem; align-items: center; background: white; border-radius: 1rem; padding: 1.5rem 2rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); margin: 1rem 0; }}
  .cap-box {{ text-align: center; }}
  .cap-value {{ font-size: 2.5rem; font-weight: 800; }}
  .cap-label {{ font-size: .85rem; color: #64748b; margin-top: .25rem; }}
  .cap-mid .cap-value {{ color: #2563eb; font-size: 3.5rem; }}
  .cap-low .cap-value {{ color: #d97706; }}
  .cap-high .cap-value {{ color: #059669; }}
  table {{ width: 100%; border-collapse: collapse; background: white; border-radius: .5rem; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,.08); }}
  th {{ background: #1e40af; color: white; padding: .6rem 1rem; text-align: left; font-size: .85rem; }}
  td {{ padding: .5rem 1rem; border-bottom: 1px solid #e2e8f0; font-size: .85rem; font-family: monospace; }}
  tr:last-child td {{ border-bottom: none; }}
  .hash {{ font-size: .7rem; color: #94a3b8; word-break: break-all; }}
  .methodology {{ background: white; border-left: 4px solid #3b82f6; padding: 1rem 1.5rem; border-radius: 0 .5rem .5rem 0; margin: 1rem 0; }}
  .summary-grid {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 1rem; margin: 1rem 0; }}
  .summary-card {{ background: white; border-radius: .5rem; padding: 1rem; box-shadow: 0 1px 3px rgba(0,0,0,.08); text-align: center; }}
  .summary-card .value {{ font-size: 1.5rem; font-weight: 700; color: #1d4ed8; }}
  .summary-card .label {{ font-size: .8rem; color: #64748b; margin-top: .25rem; }}
</style>
</head>
<body>
<h1>Daily MRV Note</h1>
<p><strong>Date:</strong> {date} UTC &nbsp;|&nbsp; <strong>Generated:</strong> {generated_at} UTC &nbsp;|&nbsp; <strong>Edge ID:</strong> oae_edge_001</p>

<h2>Operating Envelope Summary</h2>
<div class="envelope">
  <div class="cap-box cap-low">
    <div class="cap-value">{cap_low:.1f}</div>
    <div class="cap-label">CAP LOW (t/day)</div>
  </div>
  <div class="cap-box cap-mid">
    <div class="cap-value">{cap_mid:.1f}</div>
    <div class="cap-label">CAP MID — BEST ESTIMATE (t/day)</div>
  </div>
  <div class="cap-box cap-high">
    <div class="cap-value">{cap_high:.1f}</div>
    <div class="cap-label">CAP HIGH (t/day)</div>
  </div>
</div>

<div class="summary-grid">
  <div class="summary-card">
    <div class="value">{n_decisions}</div>
    <div class="label">Decisions Logged</div>
  </div>
  <div class="summary-card">
    <div class="value">{avg_confidence:.0%}</div>
    <div class="label">Avg Confidence</div>
  </div>
  <div class="summary-card">
    <div class="value">{avg_omega:.3f}</div>
    <div class="label">Avg Ω Aragonite</div>
  </div>
</div>

<h2>Reason Codes</h2>
<div>{reason_badges}</div>

<h2>Methodology</h2>
<div class="methodology">
  <p><strong>Carbonate system:</strong> PyCO2SYS v1.8.3 (Humphreys et al. 2022) using Lueker et al. 2000 dissociation constants (opt_k_carbonic=10), Dickson 1990 bisulfate (opt_k_bisulfate=1). Parameter pairs evaluated in priority order: pH+pCO₂ → TA+pH → TA+pCO₂ → pH+TA₀ → pCO₂+TA₀ → defaults (Ω=1.0).</p>
  <p><strong>Data sources:</strong> MBARI M1 mooring replay (primary), NOAA CO-OPS 9413450 Monterey (temperature, barometric pressure, water level). Synthetic fallback seeded from Johnson et al. 2013 published M1 statistics when ERDDAP unavailable.</p>
  <p><strong>Envelope engine:</strong> Base rate 120 t/day × headroom fraction (Ω_arag vs safety threshold 1.2 / ceiling 4.0). Temperature penalties applied at &gt;14°C and &gt;16°C. Missing sensor penalties: pH (×0.4), pCO₂ (×0.7). Spread calculated from tidal mixing × sensor confidence.</p>
  <p><strong>Audit integrity:</strong> HMAC-SHA256 hash chain — each record hashed against previous row hash. Chain verification available via <code>/verify_chain</code>.</p>
</div>

<h2>Decision Log</h2>
<table>
<thead><tr>
  <th>ID</th><th>Timestamp</th><th>Cap Low</th><th>Cap Mid</th><th>Cap High</th>
  <th>Ω Arag</th><th>Confidence</th><th>Source</th><th>Hash</th>
</tr></thead>
<tbody>
{decision_rows}
</tbody>
</table>

<p style="margin-top:2rem;font-size:.8rem;color:#94a3b8;">
  Generated by OAE Edge MRV System v1.0.0 &mdash;
  Reference: Humphreys et al. 2022 (PyCO2SYS), Johnson et al. 2013 (MBARI M1),
  Lueker et al. 2000 (carbonate constants), Feely et al. 2008 (Pacific carbonate chemistry)
</p>
</body>
</html>"""


class DecisionIn(BaseModel):
    decision_id: Optional[int] = None
    timestamp: str
    cap_low: float
    cap_mid: float
    cap_high: float
    reason_codes: list[str]
    confidence: float
    aragonite_saturation: float
    source: str
    row_hash: Optional[str] = None


class SyncPayload(BaseModel):
    decisions: list[DecisionIn]
    edge_id: str = "oae_edge_001"


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(CREATE_TABLE)
        await db.commit()
    logger.info("Cloud DB initialized")
    yield


app = FastAPI(title="OAE Cloud MRV", version="1.0.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.post("/sync")
async def sync(payload: SyncPayload):
    received_at = datetime.now(tz=timezone.utc).isoformat()
    synced_ids = []
    async with aiosqlite.connect(DB_PATH) as db:
        for d in payload.decisions:
            await db.execute(
                """INSERT INTO decisions
                   (edge_id, edge_decision_id, timestamp, cap_low, cap_mid, cap_high,
                    reason_codes, confidence, aragonite_saturation, source, row_hash, received_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    payload.edge_id,
                    d.decision_id,
                    d.timestamp,
                    d.cap_low,
                    d.cap_mid,
                    d.cap_high,
                    json.dumps(d.reason_codes),
                    d.confidence,
                    d.aragonite_saturation,
                    d.source,
                    d.row_hash,
                    received_at,
                ),
            )
            if d.decision_id is not None:
                synced_ids.append(d.decision_id)
        await db.commit()
    logger.info("Synced %d decisions from %s", len(synced_ids), payload.edge_id)
    return {"synced_ids": synced_ids, "count": len(synced_ids)}


def _validate_date_str(s: Optional[str]) -> tuple[str, Optional[str]]:
    """Return (valid_date_str, error_msg). If s is None, use today. If invalid, return (s, error)."""
    if s is None or s.strip() == "":
        return datetime.now(tz=timezone.utc).strftime("%Y-%m-%d"), None
    s = s.strip()
    if not DATE_STR_REGEX.match(s):
        return s, f"Invalid date format: expected YYYY-MM-DD, got {s!r}"
    try:
        datetime.strptime(s, "%Y-%m-%d")
    except ValueError:
        return s, f"Invalid date: {s!r} (e.g. 2025-02-30 is invalid)"
    return s, None


@app.get("/mrv_note", response_class=HTMLResponse)
async def mrv_note(date_str: Optional[str] = Query(None)):
    valid_date, err = _validate_date_str(date_str)
    if err:
        return HTMLResponse(f"<h1>Bad Request</h1><p>{err}</p>", status_code=400)
    return await _build_note(valid_date, download=False)


@app.get("/export")
async def export_note(date_str: Optional[str] = Query(None)):
    valid_date, err = _validate_date_str(date_str)
    if err:
        from fastapi.responses import Response
        return Response(content=err, status_code=400, media_type="text/plain")
    html = await _build_note(valid_date, download=True)
    filename = f"mrv_note_{valid_date}.html"
    from fastapi.responses import Response
    return Response(
        content=html,
        media_type="text/html",
        headers={"Content-Disposition": f"attachment; filename={filename}"},
    )


async def _build_note(date_str: str, download: bool) -> str:
    # date_str is already validated (YYYY-MM-DD)

    # Fetch decisions for date
    date_start = f"{date_str}T00:00:00"
    date_end = f"{date_str}T23:59:59"

    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, timestamp, cap_low, cap_mid, cap_high, reason_codes, confidence,
                      aragonite_saturation, source, row_hash
               FROM decisions WHERE timestamp >= ? AND timestamp <= ?
               ORDER BY id""",
            (date_start, date_end),
        ) as cursor:
            rows = await cursor.fetchall()

    # If no data for date, use latest available
    if not rows:
        async with aiosqlite.connect(DB_PATH) as db:
            async with db.execute(
                """SELECT id, timestamp, cap_low, cap_mid, cap_high, reason_codes, confidence,
                          aragonite_saturation, source, row_hash
                   FROM decisions ORDER BY id DESC LIMIT 100"""
            ) as cursor:
                rows = await cursor.fetchall()

    if not rows:
        return "<h1>No data available yet</h1>"

    # Aggregate stats
    caps_low = [r[2] for r in rows]
    caps_mid = [r[3] for r in rows]
    caps_high = [r[4] for r in rows]
    confidences = [r[6] for r in rows]
    omegas = [r[7] for r in rows]

    # Aggregate reason codes
    all_codes: dict[str, int] = {}
    for r in rows:
        codes = json.loads(r[5])
        for c in codes:
            key = c.split(":")[0]  # strip values for badge grouping
            all_codes[key] = all_codes.get(key, 0) + 1

    # Build reason badges
    def badge_class(code: str) -> str:
        if "MISSING" in code or "BELOW" in code or "PENALTY" in code:
            return "badge-red"
        if "SYNTHETIC" in code or "LOW" in code or "ELEVATED" in code:
            return "badge-amber"
        if "CARB" in code or "OMEGA" in code or "HEADROOM" in code:
            return "badge-blue"
        return "badge-green"

    badges = " ".join(
        f'<span class="badge {badge_class(c)}">{c} ({n})</span>'
        for c, n in sorted(all_codes.items(), key=lambda x: -x[1])
    )

    # Build decision rows
    def row_html(r) -> str:
        hash_short = (r[9] or "")[:12] + "..."
        return (
            f"<tr><td>{r[0]}</td><td>{r[1][:19]}</td>"
            f"<td>{r[2]:.1f}</td><td><strong>{r[3]:.1f}</strong></td><td>{r[4]:.1f}</td>"
            f"<td>{r[7]:.3f}</td><td>{r[6]:.0%}</td><td>{r[8]}</td>"
            f"<td class='hash'>{hash_short}</td></tr>"
        )

    decision_rows = "\n".join(row_html(r) for r in rows[-50:])  # last 50

    # Use median for summary (robust to outliers)
    def safe_median(lst):
        clean = [x for x in lst if x is not None]
        return statistics.median(clean) if clean else 0.0

    html = MRV_NOTE_TEMPLATE.format(
        date=date_str,
        generated_at=datetime.now(tz=timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        cap_low=safe_median(caps_low),
        cap_mid=safe_median(caps_mid),
        cap_high=safe_median(caps_high),
        n_decisions=len(rows),
        avg_confidence=safe_median(confidences),
        avg_omega=safe_median(omegas),
        reason_badges=badges,
        decision_rows=decision_rows,
    )
    return html


@app.get("/verify_chain")
async def verify_chain():
    """
    Verify HMAC-SHA256 hash chain integrity of synced decisions.
    Returns valid=True if all hashes chain correctly from genesis.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute(
            """SELECT id, edge_decision_id, timestamp, cap_low, cap_mid, cap_high,
                      reason_codes, confidence, aragonite_saturation, source, row_hash
               FROM decisions ORDER BY id"""
        ) as cursor:
            rows = await cursor.fetchall()

    if not rows:
        return {"valid": True, "message": "No decisions to verify", "total": 0, "verified": 0}

    prev_hash = "genesis"
    invalid_at: Optional[int] = None

    for row in rows:
        row_id, _, ts, cap_low, cap_mid, cap_high, reason_codes_json, conf, omega, src, stored_hash = row
        payload = json.dumps({
            "aragonite_saturation": omega,
            "cap_high": cap_high,
            "cap_low": cap_low,
            "cap_mid": cap_mid,
            "confidence": conf,
            "prev_hash": prev_hash,
            "reason_codes": json.loads(reason_codes_json) if isinstance(reason_codes_json, str) else reason_codes_json,
            "source": src or "",
            "timestamp": ts,
        }, sort_keys=True)
        expected_hash = hmac.new(HMAC_KEY, payload.encode(), digestmod=hashlib.sha256).hexdigest()
        if expected_hash != stored_hash:
            invalid_at = row_id
            break
        prev_hash = stored_hash

    if invalid_at is not None:
        return {
            "valid": False,
            "message": f"Chain broken at decision id={invalid_at}",
            "total": len(rows),
            "verified": invalid_at - 1 if invalid_at > 1 else 0,
        }
    return {
        "valid": True,
        "message": "Hash chain verified",
        "total": len(rows),
        "verified": len(rows),
    }


@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/stats")
async def stats():
    async with aiosqlite.connect(DB_PATH) as db:
        async with db.execute("SELECT COUNT(*) FROM decisions") as cursor:
            total = (await cursor.fetchone())[0]
        async with db.execute("SELECT MAX(timestamp) FROM decisions") as cursor:
            latest = (await cursor.fetchone())[0]
    return {"total_decisions": total, "latest_timestamp": latest}
