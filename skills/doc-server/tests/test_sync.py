import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestSync(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import sync, state
        self.sync = sync
        self.state = state
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs", "sub"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")
        Path(self._src.name, "docs", "sub", "b.md").write_text("# B", encoding="utf-8")

    def tearDown(self):
        self._home.cleanup()
        self._src.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)
        os.environ.pop("DOC_SERVER_NO_FETCH", None)

    def test_sync_target_writes_flat_html_and_index(self):
        names = self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html", "docs__sub__b.html"])
        self.assertTrue((self.home / "repo" / "main" / "docs__a.html").exists())
        self.assertTrue((self.home / "repo" / "main" / "index.html").exists())

    def test_sync_target_removes_stale_docs(self):
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        os.remove(os.path.join(self._src.name, "docs", "a.md"))
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.assertFalse((self.home / "repo" / "main" / "docs__a.html").exists())

    def test_sync_all_builds_project_and_root_indexes(self):
        self.state.register_target("repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.state.register_target("repo/worktrees/feat", self._src.name, self.sync.DEFAULT_GLOB)
        self.sync.sync_all(self.home)
        proj_index = (self.home / "repo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("main/index.html", proj_index)
        self.assertIn("worktrees/feat/index.html", proj_index)
        root_index = (self.home / "index.html").read_text(encoding="utf-8")
        self.assertIn("repo/index.html", root_index)


if __name__ == "__main__":
    unittest.main()
