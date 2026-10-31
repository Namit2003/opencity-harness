# OpenCity Harness: Build Spec

Oct 31, 2026 · @Namit Patel

## Overview

**OpenCity Harness** is an open-source municipal AI engine. Type any city, and it pulls live weather, air quality and US weather alerts. Show it a street image, and Gemma 4 evaluates 4 city safety pipelines in one pass. The worst finding lights up the LED matrix on an **Arduino UNO Q 4GB** sitting on the judges' table.

**Prizes:** Best Use of Gemma 4 (multimodal: image plus live telemetry in one call) and Best Open-Source AI Project (open-weight model, public repo, a reusable "harness" for city pipelines).

**Key change from the first draft:** on the UNO Q, USB-C connects to the Linux processor, not the microcontroller, so the laptop cannot talk to the sketch over `pyserial`. The laptop sends an HTTP request to a small app on the board, which calls the microcontroller through the RouterBridge.

## Architecture

```
LAPTOP                                              CLOUD APIs
+---------------------------------------------+    +----------------------+
|  Dashboard (static/index.html)              |    |                      |
|        |  POST /api/evaluate                |    |                      |
|        v                                    |    |                      |
|  FastAPI app (app.py) --+--> Gemma harness -------> Gemini API          |
|                         |   (score, byte)   |    |  (Gemma 4 26B / 31B) |
|                         +--> City feeds ---------> Open-Meteo + NWS     |
|                         |   (city_feeds.py) |    |  (weather/AQI/alerts)|
|                         +--> Board client   |    +----------------------+
|                             (POST /mode,    |
|                              mock fallback) |    ARDUINO UNO Q 4GB
+-------------------------------|-------------+    +----------------------+
                                +--------------------> Linux side         |
                                     Wi-Fi HTTP     |  (HTTP server :8080) |
                                                    |        | RouterBridge|
                                                    |        v             |
                                                    |  MCU sketch          |
                                                    |  (8x13 LED matrix)   |
                                                    +----------------------+
```

The laptop does all AI work and the board only receives one byte per evaluation, so a dead board never blocks the demo.

## Pipelines and command bytes

| Pipeline key | Triggers (image + telemetry) | UI action | Board action (8x13 matrix) | Byte |
| --- | --- | --- | --- | --- |
| `disaster` | Flooding, wildfire smoke, downed trees, active NWS alerts | Hazard polygon on Leaflet map | Flashing `[!]` hazard beacon | `W` |
| `grid` | Transformer fire or arc, downed lines, extreme heat | Load-shedding advisory | Load bars + built-in LED on (simulated relay) | `G` |
| `mobility` | Gridlock, crash, stalled vehicle, emergency vehicle | Reroute advisory, delay note | Lane arrows `<<<` / `>>>` | `T` |
| `infrastructure` | Potholes, bridge cracks, blocked curb ramps | Ready-to-submit Open311 ticket JSON | Work-zone checkerboard | `I` |
| none (all nominal) | Clear street, normal telemetry | Green heartbeat | Checkmark, built-in LED off | `0` |

Rows are in **tie-break priority order**: if two pipelines share the top score, the higher row wins.

## Contracts (freeze at minute 15)

Everyone builds against these. Do not change them without updating this file first.

**1. Backend endpoints** (Member 2 serves them)

- `GET /api/city?name=Raleigh` returns the `city` object below
- `POST /api/evaluate` with body `{"city": "Raleigh", "image_b64": "..."}` returns the full response below
- `GET /` serves `static/index.html`

**2. `/api/evaluate` response**

