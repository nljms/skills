import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestApp(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state, app
        self.server = server
        self.state = state
        self.app = app
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")

        # Start a real doc-server on a known port so bring_up reuses it.
        self.port = _free_port()
        self.httpd = server.make_server(self.home, self.port)
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
        self._src.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def test_bring_up_reuses_running_server(self):
        result = self.app.bring_up(self._src.name, "docs/**/*.md")
        self.assertEqual(result["port"], self.port)
        self.assertFalse(result["started"])
        self.assertTrue(result["url"].endswith("/main/"))
        # the registered target is now reachable
        with urllib.request.urlopen(result["url"] + "index.html", timeout=2) as r:
            self.assertEqual(r.status, 200)

    def test_bring_up_registers_context(self):
        self.app.bring_up(self._src.name, "docs/**/*.md", context="docs/worktree-context.md")
        reg = self.state.read_registry()
        entry = next(iter(reg.values()))
        self.assertEqual(entry["context"], "docs/worktree-context.md")

    def test_summary_path_resolves_and_creates_dir(self):
        # self._src is a non-git temp dir → identity branch is "main",
        # project is the dir basename.
        p = self.app.summary_path(self._src.name)
        self.assertEqual(p.name, "worktree-summary.md")
        self.assertIn("_context", str(p))
        self.assertTrue(p.parent.is_dir())  # parent dir created


if __name__ == "__main__":
    unittest.main()
