from pydantic import BaseModel, Field
from typing import Optional
from enum import Enum


class SymptomSeverity(str, Enum):
    mild     = "mild"
    moderate = "moderate"
    severe   = "severe"


class SymptomItem(BaseModel):
    """A single symptom with its severity."""
    name: str = Field(..., min_length=1, max_length=100)
    severity: SymptomSeverity


class SensorPayload(BaseModel):
    temperature: float        = Field(..., ge=-10, le=60,  description="Celsius")
    humidity:    float        = Field(..., ge=0,   le=100, description="Relative humidity %")
    aqi:         int          = Field(..., ge=0,   le=500, description="AQI from ESP32 sensor")
    device_id:   Optional[str] = Field(default="esp32-001")
    latitude:    Optional[float] = Field(default=None, ge=-90,  le=90,  description="GPS lat from frontend")
    longitude:   Optional[float] = Field(default=None, ge=-180, le=180, description="GPS lon from frontend")


class SymptomEntry(BaseModel):
    """
    Matches the frontend symptom log UI exactly.
    - symptoms: the predefined buttons the user selected
    - other_symptoms: anything typed into the Other field
    - notes: the free text box
    """
    symptoms:       list[SymptomItem] = Field(default_factory=list)
    other_symptoms: list[SymptomItem] = Field(default_factory=list)
    notes:          Optional[str]     = Field(default=None, max_length=500)


class OutcomeLabel(BaseModel):
    """
    User labels whether they had an asthma episode after a reading.
    This is what trains the XGBoost model over time.
    """
    reading_id:  int
    had_episode: bool
    notes:       Optional[str] = Field(default=None, max_length=500)