"""
QC and confidence scorer.
Sensor weights: pH=0.35, pCO2=0.25, temp=0.20, salinity=0.12, TA=0.08
"""
import statistics
from models import SensorReading, QCResult

SENSOR_WEIGHTS = {
    "pH": 0.35,
    "pCO2": 0.25,
    "temperature": 0.20,
    "salinity": 0.12,
    "total_alkalinity": 0.08,
}

VALID_RANGES = {
    "pH": (7.50, 8.50),
    "pCO2": (200.0, 800.0),
    "temperature": (0.0, 30.0),
    "salinity": (28.0, 38.0),
    "total_alkalinity": (2100.0, 2500.0),
    "baro_pressure": (950.0, 1060.0),
    "water_level": (-2.0, 5.0),
}

SYNTHETIC_MULTIPLIER = 0.75

# Field name mapping: sensor key → SensorReading attribute and flag suffix
_ANOMALY_FIELDS = {
    "ph": ("pH", "PH"),
    "pco2": ("pCO2", "PCO2"),
    "temperature": ("temperature", "TEMPERATURE"),
    "salinity": ("salinity", "SALINITY"),
    "total_alkalinity": ("total_alkalinity", "TA"),
}

STUCK_THRESHOLDS = {
    "ph": 1e-6,
    "pco2": 0.01,
    "temperature": 0.01,
    "salinity": 1e-6,
    "total_alkalinity": 0.01,
}

DRIFT_SCALES = {
    "ph": 0.1,
    "pco2": 50.0,
    "temperature": 2.0,
    "salinity": 0.5,
    "total_alkalinity": 20.0,
}
DRIFT_THRESHOLD = 0.05  # 5% of scale per window


def _linear_regression_slope_r2(xs: list[float], ys: list[float]) -> tuple[float, float]:
    """Return (slope, r_squared) via simple least-squares."""
    n = len(xs)
    if n < 2:
        return 0.0, 0.0
    x_mean = sum(xs) / n
    y_mean = sum(ys) / n
    ss_xx = sum((x - x_mean) ** 2 for x in xs)
    ss_xy = sum((x - x_mean) * (y - y_mean) for x, y in zip(xs, ys))
    ss_yy = sum((y - y_mean) ** 2 for y in ys)
    if ss_xx == 0:
        return 0.0, 0.0
    slope = ss_xy / ss_xx
    r2 = (ss_xy ** 2 / (ss_xx * ss_yy)) if ss_yy > 0 else 0.0
    return slope, r2


def run_qc(reading: SensorReading, history: list[SensorReading] | None = None) -> QCResult:
    flags: list[str] = []
    missing: list[str] = []
    out_of_range: list[str] = []

    weighted_score = 0.0
    total_weight = 0.0

    for sensor, weight in SENSOR_WEIGHTS.items():
        value = getattr(reading, sensor, None)
        total_weight += weight

        if value is None:
            missing.append(sensor)
            flags.append(f"MISSING_{sensor.upper()}")
            # No credit for missing sensors
            continue

        lo, hi = VALID_RANGES.get(sensor, (-1e9, 1e9))
        if not (lo <= value <= hi):
            out_of_range.append(sensor)
            flags.append(f"OOR_{sensor.upper()}")
            weighted_score += weight * 0.5  # 50% credit for out-of-range
        else:
            weighted_score += weight

    # Normalize to 0-1
    confidence = weighted_score / total_weight if total_weight > 0 else 0.0

    # Source penalty
    if reading.source == "synthetic_seed":
        confidence *= SYNTHETIC_MULTIPLIER
        flags.append("SYNTHETIC_DATA")

    # Windowed anomaly detection
    if history and len(history) >= 10:
        for key, (attr, flag_suffix) in _ANOMALY_FIELDS.items():
            hist_vals = [getattr(r, attr, None) for r in history]
            none_count = sum(1 for v in hist_vals if v is None)
            non_none = [v for v in hist_vals if v is not None]

            # Dropout: too many missing values
            if none_count / len(history) > 0.30:
                flags.append(f"DROPOUT_{flag_suffix}")
                confidence *= 0.90

            # Stuck sensor: variance near zero
            if len(non_none) >= 10:
                var = statistics.variance(non_none)
                if var < STUCK_THRESHOLDS[key]:
                    flags.append(f"STUCK_{flag_suffix}")
                    confidence *= 0.85

                # Drift: sustained linear slope
                xs = [float(i) for i in range(len(non_none))]
                slope, r2 = _linear_regression_slope_r2(xs, non_none)
                scale = DRIFT_SCALES[key]
                if abs(slope) / scale > DRIFT_THRESHOLD and r2 > 0.7:
                    flags.append(f"DRIFT_{flag_suffix}")
                    confidence *= 0.92

    # Cross-sensor plausibility: pH and pCO2 are anti-correlated in seawater.
    # A simple proxy: pH + 0.001 * pCO2 ≈ 8.5 ± 0.9 for open ocean surface.
    # Values outside that band indicate physically inconsistent readings.
    ph = reading.pH
    pco2 = reading.pCO2
    if ph is not None and pco2 is not None:
        proxy = ph + 0.001 * pco2
        if proxy < 7.6 or proxy > 9.4:
            flags.append("IMPLAUSIBLE_PH_PCO2")
            confidence = 0.0

    confidence = max(0.0, min(1.0, confidence))

    return QCResult(
        reading=reading,
        confidence=round(confidence, 4),
        flags=flags,
        missing_sensors=missing,
        out_of_range=out_of_range,
    )
