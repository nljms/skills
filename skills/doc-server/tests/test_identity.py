import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver.identity import resolve_identity


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t"] + args,
        cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class TestIdentity(unittest.TestCase):
    def test_non_git_dir_falls_back_to_cwd_basename(self):
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "myproj")
            os.makedirs(proj)
            ident = resolve_identity(proj)
            self.assertEqual(ident.project, "myproj")
            self.assertEqual(ident.group, "main")
            self.assertFalse(ident.is_git)
            self.assertEqual(ident.key, "myproj/main")

    def test_main_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            os.makedirs(repo)
            _git(["init"], repo)
            open(os.path.join(repo, "f.txt"), "w").close()
            _git(["add", "."], repo)
            _git(["commit", "-m", "init"], repo)
            ident = resolve_identity(repo)
            self.assertEqual(ident.project, "repo")
            self.assertEqual(ident.group, "main")
            self.assertTrue(ident.is_git)

    def test_linked_worktree_is_grouped(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            os.makedirs(repo)
            _git(["init"], repo)
            open(os.path.join(repo, "f.txt"), "w").close()
            _git(["add", "."], repo)
            _git(["commit", "-m", "init"], repo)
            wt = os.path.join(d, "feature-x")
            _git(["worktree", "add", wt, "-b", "feature-x"], repo)
            ident = resolve_identity(wt)
            self.assertEqual(ident.project, "repo")
            self.assertEqual(ident.group, "worktrees/feature-x")
            self.assertEqual(ident.key, "repo/worktrees/feature-x")


if __name__ == "__main__":
    unittest.main()
