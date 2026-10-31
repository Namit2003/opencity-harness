# OpenCity Harness

An open-source municipal AI harness. Type any city, show it a street image, and Gemma 4 evaluates four city safety pipelines in a single multimodal call, using live weather, air quality and US weather alerts.

| Pipeline | Looks for | Output |
| --- | --- | --- |
| `disaster` | Flooding, wildfire smoke, downed trees, active alerts | Hazard zone on the map |
| `grid` | Transformer fire, downed lines, extreme heat | Load-shedding advisory |
| `mobility` | Gridlock, crashes, stalled vehicles | Reroute advisory |
| `infrastructure` | Potholes, bridge cracks, blocked curb ramps | Draft Open311 ticket |

All actions are advisories. The worst finding is sent as one command byte to an LED matrix, with a virtual matrix in the dashboard. The Arduino UNO Q board app lives in `uno_q_edge/` and is still being integrated.

## How it works

Gemma returns only a score, summary and action for each pipeline. Validated output then goes through deterministic code: Pydantic checks the JSON and retries once on failure, code sets the status from the score (under 40 nominal, 40 to 74 warning, 75 and up critical), and code picks the command byte. If Gemma fails, the app returns an error instead of crashing.

## Model

- **Model:** [Gemma 4 26B A4B](https://huggingface.co/google/gemma-4-26b-a4b-it) (`gemma-4-26b-a4b-it`), open-weight, text and image input
- **Model license:** [Apache 2.0](https://ai.google.dev/gemma/docs/gemma_4_license)
- **Served through:** the Gemini API
- **Alternative:** `gemma-4-31b-it`, set with `GEMMA_MODEL`

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env    # add GEMINI_API_KEY
uvicorn app:app --port 8000
```

Open http://localhost:8000. Add `?mock=1` to explore the dashboard without a key.

Each module also runs alone:

```bash
python gemma_harness.py samples/flood.jpg
python city_feeds.py Raleigh
python hardware_client.py W
python gemma_harness.py --selftest
```

## Key dependencies

FastAPI, Uvicorn, HTTPX, Pydantic, python-dotenv and `google-genai`, with Tailwind and Leaflet in the dashboard. Live data comes from [Open-Meteo](https://open-meteo.com/) and the [National Weather Service](https://www.weather.gov/documentation/services-web-api). Map tiles © OpenStreetMap contributors.

## Layout

```
app.py              FastAPI wiring
gemma_harness.py    Prompt, validation, scoring, command byte
city_feeds.py       Live telemetry with a 60 second cache
hardware_client.py  Board client with mock fallback
static/index.html   Dashboard
samples/            Demo images
uno_q_edge/         Arduino UNO Q app (sketch and board API)
```

## License

MIT. See [LICENSE](LICENSE).
