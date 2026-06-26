import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t"] + args,
        cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class TestMigrate(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._work = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import state, migrate
        self.state = state
        self.migrate = migrate
        self.home = Path(self._home.name)

    def tearDown(self):
        self._home.cleanup()
        self._work.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def test_remaps_old_worktree_key_to_branch_and_clears_stale(self):
        # A real git repo so identity now resolves to <project>/<branch>.
        repo = os.path.join(self._work.name, "repo")
        os.makedirs(os.path.join(repo, "docs"))
        _git(["init", "-b", "main"], repo)
        Path(repo, "docs", "a.md").write_text("# A", encoding="utf-8")
        _git(["add", "."], repo)
        _git(["commit", "-m", "init"], repo)

        # Seed an OLD-layout registry + stale generated dir.
        self.state.register_target("repo/worktrees/legacy", repo, "docs/**/*.md")
        stale = self.home / "repo" / "worktrees" / "legacy"
        stale.mkdir(parents=True)
        (stale / "index.html").write_text("old", encoding="utf-8")

        result = self.migrate.migrate_home(self.home)

        reg = self.state.read_registry()
        self.assertIn("repo/main", reg)               # re-keyed to the branch
        self.assertNotIn("repo/worktrees/legacy", reg)
        self.assertFalse(stale.exists())              # stale generated dir removed
        self.assertTrue((self.home / "repo" / "main" / "index.html").exists())
        self.assertIn(("repo/worktrees/legacy", "repo/main"), result["remapped"])

    def test_drops_entries_whose_source_is_gone(self):
        self.state.register_target("ghost/main", "/no/such/path", "docs/**/*.md")
        result = self.migrate.migrate_home(self.home)
        self.assertIn("ghost/main", result["dropped"])
        self.assertNotIn("ghost/main", self.state.read_registry())


if __name__ == "__main__":
    unittest.main()
