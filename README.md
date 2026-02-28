# OAE MRV Dashboard — Track 2A “Bicarbonate Ceiling”

**Offline-first edge MRV system that computes a safe operating envelope and a tamper-evident audit trail.**

## **DEMO SLIDES**

**[→ VIEW / DOWNLOAD DEMO SLIDES (PDF)](https://drive.google.com/file/d/1FaWIJt85IXvuusukZOERdN_Ags2rC3fS/view?usp=sharing)** — *OAE_MRV_TechPitch.pdf*

---

- **Output:** Max safe discharge rate as `cap_low` / `cap_mid` / `cap_high` (t/day)
- **Real-time:** Confidence score + reason codes
- **Audit:** Hash-chained log + exportable Daily MRV Note
- **Degrades safely** when sensors are unreliable

---

## The problem in one sentence

The “bicarbonate ceiling” is **dynamic**: operators need to know *is today safe? how much is too much?* Coastal systems aren’t well-mixed, so capacity shifts with mixing, temperature, and chemistry. The hard part is **trustworthy MRV when the signal is small and sensors are messy** — we need a conservative envelope and an evidentiary record that can survive audit.


# Our solution: an offline-first IoT MRV system
One-sentence description

We built an offline-first edge MRV system that fuses time-series sensor data, computes a conservative safety envelope (cap_low/mid/high), detects data-quality issues, and produces tamper-evident audit logs and a Daily MRV Note.

# Primary user
Operator / field team responsible for deciding day-of discharge operations at a coastal site (bay/fjord/estuary) under uncertainty.

Primary output (the “decision”)
Instead of a generic dashboard, our primary output is:
Recommended max discharge cap today (low / mid / high)
Confidence score + QC flags
Reason codes (what drove the cap)
MRV evidence artifact (exportable note + verifiable log chain)


# Architecture mapped to 6 IoT system criteria
Criteria list: 1) Communications, 2) Cloud–Fog Hybrid Architecture, 3) Privacy & Security, 4) Robustness & Reliability, 5) Algorithms, 6) User + IoT Device Interactions

1) Communications
Goal: keep operating with intermittent/poor connectivity.
Edge generates decisions locally (no cloud dependency)
Store-and-forward sync: when connectivity is available, edge batches decisions to cloud
Payloads are compact: decision records + summary stats + hashes (not full raw streams)

2) Cloud–Fog Hybrid Architecture
Fog (edge) responsibilities:
Sensor ingestion / replay
QC and anomaly checks
Envelope calculation (cap_low/mid/high)
Local persistence
Cloud responsibilities:
Receive batches and persist
Verify integrity (hash chain)
Generate MRV artifact exports (Daily MRV Note)

3) Privacy & Security
Goal: MRV requires tamper resistance and provenance.
Tamper-evident logging via hash chaining across decisions
Decision export includes model/config identifiers so audits can validate “what code produced this”
Minimal data principle: export what’s needed for MRV (inputs + decisions + QC), not everything

4) Robustness & Reliability
Goal: handle faulty sensors / missing data safely.
QC scoring reduces confidence when readings are missing/out-of-range
Conservative envelope policy tightens caps when confidence drops
Offline mode: edge continues producing decisions even when cloud is down

5) Algorithms
Goal: compute a defensible envelope from available signals.
Physics-informed carbonate computation (Ω) when inputs allow
Safety envelope logic combining Ω, temperature, mixing proxy, QC flags
Output is cap range + reason codes, not opaque numbers

6) User + IoT Device Interactions
Goal: the UI must help a non-data-scientist decide.
One-screen view: cap range, confidence, reason codes
Simple alerting: “degraded mode” when sensors fail
Export button: generate Daily MRV Note


---

## What we compute (minimum viable physics)

| Layer | Description |
|-------|-------------|
| **Inputs** | T, S, pH, pCO₂, TA (some may be missing) |
| **Derived** | Carbonate chemistry → Ω_arag (aragonite saturation) as safety proxy |
| **Context** | Mixing proxy (tidal amplitude / stagnation) |
| **Output** | Envelope `cap_low` / `cap_mid` / `cap_high` + confidence + reason codes |

