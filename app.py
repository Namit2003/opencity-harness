"""FastAPI wiring: city feeds + Gemma harness + board client."""
import asyncio
import re
import sys
import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import city_feeds
import hardware_client

try:
    import gemma_harness
except ImportError:  # lets --selftest run before gemma_harness.py exists
    gemma_harness = None

BASE = Path(__file__).parent
app = FastAPI(title="OpenCity Harness")

_DATA_URI = re.compile(r"^data:[^,]*;base64,", re.IGNORECASE)


class EvaluateRequest(BaseModel):
    city: str
    image_b64: str


async def _telemetry(name: str) -> dict:
    try:
        return await city_feeds.get_city_telemetry(name)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"City feeds unavailable: {e}")


@app.get("/api/city")
async def api_city(name: str):
    return await _telemetry(name)


@app.post("/api/evaluate")
async def api_evaluate(req: EvaluateRequest):
    t0 = time.perf_counter()
    city = await _telemetry(req.city)
    image_b64 = _DATA_URI.sub("", req.image_b64.strip())

    pipelines = dict(await asyncio.to_thread(gemma_harness.evaluate_city_frame, image_b64, city))
    error = pipelines.pop("_error", None)

    byte = gemma_harness.pick_command_byte(pipelines)
    label = gemma_harness.MODE_LABELS[byte]
    hw = await asyncio.to_thread(hardware_client.send_to_arduino, byte)

    resp = {
        "city": city,
        "gemma_pipelines": pipelines,
        "hardware": {
            "command_byte": byte,
            "mode_label": label,
            "connected": bool(hw.get("connected", False)),
            "mock": bool(hw.get("mock", True)),
        },
        "latency_ms": 0,
    }
    if error:
        resp["error"] = error
    resp["latency_ms"] = int((time.perf_counter() - t0) * 1000)
    return resp


@app.get("/")
async def index():
    p = BASE / "static" / "index.html"
    if not p.exists():
        raise HTTPException(status_code=404, detail="static/index.html not found")
    return FileResponse(p)


for _route, _dir in (("/samples", "samples"), ("/static", "static")):
    (BASE / _dir).mkdir(exist_ok=True)
    app.mount(_route, StaticFiles(directory=BASE / _dir), name=_dir)


def _selftest():
    import types

    from fastapi.testclient import TestClient

    stub = types.ModuleType("gemma_harness")
    stub.MODE_LABELS = {"W": "DISASTER_BEACON_ACTIVE", "0": "ALL_NOMINAL"}
    seen = {}

    def fake_eval(image_b64, telemetry):
        seen["img"] = image_b64
        out = {
            "disaster": {"status": "CRITICAL", "score": 92, "summary": "s", "action": "a"},
            "grid": {"status": "NOMINAL", "score": 15, "summary": "s", "action": "None"},
            "mobility": {"status": "WARNING", "score": 65, "summary": "s", "action": "a"},
            "infrastructure": {"status": "NOMINAL", "score": 10, "summary": "s",
                               "action": "None", "open311_category": "NONE"},
        }
        if image_b64 == "BAD":
            out["_error"] = "fallback"
        return out

    stub.evaluate_city_frame = fake_eval
    stub.pick_command_byte = lambda p: "W" if p["disaster"]["score"] >= 40 else "0"
    sys.modules["gemma_harness"] = stub
    global gemma_harness
    gemma_harness = stub
    hardware_client.send_to_arduino = lambda b: {"connected": False, "mock": True}

    c = TestClient(app)
    r = c.get("/api/city", params={"name": "Raleigh"})
    assert r.status_code == 200, r.text
    assert set(r.json()) == {"name", "lat", "lon", "temp_c", "wind_kmh", "precip_mm",
                             "us_aqi", "active_alerts"}, r.json()
    assert c.get("/api/city", params={"name": "Zzxqwvv"}).status_code == 404
    r = c.post("/api/evaluate", json={"city": "Raleigh", "image_b64": "data:image/jpeg;base64,QUJD"})
    assert r.status_code == 200, r.text
    j = r.json()
    assert seen["img"] == "QUJD"
    assert list(j) == ["city", "gemma_pipelines", "hardware", "latency_ms"], list(j)
    assert set(j["gemma_pipelines"]) == {"disaster", "grid", "mobility", "infrastructure"}
    assert j["hardware"] == {"command_byte": "W", "mode_label": "DISASTER_BEACON_ACTIVE",
                             "connected": False, "mock": True}
    assert isinstance(j["latency_ms"], int)
    j = c.post("/api/evaluate", json={"city": "Raleigh", "image_b64": "BAD"}).json()
    assert j["error"] == "fallback" and "_error" not in j["gemma_pipelines"]
    assert c.post("/api/evaluate", json={"city": "Zzxqwvv", "image_b64": "x"}).status_code == 404
    print("app selftest OK")


if __name__ == "__main__":
    if "--selftest" in sys.argv:
        _selftest()
    else:
        import uvicorn

        uvicorn.run("app:app", host="0.0.0.0", port=8000)
