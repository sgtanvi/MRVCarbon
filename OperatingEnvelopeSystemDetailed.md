# OAE MRV — Operating Envelope System
Track 2A · Bicarbonate Ceiling · Hackathon Prototype

Answers: **"What is the max safe OAE discharge rate right now?"**
Returns a range (`cap_low` / `cap_mid` / `cap_high`) in tonnes/day with reason codes, confidence score, and an exportable Daily MRV Note.

---

## Quick Start

```bash
docker compose up --build edge cloud
# Edge API:  http://localhost:8001
# Cloud API: http://localhost:8002

# UI (separate):
docker compose up ui
# Dashboard:  http://localhost:5173
```

---

## Architecture

```
Browser → UI (React)
            ↓ polls /decision every 10s
         Edge (FastAPI) ──── SQLite (edge_audit.db, hash-chained)
            ↓ syncs every 30s
         Cloud (FastAPI) ─── SQLite (cloud_audit.db)
            ↓
         /mrv_note  →  exportable HTML report
```

**Offline continuity:** Edge keeps running and writing decisions if cloud goes down. When cloud reconnects, the sync loop sends the backlog automatically.

---

## File Reference

### `edge/`

#### `main.py`
Entry point for the edge FastAPI service. Runs two background async tasks on startup:
- `decision_loop` — fires every `60/REPLAY_SPEED_X` real seconds, runs the full pipeline (sensor → QC → carbonate → envelope → audit)
- `sync_loop` — every 30 seconds, sends unsynced decisions to cloud and marks them synced on 200 response

Endpoints:
- `GET /decision` — latest envelope decision (cap_low, cap_mid, cap_high, reason_codes, confidence, row_hash)
- `GET /status` — replay index, unsynced count, data source
- `GET /audit_log` — recent hash-chained log entries

#### `sensor_adapter.py`
Loads sensor data using a three-tier fallback:
1. `edge/data/mbari_m1_live.csv` — live MBARI ERDDAP download (if available)
2. `edge/data/mbari_m1_seed.csv` — pre-downloaded CSV
3. **Auto-generated synthetic seed** — built from published MBARI M1 statistics (Johnson et al. 2013): pH sinusoidal 7.95–8.15, pCO₂ 350–500 µatm, salinity 33.2–33.8, TA 2280–2320 µmol/kg

`SensorAdapter.next_reading()` replays MBARI rows circularly and overlays real NOAA temperature, barometric pressure, and water level from the cached JSON files. `get_tidal_amplitude()` derives mixing proxy from NOAA water level range.

#### `qc.py`
Assigns a confidence score (0–1) to each sensor reading based on which sensors are present and in range. Sensor weights: pH=0.35, pCO₂=0.25, temp=0.20, salinity=0.12, TA=0.08. Out-of-range values get 50% credit. Synthetic source applies a 75% multiplier. Produces a list of flag strings (e.g. `MISSING_PCO2`, `OOR_TEMPERATURE`, `SYNTHETIC_DATA`) passed downstream.

#### `carbonate.py`
Wraps PyCO2SYS to compute aragonite saturation state (Ω). Tries parameter pairs in priority order:
1. pH + pCO₂ (best)
2. TA + pH
3. TA + pCO₂
4. pH + default TA (2300 µmol/kg)
5. pCO₂ + default TA
6. All defaults → returns Ω = 1.0 (hard conservative fallback)

Constants: Lueker 2000 dissociation (`opt_k_carbonic=10`), Dickson 1990 bisulfate (`opt_k_bisulfate=1`), total pH scale (`opt_pH_scale=1`), surface pressure.

#### `envelope.py`
Computes `cap_low`, `cap_mid`, `cap_high` in tonnes/day:
- **Safety gate:** Ω < 1.2 → all caps = 0
- **Base:** 120 t/day × headroom fraction ((Ω − 1.2) / (4.0 − 1.2))
- **Temperature penalty:** >16°C → ×0.6, >14°C → ×0.85
- **Missing sensor penalty:** no pH → ×0.4, no pCO₂ → ×0.7
- **Spread:** `1 − (mixing_confidence × sensor_confidence)` — widens the range when data is uncertain
- `cap_low = cap_mid × (1 − spread×0.5)`, `cap_high = cap_mid × (1 + spread×0.3)`

