import json
import socket
import subprocess
import sys
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import state, sync

HEALTH_PATH = "/__doc_server_health__"
HEALTH_MARKER = {"doc_server": True}
PORT_SCAN_RANGE = 50
CSP = (
    "default-src 'none'; "
    "script-src 'self' https://cdn.jsdelivr.net; "
    "style-src 'self' https://cdn.jsdelivr.net 'unsafe-inline'; "
    "img-src 'self' data: https:; "
    "font-src 'self' https://cdn.jsdelivr.net; "
    "connect-src 'self'"
)


def is_port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def probe_health(port: int, timeout: float = 0.5) -> bool:
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("doc_server") is True
    except Exception:
        return False


def resolve_port(preferred: int):
    if is_port_free(preferred):
        return preferred, "bind"
    if probe_health(preferred):
        return preferred, "reuse"
    for p in range(preferred + 1, preferred + 1 + PORT_SCAN_RANGE):
        if is_port_free(p):
            return p, "bind"
        if probe_health(p):
            return p, "reuse"
    raise RuntimeError(
        f"No free port found in range {preferred}-{preferred + PORT_SCAN_RANGE}; pass --port."
    )


class DocHandler(SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def do_GET(self):
        if self.path == HEALTH_PATH:
            body = json.dumps(HEALTH_MARKER).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/_assets/"):
            try:
                sync.sync_all(Path(self.directory))
            except Exception:
                pass
        return super().do_GET()

    def log_message(self, *args):
        pass


def make_server(home: Path, port: int) -> ThreadingHTTPServer:
    handler = partial(DocHandler, directory=str(home))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def run_server_forever(home: Path, port: int) -> None:
    make_server(home, port).serve_forever()


def ensure_server(home: Path, preferred: int):
    port, action = resolve_port(preferred)
    if action == "reuse":
        state.set_remembered_port(port)
        return port, False

    serve_py = Path(__file__).resolve().parent.parent / "serve.py"
    subprocess.Popen(
        [sys.executable, str(serve_py), "--daemon", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(100):
        if probe_health(port):
            break
        time.sleep(0.05)
    state.set_remembered_port(port)
    return port, True
