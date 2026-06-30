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

    def test_modified_base_doc_excluded(self):
        # on a feature branch, modify existing docs/base.md (from main) WITHOUT committing
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "base.md").write_text("# base modified", encoding="utf-8")
        added = gitscope.worktree_added_docs(self.root)
        # modified docs that exist on source branch should NOT appear in the added set
        self.assertNotIn("docs/base.md", added)
        # also verify it's empty or doesn't contain base.md (should be empty if no new files)
        self.assertEqual(added, set())

    def test_pushed_branch_uses_forkpoint(self):
        """When upstream==HEAD (branch fully pushed), fall back to fork-point base.

        Simulate a fully-pushed feature branch by making @{upstream} resolve to a
        ref that points at the same commit as HEAD, then assert that the added doc
        is still returned (not empty, which would happen if HEAD...HEAD is used).
        """
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "new.md").write_text("# new", encoding="utf-8")
        _run(["git", "add", "."], self.root)
        _run(["git", "commit", "-m", "add new"], self.root)
        # Create a local "remote-tracking" branch at the same commit and wire it
        # as the upstream so @{upstream} == HEAD.
        _run(["git", "branch", "feat-remote"], self.root)
        _run(["git", "config", "branch.feat.remote", "."], self.root)
        _run(["git", "config", "branch.feat.merge", "refs/heads/feat-remote"], self.root)
        # With the bug, merge-base HEAD @{upstream} == HEAD is returned first and
        # the diff HEAD...HEAD is empty → worktree_added_docs returns set().
        # With the fix, the fork-point / merge-base against main is used instead.
        added = gitscope.worktree_added_docs(self.root)
        self.assertEqual(added, {"docs/new.md"})


if __name__ == "__main__":
    unittest.main()