#### `audit.py`
Writes every decision to SQLite at `/app/data/edge_audit.db` with an HMAC-SHA256 hash chain. Each row's hash is computed over its fields plus the previous row's hash, creating a tamper-evident append-only log. Provides `write_decision()`, `get_unsynced()`, `mark_synced()`.

#### `models.py`
Pydantic models shared across the edge service: `SensorReading`, `QCResult`, `EnvelopeDecision`, `SyncPayload`.

---

### `cloud/`

#### `main.py`
Cloud FastAPI service. Receives synced decisions from edge and stores them in `/app/data/cloud_audit.db`.

Endpoints:
- `POST /sync` — receives a `SyncPayload` batch from edge, inserts rows, returns `{synced_ids: [...]}`
- `GET /mrv_note?date_str=YYYY-MM-DD` — HTML report for a given day with envelope summary, methodology section, reason code badges, and decision log table
- `GET /export?date_str=YYYY-MM-DD` — same report with `Content-Disposition: attachment` for download
- `GET /verify_chain` — re-derives the HMAC-SHA256 hash chain over all synced decisions (ordered by edge decision ID) and returns `{valid, verified, total}`
- `GET /stats` — total decision count and latest timestamp

`_validate_date_str()` enforces `YYYY-MM-DD` format and rejects invalid calendar dates before any DB query.

---

### `ui/src/`

#### `App.tsx`
Root component. Polls `/decision` every 10s and `/status` every 10s via React Query. Handles three states: loading, edge unreachable, initializing (first decision not yet ready), and normal. Renders the component tree below.

#### `components/EnvelopeGauge.tsx`
Hero component. Displays `cap_mid` in large type flanked by `cap_low` and `cap_high`. Shows a visual range bar scaled to 0–120 t/day and an aragonite saturation readout colour-coded by safety threshold.

#### `components/ReasonBadges.tsx`
Renders each reason code string from the latest decision as a colour-coded badge: red for penalties/missing sensors, amber for warnings, blue for informational (omega, headroom, carbonate method).

#### `components/ConfidenceBar.tsx`
Horizontal bar showing the QC confidence percentage with colour (green ≥70%, amber ≥40%, red below). Displays sensor weight breakdown and pending-sync count.

#### `components/AuditLog.tsx`
Table of the 20 most recent audit entries fetched from `/audit_log`. Shows cap values, Ω, confidence, truncated hash, and sync status per row.

#### `components/ExportButton.tsx`
Two links: "View MRV Note" opens the cloud HTML report in a new tab; "Export Daily MRV Note" triggers a file download.

#### `api/edge.ts`
Typed fetch functions (`fetchDecision`, `fetchStatus`, `fetchAuditLog`) and URL helpers (`getExportUrl`, `getMrvNoteUrl`). Reads `VITE_EDGE_URL` and `VITE_CLOUD_URL` from environment.

---

### Root

#### `docker-compose.yml`
Three services on `oae_net` bridge network:
- `edge` — port 8001, mounts `./edge/data` so NOAA JSONs and the audit DB persist across restarts
- `cloud` — port 8002, mounts `./cloud/data`
- `ui` — port 5173, runs `npm install && npm run dev` on container start

#### `.env`
`REPLAY_SPEED_X` (default 60 — one decision per second), `CLOUD_SYNC_URL`, `HMAC_KEY`.

---

## Data Files (`edge/data/`)

| File | Source | Content |
|---|---|---|
| `noaa_temp_raw.json` | Real — NOAA CO-OPS 9413450 | Water temperature, Jan 2025, 6-min intervals |
| `noaa_baro_raw.json` | Real — NOAA CO-OPS 9413450 | Barometric pressure, Jan 2025 |
| `noaa_wl_raw.json` | Real — NOAA CO-OPS 9413450 | Water level (MLLW), Jan 2025 — used for tidal amplitude |
| `mbari_m1_seed.csv` | Synthetic | Auto-generated on first run from M1 published statistics |
| `mbari_m1_live.csv` | Real (when available) | MBARI ERDDAP live download — auto-preferred if present |

