import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import cli, commands, store  # noqa: E402

CWD = "/tmp/project"
PROJECT = "/tmp/project"
LINEAR = {"type": "http", "url": "https://mcp.linear.app/mcp"}

CONNECTED = "n:\n  Status: ✔ Connected\n  Type: http\n  URL: https://mcp.linear.app/mcp"
NEEDS_AUTH = "n:\n  Status: ! Needs authentication\n  Type: http\n  URL: https://mcp.linear.app/mcp"
BROKEN = "n:\n  Status: ✘ Failed to connect\n  Type: http\n  URL: https://mcp.linear.app/mcp"

LIST_WITH_CONNECTOR = (
    "claude.ai Linear MCP: https://mcp.linear.app/mcp - ✔ Connected\n"
    "linear-personal: https://mcp.linear.app/mcp - ✔ Connected"
)
LIST_WITH_LOCAL_TWIN = (
    "some-other-linear: https://mcp.linear.app/mcp - ✔ Connected\n"
    "linear-personal: https://mcp.linear.app/mcp - ✔ Connected"
)
LIST_CLEAN = "linear-personal: https://mcp.linear.app/mcp - ✔ Connected"

NOT_REGISTERED = 'No MCP server named "{}" in local scope'


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
            message = self.remove_error if isinstance(self.remove_error, str) \
                else NOT_REGISTERED.format(name)
            raise cli.ClaudeError(message)
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

    def _use(self, profile, fake, provider="linear"):
        return commands.use(self.root, CWD, PROJECT, provider, profile, fake)

    def _mutations(self, fake):
        return [(kind, name) for kind, name, _ in fake.calls if kind in ("add", "remove")]

    def test_a_fresh_switch_clears_the_target_name_then_adds(self):
        fake = FakeClaude()
        result = self._use("work", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-work")])

    def test_add_receives_the_profile_without_the_server_key(self):
        store.write_profile(self.root, "linear", "named", dict(LINEAR, server="lw"))
        fake = FakeClaude()
        self._use("named", fake)
        add = [c for c in fake.calls if c[0] == "add"][0]
        self.assertEqual(add[1], "lw")
        self.assertEqual(add[2], LINEAR)

    def test_switching_removes_the_previous_profile_first(self):
        fake = FakeClaude()
        self._use("work", fake)
        fake.calls.clear()
        self._use("personal", fake)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"),
                          ("remove", "linear-personal"),
                          ("add", "linear-personal")])

    def test_reselecting_the_active_profile_reregisters_it(self):
        fake = FakeClaude()
        self._use("work", fake)
        fake.calls.clear()
        result = self._use("work", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-work")])

    def test_an_unregistered_target_is_added_all_the_same(self):
        fake = FakeClaude(remove_error=True)
        result = self._use("work", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"), ("add", "linear-work")])
        self.assertNotIn("could not remove", "\n".join(result.lines))

    def test_active_profile_and_its_server_are_recorded(self):
        store.write_profile(self.root, "linear", "named", dict(LINEAR, server="lw"))
        self._use("named", FakeClaude())
        self.assertEqual(store.get_active(self.root, PROJECT, "linear"), "named")
        self.assertEqual(store.get_active_server(self.root, PROJECT, "linear"), "lw")

    def test_unknown_profile_fails_without_mutating(self):
        fake = FakeClaude()
        result = self._use("ghost", fake)
        self.assertFalse(result.ok)
        self.assertEqual(self._mutations(fake), [])
        self.assertIsNone(store.get_active(self.root, PROJECT, "linear"))
        self.assertIn("ghost", "\n".join(result.lines))

    def test_a_failing_remove_does_not_abort_the_switch(self):
        fake = FakeClaude(remove_error=True)
        self._use("work", fake)
        fake.calls.clear()
        result = self._use("personal", fake)
        self.assertTrue(result.ok)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"),
                          ("remove", "linear-personal"),
                          ("add", "linear-personal")])

    def test_a_previous_server_that_was_not_registered_is_reported_as_gone(self):
        fake = FakeClaude(remove_error=True)
        self._use("work", fake)
        result = self._use("personal", fake)
        self.assertIn("linear-work was already gone", "\n".join(result.lines))

    def test_a_remove_that_fails_for_another_reason_says_so(self):
        fake = FakeClaude(remove_error="EACCES: permission denied")
        self._use("work", fake)
        result = self._use("personal", fake)
        text = "\n".join(result.lines)
        self.assertIn("could not remove linear-work", text)
        self.assertIn("permission denied", text)
        self.assertNotIn("already gone", text)

    def test_needs_auth_prints_the_login_command(self):
        fake = FakeClaude(get_output=NEEDS_AUTH)
        result = self._use("work", fake)
        self.assertTrue(result.ok)
        self.assertIn("claude mcp login linear-work", "\n".join(result.lines))

    def test_failed_connection_is_reported(self):
        fake = FakeClaude(get_output=BROKEN)
        result = self._use("work", fake)
        self.assertIn("claude mcp get linear-work", "\n".join(result.lines))

    def test_connector_on_the_same_host_points_at_claude_ai_settings(self):
        fake = FakeClaude(list_output=LIST_WITH_CONNECTOR)
        result = self._use("personal", fake)
        text = "\n".join(result.lines)
        self.assertIn("claude.ai Linear MCP", text)
        self.assertIn("claude.ai settings", text)

    def test_local_server_on_the_same_host_suggests_removing_it(self):
        fake = FakeClaude(list_output=LIST_WITH_LOCAL_TWIN)
        result = self._use("personal", fake)
        text = "\n".join(result.lines)
        self.assertIn("claude mcp remove some-other-linear -s local", text)
        self.assertNotIn("claude.ai settings", text)

    def test_no_warning_when_no_other_server_shares_the_host(self):
        fake = FakeClaude(list_output=LIST_CLEAN)
        result = self._use("personal", fake)
        self.assertNotIn("warning", "\n".join(result.lines).lower())

    def test_every_switch_ends_with_the_reconnect_hint(self):
        result = self._use("work", FakeClaude())
        self.assertEqual(result.lines[-1], commands.RECONNECT_HINT)

    def test_add_failure_is_reported_and_state_untouched(self):
        class Boom(FakeClaude):
            def add_json(self, name, config, cwd):
                raise cli.ClaudeError("add exploded")

        result = self._use("work", Boom())
        self.assertFalse(result.ok)
        self.assertIn("add exploded", "\n".join(result.lines))
        self.assertIsNone(store.get_active(self.root, PROJECT, "linear"))

    def test_previous_profile_deleted_from_store_still_gets_removed(self):
        fake = FakeClaude()
        self._use("work", fake)
        store.delete_profile(self.root, "linear", "work")
        fake.calls.clear()
        self._use("personal", fake)
        self.assertEqual(self._mutations(fake),
                         [("remove", "linear-work"),
                          ("remove", "linear-personal"),
                          ("add", "linear-personal")])

    def test_a_deleted_profile_with_a_custom_server_name_is_still_removed(self):
        store.write_profile(self.root, "linear", "named", dict(LINEAR, server="lw"))
        fake = FakeClaude()
        self._use("named", fake)
        store.delete_profile(self.root, "linear", "named")
        fake.calls.clear()
        self._use("personal", fake)
        self.assertEqual(self._mutations(fake)[0], ("remove", "lw"))

    def test_a_state_entry_without_a_server_name_falls_back_to_the_profile(self):
        (self.root / "state.json").write_text(
            '{"%s": {"linear": "work"}}' % PROJECT, encoding="utf-8")
        fake = FakeClaude()
        self._use("personal", fake)
        self.assertEqual(self._mutations(fake)[0], ("remove", "linear-work"))

    def test_activation_is_shared_across_worktrees_of_one_project(self):
        # Two working directories of the same repo resolve to one project root,
        # so the second switch sees the first as the previous activation.
        fake = FakeClaude()
        commands.use(self.root, "/tmp/project", PROJECT, "linear", "work", fake)
        fake.calls.clear()
        commands.use(self.root, "/tmp/project/worktrees/feature", PROJECT,
                     "linear", "personal", fake)
        self.assertIn(("remove", "linear-work"), self._mutations(fake))


if __name__ == "__main__":
    unittest.main()
