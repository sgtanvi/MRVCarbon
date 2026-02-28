"""
Operating envelope engine.

Outputs cap_low / cap_mid / cap_high (tonnes/day) with reason codes.

Key rules:
- Safety gate: Omega_arag < 1.2 → cap = 0
- Base = 120 t/day × headroom_fraction (Omega_arag vs ceiling of 4.0)
- Temp penalty: >16°C → ×0.6, >14°C → ×0.85
- Tidal mixing: <0.3m range → mixing_confidence=0.3
- Missing pH → ×0.4, missing pCO2 → ×0.7
- spread = 1 - (mixing_confidence × sensor_confidence)
- cap_low = cap_mid × (1 - spread×0.5)
- cap_high = cap_mid × (1 + spread×0.3)
"""
from datetime import datetime, timezone
from models import QCResult, EnvelopeDecision
from carbonate import compute_aragonite

BASE_RATE = 120.0       # t/day — max rate under ideal conditions
OMEGA_CEILING = 4.0     # target max Omega for headroom calc
OMEGA_SAFETY = 1.2      # below this → hard zero
TEMP_HIGH = 16.0        # °C
TEMP_MED = 14.0         # °C


def compute_envelope(
    qc: QCResult,
    tidal_amplitude: float,
) -> EnvelopeDecision:
    reading = qc.reading
    reason_codes: list[str] = list(qc.flags)

    # --- Plausibility hard stop ---
    if "IMPLAUSIBLE_PH_PCO2" in qc.flags:
        reason_codes.append("PLAUSIBILITY_FAIL")
        return EnvelopeDecision(
            timestamp=datetime.now(tz=timezone.utc),
            cap_low=0.0,
            cap_mid=0.0,
            cap_high=0.0,
            reason_codes=reason_codes,
            confidence=0.0,
            aragonite_saturation=0.0,
            source=reading.source,
        )

    # --- Carbonate system ---
    omega, carb_method = compute_aragonite(
        pH=reading.pH,
        pCO2=reading.pCO2,
        total_alkalinity=reading.total_alkalinity,
        salinity=reading.salinity or 33.5,
        temperature=reading.temperature or 12.5,
    )
    reason_codes.append(f"CARB_METHOD:{carb_method}")

    # --- Safety gate ---
    if omega < OMEGA_SAFETY:
        reason_codes.append("OMEGA_BELOW_SAFETY_THRESHOLD")
        return EnvelopeDecision(
            timestamp=datetime.now(tz=timezone.utc),
            cap_low=0.0,
            cap_mid=0.0,
            cap_high=0.0,
            reason_codes=reason_codes,
            confidence=qc.confidence,
            aragonite_saturation=round(omega, 4),
            source=reading.source,
        )

    # --- Headroom fraction ---
    headroom = max(0.0, min(1.0, (omega - OMEGA_SAFETY) / (OMEGA_CEILING - OMEGA_SAFETY)))
    cap_mid = BASE_RATE * headroom

    # --- Temperature penalty ---
    temp = reading.temperature
    if temp is not None:
        if temp > TEMP_HIGH:
            cap_mid *= 0.6
            reason_codes.append(f"TEMP_HIGH:{temp:.1f}C")
        elif temp > TEMP_MED:
            cap_mid *= 0.85
            reason_codes.append(f"TEMP_ELEVATED:{temp:.1f}C")

    # --- Missing sensor penalties ---
    if reading.pH is None:
        cap_mid *= 0.4
        reason_codes.append("PENALTY_MISSING_PH")
    if reading.pCO2 is None:
        cap_mid *= 0.7
        reason_codes.append("PENALTY_MISSING_PCO2")

    # --- Tidal mixing confidence ---
    if tidal_amplitude < 0.3:
        mixing_confidence = 0.3
        reason_codes.append("LOW_TIDAL_MIXING")
    elif tidal_amplitude < 0.8:
        mixing_confidence = 0.6
    else:
        mixing_confidence = 1.0

    # --- Uncertainty spread ---
    spread = 1.0 - (mixing_confidence * qc.confidence)
    spread = max(0.0, min(1.0, spread))

    cap_low = cap_mid * (1.0 - spread * 0.5)
    cap_high = cap_mid * (1.0 + spread * 0.3)

    reason_codes.append(f"OMEGA_ARAG:{omega:.3f}")
    reason_codes.append(f"HEADROOM:{headroom:.2f}")
    reason_codes.append(f"TIDAL_AMP:{tidal_amplitude:.2f}m")

    return EnvelopeDecision(
        timestamp=datetime.now(tz=timezone.utc),
        cap_low=round(max(0.0, cap_low), 2),
        cap_mid=round(max(0.0, cap_mid), 2),
        cap_high=round(max(0.0, cap_high), 2),
        reason_codes=reason_codes,
        confidence=round(qc.confidence, 4),
        aragonite_saturation=round(omega, 4),
        source=reading.source,
    )
