import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import cli, commands, store  # noqa: E402

CWD = "/tmp/project"
LINEAR = {"type": "http", "url": "https://mcp.linear.app/mcp"}

CONNECTED = "n:\n  Status: ✔ Connected\n  Type: http\n  URL: https://mcp.linear.app/mcp"
NEEDS_AUTH = "n:\n  Status: ! Needs authentication\n  Type: http\n  URL: https://mcp.linear.app/mcp"
BROKEN = "n:\n  Status: ✘ Failed to connect\n  Type: http\n  URL: https://mcp.linear.app/mcp"

LIST_WITH_CONNECTOR = (
    "claude.ai Linear MCP: https://mcp.linear.app/mcp - ✔ Connected\n"
    "linear-personal: https://mcp.linear.app/mcp - ✔ Connected"
)
LIST_CLEAN = "linear-personal: https://mcp.linear.app/mcp - ✔ Connected"


class FakeClaude:
    """Records mutations; replays canned read output."""

    def __init__(self, get_output=CONNECTED, list_output=LIST_CLEAN, remove_error=False):
        self.calls = []
        self.get_output = get_output
        self.list_output = list_output
        self.remove_error = remove_error

    def add_json(self, name, config, cwd):
        self.calls.append(("add", name, config))
        return "added"

    def remove(self, name, cwd):
        self.calls.append(("remove", name, None))
        if self.remove_error:
            raise cli.ClaudeError(f'No MCP server named "{name}"')
        return "removed"

    def get(self, name, cwd):
        self.calls.append(("get", name, None))
        return self.get_output

    def list(self, cwd):
        self.calls.append(("list", None, None))
        return self.list_output


class TestUse(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        store.write_profile(self.root, "linear", "work", LINEAR)
        store.write_profile(self.root, "linear", "personal", LINEAR)

    def tearDown(self):
        self._tmp.cleanup()

    def _mutations(self, fake):
        return [(kind, name) for kind, name, _ in fake.calls if kind in ("add", "remove")]

    def test_first_switch_only_adds(self):
        fake = FakeClaude()
        result = commands.use(self.root, CWD, "linear", "work", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake), [("add", "linear-work")])

    def test_add_receives_the_profile_without_the_server_key(self):
        store.write_profile(self.root, "linear", "named", dict(LINEAR, server="lw"))
        fake = FakeClaude()
        commands.use(self.root, CWD, "linear", "named", fake)
        add = [c for c in fake.calls if c[0] == "add"][0]
        self.assertEqual(add[1], "lw")
        self.assertEqual(add[2], LINEAR)

    def test_switching_removes_the_previous_profile_first(self):
        fake = FakeClaude()
        commands.use(self.root, CWD, "linear", "work", fake)
        fake.calls.clear()
        commands.use(self.root, CWD, "linear", "personal", fake)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-personal")])

    def test_reswitching_to_the_same_profile_skips_the_remove(self):
        fake = FakeClaude()
        commands.use(self.root, CWD, "linear", "work", fake)
        fake.calls.clear()
        commands.use(self.root, CWD, "linear", "work", fake)
        self.assertEqual(self._mutations(fake), [("add", "linear-work")])

    def test_active_profile_is_recorded(self):
        commands.use(self.root, CWD, "linear", "personal", FakeClaude())
        self.assertEqual(store.get_active(self.root, CWD, "linear"), "personal")

    def test_unknown_profile_fails_without_mutating(self):
        fake = FakeClaude()
        result = commands.use(self.root, CWD, "linear", "ghost", fake)
        self.assertFalse(result.ok)
        self.assertEqual(self._mutations(fake), [])
        self.assertIsNone(store.get_active(self.root, CWD, "linear"))
        self.assertIn("ghost", "\n".join(result.lines))

    def test_a_failing_remove_does_not_abort_the_switch(self):
        fake = FakeClaude(remove_error=True)
        commands.use(self.root, CWD, "linear", "work", fake)
        fake.calls.clear()
        result = commands.use(self.root, CWD, "linear", "personal", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-personal")])

    def test_needs_auth_prints_the_login_command(self):
        fake = FakeClaude(get_output=NEEDS_AUTH)
        result = commands.use(self.root, CWD, "linear", "work", fake)
        self.assertTrue(result.ok)
        self.assertIn("claude mcp login linear-work", "\n".join(result.lines))

    def test_failed_connection_is_reported(self):
        fake = FakeClaude(get_output=BROKEN)
        result = commands.use(self.root, CWD, "linear", "work", fake)
        self.assertIn("claude mcp get linear-work", "\n".join(result.lines))

    def test_connector_on_the_same_host_warns(self):
        fake = FakeClaude(list_output=LIST_WITH_CONNECTOR)
        result = commands.use(self.root, CWD, "linear", "personal", fake)
        text = "\n".join(result.lines)
        self.assertIn("claude.ai Linear MCP", text)
        self.assertIn("claude.ai settings", text)

    def test_no_warning_when_no_other_server_shares_the_host(self):
        fake = FakeClaude(list_output=LIST_CLEAN)
        result = commands.use(self.root, CWD, "linear", "personal", fake)
        self.assertNotIn("warning", "\n".join(result.lines).lower())

    def test_every_switch_ends_with_the_reconnect_hint(self):
        result = commands.use(self.root, CWD, "linear", "work", FakeClaude())
        self.assertEqual(result.lines[-1], commands.RECONNECT_HINT)

    def test_add_failure_is_reported_and_state_untouched(self):
        class Boom(FakeClaude):
            def add_json(self, name, config, cwd):
                raise cli.ClaudeError("add exploded")

        result = commands.use(self.root, CWD, "linear", "work", Boom())
        self.assertFalse(result.ok)
        self.assertIn("add exploded", "\n".join(result.lines))
        self.assertIsNone(store.get_active(self.root, CWD, "linear"))

    def test_previous_profile_deleted_from_store_still_gets_removed(self):
        fake = FakeClaude()
        commands.use(self.root, CWD, "linear", "work", fake)
        store.delete_profile(self.root, "linear", "work")
        fake.calls.clear()
        commands.use(self.root, CWD, "linear", "personal", fake)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-personal")])


if __name__ == "__main__":
    unittest.main()
