"""
Three-tier sensor adapter:
1. Live MBARI ERDDAP CSV (may fail)
2. Pre-downloaded mbari_m1_live.csv
3. Synthetic seed from published M1 statistics
"""
import json
import math
import os
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
import pandas as pd
import numpy as np

from models import SensorReading

logger = logging.getLogger(__name__)

DATA_DIR = Path("/app/data")
NOAA_TEMP_PATH = DATA_DIR / "noaa_temp_raw.json"
NOAA_BARO_PATH = DATA_DIR / "noaa_baro_raw.json"
NOAA_WL_PATH = DATA_DIR / "noaa_wl_raw.json"
MBARI_LIVE_PATH = DATA_DIR / "mbari_m1_live.csv"
MBARI_SEED_PATH = DATA_DIR / "mbari_m1_seed.csv"

# Published M1 statistics (Johnson et al. 2013, Feely et al. 2008)
M1_STATS = {
    "pH_mean": 8.05, "pH_amp": 0.10,
    "pCO2_mean": 420.0, "pCO2_amp": 75.0,
    "salinity_mean": 33.5, "salinity_amp": 0.3,
    "TA_mean": 2300.0, "TA_amp": 20.0,
    "temp_mean": 12.5, "temp_amp": 3.0,
}

SYNTHETIC_N = 8760  # 1 year of hourly readings


def _generate_synthetic_seed() -> pd.DataFrame:
    """Generate synthetic M1-like data seeded from published statistics."""
    logger.info("Generating synthetic MBARI M1 seed data")
    rng = np.random.default_rng(42)
    t = np.linspace(0, 2 * math.pi, SYNTHETIC_N)

    # Seasonal sinusoid + noise
    pH = (
        M1_STATS["pH_mean"]
        + M1_STATS["pH_amp"] * np.sin(t)
        + rng.normal(0, 0.02, SYNTHETIC_N)
    )
    pCO2 = (
        M1_STATS["pCO2_mean"]
        - M1_STATS["pCO2_amp"] * np.sin(t)  # anti-correlated with pH
        + rng.normal(0, 15.0, SYNTHETIC_N)
    )
    salinity = (
        M1_STATS["salinity_mean"]
        + M1_STATS["salinity_amp"] * np.sin(t + 0.5)
        + rng.normal(0, 0.05, SYNTHETIC_N)
    )
    ta = (
        M1_STATS["TA_mean"]
        + M1_STATS["TA_amp"] * np.sin(t + 0.3)
        + rng.normal(0, 5.0, SYNTHETIC_N)
    )
    temp = (
        M1_STATS["temp_mean"]
        + M1_STATS["temp_amp"] * np.sin(t - 0.5)
        + rng.normal(0, 0.3, SYNTHETIC_N)
    )

    # Clip to realistic ranges
    pH = np.clip(pH, 7.80, 8.30)
    pCO2 = np.clip(pCO2, 300.0, 600.0)
    salinity = np.clip(salinity, 32.5, 34.5)
    ta = np.clip(ta, 2240.0, 2360.0)
    temp = np.clip(temp, 8.0, 18.0)

    start = pd.Timestamp("2024-01-01", tz="UTC")
    timestamps = pd.date_range(start, periods=SYNTHETIC_N, freq="h")

    df = pd.DataFrame({
        "time": timestamps,
        "temperature": temp,
        "salinity": salinity,
        "pH": pH,
        "pCO2": pCO2,
        "total_alkalinity": ta,
    })
    df.to_csv(MBARI_SEED_PATH, index=False)
    logger.info("Synthetic seed written to %s (%d rows)", MBARI_SEED_PATH, len(df))
    return df


def _load_mbari_df() -> tuple[pd.DataFrame, str]:
    """Load MBARI data: live CSV → seed CSV → generate seed. Returns (df, source)."""
    # Tier 1: live CSV
    if MBARI_LIVE_PATH.exists() and MBARI_LIVE_PATH.stat().st_size > 1000:
        try:
            df = pd.read_csv(MBARI_LIVE_PATH, parse_dates=["time"])
            if len(df) > 10:
                logger.info("Loaded MBARI live CSV (%d rows)", len(df))
                return df, "mbari_live"
        except Exception as e:
            logger.warning("Failed to load MBARI live CSV: %s", e)

    # Tier 2: pre-downloaded seed
    if MBARI_SEED_PATH.exists() and MBARI_SEED_PATH.stat().st_size > 1000:
        try:
            df = pd.read_csv(MBARI_SEED_PATH, parse_dates=["time"])
            if len(df) > 10:
                logger.info("Loaded MBARI seed CSV (%d rows)", len(df))
                return df, "synthetic_seed"
        except Exception as e:
            logger.warning("Failed to load MBARI seed CSV: %s", e)

    # Tier 3: generate synthetic seed
    df = _generate_synthetic_seed()
    return df, "synthetic_seed"


def _load_noaa_temp() -> dict[str, float]:
    """Load NOAA temperature time series, keyed by 'YYYY-MM-DD HH:MM'."""
    temps: dict[str, float] = {}
    if not NOAA_TEMP_PATH.exists():
        return temps
    try:
        with open(NOAA_TEMP_PATH) as f:
            data = json.load(f)
        for rec in data.get("data", []):
            try:
                temps[rec["t"]] = float(rec["v"])
            except (KeyError, ValueError):
                pass
    except Exception as e:
        logger.warning("Failed to load NOAA temp: %s", e)
    return temps


