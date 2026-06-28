import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import state, sync, version

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


def _health_payload(port: int, timeout: float = 0.5):
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def probe_health(port: int, timeout: float = 0.5) -> bool:
    data = _health_payload(port, timeout)
    return bool(data) and data.get("doc_server") is True


def probe_version(port: int, timeout: float = 0.5):
    """Version the daemon on `port` is running, or None if unreachable/legacy."""
    data = _health_payload(port, timeout)
    if not data or data.get("doc_server") is not True:
        return None
    return data.get("version")


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
    version_tag = None  # set per-server via make_server

    def end_headers(self):
        self.send_header("Content-Security-Policy", CSP)
        super().end_headers()

    def do_GET(self):
        if self.path == HEALTH_PATH:
            marker = dict(HEALTH_MARKER)
            if self.version_tag is not None:
                marker["version"] = self.version_tag
            body = json.dumps(marker).encode("utf-8")
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


def make_server(home: Path, port: int, version: str = None) -> ThreadingHTTPServer:
    # version_tag is read off the handler class; bake it in per server so the
    # health endpoint can advertise which code the daemon is running.
    cls = type("DocHandler", (DocHandler,), {"version_tag": version})
    handler = partial(cls, directory=str(home))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def run_server_forever(home: Path, port: int) -> None:
    make_server(home, port, version=version.code_version()).serve_forever()


def _wait_port_free(port: int, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if is_port_free(port):
            return True
        time.sleep(0.05)
    return is_port_free(port)


def stop_daemon(home: Path, port: int, timeout: float = 3.0) -> bool:
    """Stop the recorded daemon and wait for `port` to free up. SIGTERM first,
    SIGKILL if it lingers. Returns True once the port is free."""
    import signal
    pid = state.get_daemon_pid()
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
        except (ProcessLookupError, PermissionError):
            pid = None
    if _wait_port_free(port, timeout):
        return True
    if pid:
        try:
            os.kill(pid, signal.SIGKILL)
        except (ProcessLookupError, PermissionError):
            pass
    return _wait_port_free(port, timeout)


def _spawn_daemon(home: Path, port: int) -> None:
    serve_py = Path(__file__).resolve().parent.parent / "serve.py"
    proc = subprocess.Popen(
        [sys.executable, str(serve_py), "--daemon", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    state.set_daemon_pid(proc.pid)
    for _ in range(100):
        if probe_health(port):
            break
        time.sleep(0.05)
    state.set_remembered_port(port)
    state.set_code_version(version.code_version())


def ensure_server(home: Path, preferred: int):
    """Bring up (or reuse) the shared daemon. If the skill code has changed since
    the running daemon launched, stop it, drop the now-stale generated cache, and
    spawn a fresh daemon so the new code takes effect."""
    current = version.code_version()
    port, action = resolve_port(preferred)

    if action == "reuse":
        if probe_version(port) == current:
            state.set_remembered_port(port)
            return port, False
        # Skill updated: the running daemon serves stale in-memory code.
        stop_daemon(home, port)
        sync.clear_generated(home)
        _spawn_daemon(home, port)
        return port, True

    # No live daemon on this port. If the on-disk cache predates the current
    # code, clear it so the fresh daemon rebuilds everything from new code.
    if state.get_code_version() != current:
        sync.clear_generated(home)
    _spawn_daemon(home, port)
    return port, True
