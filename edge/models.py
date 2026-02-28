from pydantic import BaseModel, Field
from typing import Optional
from datetime import datetime


class SensorReading(BaseModel):
    timestamp: datetime
    temperature: Optional[float] = None
    salinity: Optional[float] = None
    pH: Optional[float] = None
    pCO2: Optional[float] = None
    total_alkalinity: Optional[float] = None
    baro_pressure: Optional[float] = None
    water_level: Optional[float] = None
    source: str = "synthetic"


class QCResult(BaseModel):
    reading: SensorReading
    confidence: float = Field(ge=0.0, le=1.0)
    flags: list[str] = []
    missing_sensors: list[str] = []
    out_of_range: list[str] = []


class EnvelopeDecision(BaseModel):
    timestamp: datetime
    cap_low: float
    cap_mid: float
    cap_high: float
    reason_codes: list[str]
    confidence: float = Field(ge=0.0, le=1.0)
    aragonite_saturation: float
    source: str
    row_hash: Optional[str] = None
    decision_id: Optional[int] = None


class SyncPayload(BaseModel):
    decisions: list[EnvelopeDecision]
    edge_id: str = "oae_edge_001"
