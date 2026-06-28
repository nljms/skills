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

    def test_code_version_round_trips(self):
        self.assertIsNone(self.state.get_code_version())
        self.state.set_code_version("abc123")
        self.assertEqual(self.state.get_code_version(), "abc123")

    def test_daemon_pid_round_trips(self):
        self.assertIsNone(self.state.get_daemon_pid())
        self.state.set_daemon_pid(4242)
        self.assertEqual(self.state.get_daemon_pid(), 4242)

    def test_state_keys_are_independent(self):
        self.state.set_remembered_port(8911)
        self.state.set_code_version("v")
        self.state.set_daemon_pid(7)
        self.assertEqual(self.state.get_remembered_port(), 8911)
        self.assertEqual(self.state.get_code_version(), "v")
        self.assertEqual(self.state.get_daemon_pid(), 7)

    def test_register_target(self):
        self.state.register_target("repo/main", "/abs/repo", "docs/**/*.md")
        reg = self.state.read_registry()
        self.assertEqual(reg["repo/main"], {"source_root": "/abs/repo", "glob": "docs/**/*.md"})


if __name__ == "__main__":
    unittest.main()
