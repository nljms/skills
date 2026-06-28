import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path

_SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, _SKILL_DIR)
from docserver import server, state, version


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _wait(cond, timeout=5.0):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if cond():
            return True
        time.sleep(0.05)
    return cond()


class TestRestartOnUpdate(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")
        from docserver import app
        self.app = app
        self._procs = []

    def tearDown(self):
        for p in self._procs:
            if p.poll() is None:
                p.kill()
        pid = state.get_daemon_pid()
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        self._home.cleanup()
        self._src.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def _spawn_daemon_with_version(self, port, ver):
        code = (
            f"import sys; sys.path.insert(0, {_SKILL_DIR!r});"
            "from pathlib import Path;"
            "from docserver import server;"
            f"server.make_server(Path({self._home.name!r}), {port}, version={ver!r}).serve_forever()"
        )
        proc = subprocess.Popen([sys.executable, "-c", code])
        self._procs.append(proc)
        _wait(lambda: server.probe_health(port))
        return proc

    def test_reuses_when_version_matches(self):
        port = _free_port()
        proc = self._spawn_daemon_with_version(port, version.code_version())
        state.set_remembered_port(port)
        state.set_daemon_pid(proc.pid)

        result = self.app.bring_up(self._src.name, "docs/**/*.md")
        self.assertEqual(result["port"], port)
        self.assertFalse(result["started"])
        self.assertIsNone(proc.poll())  # original daemon untouched

    def test_restarts_and_clears_cache_when_version_changes(self):
        port = _free_port()
        proc = self._spawn_daemon_with_version(port, "stale-version")
        state.set_remembered_port(port)
        state.set_daemon_pid(proc.pid)
        # A stale generated dir that a restart should wipe.
        junk = self.home / "ghost"
        junk.mkdir()
        (junk / "x.html").write_text("old", encoding="utf-8")

        result = self.app.bring_up(self._src.name, "docs/**/*.md")
        self.assertTrue(result["started"])
        self.assertEqual(result["port"], port)
        # Old daemon is gone; new one reports the current version.
        self.assertTrue(_wait(lambda: proc.poll() is not None))
        self.assertEqual(server.probe_version(port), version.code_version())
        self.assertFalse(junk.exists())

    def test_cold_bind_clears_stale_cache(self):
        port = _free_port()
        state.set_remembered_port(port)
        state.set_code_version("old-stamp")  # cache on disk is from old code
        junk = self.home / "ghost"
        junk.mkdir()
        (junk / "x.html").write_text("old", encoding="utf-8")

        result = self.app.bring_up(self._src.name, "docs/**/*.md")
        self.assertTrue(result["started"])
        self.assertFalse(junk.exists())
        self.assertEqual(state.get_code_version(), version.code_version())


if __name__ == "__main__":
    unittest.main()
