"""Live city telemetry: Open-Meteo (geocode, weather, AQI) + NWS alerts."""
import asyncio
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()

CACHE_TTL_S = 60.0
_cache: dict = {}  # key -> (timestamp, dict)

GEO_URL = "https://geocoding-api.open-meteo.com/v1/search"
WEATHER_URL = "https://api.open-meteo.com/v1/forecast"
AQI_URL = "https://air-quality-api.open-meteo.com/v1/air-quality"
ALERTS_URL = "https://api.weather.gov/alerts/active"


async def _weather(client, lat, lon):
    try:
        r = await client.get(
            WEATHER_URL,
            params={"latitude": lat, "longitude": lon,
                    "current": "temperature_2m,precipitation,wind_speed_10m"},
        )
        r.raise_for_status()
        cur = r.json().get("current", {})
        return cur.get("temperature_2m"), cur.get("wind_speed_10m"), cur.get("precipitation")
    except Exception:
        return None, None, None


async def _aqi(client, lat, lon):
    try:
        r = await client.get(
            AQI_URL,
            params={"latitude": lat, "longitude": lon, "current": "us_aqi,pm2_5"},
        )
        r.raise_for_status()
        v = r.json().get("current", {}).get("us_aqi")
        return None if v is None else round(v)
    except Exception:
        return None


async def _alerts(client, lat, lon):
    try:
        ua = os.getenv("NWS_USER_AGENT") or "opencity-harness"
        r = await client.get(
            ALERTS_URL,
            params={"point": f"{lat},{lon}"},
            headers={"User-Agent": ua, "Accept": "application/geo+json"},
        )
        r.raise_for_status()
        out = []
        for f in r.json().get("features", []):
            ev = f.get("properties", {}).get("event")
            if ev and ev not in out:
                out.append(ev)
        return out
    except Exception:
        return []


async def _fetch(name: str) -> dict:
    async with httpx.AsyncClient(timeout=10.0) as client:
        try:
            r = await client.get(GEO_URL, params={"name": name, "count": 1})
            r.raise_for_status()
            results = r.json().get("results") or []
        except Exception as e:
            raise RuntimeError(f"Geocoding failed for {name!r}: {e}") from e
        if not results:
            raise ValueError(f"Unknown city: {name!r}")
        g = results[0]
        lat, lon = g["latitude"], g["longitude"]
        (temp, wind, precip), aqi, alerts = await asyncio.gather(
            _weather(client, lat, lon), _aqi(client, lat, lon), _alerts(client, lat, lon)
        )
    return {
        "name": g.get("name", name),
        "lat": lat,
        "lon": lon,
        "temp_c": temp,
        "wind_kmh": wind,
        "precip_mm": precip,
        "us_aqi": aqi,
        "active_alerts": alerts,
    }


async def get_city_telemetry(name: str) -> dict:
    name = (name or "").strip()
    if not name:
        raise ValueError("City name is required")
    key = name.lower()
    hit = _cache.get(key)
    if hit and time.monotonic() - hit[0] < CACHE_TTL_S:
        return dict(hit[1], active_alerts=list(hit[1]["active_alerts"]))
    data = await _fetch(name)
    _cache[key] = (time.monotonic(), data)
    return dict(data, active_alerts=list(data["active_alerts"]))


def _selftest():
    global _fetch
    calls = []
    real = _fetch

    async def fake(name):
        calls.append(name)
        return {"name": name, "lat": 1.0, "lon": 2.0, "temp_c": 20.0, "wind_kmh": 1.0,
                "precip_mm": 0.0, "us_aqi": 10, "active_alerts": []}

    _fetch = fake
    _cache.clear()
    try:
        a = asyncio.run(get_city_telemetry("Raleigh"))
        b = asyncio.run(get_city_telemetry("  raleigh "))
        assert len(calls) == 1 and a == b, "cache miss"
        _cache["raleigh"] = (time.monotonic() - CACHE_TTL_S - 1, _cache["raleigh"][1])
        asyncio.run(get_city_telemetry("RALEIGH"))
        assert len(calls) == 2, "expiry failed"
    finally:
        _fetch = real
        _cache.clear()
    print("city_feeds selftest OK")


if __name__ == "__main__":
    import json

    if "--selftest" in sys.argv:
        _selftest()
    else:
        city = " ".join(a for a in sys.argv[1:]) or "Raleigh"
        try:
            print(json.dumps(asyncio.run(get_city_telemetry(city)), indent=2))
        except ValueError as e:
            sys.exit(str(e))
