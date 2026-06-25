import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVE = os.path.join(SKILL_DIR, "serve.py")


def _probe(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/__doc_server_health__", timeout=0.5
        ) as r:
            return r.status == 200
    except Exception:
        return False


class TestCli(unittest.TestCase):
    def test_serve_brings_up_and_prints_url(self):
        home = tempfile.mkdtemp()
        src = tempfile.mkdtemp()
        os.makedirs(os.path.join(src, "docs"))
        Path(src, "docs", "a.md").write_text("# A", encoding="utf-8")
        env = dict(os.environ, DOC_SERVER_HOME=home, DOC_SERVER_NO_FETCH="1")
        proc = subprocess.run(
            [sys.executable, SERVE, "--docs", "docs/**/*.md"],
            cwd=src, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        url = proc.stdout.strip().splitlines()[-1]
        self.assertIn("/main/", url)
        port = int(url.split(":")[2].split("/")[0])
        # the daemon spawned by ensure_server should answer health
        ok = any(_probe(port) or time.sleep(0.1) for _ in range(30))
        self.assertTrue(_probe(port), "daemon did not come up")
        # cleanup the detached daemon
        subprocess.run(["pkill", "-f", f"serve.py --daemon --port {port}"])


if __name__ == "__main__":
    unittest.main()
