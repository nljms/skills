import importlib.util
import os
import subprocess
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


def _run(cmd, cwd):
    subprocess.run(cmd, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _git_repo(d, branch):
    _run(["git", "init", "-q"], d)
    _run(["git", "config", "user.email", "t@t"], d)
    _run(["git", "config", "user.name", "t"], d)
    Path(d, "f.txt").write_text("x")
    _run(["git", "add", "-A"], d)
    _run(["git", "commit", "-q", "-m", "init"], d)
    _run(["git", "branch", "-m", branch], d)


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

    def test_nudge_on_feature_branch_without_summary(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            _git_repo(d, "feat/login")
            os.makedirs(os.path.join(d, "docs"))
            Path(d, "docs", "plan.md").write_text("# Plan", encoding="utf-8")
            nudge = hook.summary_nudge(d)
            self.assertIsNotNone(nudge)
            self.assertIn("--summary-path", nudge)
            self.assertIn("_context", nudge)

    def test_no_nudge_when_summary_present(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            _git_repo(d, "feat/login")
            os.makedirs(os.path.join(d, "docs"))
            Path(d, "docs", "worktree-summary.md").write_text("# S", encoding="utf-8")
            self.assertIsNone(hook.summary_nudge(d))

    def test_no_nudge_on_default_branch(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            _git_repo(d, "main")
            os.makedirs(os.path.join(d, "docs"))
            Path(d, "docs", "plan.md").write_text("# Plan", encoding="utf-8")
            self.assertIsNone(hook.summary_nudge(d))

    def test_no_nudge_outside_git(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(hook.summary_nudge(d))


if __name__ == "__main__":
    unittest.main()
