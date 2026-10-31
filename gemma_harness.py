"""OpenCity Harness: Gemma 4 evaluation of 4 city safety pipelines.

Public API
----------
evaluate_city_frame(image_b64, telemetry) -> dict
    Returns ONLY the ``gemma_pipelines`` dict (keys: disaster, grid, mobility,
    infrastructure). Each entry has status, score, summary, action;
    infrastructure also has open311_category.

    Failure convention: if the API key is missing, the API errors, or the
    output is still invalid after one retry, every pipeline is NOMINAL
    (score 0, summary notes the error) and the dict gains an extra key
    ``"_error": "<msg>"``. ``_error`` is present ONLY in that case. app.py
    should pop it (``pipes.pop("_error", None)``) and surface it as an error
    badge before putting the dict in the response.

score_to_status(score) -> str
pick_command_byte(pipelines) -> str
MODE_LABELS: dict byte -> label

Thread safety: no shared mutable state, so safe for asyncio.to_thread.
"""
from __future__ import annotations

import base64
import json
import os
import re
import sys

from dotenv import load_dotenv
from pydantic import BaseModel, Field, ValidationError

load_dotenv()

PIPELINE_KEYS = ("disaster", "grid", "mobility", "infrastructure")
BYTE_FOR = {"disaster": "W", "grid": "G", "mobility": "T", "infrastructure": "I"}
MODE_LABELS = {
    "W": "DISASTER_BEACON_ACTIVE",
    "G": "GRID_LOAD_SHED_ACTIVE",
    "T": "MOBILITY_REROUTE_ACTIVE",
    "I": "INFRA_WORKZONE_ACTIVE",
    "0": "ALL_NOMINAL",
}
DEFAULT_MODEL = "gemma-4-26b-a4b-it"


def score_to_status(score) -> str:
    s = float(score)
    if s < 40:
        return "NOMINAL"
    if s < 75:
        return "WARNING"
    return "CRITICAL"


def pick_command_byte(pipelines: dict) -> str:
    best_key, best = None, -1.0
    for key in PIPELINE_KEYS:  # table order resolves ties (strict >)
        entry = pipelines.get(key)
        if not entry:
            continue
        sc = float(entry.get("score", 0))
        if sc > best:
            best_key, best = key, sc
    if best_key is None or best < 40:
        return "0"
    return BYTE_FOR[best_key]


# ---------- validation models ----------
class _Pipe(BaseModel):
    score: float = Field(ge=-1000, le=1000)
    summary: str = ""
    action: str = "None"


class _Infra(_Pipe):
    open311_category: str = "NONE"


class _GemmaOut(BaseModel):
    disaster: _Pipe
    grid: _Pipe
    mobility: _Pipe
    infrastructure: _Infra


PROMPT = """You are a municipal city-safety inspector. Look at the street image and the live telemetry, then evaluate FOUR pipelines in one pass.

Pipelines:
- disaster: flooding, wildfire smoke, downed trees, active weather alerts
- grid: transformer fire or arcing, downed power lines, extreme heat stress on the grid
- mobility: gridlock, crash, stalled vehicle, emergency vehicle
- infrastructure: potholes, bridge cracks, blocked curb ramps

For each pipeline give a score from 0 (nothing wrong) to 100 (severe, immediate danger), a one-sentence summary of what you see, and a short recommended action ("None" if nominal). For infrastructure also give open311_category, e.g. "Pothole", "Bridge Damage", "Curb Ramp Obstruction", or "NONE".

Telemetry nudges (apply on top of what the image shows):
- An active Flood Watch/Warning or heavy precipitation raises disaster.
- High AQI (above 150) or wildfire smoke raises disaster.
- Extreme heat (above 38 C) raises grid.
- Other active alerts raise the relevant pipeline modestly.
- If the image shows nothing wrong and telemetry is normal, keep all scores low (under 25).

Telemetry:
{telemetry}

Respond with JSON ONLY, no prose and no markdown fences, exactly this shape:
{{"disaster": {{"score": 0, "summary": "", "action": ""}},
 "grid": {{"score": 0, "summary": "", "action": ""}},
 "mobility": {{"score": 0, "summary": "", "action": ""}},
 "infrastructure": {{"score": 0, "summary": "", "action": "", "open311_category": ""}}}}"""


