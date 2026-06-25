import base64
import json
import os
import re
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


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
        return r.read().decode("utf-8")


class TestHandler(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state, sync
        self.server = server
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs"))
        self._doc = Path(self._src.name, "docs", "a.md")
        self._doc.write_text("# Hello", encoding="utf-8")
        state.register_target("repo/main", self._src.name, sync.DEFAULT_GLOB)
        sync.sync_all(self.home)

        self.port = _free_port()
        self.httpd = server.make_server(self.home, self.port)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        for _ in range(40):
            if server.probe_health(self.port):
                break
            time.sleep(0.05)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._home.cleanup()
        self._src.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)
        os.environ.pop("DOC_SERVER_NO_FETCH", None)

    def test_health_marker(self):
        body = _get(self.port, self.server.HEALTH_PATH)
        self.assertEqual(json.loads(body), {"doc_server": True})

    def test_response_includes_csp_header(self):
        with urllib.request.urlopen(
            f"http://127.0.0.1:{self.port}/repo/main/docs__a.html", timeout=2
        ) as r:
            csp = r.headers.get("Content-Security-Policy", "")
        self.assertIn("script-src 'self'", csp)
        # script-src must NOT contain 'unsafe-inline'
        # Extract just the script-src directive value
        script_src_match = re.search(r"script-src([^;]+)", csp)
        self.assertIsNotNone(script_src_match, "script-src directive must be present")
        self.assertNotIn("'unsafe-inline'", script_src_match.group(1))

    def test_serves_doc_and_live_resyncs_on_edit(self):
        def decoded():
            html = _get(self.port, "/repo/main/docs__a.html")
            b64 = re.search(r'id="md-data"[^>]*>([^<]+)<', html).group(1)
            return base64.b64decode(b64).decode("utf-8")

        self.assertEqual(decoded(), "# Hello")
        self._doc.write_text("# Updated", encoding="utf-8")
        self.assertEqual(decoded(), "# Updated")


if __name__ == "__main__":
    unittest.main()
