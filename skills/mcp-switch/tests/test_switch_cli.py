import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import switch  # noqa: E402
from mcpswitch import identity, store  # noqa: E402

LINEAR_URL = "https://mcp.linear.app/mcp"
CONNECTED = f"n:\n  Status: \u2714 Connected\n  Type: http\n  URL: {LINEAR_URL}"


class FakeClaude:
    def __init__(self):
        self.calls = []

    def add_json(self, name, config, cwd):
        self.calls.append(("add", name))

    def remove(self, name, cwd):
        self.calls.append(("remove", name))

    def get(self, name, cwd):
        return CONNECTED

    def list(self, cwd):
        return f"linear-work: {LINEAR_URL} - \u2714 Connected"


class TestSwitchCli(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["MCP_SWITCH_HOME"] = self._home.name
        self.claude = FakeClaude()
        # Same resolution the CLI uses: the main repo's name, not the cwd's.
        self.root = identity.project_store(os.getcwd())

    def tearDown(self):
        os.environ.pop("MCP_SWITCH_HOME", None)
        self._home.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = switch.main(argv, claude=self.claude)
        return code, buf.getvalue()

    def test_add_then_use_then_list(self):
        code, _ = self._run(["add", "linear", "work", "--url", LINEAR_URL])
        self.assertEqual(code, 0)

        code, out = self._run(["use", "linear", "work"])
        self.assertEqual(code, 0)
        self.assertIn("linear-work", out)
        self.assertIn("/mcp", out)
        self.assertIn(("add", "linear-work"), self.claude.calls)

        code, out = self._run(["list"])
        self.assertEqual(code, 0)
        self.assertIn("* work", out)

    def test_use_unknown_profile_exits_nonzero(self):
        code, out = self._run(["use", "linear", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("ghost", out)

    def test_add_with_headers_and_transport(self):
        self._run(["add", "acme", "prod", "--url", "https://x.dev/mcp",
                   "--transport", "sse", "-H", "X-Api-Key: abc"])
        cfg = store.read_profile(self.root, "acme", "prod")
        self.assertEqual(cfg["type"], "sse")
        self.assertEqual(cfg["headers"], {"X-Api-Key": "abc"})

    def test_add_with_json(self):
        self._run(["add", "local", "vault", "--json",
                   json.dumps({"type": "stdio", "command": "npx"})])
        self.assertEqual(store.read_profile(self.root, "local", "vault")["command"], "npx")

    def test_save_captures_from_a_live_server(self):
        code, _ = self._run(["save", "linear", "work", "--from", "linear-work"])
        self.assertEqual(code, 0)
        self.assertEqual(store.read_profile(self.root, "linear", "work")["url"], LINEAR_URL)

    def test_rm_deletes_an_inactive_profile(self):
        self._run(["add", "linear", "spare", "--url", LINEAR_URL])
        code, _ = self._run(["rm", "linear", "spare"])
        self.assertEqual(code, 0)
        self.assertFalse(store.profile_path(self.root, "linear", "spare").exists())

    def test_list_filtered_by_provider(self):
        self._run(["add", "linear", "work", "--url", LINEAR_URL])
        code, out = self._run(["list", "linear"])
        self.assertEqual(code, 0)
        self.assertIn("linear", out)

    def test_no_subcommand_exits_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                switch.main([], claude=self.claude)


if __name__ == "__main__":
    unittest.main()
