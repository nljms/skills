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
        self._orig_worktree_added_docs = sync.gitscope.worktree_added_docs
        os.makedirs(os.path.join(self._src.name, "docs", "sub"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")
        Path(self._src.name, "docs", "sub", "b.md").write_text("# B", encoding="utf-8")

    def tearDown(self):
        self.sync.gitscope.worktree_added_docs = self._orig_worktree_added_docs
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

    def test_sync_target_kept_file_continuously_present(self):
        """A doc that survives across two syncs must exist both before and after."""
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        kept = self.home / "repo" / "main" / "docs__sub__b.html"
        self.assertTrue(kept.exists(), "kept file should exist after first sync")
        # Remove only a.md so b.md (kept) is still present in source.
        os.remove(os.path.join(self._src.name, "docs", "a.md"))
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.assertTrue(kept.exists(), "kept file should still exist after second sync")
        # Stale file should be gone.
        self.assertFalse((self.home / "repo" / "main" / "docs__a.html").exists())

    def test_sync_target_filters_to_added_docs(self):
        # Monkeypatch the git scope so the test stays filesystem-only.
        self.sync.gitscope.worktree_added_docs = lambda root: {"docs/a.md"}
        names = self.sync.sync_target(self.home, "repo/feat", self._src.name,
                                      self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html"])
        self.assertFalse((self.home / "repo" / "feat" / "docs__sub__b.html").exists())

    def test_sync_target_none_shows_all(self):
        self.sync.gitscope.worktree_added_docs = lambda root: None
        names = self.sync.sync_target(self.home, "repo/main", self._src.name,
                                      self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html", "docs__sub__b.html"])

    def test_sync_all_builds_project_and_root_indexes(self):
        self.state.register_target("repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.state.register_target("repo/worktrees/feat", self._src.name, self.sync.DEFAULT_GLOB)
        self.sync.sync_all(self.home)
        proj_index = (self.home / "repo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("main/index.html", proj_index)
        self.assertIn("worktrees/feat/index.html", proj_index)
        root_index = (self.home / "index.html").read_text(encoding="utf-8")
        self.assertIn("repo/index.html", root_index)


    def test_is_context_doc_registry_path(self):
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {}, "docs/x.md"))
        self.assertFalse(self.sync.is_context_doc("docs/y.md", {}, "docs/x.md"))

    def test_is_context_doc_frontmatter(self):
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {"worktree_context": True}))

    def test_is_context_doc_legacy_aliases(self):
        self.assertTrue(self.sync.is_context_doc("docs/worktree-summary.md", {}))
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {"worktree_summary": True}))


if __name__ == "__main__":
    unittest.main()