def _strip_fences(text: str) -> str:
    t = (text or "").strip()
    m = re.search(r"```(?:json|JSON)?\s*(.*?)```", t, re.DOTALL)
    if m:
        t = m.group(1).strip()
    if not t.startswith("{"):
        i, j = t.find("{"), t.rfind("}")
        if i != -1 and j > i:
            t = t[i : j + 1]
    return t


def _parse(text: str) -> dict:
    """Parse + validate model text into the final pipelines dict. Raises on bad input."""
    data = json.loads(_strip_fences(text))
    out = _GemmaOut.model_validate(data)
    result = {}
    for key in PIPELINE_KEYS:
        entry = getattr(out, key).model_dump()
        entry["score"] = int(round(max(0.0, min(100.0, entry["score"]))))
        entry["status"] = score_to_status(entry["score"])
        ordered = {
            "status": entry["status"],
            "score": entry["score"],
            "summary": entry["summary"],
            "action": entry["action"] or "None",
        }
        if key == "infrastructure":
            ordered["open311_category"] = entry["open311_category"] or "NONE"
        result[key] = ordered
    return result


def _fallback(msg: str) -> dict:
    res = {}
    for key in PIPELINE_KEYS:
        res[key] = {
            "status": "NOMINAL",
            "score": 0,
            "summary": f"Gemma unavailable: {msg}"[:200],
            "action": "None",
        }
    res["infrastructure"]["open311_category"] = "NONE"
    res["_error"] = msg
    return res


def _call_gemma(client, model: str, image_bytes: bytes, prompt: str) -> str:
    from google.genai import types

    resp = client.models.generate_content(
        model=model,
        contents=[
            types.Part.from_bytes(data=image_bytes, mime_type=_mime(image_bytes)),
            prompt,
        ],
        # Thinking dominates latency (~30s+); the JSON task doesn't need it.
        config=types.GenerateContentConfig(
            thinking_config=types.ThinkingConfig(thinking_level="MINIMAL")
        ),
    )
    return resp.text or ""


def _mime(b: bytes) -> str:
    if b[:8] == b"\x89PNG\r\n\x1a\n":
        return "image/png"
    if b[:4] == b"RIFF" and b[8:12] == b"WEBP":
        return "image/webp"
    return "image/jpeg"


def _decode_image(image_b64: str) -> bytes:
    if image_b64.startswith("data:") and "," in image_b64:
        image_b64 = image_b64.split(",", 1)[1]
    return base64.b64decode(image_b64)


def evaluate_city_frame(image_b64: str, telemetry: dict) -> dict:
    """See module docstring. Never raises; failure returns all-NOMINAL plus ``_error``."""
    try:
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            return _fallback("GEMINI_API_KEY not set")
        try:
            image_bytes = _decode_image(image_b64)
        except Exception as e:
            return _fallback(f"invalid image: {e}")
        if not image_bytes:
            return _fallback("empty image")
        from google import genai

        client = genai.Client(api_key=api_key)
        model = os.getenv("GEMMA_MODEL", DEFAULT_MODEL)
        base = PROMPT.format(telemetry=json.dumps(telemetry, indent=2, default=str))
        prompt = base
        last_err = "unknown"
        for attempt in range(2):
            text = ""
            try:
                text = _call_gemma(client, model, image_bytes, prompt)
                return _parse(text)
            except (ValidationError, ValueError) as e:  # JSONDecodeError is a ValueError
                last_err = f"invalid model output: {str(e)[:300]}"
                prompt = (
                    base
                    + f"\n\nYour previous reply was invalid.\nReply: {text[:500]}\n"
                    f"Error: {str(e)[:500]}\nReturn corrected JSON ONLY."
                )
            except Exception as e:
                return _fallback(f"API error: {str(e)[:200]}")
        return _fallback(last_err)
    except Exception as e:  # last-resort guard
        return _fallback(f"unexpected error: {str(e)[:200]}")