```json
{
  "city": {"name": "Raleigh", "lat": 35.7796, "lon": -78.6382, "temp_c": 24.5, "wind_kmh": 18.2,
           "precip_mm": 0.0, "us_aqi": 42, "active_alerts": ["Flood Watch"]},
  "gemma_pipelines": {
    "disaster":       {"status": "CRITICAL", "score": 92, "summary": "Standing water above curb height", "action": "Close underpass"},
    "grid":           {"status": "NOMINAL",  "score": 15, "summary": "No visible grid damage", "action": "None"},
    "mobility":       {"status": "WARNING",  "score": 65, "summary": "Stalled vehicle in right lane", "action": "Open shoulder lane"},
    "infrastructure": {"status": "NOMINAL",  "score": 10, "summary": "Road surface intact", "action": "None", "open311_category": "NONE"}
  },
  "hardware": {"command_byte": "W", "mode_label": "DISASTER_BEACON_ACTIVE", "connected": true, "mock": false},
  "latency_ms": 4200
}
```

**3. Scoring rules** (computed in code, never by Gemma)

- Gemma returns only `score` (0 to 100), `summary`, `action` per pipeline (+ `open311_category` for infrastructure)
- Code sets `status` from score: under 40 is `NOMINAL`, 40 to 74 is `WARNING`, 75+ is `CRITICAL`
- Code picks `command_byte`: the highest score wins; if every score is under 40, send `0`; ties follow the table order above

**4. Board API** (Member 4 serves it on the UNO Q, port 8080)

- `POST /mode` with `{"byte": "W"}` returns `{"ok": true, "mode": "W"}`
- `GET /health` returns `{"ok": true}`
- Laptop side: `send_to_arduino(byte) -> dict` posts with a 1 second timeout; on any error it returns `{"connected": false, "mock": true}` so the demo never crashes

## Repo layout and setup

```
opencity-harness/
├── app.py                 # Member 2: FastAPI, wiring
├── city_feeds.py          # Member 2: live telemetry
├── gemma_harness.py       # Member 1: Gemma call, scoring, command byte
├── hardware_client.py     # Member 4: send_to_arduino() over HTTP
├── static/index.html      # Member 3: dashboard
├── samples/               # Member 1: flood.jpg, crash.jpg, pothole.jpg, transformer_fire.jpg
└── uno_q_edge/            # Member 4: App Lab app (sketch + board-side Python)
```

**Env vars** (in `.env`, never committed)

