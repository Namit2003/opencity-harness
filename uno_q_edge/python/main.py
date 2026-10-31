"""Board API for the UNO Q (POST /mode, GET /health on :8080).

Runs on the board's Linux side and forwards each byte to the sketch over the
Bridge. Off the board there is no Bridge, so it runs as a local stand-in.
"""
import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

try:
    from arduino.app_utils import App, Bridge
except ImportError:  # laptop stand-in
    App = Bridge = None

PORT = 8080
VALID_BYTES = ("W", "G", "T", "I", "0")


def set_mode(byte: str) -> None:
    if Bridge is not None:
        Bridge.call("set_mode", ord(byte))
    print(f"mode -> {byte}", flush=True)


class Handler(BaseHTTPRequestHandler):
    def _reply(self, status: int, body: dict) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self):
        if self.path == "/health":
            self._reply(200, {"ok": True})
        else:
            self._reply(404, {"ok": False, "error": "not found"})

    def do_POST(self):
        if self.path != "/mode":
            self._reply(404, {"ok": False, "error": "not found"})
            return
        try:
            length = int(self.headers.get("Content-Length", 0))
            byte = json.loads(self.rfile.read(length)).get("byte")
        except (ValueError, AttributeError):
            self._reply(400, {"ok": False, "error": "invalid JSON"})
            return
        if byte not in VALID_BYTES:
            self._reply(400, {"ok": False, "error": f"invalid byte: {byte!r}"})
            return
        try:
            set_mode(byte)
        except Exception as e:
            self._reply(500, {"ok": False, "error": str(e)})
            return
        self._reply(200, {"ok": True, "mode": byte})

    def log_message(self, format, *args):
        pass


def serve() -> None:
    ThreadingHTTPServer(("0.0.0.0", PORT), Handler).serve_forever()


if __name__ == "__main__":
    print(f"board API on :{PORT}", flush=True)
    if App is None:
        serve()
    else:
        threading.Thread(target=serve, daemon=True).start()
        App.run()