---

## Key Design Decisions

**Why a range instead of a single number?** Single values imply false precision. The spread between `cap_low` and `cap_high` is physically grounded: it widens when sensors are missing, tidal mixing is low, or data is synthetic. Regulators prefer explicit uncertainty quantification.

**Why PyCO2SYS?** The carbonate system requires two measured parameters. Hard thresholds can't account for temperature–pH coupling. PyCO2SYS uses Lueker 2000 — the published community standard for seawater CO₂ chemistry.

**Why a hash chain?** Editing any row in the audit log breaks all subsequent hashes. This proves what the system knew and when — operators can demonstrate the decision record is unaltered.

**Why synthetic MBARI data?** MBARI ERDDAP was down at build time. The synthetic seed is statistically grounded in published M1 observations and explicitly flagged in every decision record. Dropping a real CSV into `edge/data/` makes the system use it automatically.

---

## Planned Upgrades

These features are scoped and ready for a post-hackathon sprint. None require changes to the core architecture — each is additive.

### 1. Live MBARI ERDDAP Integration

Replace the synthetic seed with a real-time ERDDAP pull. The `sensor_adapter.py` fallback chain already has a slot for `mbari_m1_live.csv`; the upgrade wires in a background fetch that refreshes every hour and validates the downloaded file before promoting it. If ERDDAP returns a non-200 or malformed data, the adapter silently falls back to the seed — no service disruption.

### 2. Windowed Anomaly Detection

Add a sliding-window anomaly filter in `qc.py`. For each incoming sensor reading, compare it against a rolling 24-hour z-score across stored audit rows. Any value more than 3σ from the local mean appends a `SENSOR_SPIKE_<FIELD>` reason code and applies an additional confidence penalty proportional to the deviation magnitude. The window is computed from the SQLite audit DB — no external state required.

Implementation sketch:
- On each `decision_loop` tick, query the last 1440 rows from `edge_audit.db`
- Compute per-field rolling mean and standard deviation
- Flag and penalise outliers before the envelope step
- Reason codes follow the existing naming convention so the UI badge colours apply automatically

### 3. Tiny On-Device ML Cap Predictor

Replace the rule-based headroom formula in `envelope.py` with a lightweight gradient-boosted tree (XGBoost, ~50 KB serialised) trained on historical `cap_mid` targets. Input features: Ω, temperature, salinity, tidal amplitude, QC confidence, hour-of-day, and 3-hour lag of each variable.

The rule-based formula stays as a fallback: if the model file is absent or produces an out-of-range prediction, `envelope.py` reverts to the current formula transparently. This means the upgrade is zero-risk to deploy — ship the model file when ready.

Training pipeline:
1. Export `cloud_audit.db` decisions labelled against post-hoc verified discharge records
2. Train with 5-fold cross-validation; target RMSE < 5 t/day
3. Serialise with `joblib`; embed version hash in the model file name
4. Edge loads model at startup; logs model version in `GET /status`

### 4. Regulatory Export Enhancements

Extend the HTML MRV Note (`cloud/main.py`) to include:
- A machine-readable JSON-LD summary block (schema.org `Dataset`) for automated ingestion by monitoring registries
- A per-decision chain-of-custody section showing the HMAC hash, previous hash, and a one-click `/verify_chain` result badge
- Optional PDF rendering via `weasyprint` so operators can attach a single file to permit submissions without needing a browser

### 5. Multi-Site Federation

Promote the cloud service to a federation hub. Each deployment site runs its own edge + local cloud pair. A top-level aggregator cloud polls each site's `/stats` and `/sync` endpoints, merges hash chains with site-prefix namespacing, and exposes a combined `/fleet_note` report. The edge and local cloud code are unchanged — federation is purely additive at the aggregator layer.
