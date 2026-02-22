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