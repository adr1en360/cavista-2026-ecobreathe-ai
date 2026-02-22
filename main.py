from contextlib import asynccontextmanager
from datetime import datetime, timezone
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from schemas import SensorPayload, SymptomEntry, OutcomeLabel
from risk_engine import assess_environment_risk
from aqi_service import (
    resolve_aqi_from_device,
    get_aqi_with_fallback,
    fetch_aqi_forecast,
    DEFAULT_LAT,
    DEFAULT_LON,
)
from database import (
    init_db,
    save_sensor_reading,
    get_latest_sensor_reading,
    get_reading_history,
    save_symptom_log,
    get_latest_symptom_log,
    save_aqi_cache,
    get_last_known_aqi,
    save_outcome_label,
    get_training_data,
)


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
    last_known = await get_last_known_aqi()
    aqi_info = await resolve_aqi_from_device(
        device_aqi=payload.aqi,
        request=request,
        last_known=last_known,
    )

    if aqi_info.get("source") == "open-meteo":
        await save_aqi_cache(aqi_info)

    latest_symptoms = await get_latest_symptom_log()

    risk = assess_environment_risk(
        temperature=payload.temperature,
        humidity=payload.humidity,
        aqi=aqi_info["aqi"],
        symptoms=latest_symptoms,
    )

    record = {
        "sensor_readings":   payload.model_dump(),
        "aqi_info":          aqi_info,
        "health_assessment": risk,
    }
    doc_id = await save_sensor_reading(record, risk)

    return {"status": "success", "id": doc_id}


# ---------------------------------------------------------------------------
# AQI endpoint
# ---------------------------------------------------------------------------

@app.post("/get-aqi", summary="Fetch AQI for a location")
async def get_aqi(request: Request, latitude: float = None, longitude: float = None):
    last_known = await get_last_known_aqi()
    aqi_info = await get_aqi_with_fallback(
        lat=latitude,
        lon=longitude,
        request=request,
        last_known=last_known,
    )
    if aqi_info.get("source") == "open-meteo":
        await save_aqi_cache(aqi_info)
    return aqi_info


# ---------------------------------------------------------------------------
# Forecast endpoint — AI prevention feature
# ---------------------------------------------------------------------------

@app.get("/forecast", summary="6 hour air quality forecast with risk trajectory")
async def get_forecast(latitude: float = None, longitude: float = None):
    """
    Fetches 6 hour AQI forecast and runs each hour through the risk engine.
    Returns a risk trajectory — improving, stable, or worsening.
    This is prevention not reaction: act before conditions deteriorate.
    """
    lat = latitude or DEFAULT_LAT
    lon = longitude or DEFAULT_LON

    forecast_data = await fetch_aqi_forecast(lat, lon)

    if not forecast_data:
        raise HTTPException(status_code=503, detail="Forecast data unavailable.")

    # Get current reading for temperature and humidity context
    current = await get_latest_sensor_reading()
    current_temp     = current["sensor_readings"].get("temperature", 30) if current else 30
    current_humidity = current["sensor_readings"].get("humidity", 70)    if current else 70

    forecast_risk = []
    for hour in forecast_data:
        if hour["aqi"] is not None:
            risk = assess_environment_risk(
                temperature=current_temp,
                humidity=current_humidity,
                aqi=hour["aqi"],
            )
            forecast_risk.append({
                "time":             hour["time"],
                "aqi":              hour["aqi"],
                "pm2_5":            hour["pm2_5"],
                "pm10":             hour["pm10"],
                "health_score":     risk["health_score"],
                "overall_status":   risk["overall_status"],
                "respiratory_risk": risk["respiratory_risk"],
            })

    # Determine trajectory from first to last hour
    trajectory = "Stable"
    if len(forecast_risk) >= 2:
        diff = forecast_risk[-1]["health_score"] - forecast_risk[0]["health_score"]
        if diff > 10:
            trajectory = "Improving"
        elif diff < -10:
            trajectory = "Worsening"

    return {
        "trajectory":     trajectory,
        "forecast_hours": forecast_risk,
        "coordinates":    {"latitude": lat, "longitude": lon},
        "generated_at":   datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Symptom diary
# ---------------------------------------------------------------------------

@app.post("/symptom-diary", summary="User logs current symptoms")
async def log_symptoms(entry: SymptomEntry):
    doc_id = await save_symptom_log(entry.model_dump())
    return {"status": "success", "id": doc_id}


# ---------------------------------------------------------------------------
# Outcome label — XGBoost training data collection
# ---------------------------------------------------------------------------

@app.post("/outcome", summary="User labels whether an episode occurred")
async def label_outcome(entry: OutcomeLabel):
    """
    User marks whether they had an asthma episode after a reading.
    Every labelled record becomes a training data point for XGBoost.
    """
    doc_id = await save_outcome_label(
        reading_id=entry.reading_id,
        had_episode=entry.had_episode,
        notes=entry.notes,
    )
    return {"status": "success", "id": doc_id}


@app.get("/training-data", summary="Export labelled records for XGBoost training")
async def export_training_data():
    """
    Returns all readings that have been labelled with outcomes.
    This is the dataset the XGBoost model trains on.
    """
    records = await get_training_data(limit=500)
    return {
        "count":   len(records),
        "records": records,
    }


# ---------------------------------------------------------------------------
# Dashboard read endpoints
# ---------------------------------------------------------------------------

@app.get("/latest-data", summary="Full latest record for the dashboard")
async def get_latest_data():
    doc = await get_latest_sensor_reading()
    if not doc:
        raise HTTPException(status_code=404, detail="No sensor data received yet.")
    return doc


@app.get("/risk-level", summary="Lightweight risk summary for frequent polling")
async def get_risk_level():
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
    readings = await get_reading_history(limit=50)
    return {"readings": readings}


@app.get("/health", summary="Service health check")
async def health_check():
    return {"status": "ok", "service": "EcoBreathe AI"}