- `GEMINI_API_KEY`: from Google AI Studio
- `GEMMA_MODEL`: `gemma-4-26b-a4b-it` (default, faster) or `gemma-4-31b-it`
- `BOARD_URL`: e.g. `http://192.168.1.50:8080` (the UNO Q's IP on venue Wi-Fi)
- `NWS_USER_AGENT`: e.g. `opencity-harness (your-email)`; the weather.gov API rejects requests without one

**Run**

```bash
pip install fastapi uvicorn httpx google-genai pydantic python-dotenv
uvicorn app:app --reload --port 8000
```

Each module must also run alone (`python gemma_harness.py samples/flood.jpg`, `python city_feeds.py Raleigh`, `python hardware_client.py W`) so integration is just imports.

## Roles (zero file overlap)

| Role | Owner | Files | Start against this mock |
| --- | --- | --- | --- |
| 1. Gemma harness | | `gemma_harness.py`, `samples/` | Any street photo + a hardcoded city dict |
| 2. City feeds + API | | `city_feeds.py`, `app.py` | Stub `evaluate_city_frame()` returning the contract JSON |
| 3. Dashboard | | `static/index.html` | The contract JSON saved as a static file |
| 4. UNO Q edge | | `uno_q_edge/`, `hardware_client.py` | Board API answered by a 5-line local FastAPI stub |

**Member 1: Gemma harness**

- [ ] `evaluate_city_frame(image_b64, telemetry) -> dict`: one Gemma 4 call with the image and telemetry text
- [ ] Prompt asks for JSON only with the 4 pipeline keys; validate with Pydantic, retry once with the error on failure
- [ ] `score_to_status()` and `pick_command_byte()` as pure functions, per the scoring rules
- [ ] Telemetry nudges scores (e.g. an active Flood Watch raises `disaster`), stated in the prompt
- [ ] 4 sample images in `samples/`, tested until each triggers its intended pipeline every time

**Member 2: City feeds + API**

- [ ] `get_city_telemetry(name) -> dict`, fetching in parallel with `httpx.AsyncClient`:
  - geocoding: `https://geocoding-api.open-meteo.com/v1/search?name={city}&count=1`
  - weather: `https://api.open-meteo.com/v1/forecast?latitude={lat}&longitude={lon}&current=temperature_2m,precipitation,wind_speed_10m`
  - air quality: `https://air-quality-api.open-meteo.com/v1/air-quality?latitude={lat}&longitude={lon}&current=us_aqi,pm2_5`
  - alerts: `https://api.weather.gov/alerts/active?point={lat},{lon}` with the `User-Agent` header; any error returns `[]`
- [ ] Cache telemetry per city for 60 seconds so repeated evaluations stay fast
- [ ] `app.py`: the 3 endpoints, calls `evaluate_city_frame()` then `send_to_arduino()`, adds `latency_ms`

**Member 3: Dashboard**

- [ ] Dark single-screen layout with Tailwind and Leaflet (dark tiles, e.g. CARTO Dark Matter)
- [ ] City search bar: flies the map, updates weather, AQI and alert badges
- [ ] Left panel: webcam via `getUserMedia`, Capture and Inspect button, 4 preset buttons using `samples/`
- [ ] Right panel: 4 pipeline cards with NOMINAL / WARNING / CRITICAL colors, plus a virtual 8x13 matrix mirroring the board
- [ ] Loading state during the 3 to 8 second Gemma call, and a hardware badge showing connected or mock

**Member 4: UNO Q edge** (riskiest piece, start the board first)

- [ ] Flash a blank App Lab example to confirm the toolchain works before writing anything
- [ ] Sketch: `Arduino_RouterBridge`, expose `set_mode` via `Bridge.provide`, draw 5 bitmaps on the 8x13 matrix, toggle the built-in LED
- [ ] Board-side Python: small HTTP server on port 8080 that calls `Bridge.call("set_mode", byte)`
- [ ] Verify exact Bridge and LED matrix APIs against App Lab's built-in examples; do not trust generated code for UNO Q specifics
- [ ] Note the board's Wi-Fi IP for `BOARD_URL`; write `hardware_client.py` with the 1 second timeout and mock fallback
- [ ] Prep a phone with full-screen hazard photos to hold up to the webcam during the demo

## Timeline

| Phase | Time | Work |
| --- | --- | --- |
| Lock spec | 0:00 to 0:15 | Freeze contracts; repo, `.env`, keys; board toolchain up |
| Build solo | 0:15 to 1:45 | Own files only, against mocks, commit often |
| Integrate | 1:45 to 2:15 | Wire `app.py`, real board IP, presets end to end |
| Polish | 2:15 to 2:45 | City switching, webcam + phone, 10 clean runs |
| Rehearse | 2:45 to 4:00 | 90s walkthrough, buffer for bugs, submit Devpost |

**Gates:**
- **1:00: Board answers HTTP**, else switch to plan B
- **2:15: End-to-end works**
- **2:45: Code freeze**

Start on the board in minute one, since the hardware bridge is the only part nobody has done before. Times are relative to when hacking starts.

## Risks and fallbacks

| Risk | Fallback |
| --- | --- |
| Board HTTP server or Bridge not working by 1:00 | Plan B: USB-to-serial adapter on header pins 0/1. Plan C: virtual matrix in the UI only, board shows a static demo animation |
| Board and laptop can't see each other on venue Wi-Fi | Phone hotspot for both devices |
| Gemma returns bad JSON | Pydantic validation + one retry; if still bad, return all-NOMINAL and show an error badge |
| Gemma too slow or rate limited | Switch `GEMMA_MODEL`; cache results for the 4 preset images |
| Webcam photo misread | Presets are the primary demo path; live webcam is the bonus |
| weather.gov errors or non-US city | Return empty alerts; Open-Meteo still covers every city |

**Pitch honesty:** call the built-in LED a "simulated relay", and present all actions as advisories, not real city control.