Safety is a function of carbonate chemistry state plus the site’s ability to flush/mix. Ω_arag is the proxy for “how close are we to unsafe chemistry”; mixing proxies drive how conservative we are today.

---

## Libraries (and why they’re defensible)

| Component | Choice | Rationale |
|-----------|--------|------------|
| API | FastAPI + Uvicorn | Deterministic, testable edge/cloud services |
| Carbonate | **PyCO2SYS** | Standard solver in ocean carbon work — not a black box |
| Storage | SQLite / aiosqlite | Offline-first, no external DB |
| Comms | httpx + cached JSON | Store-and-forward, optional cloud sync |
| UI | React + Vite | Minimal surface area, type-safe |

---

## Carbonate chemistry → Ω_arag

We solve the carbonate system with **PyCO2SYS** from whichever parameter pairs are available (e.g. pH + pCO₂, pH + TA, TA + DIC), then compute **Ω_arag**. A safety threshold **Ω_min = 1.2** is applied as a hard constraint: below it, discharge is held at zero.

---

## Envelope logic (cap_low / cap_mid / cap_high)

- **cap_mid:** Best estimate from chemistry + mixing + QC.
- **cap_low:** Conservative bound (limited mixing / degraded sensors).
- **cap_high:** Optimistic bound (ideal mixing, high confidence).

**Hard stops:**

- `Ω_arag < Ω_min` → `cap_low = cap_mid = cap_high = 0`
- `confidence == 0` or **PLAUSIBILITY_FAIL** → cap = 0 (hold)

The system refuses to produce a nonzero cap when data are implausible or chemistry is below threshold.

---

## Quality control: confidence + flags

QC yields:

- **confidence** ∈ [0, 1]
- **flags[]** — reason codes shown to the operator and written to the MRV log

Flags (e.g. `OOR_PH`, `STUCK_PH`, `IMPLAUSIBLE_PH_PCO2`, `PLAUSIBILITY_FAIL`) reduce confidence; critical flags force a hold. We don’t blindly accept sensor feeds — QC gates shrink the envelope or trigger a hold.

---

## Plausibility check (two-parameter consistency)

Many carbonate computations use two carbonate parameters (e.g. pH + pCO₂). We apply a **consistency check**: if the solved state is implausible given T/S and expected ranges → confidence → 0, **PLAUSIBILITY_FAIL**. That prevents operating on “garbage-in / plausible-looking UI” and keeps the MRV log defensible under audit.

---

## IoT system framing (6 criteria)

| Criterion | How we meet it |
|-----------|----------------|
| **Communications** | Store-and-forward; edge works without cloud |
| **Cloud–fog** | Decisions at edge; reporting in cloud |
| **Security** | Hash-chained logs (tamper evidence) |
| **Reliability** | QC gates + degraded modes |
| **Algorithms** | PyCO2SYS + envelope policy + plausibility |
| **User/device** | Operator sees cap, confidence, reasons, export |

---

## Auditability: hash-chained MRV log

Each decision record includes:

- Input snapshot (T, S, pH, pCO₂, …)
- Derived Ω_arag + envelope caps
- Confidence + flags
- `prev_hash` and `hash = HMAC_SHA256(secret, canonical_payload + prev_hash)`

Cloud can verify chain integrity end-to-end. The MRV requirement is **provenance** — we hash-chain every decision so any modification breaks verification.

---

## Demo scenarios

1. **Normal ops** — Fault simulator: Normal. Nonzero caps, Ω_arag above threshold, nonzero confidence, reason codes include method + mixing + synthetic label. Sync pending count shows store-and-forward.
2. **pH flatline** — Simulate stuck/fouled pH. System flags `STUCK_PH`, confidence drops, envelope tightens or hold if policy requires.
3. **Implausible pH** — Inject e.g. pH = 6.2. Flags: `OOR_PH`, `IMPLAUSIBLE_PH_PCO2`, `PLAUSIBILITY_FAIL`. Confidence → 0%, cap_low = cap_mid = cap_high = 0; UI shows HOLD + reason codes.

---

## Daily MRV Note (regulatory artifact)

Exportable summary for a given day:

