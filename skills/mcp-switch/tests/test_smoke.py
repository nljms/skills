import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SWITCH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "switch.py"))
URL = "https://example.invalid/mcp"


@unittest.skipIf(shutil.which("claude") is None, "claude CLI not on PATH")
class TestSmoke(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._cwd = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, MCP_SWITCH_HOME=self._home.name)

    def tearDown(self):
        # Leave no local-scope server behind for the temp cwd.
        subprocess.run(["claude", "mcp", "remove", "smoke-one", "-s", "local"],
                       cwd=self._cwd.name, capture_output=True, text=True)
        subprocess.run(["claude", "mcp", "remove", "smoke-two", "-s", "local"],
                       cwd=self._cwd.name, capture_output=True, text=True)
        self._home.cleanup()
        self._cwd.cleanup()

    def _switch(self, *args):
        return subprocess.run([sys.executable, SWITCH, *args], cwd=self._cwd.name,
                              env=self.env, capture_output=True, text=True, timeout=180)

    def test_add_use_switch_and_list(self):
        self.assertEqual(self._switch("add", "smoke", "one", "--url", URL,
                                      "--server", "smoke-one").returncode, 0)
        self.assertEqual(self._switch("add", "smoke", "two", "--url", URL,
                                      "--server", "smoke-two").returncode, 0)

        first = self._switch("use", "smoke", "one")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("smoke-one", first.stdout)

        second = self._switch("use", "smoke", "two")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("removed smoke-one", second.stdout)

        listing = self._switch("list", "smoke")
        self.assertIn("* two", listing.stdout)


if __name__ == "__main__":
    unittest.main()