def _load_noaa_baro() -> dict[str, float]:
    """Load NOAA barometric pressure, keyed by 'YYYY-MM-DD HH:MM'."""
    baro: dict[str, float] = {}
    if not NOAA_BARO_PATH.exists():
        return baro
    try:
        with open(NOAA_BARO_PATH) as f:
            data = json.load(f)
        for rec in data.get("data", []):
            try:
                baro[rec["t"]] = float(rec["v"])
            except (KeyError, ValueError):
                pass
    except Exception as e:
        logger.warning("Failed to load NOAA baro: %s", e)
    return baro


def _load_noaa_wl() -> dict[str, float]:
    """Load NOAA water level, keyed by 'YYYY-MM-DD HH:MM'."""
    wl: dict[str, float] = {}
    if not NOAA_WL_PATH.exists():
        return wl
    try:
        with open(NOAA_WL_PATH) as f:
            data = json.load(f)
        for rec in data.get("data", []):
            try:
                wl[rec["t"]] = float(rec["v"])
            except (KeyError, ValueError):
                pass
    except Exception as e:
        logger.warning("Failed to load NOAA water level: %s", e)
    return wl


class SensorAdapter:
    def __init__(self):
        self.mbari_df, self.mbari_source = _load_mbari_df()
        self.noaa_temp = _load_noaa_temp()
        self.noaa_baro = _load_noaa_baro()
        self.noaa_wl = _load_noaa_wl()
        self._index = 0
        logger.info(
            "SensorAdapter ready: %d MBARI rows (%s), %d NOAA temp, %d NOAA baro, %d NOAA WL",
            len(self.mbari_df), self.mbari_source,
            len(self.noaa_temp), len(self.noaa_baro), len(self.noaa_wl),
        )

    @property
    def replay_index(self) -> int:
        return self._index

    @property
    def total_rows(self) -> int:
        return len(self.mbari_df)

    def next_reading(self) -> SensorReading:
        """Return next replayed MBARI row with NOAA overlays."""
        row = self.mbari_df.iloc[self._index % len(self.mbari_df)]
        replay_pos = self._index % len(self.mbari_df)
        self._index += 1

        # NOAA data is keyed by timestamp (e.g. Jan 2025 "YYYY-MM-DD HH:MM").
        # Use replay position to cycle through NOAA keys so lookups actually hit.
        noaa_key = None
        if self.noaa_temp:
            noaa_keys = list(self.noaa_temp.keys())
            noaa_key = noaa_keys[replay_pos % len(noaa_keys)]
        if noaa_key is None and self.noaa_baro:
            noaa_keys = list(self.noaa_baro.keys())
            noaa_key = noaa_keys[replay_pos % len(noaa_keys)]
        if noaa_key is None and self.noaa_wl:
            noaa_keys = list(self.noaa_wl.keys())
            noaa_key = noaa_keys[replay_pos % len(noaa_keys)]

        # NOAA temperature overrides MBARI temperature when available
        temp = self.noaa_temp.get(noaa_key) if noaa_key else None
        if temp is None:
            temp = row.get("temperature")
        baro = self.noaa_baro.get(noaa_key) if noaa_key else None

        # Water level for tidal amplitude proxy (use std dev of last hour)
        wl_value = self.noaa_wl.get(noaa_key) if noaa_key else None
        if wl_value is None and self.noaa_wl:
            wl_keys = list(self.noaa_wl.keys())
            wl_value = self.noaa_wl[wl_keys[replay_pos % len(wl_keys)]]

        # Extract carbonate params (may be missing in live CSV)
        def _safe(col: str) -> Optional[float]:
            v = row.get(col)
            if v is None or pd.isna(v):
                return None
            try:
                f = float(v)
                return None if math.isnan(f) else f
            except (TypeError, ValueError):
                return None

        # Use replayed row time; ensure timezone-aware for SensorReading
        row_ts = row.get("time")
        if hasattr(row_ts, "to_pydatetime"):
            row_ts = row_ts.to_pydatetime()
        if row_ts is not None and row_ts.tzinfo is None:
            row_ts = row_ts.replace(tzinfo=timezone.utc)
        if row_ts is None:
            row_ts = datetime.now(tz=timezone.utc)

        return SensorReading(
            timestamp=row_ts,
            temperature=float(temp) if temp is not None else None,
            salinity=_safe("salinity"),
            pH=_safe("pH"),
            pCO2=_safe("pCO2"),
            total_alkalinity=_safe("total_alkalinity"),
            baro_pressure=float(baro) if baro is not None else None,
            water_level=float(wl_value) if wl_value is not None else None,
            source=self.mbari_source,
        )

    def get_tidal_amplitude(self) -> float:
        """Compute approximate tidal range from WL window centered on replay position."""
        if not self.noaa_wl:
            return 1.0  # assume moderate mixing if no data
        vals = list(self.noaa_wl.values())
        n = len(vals)
        if n < 2:
            return 0.5
        pos = self.replay_index % n
        half = 30
        indices = [(pos - half + i) % n for i in range(60)]
        recent = [vals[i] for i in indices]
        return max(recent) - min(recent)
