"""Laptop-side client for the UNO Q board API (POST /mode on :8080).

Never raises: on any failure the demo falls back to mock mode.
"""
import os
import sys

import httpx
from dotenv import load_dotenv

load_dotenv()

TIMEOUT_S = 1.0
MOCK = {"connected": False, "mock": True}


def send_to_arduino(byte: str) -> dict:
    board_url = os.getenv("BOARD_URL", "").rstrip("/")
    if not board_url:
        return dict(MOCK)
    try:
        r = httpx.post(f"{board_url}/mode", json={"byte": byte}, timeout=TIMEOUT_S)
        r.raise_for_status()
        if r.json().get("ok") is not True:
            return dict(MOCK)
        return {"connected": True, "mock": False}
    except Exception:
        return dict(MOCK)


if __name__ == "__main__":
    print(send_to_arduino(sys.argv[1] if len(sys.argv) > 1 else "0"))