- Average confidence, anomaly counts, time in HOLD / conservative mode
- Methodology version + config hash
- Latest event hash (chain-of-custody proof)

Export is offline-friendly (HTML/PDF).

---

## What works today

| Area | Status |
|------|--------|
| **Edge** | Decision loop runs on a fixed interval; PyCO2SYS carbonate solve → Ω_arag; envelope (cap_low/mid/high) with safety gate, temp penalty, missing-sensor penalties, tidal mixing, uncertainty spread. |
| **QC** | Sensor weights, in-range / OOR / missing; synthetic-data penalty; windowed stuck (variance), dropout (>30% missing), drift (linear slope); pH–pCO₂ plausibility gate → confidence 0 + PLAUSIBILITY_FAIL. |
| **Data** | Three-tier adapter: live MBARI ERDDAP attempt → pre-downloaded CSV → synthetic seed from M1 stats. Replay from CSV/seed with configurable speed; tidal amplitude from NOAA water level or fixed default. |
| **Fault simulator** | UI toggles: Normal, pH Flatline (stuck), pH Spike (implausible). Edge applies fault before QC; history clears on return to Normal so flags reset. |
| **Audit** | SQLite on edge with HMAC-SHA256 hash chain; store-and-forward sync to cloud; cloud stores synced decisions and serves Daily MRV Note by date. |
| **Cloud** | `POST /sync`, `GET /mrv_note?date_str=`, `GET /export?date_str=`, `GET /verify_chain`, `GET /health`. MRV Note = HTML summary + envelope + reason badges + methodology + decision table. |
| **UI** | Dashboard: envelope gauge (low/mid/high), confidence bar, reason badges, fault toggles, audit log (recent entries + sync status), export links (View MRV Note, Export Daily MRV Note). Chemistry panel for Ω_arag and method. |
| **Deploy** | Docker Compose: edge (8001), cloud (8002), ui (5173). Edge/cloud persist SQLite in mounted `data/`; UI uses env for API URLs. |

---

## What’s incomplete / next steps

| Gap or next step | Notes |
|------------------|--------|
| **Live MBARI ERDDAP** | Adapter has a slot for live CSV; currently falls back to seed or pre-downloaded file. Wire a background fetch, validate, then promote so real data is used when available. |
| **Windowed anomaly detection** | No z-score / spike filter yet. Add rolling window (e.g. 24 h) over audit rows, flag values >3σ, append `SENSOR_SPIKE_*` and confidence penalty. |
| **Real permit calibration** | BASE_RATE (120 t/day) and OMEGA_CEILING (4.0) are placeholders. Calibrate against actual OAE deployment permit and site capacity. |
| **Operator override + justification** | No formal “override hold” with logged reason. Add optional operator override that writes a signed justification into the audit chain. |
| **Regulatory export** | MRV Note is HTML only. Add JSON-LD summary for registries, per-decision chain snippet with verify link, and optional PDF (e.g. weasyprint). |
| **Multi-site / federation** | Single edge ↔ single cloud. Aggregator that polls multiple sites, merges chains with site IDs, and exposes a fleet-level report is not implemented. |
| **ML cap predictor (optional)** | Rule-based envelope only. Optional small model (e.g. XGBoost) trained on historical caps with rule fallback is scoped but not built. |

---

## Envelope & QC math (reference)

All of it lives in **`edge/envelope.py`** (cap) and **`edge/qc.py`** (confidence).

### `edge/envelope.py` — cap math

| Constant | Value | Meaning |
|----------|--------|---------|
| `BASE_RATE` | 120.0 t/day | Max discharge under ideal conditions |
| `OMEGA_SAFETY` | 1.2 | Hard zero below this |
| `OMEGA_CEILING` | 4.0 | Headroom denominator |

