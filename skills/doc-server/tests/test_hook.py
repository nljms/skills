import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_DIR)
HOOK = os.path.join(SKILL_DIR, "hooks", "session_start.py")


def _load_hook():
    spec = importlib.util.spec_from_file_location("session_start", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestHook(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state
        self.port = _free_port()
        self.httpd = server.make_server(Path(self._home.name), self.port)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        for _ in range(40):
            if server.probe_health(self.port):
                break
            time.sleep(0.05)
        state.set_remembered_port(self.port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._home.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def test_run_returns_none_without_docs(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(hook.run(d))

    def test_run_brings_up_with_docs(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "docs"))
            Path(d, "docs", "a.md").write_text("# A", encoding="utf-8")
            result = hook.run(d)
            self.assertIsNotNone(result)
            self.assertEqual(result["port"], self.port)


if __name__ == "__main__":
    unittest.main()
