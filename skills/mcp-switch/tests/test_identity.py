import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import identity  # noqa: E402


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self._home = tempfile.TemporaryDirectory()
        os.environ["MCP_SWITCH_HOME"] = self._home.name

    def tearDown(self):
        os.environ.pop("MCP_SWITCH_HOME", None)
        self._tmp.cleanup()
        self._home.cleanup()

    def _repo(self, name):
        root = os.path.join(self.tmp, name)
        os.makedirs(root)
        _run(["git", "init", "-b", "main"], root)
        _run(["git", "config", "user.email", "t@t.t"], root)
        _run(["git", "config", "user.name", "t"], root)
        Path(root, "f.txt").write_text("x", encoding="utf-8")
        _run(["git", "add", "."], root)
        _run(["git", "commit", "-m", "init"], root)
        return root

    def test_home_honours_env_override(self):
        self.assertEqual(identity.store_home(), Path(self._home.name))

    def test_home_is_created(self):
        target = os.path.join(self.tmp, "nested", "home")
        os.environ["MCP_SWITCH_HOME"] = target
        self.assertTrue(identity.store_home().is_dir())

    def test_project_key_is_repo_dir_name(self):
        root = self._repo("myrepo")
        self.assertEqual(identity.project_key(root), "myrepo")

    def test_project_root_is_the_main_repo_directory(self):
        root = self._repo("myrepo")
        self.assertEqual(identity.project_root(root), root)

    def test_project_root_from_a_subdirectory_is_the_repo(self):
        root = self._repo("myrepo")
        sub = os.path.join(root, "deep", "dir")
        os.makedirs(sub)
        self.assertEqual(identity.project_root(sub), root)

    def test_project_root_of_a_worktree_is_the_main_repo(self):
        root = self._repo("myrepo")
        wt = os.path.join(self.tmp, "elsewhere", "feature-checkout")
        os.makedirs(os.path.dirname(wt))
        _run(["git", "worktree", "add", "-b", "feat", wt], root)
        self.assertEqual(identity.project_root(wt), root)

    def test_project_root_outside_a_repo_is_the_directory_itself(self):
        plain = os.path.join(self.tmp, "loose-folder")
        os.makedirs(plain)
        self.assertEqual(identity.project_root(plain), plain)

    def test_project_key_is_the_basename_of_project_root(self):
        root = self._repo("myrepo")
        sub = os.path.join(root, "deep")
        os.makedirs(sub)
        for where in (root, sub):
            self.assertEqual(identity.project_key(where),
                             os.path.basename(identity.project_root(where)))

    def test_subdirectory_resolves_to_repo_name(self):
        root = self._repo("myrepo")
        sub = os.path.join(root, "deep", "dir")
        os.makedirs(sub)
        self.assertEqual(identity.project_key(sub), "myrepo")

    def test_worktree_shares_the_main_repo_key(self):
        root = self._repo("myrepo")
        wt = os.path.join(self.tmp, "elsewhere", "feature-checkout")
        os.makedirs(os.path.dirname(wt))
        _run(["git", "worktree", "add", "-b", "feat", wt], root)
        self.assertEqual(identity.project_key(wt), "myrepo")

    def test_non_git_falls_back_to_directory_name(self):
        plain = os.path.join(self.tmp, "loose-folder")
        os.makedirs(plain)
        self.assertEqual(identity.project_key(plain), "loose-folder")

    def test_project_store_is_created_under_home(self):
        root = self._repo("myrepo")
        store = identity.project_store(root)
        self.assertEqual(store, Path(self._home.name) / "myrepo")
        self.assertTrue(store.is_dir())


if __name__ == "__main__":
    unittest.main()