1. **Safety gate:** `if omega < 1.2` → `cap_low = cap_mid = cap_high = 0`.
2. **Headroom:** `headroom = (omega - 1.2) / (4.0 - 1.2)` clamped [0,1]; `cap_mid = 120.0 × headroom`. At Ω=2.2 (typical) → cap ≈ 36 t/day.
3. **Temperature:** `temp > 16°C` → cap_mid × 0.6; `temp > 14°C` → cap_mid × 0.85.
4. **Missing sensors:** pH missing → ×0.4; pCO₂ missing → ×0.7.
5. **Tidal mixing:** &lt;0.3 m → mixing_conf 0.3; 0.3–0.8 m → 0.6; ≥0.8 m → 1.0.
6. **Uncertainty spread:** `spread = 1 - (mixing_conf × sensor_confidence)`; `cap_low = cap_mid × (1 - spread×0.5)`; `cap_high = cap_mid × (1 + spread×0.3)`.

### `edge/qc.py` — confidence weights

| Sensor | Weight |
|--------|--------|
| pH | 0.35 |
| pCO2 | 0.25 |
| temperature | 0.20 |
| salinity | 0.12 |
| total_alkalinity | 0.08 |

- Sensor present + in-range → full weight; out-of-range → 50% + OOR_*; missing → 0 + MISSING_*.
- Multipliers: ×0.75 synthetic_seed; ×0.90 per DROPOUT_*; ×0.85 per STUCK_*; ×0.92 per DRIFT_*; =0 if IMPLAUSIBLE_PH_PCO2.

### How the numbers were chosen

| Parameter | Basis |
|-----------|--------|
| OMEGA_SAFETY = 1.2 | Below Ω=1 shells dissolve; 1.2 gives buffer |
| OMEGA_CEILING = 4.0 | Above typical surface ~2–3; “ideal” headroom |
| BASE_RATE = 120 t/day | Placeholder; needs real permit calibration |
| pH weight 0.35 | Primary observable for carbonate chemistry |
| SYNTHETIC_MULTIPLIER 0.75 | 25% haircut for non-calibrated data |
| STUCK_THRESHOLD[pH] 1e-6 | Variance &lt; 1e-6 ≈ frozen sensor |
| Plausibility | pH + 0.001×pCO2 ∈ [7.6, 9.4] (rough anti-correlation) |

The 120 t/day base and 4.0 ceiling are the ones most in need of real-world calibration against an actual OAE deployment permit.

---

## Next steps (technical)

- Windowed feature pipeline (30–60 min rolling stats)
- Better mixing proxies (currents / residence-time)
- Sensor redundancy + automatic failover
- Optional lightweight learned model: ship logistic weights JSON for p(unsafe)
- Formalize safety policy with operator override + logged justification

---

## Setup

### Prerequisites

- **Docker + Docker Compose** (easiest), or
- **Python 3.12+** (edge + cloud), **Node 18+** (UI)

### Option A: Docker Compose (recommended)

```bash
git clone <repo-url>
cd mrvcarbon
docker compose up --build
```

- **Edge API:** http://localhost:8001  
- **Cloud API:** http://localhost:8002  
- **UI:** http://localhost:5173  

Edge and cloud use SQLite under `edge/data` and `cloud/data`; UI talks to edge/cloud via the URLs above (set in docker-compose for the browser).

### Option B: Run services locally

**1. Edge (from repo root)**

```bash
cd edge
python -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
mkdir -p data
uvicorn main:app --host 0.0.0.0 --port 8001 --reload
```

**2. Cloud**

```bash
cd cloud
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
mkdir -p data
uvicorn main:app --host 0.0.0.0 --port 8002 --reload
```

**3. UI**

```bash
cd ui
npm install
npm run dev
```

UI defaults: `VITE_EDGE_URL=http://localhost:8001`, `VITE_CLOUD_URL=http://localhost:8002`. Override with a `.env` in `ui/` if needed.

### Environment (optional)

| Variable | Default | Description |
|----------|---------|-------------|
| `REPLAY_SPEED_X` | 60 | Replay speed multiplier for edge data |
| `CLOUD_SYNC_URL` | http://cloud:8002/sync | Cloud sync endpoint (edge) |
| `HMAC_KEY` | (dev key) | Set in production for audit hashes |
| `VITE_EDGE_URL` | http://localhost:8001 | Edge API base (UI) |
| `VITE_CLOUD_URL` | http://localhost:8002 | Cloud API base (UI) |

---

## License

See repository license file.
