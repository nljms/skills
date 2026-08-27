import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SWITCH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "switch.py"))
URL = "https://example.invalid/mcp"

# Isolation guarantee: this test writes nothing to the real user config. It
# runs `switch.py` (and, in tearDown, `claude mcp remove`) with cwd pointed
# at a temp directory, MCP_SWITCH_HOME pointed at a temp directory, and
# CLAUDE_CONFIG_DIR pointed at a temp directory. The `claude` CLI honours
# CLAUDE_CONFIG_DIR and reads/writes its own `.claude.json` there instead of
# under ~/.claude.json, so local-scope server registration (keyed by the main
# repository root under the config's "projects" map) never touches the real
# config. Only servers this test created are ever removed.


@unittest.skipIf(shutil.which("claude") is None, "claude CLI not on PATH")
class TestSmoke(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._cwd = tempfile.TemporaryDirectory()
        self._config = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, MCP_SWITCH_HOME=self._home.name,
                        CLAUDE_CONFIG_DIR=self._config.name)

    def tearDown(self):
        # Leave no local-scope server behind. Use the same isolated
        # CLAUDE_CONFIG_DIR so this operates on the temp config, not the real
        # one, and only on the names this test registered.
        repo = os.path.join(self._cwd.name, "repo")
        places = [self._cwd.name] + ([repo] if os.path.isdir(repo) else [])
        for where in places:
            for name in ("smoke-one", "smoke-two", "smoke-own"):
                subprocess.run(["claude", "mcp", "remove", name, "-s", "local"],
                               cwd=where, env=self.env,
                               capture_output=True, text=True)
        self._home.cleanup()
        self._cwd.cleanup()
        self._config.cleanup()

    def _switch(self, *args, cwd=None):
        return subprocess.run([sys.executable, SWITCH, *args], cwd=cwd or self._cwd.name,
                              env=self.env, capture_output=True, text=True, timeout=180)

    def _repo(self):
        """A real git repo inside the temp cwd, plus a subdirectory of it."""
        root = os.path.join(self._cwd.name, "repo")
        sub = os.path.join(root, "deep", "dir")
        os.makedirs(sub)
        subprocess.run(["git", "init", "-q", "-b", "main"], cwd=root, check=True,
                       stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        return root, sub

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

    def test_use_is_idempotent_against_the_real_cli(self):
        # `claude mcp add-json` refuses a name that is already registered, so
        # re-selecting the active profile has to clear it first.
        self._switch("add", "smoke", "one", "--url", URL, "--server", "smoke-one")
        first = self._switch("use", "smoke", "one")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        second = self._switch("use", "smoke", "one")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("smoke-one", second.stdout)

    def test_use_refuses_to_replace_a_server_it_did_not_register(self):
        # A hand-configured server holds things `claude mcp get` never prints
        # (headers, env), so replacing it would destroy them unrecoverably.
        own = "https://original.invalid/mcp"
        added = subprocess.run(
            ["claude", "mcp", "add-json", "smoke-own",
             '{"type":"http","url":"%s","headers":{"X-Api-Key":"secret"}}' % own,
             "-s", "local"],
            cwd=self._cwd.name, env=self.env, capture_output=True, text=True)
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)

        saved = self._switch("save", "smoke", "one", "--from", "smoke-own")
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)
        self.assertIn("headers", saved.stdout)      # the lossy-copy warning

        # A different profile pointed at the same server name must be refused.
        self._switch("add", "smoke", "two", "--url", URL, "--server", "smoke-own")
        refused = self._switch("use", "smoke", "two")
        self.assertEqual(refused.returncode, 1, refused.stdout + refused.stderr)
        self.assertIn("already registered", refused.stdout)
        self.assertIn("claude mcp remove smoke-own -s local", refused.stdout)

        survived = subprocess.run(["claude", "mcp", "get", "smoke-own"],
                                  cwd=self._cwd.name, env=self.env,
                                  capture_output=True, text=True, timeout=180)
        self.assertIn(own, survived.stdout)
        self.assertNotIn(URL, survived.stdout)

    def test_saving_a_server_does_not_make_it_ours_to_delete(self):
        # `save` captures a server the user configured; nothing about that makes
        # it a registration this store may later remove on its own initiative.
        own = "https://original.invalid/mcp"
        added = subprocess.run(
            ["claude", "mcp", "add-json", "smoke-own",
             '{"type":"http","url":"%s","headers":{"X-Api-Key":"secret"}}' % own,
             "-s", "local"],
            cwd=self._cwd.name, env=self.env, capture_output=True, text=True)
        self.assertEqual(added.returncode, 0, added.stdout + added.stderr)

        saved = self._switch("save", "smoke", "one", "--from", "smoke-own")
        self.assertEqual(saved.returncode, 0, saved.stdout + saved.stderr)

        # A different profile, under a name of its own: nothing to deactivate.
        self._switch("add", "smoke", "two", "--url", URL, "--server", "smoke-two")
        used = self._switch("use", "smoke", "two")
        self.assertEqual(used.returncode, 0, used.stdout + used.stderr)
        self.assertNotIn("removed smoke-own", used.stdout)

        survived = subprocess.run(["claude", "mcp", "get", "smoke-own"],
                                  cwd=self._cwd.name, env=self.env,
                                  capture_output=True, text=True, timeout=180)
        self.assertIn(own, survived.stdout)

    def test_activation_is_shared_across_a_repo(self):
        # Claude Code keys local scope on the main repository root, so a
        # subdirectory of the repo must see the same active profile.
        root, sub = self._repo()
        self._switch("add", "smoke", "one", "--url", URL, "--server", "smoke-one",
                     cwd=root)
        used = self._switch("use", "smoke", "one", cwd=root)
        self.assertEqual(used.returncode, 0, used.stdout + used.stderr)

        listing = self._switch("list", "smoke", cwd=sub)
        self.assertEqual(listing.returncode, 0, listing.stdout + listing.stderr)
        self.assertIn("* one", listing.stdout)

        # And a second profile activated from the subdirectory unregisters the
        # first, rather than leaving both live under the one project key.
        self._switch("add", "smoke", "two", "--url", URL, "--server", "smoke-two",
                     cwd=sub)
        switched = self._switch("use", "smoke", "two", cwd=sub)
        self.assertEqual(switched.returncode, 0, switched.stdout + switched.stderr)
        self.assertIn("removed smoke-one", switched.stdout)

        registered = subprocess.run(["claude", "mcp", "list"], cwd=root, env=self.env,
                                    capture_output=True, text=True, timeout=180).stdout
        self.assertNotIn("smoke-one", registered)
        self.assertIn("smoke-two", registered)


if __name__ == "__main__":
    unittest.main()
