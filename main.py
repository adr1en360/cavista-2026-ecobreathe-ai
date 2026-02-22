from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from schemas import SensorPayload, SymptomEntry
from risk_engine import assess_environment_risk
from aqi_service import resolve_aqi_from_device, get_aqi_with_fallback
from database import (
    init_db,
    save_sensor_reading,
    get_latest_sensor_reading,
    get_reading_history,
    save_symptom_log,
    get_latest_symptom_log,
    save_aqi_cache,
    get_last_known_aqi,
)


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield


app = FastAPI(
    title="EcoBreathe AI",
    description="Backend bridging ESP32 hardware and the React dashboard.",
    version="1.0.0",
    lifespan=lifespan
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ---------------------------------------------------------------------------
# Hardware endpoint
# ---------------------------------------------------------------------------

@app.post("/sensor-data", summary="Receive data from ESP32")
async def receive_sensor_data(payload: SensorPayload, request: Request):
    """
    ESP32 hits this endpoint every 30-60 seconds.

    AQI resolution order:
        1. Device AQI is valid (1-400)  → use it, stamp source: device
        2. Device AQI is flagged        → run fallback chain via aqi_service
    """
    # 1. Resolve AQI — validate device value or run fallback
    last_known = await get_last_known_aqi()
    aqi_info = await resolve_aqi_from_device(
        device_aqi=payload.aqi,
        request=request,
        last_known=last_known,
    )

    # 2. If we got a fresh Open-Meteo result, cache it for future fallbacks
    if aqi_info.get("source") == "open-meteo":
        await save_aqi_cache(aqi_info)

    # 3. Pull latest symptom log
    latest_symptoms = await get_latest_symptom_log()

    # 4. Run risk assessment with resolved AQI
    risk = assess_environment_risk(
        temperature=payload.temperature,
        humidity=payload.humidity,
        aqi=aqi_info["aqi"],
        symptoms=latest_symptoms,
    )

    # 5. Build and save the full record
    record = {
        "sensor_readings": payload.model_dump(),
        "aqi_info":        aqi_info,
        "health_assessment": risk,
    }
    doc_id = await save_sensor_reading(record, risk)

    return {"status": "success", "id": doc_id}


# ---------------------------------------------------------------------------
# AQI endpoint — dashboard calls this independently
# ---------------------------------------------------------------------------

@app.post("/get-aqi", summary="Fetch AQI for a location")
async def get_aqi(request: Request, latitude: float = None, longitude: float = None):
    """
    Dashboard calls this on page load.
    Accepts optional GPS coordinates from the frontend.
    Runs the full fallback chain if coordinates are missing or fail.
    Frontend reads the source field to display the right label:
        device      → reading from ESP32 sensor
        open-meteo  → fetched from Open-Meteo API
        last_known  → cached value, API was unreachable
        unavailable → no data from any source
    """
    last_known = await get_last_known_aqi()
    aqi_info = await get_aqi_with_fallback(
        lat=latitude,
        lon=longitude,
        request=request,
        last_known=last_known,
    )

    # Cache any fresh Open-Meteo result
    if aqi_info.get("source") == "open-meteo":
        await save_aqi_cache(aqi_info)

    return aqi_info


# ---------------------------------------------------------------------------
# Symptom diary endpoint
# ---------------------------------------------------------------------------

@app.post("/symptom-diary", summary="User logs current symptoms")
async def log_symptoms(entry: SymptomEntry):
    """
    Receives structured symptom entry from the dashboard.
    Stored independently — factored into the next sensor reading automatically.
    """
    doc_id = await save_symptom_log(entry.model_dump())
    return {"status": "success", "id": doc_id}


# ---------------------------------------------------------------------------
# Dashboard read endpoints
# ---------------------------------------------------------------------------

@app.get("/latest-data", summary="Full latest record for the dashboard")
async def get_latest_data():
    """
    Returns the most recent sensor reading with full risk assessment and AQI info.
    """
    doc = await get_latest_sensor_reading()
    if not doc:
        raise HTTPException(status_code=404, detail="No sensor data received yet.")
    return doc


@app.get("/risk-level", summary="Lightweight risk summary for frequent polling")
async def get_risk_level():
    """
    Smaller payload than /latest-data.
    Poll this frequently to update the dashboard risk badge.
    """
    doc = await get_latest_sensor_reading()
    if not doc:
        raise HTTPException(status_code=404, detail="No data yet.")
    assessment = doc.get("health_assessment", {})
    aqi_info   = doc.get("aqi_info", {})
    return {
        "health_score":       assessment.get("health_score"),
        "overall_status":     assessment.get("overall_status"),
        "active_alerts":      assessment.get("active_alerts", []),
        "asthma_attack_risk": assessment.get("asthma_attack_risk"),
        "aqi_source":         aqi_info.get("source"),
        "flagged_device_aqi": aqi_info.get("flagged_device_aqi", False),
    }


@app.get("/history", summary="Trend data for dashboard charts")
async def get_history():
    """
    Returns last 50 readings oldest-first so charts render correctly.
    """
    readings = await get_reading_history(limit=50)
    return {"readings": readings}


@app.get("/health", summary="Service health check")
async def health_check():
    return {"status": "ok", "service": "EcoBreathe AI"}