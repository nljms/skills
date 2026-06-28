import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._tmp.name
        # import after env is set so module-level paths are not cached wrongly
        from docserver import state
        self.state = state

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)

    def test_home_is_created_from_env(self):
        home = self.state.doc_server_home()
        self.assertEqual(str(home), self._tmp.name)
        self.assertTrue(home.is_dir())

    def test_port_round_trips(self):
        self.assertIsNone(self.state.get_remembered_port())
        self.state.set_remembered_port(8912)
        self.assertEqual(self.state.get_remembered_port(), 8912)

    def test_register_target(self):
        self.state.register_target("repo/main", "/abs/repo", "docs/**/*.md")
        reg = self.state.read_registry()
        self.assertEqual(reg["repo/main"], {"source_root": "/abs/repo", "glob": "docs/**/*.md"})

    def test_register_target_with_context(self):
        self.state.register_target("repo/feat", "/abs/repo", "docs/**/*.md",
                                   context="docs/worktree-context.md")
        reg = self.state.read_registry()
        self.assertEqual(reg["repo/feat"]["context"], "docs/worktree-context.md")

    def test_register_target_without_context_has_no_key(self):
        self.state.register_target("repo/main", "/abs/repo", "docs/**/*.md")
        self.assertNotIn("context", self.state.read_registry()["repo/main"])

    def test_context_summary_path(self):
        from pathlib import Path
        home = self.state.doc_server_home()
        p = self.state.context_summary_path(home, "repo/feat")
        self.assertEqual(p, Path(home) / "_context" / "repo" / "feat" / "worktree-summary.md")


if __name__ == "__main__":
    unittest.main()
