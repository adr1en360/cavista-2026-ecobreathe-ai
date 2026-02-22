import asyncio
from aqi_service import fetch_aqi, get_aqi_with_fallback, is_device_aqi_valid


async def main():
    print("--- Test 1: Valid Lagos coordinates ---")
    result = await get_aqi_with_fallback(lat=6.5244, lon=3.3792)
    print(result)
    assert result["source"] == "open-meteo"
    assert result["coordinate_source"] == "gps"

    print("\n--- Test 2: No coordinates (default Lagos fallback) ---")
    result = await get_aqi_with_fallback()
    print(result)
    assert result["source"] == "open-meteo"
    assert result["coordinate_source"] == "default"

    print("\n--- Test 3: Bad coordinates, last known available ---")
    fake_last_known = {
        "aqi": 95,
        "pm2_5": 28.1,
        "pm10": 80.0,
        "fetched_at": "2026-02-21T22:00:00+00:00",
    }
    result = await get_aqi_with_fallback(lat=999, lon=999, last_known=fake_last_known)
    print(result)
    assert result["source"] == "last_known"
    assert result["aqi"] == 95

    print("\n--- Test 4: Bad coordinates, no last known (unavailable) ---")
    result = await get_aqi_with_fallback(lat=999, lon=999)
    print(result)
    assert result["source"] == "unavailable"
    assert result["aqi"] is None

    print("\n--- Test 5: Device AQI validation ---")
    assert is_device_aqi_valid(115)  is True,  "115 should be valid"
    assert is_device_aqi_valid(0)    is False,  "0 should be flagged"
    assert is_device_aqi_valid(500)  is False,  "500 should be flagged"
    assert is_device_aqi_valid(401)  is False,  "401 should be flagged"
    assert is_device_aqi_valid(400)  is True,   "400 should be valid"
    assert is_device_aqi_valid(1)    is True,   "1 should be valid"
    print("All validation checks passed.")

    print("\n--- All tests passed ---")


asyncio.run(main())