# ---------- standalone ----------
RALEIGH = {
    "name": "Raleigh", "lat": 35.7796, "lon": -78.6382, "temp_c": 24.5,
    "wind_kmh": 18.2, "precip_mm": 0.0, "us_aqi": 42, "active_alerts": ["Flood Watch"],
}


def _selftest() -> None:
    from unittest import mock

    for s, e in [(0, "NOMINAL"), (39, "NOMINAL"), (40, "WARNING"), (74, "WARNING"),
                 (75, "CRITICAL"), (100, "CRITICAL")]:
        assert score_to_status(s) == e, (s, e)

    def mk(d=0, g=0, m=0, i=0):
        return {k: {"score": v} for k, v in
                zip(PIPELINE_KEYS, (d, g, m, i))}

    assert pick_command_byte(mk()) == "0"
    assert pick_command_byte(mk(39, 39, 39, 39)) == "0"
    assert pick_command_byte(mk(40)) == "W"
    assert pick_command_byte(mk(0, 74, 73, 10)) == "G"
    assert pick_command_byte(mk(10, 20, 80, 30)) == "T"
    assert pick_command_byte(mk(0, 0, 0, 75)) == "I"
    assert pick_command_byte(mk(80, 80, 80, 80)) == "W"
    assert pick_command_byte(mk(0, 60, 60, 60)) == "G"
    assert pick_command_byte(mk(0, 0, 60, 60)) == "T"
    assert set(MODE_LABELS) == set("WGTI0")

    good = {
        "disaster": {"score": 92, "summary": "Flooding", "action": "Close underpass"},
        "grid": {"score": 15.4, "summary": "ok", "action": "None"},
        "mobility": {"score": 150, "summary": "jam", "action": "Reroute"},
        "infrastructure": {"score": -5, "summary": "ok", "action": "None",
                           "open311_category": "NONE"},
    }
    fenced = "Here you go:\n```json\n" + json.dumps(good) + "\n```"
    p = _parse(fenced)
    assert p["disaster"]["status"] == "CRITICAL" and p["grid"]["score"] == 15
    assert p["mobility"]["score"] == 100 and p["infrastructure"]["score"] == 0
    assert p["infrastructure"]["open311_category"] == "NONE"
    assert "_error" not in p

    img = base64.b64encode(b"\xff\xd8\xff fake").decode()
    env = {"GEMINI_API_KEY": "x"}
    with mock.patch.dict(os.environ, env), mock.patch("google.genai.Client"):
        # success after one bad reply (retry path)
        with mock.patch(f"{__name__}._call_gemma",
                        side_effect=["not json", fenced]) as c:
            r = evaluate_city_frame(img, RALEIGH)
            assert c.call_count == 2 and "_error" not in r
            assert "Error:" in c.call_args_list[1].args[3]
            assert r["disaster"]["score"] == 92
        # bad twice -> fallback
        with mock.patch(f"{__name__}._call_gemma", return_value='{"disaster": 1}'):
            r = evaluate_city_frame(img, RALEIGH)
            assert "_error" in r and all(r[k]["status"] == "NOMINAL" and r[k]["score"] == 0
                                         for k in PIPELINE_KEYS)
        # API error -> fallback, no retry
        with mock.patch(f"{__name__}._call_gemma", side_effect=RuntimeError("boom")) as c:
            r = evaluate_city_frame(img, RALEIGH)
            assert c.call_count == 1 and "boom" in r["_error"]
    with mock.patch.dict(os.environ, {"GEMINI_API_KEY": ""}):
        r = evaluate_city_frame(img, RALEIGH)
        assert "_error" in r and r["infrastructure"]["open311_category"] == "NONE"
        assert pick_command_byte(r) == "0"
    print("selftest OK")


def main(argv: list[str]) -> int:
    if len(argv) >= 2 and argv[1] == "--selftest":
        _selftest()
        return 0
    if len(argv) < 2:
        print("usage: python gemma_harness.py <image> | --selftest")
        return 2
    with open(argv[1], "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    res = evaluate_city_frame(b64, RALEIGH)
    print(json.dumps(res, indent=2))
    byte = pick_command_byte(res)
    print(f"byte={byte} label={MODE_LABELS[byte]}")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
