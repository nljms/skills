import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from docserver import gitscope  # noqa: E402


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init_repo(root):
    _run(["git", "init", "-b", "main"], root)
    _run(["git", "config", "user.email", "t@t.t"], root)
    _run(["git", "config", "user.name", "t"], root)
    os.makedirs(os.path.join(root, "docs"))
    Path(root, "docs", "base.md").write_text("# base", encoding="utf-8")
    _run(["git", "add", "."], root)
    _run(["git", "commit", "-m", "base"], root)


class TestGitscope(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_non_git_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(gitscope.worktree_added_docs(d))

    def test_default_branch_shows_all(self):
        # On main with no divergence → None (show all).
        self.assertIsNone(gitscope.worktree_added_docs(self.root))

    def test_committed_added_doc_on_branch(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "new.md").write_text("# new", encoding="utf-8")
        _run(["git", "add", "."], self.root)
        _run(["git", "commit", "-m", "add new"], self.root)
        added = gitscope.worktree_added_docs(self.root)
        self.assertEqual(added, {"docs/new.md"})

    def test_untracked_doc_on_branch(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "wip.md").write_text("# wip", encoding="utf-8")
        added = gitscope.worktree_added_docs(self.root)
        self.assertEqual(added, {"docs/wip.md"})

    def test_base_doc_excluded(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "new.md").write_text("# new", encoding="utf-8")
        added = gitscope.worktree_added_docs(self.root)
        self.assertNotIn("docs/base.md", added)


if __name__ == "__main__":
    unittest.main()
