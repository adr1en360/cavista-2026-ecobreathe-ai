import aiosqlite
import json
import os
from datetime import datetime, timezone

DB_PATH = os.getenv("DB_PATH", "ecobreathe.db")


# ---------------------------------------------------------------------------
# Setup
# ---------------------------------------------------------------------------

async def init_db():
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS sensor_readings (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp   TEXT NOT NULL,
                sensor_data TEXT NOT NULL,
                risk_data   TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS symptom_logs (
                id        INTEGER PRIMARY KEY AUTOINCREMENT,
                logged_at TEXT NOT NULL,
                entry     TEXT NOT NULL
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS aqi_cache (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                fetched_at TEXT NOT NULL,
                aqi_data   TEXT NOT NULL
            )
        """)
        # inside init_db(), add this table:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS outcome_labels (
                id          INTEGER PRIMARY KEY AUTOINCREMENT,
                reading_id  INTEGER NOT NULL,
                labeled_at  TEXT NOT NULL,
                had_episode INTEGER NOT NULL,
                notes       TEXT
            )
        """)
        await db.commit()


# ---------------------------------------------------------------------------
# Sensor readings
# ---------------------------------------------------------------------------

async def save_sensor_reading(record: dict, risk: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO sensor_readings (timestamp, sensor_data, risk_data) VALUES (?, ?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                json.dumps(record),
                json.dumps(risk),
            )
        )
        await db.commit()
        return cursor.lastrowid


async def get_latest_sensor_reading() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None

        record = json.loads(row["sensor_data"])

        return {
            "id":                row["id"],
            "timestamp":         row["timestamp"],
            "sensor_readings":   record.get("sensor_readings", {}),
            "aqi_info":          record.get("aqi_info", {}),
            "health_assessment": record.get("health_assessment", {}),
        }


async def get_reading_history(limit: int = 50) -> list:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM sensor_readings ORDER BY id DESC LIMIT ?", (limit,)
        )
        rows = await cursor.fetchall()
        results = [
            {
                "id":          row["id"],
                "timestamp":   row["timestamp"],
                "sensor_readings": json.loads(row["sensor_data"]).get("sensor_readings", {}),
                "aqi_info":        json.loads(row["sensor_data"]).get("aqi_info", {}),
                "health_score":    json.loads(row["risk_data"]).get("health_score"),
            }
            for row in rows
        ]
        return list(reversed(results))


# ---------------------------------------------------------------------------
# Symptom logs
# ---------------------------------------------------------------------------

async def save_symptom_log(entry: dict) -> int:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO symptom_logs (logged_at, entry) VALUES (?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                json.dumps(entry),
            )
        )
        await db.commit()
        return cursor.lastrowid


async def get_latest_symptom_log() -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM symptom_logs ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row["entry"])


# ---------------------------------------------------------------------------
# AQI cache — last known good from Open-Meteo
# ---------------------------------------------------------------------------

async def save_aqi_cache(aqi_data: dict) -> int:
    """Saves the most recent successful Open-Meteo response."""
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO aqi_cache (fetched_at, aqi_data) VALUES (?, ?)",
            (
                datetime.now(timezone.utc).isoformat(),
                json.dumps(aqi_data),
            )
        )
        await db.commit()
        return cursor.lastrowid


async def get_last_known_aqi() -> dict | None:
    """
    Retrieves the most recent cached AQI result.
    Used as the third fallback when Open-Meteo is unreachable.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            "SELECT * FROM aqi_cache ORDER BY id DESC LIMIT 1"
        )
        row = await cursor.fetchone()
        if not row:
            return None
        return json.loads(row["aqi_data"])


# ---------------------------------------------------------------------------
# Outcome labels — XGBoost training data
# ---------------------------------------------------------------------------

async def save_outcome_label(reading_id: int, had_episode: bool, notes: str = None) -> int:
    """
    User labels whether they had an asthma episode after a reading.
    This is the training target for the XGBoost model.
    had_episode: True = episode occurred, False = no episode
    """
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "INSERT INTO outcome_labels (reading_id, labeled_at, had_episode, notes) VALUES (?, ?, ?, ?)",
            (
                reading_id,
                datetime.now(timezone.utc).isoformat(),
                1 if had_episode else 0,
                notes,
            )
        )
        await db.commit()
        return cursor.lastrowid


async def get_training_data(limit: int = 500) -> list:
    """
    Joins sensor readings with outcome labels.
    Returns structured training records ready for XGBoost.
    """
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("""
            SELECT
                sr.id,
                sr.timestamp,
                sr.sensor_data,
                sr.risk_data,
                ol.had_episode,
                ol.notes
            FROM sensor_readings sr
            JOIN outcome_labels ol ON sr.id = ol.reading_id
            ORDER BY sr.id DESC
            LIMIT ?
        """, (limit,))
        rows = await cursor.fetchall()
        results = []
        for row in rows:
            sensor = json.loads(row["sensor_data"])
            risk   = json.loads(row["risk_data"])
            readings = sensor.get("sensor_readings", {})
            results.append({
                "id":              row["id"],
                "timestamp":       row["timestamp"],
                "temperature":     readings.get("temperature"),
                "humidity":        readings.get("humidity"),
                "aqi":             readings.get("aqi"),
                "heat_score":      risk.get("health_score"),
                "heat_risk":       risk.get("heat_stress_risk"),
                "respiratory_risk":risk.get("respiratory_risk"),
                "had_episode":     bool(row["had_episode"]),
            })
        return results