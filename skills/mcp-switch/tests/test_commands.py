import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import commands, store  # noqa: E402

CWD = "/tmp/project"
PROJECT = "/tmp/project"
LINEAR = {"type": "http", "url": "https://mcp.linear.app/mcp"}

LIST = ("linear-work: https://mcp.linear.app/mcp - ! Needs authentication\n"
        "linear-personal: https://mcp.linear.app/mcp - ✔ Connected")

GET_HTTP = ("some-server:\n  Scope: Local config (private to you in this project)\n"
            "  Status: ✔ Connected\n  Type: http\n  URL: https://mcp.notion.com/mcp")
GET_CONNECTOR = "claude.ai Linear MCP:\n  Scope: claude.ai config\n  Status: ✔ Connected"
GET_MISSING = 'No MCP server named "nope". Configured servers: a, b'


class FakeClaude:
    def __init__(self, get_output=GET_HTTP, list_output=LIST):
        self.get_output = get_output
        self.list_output = list_output

    def get(self, name, cwd):
        return self.get_output

    def list(self, cwd):
        return self.list_output


class TestShow(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_empty_store_explains_how_to_add(self):
        result = commands.show(self.root, CWD, PROJECT, FakeClaude())
        self.assertTrue(result.ok)
        self.assertIn("add", "\n".join(result.lines))

    def test_lists_profiles_with_active_marker_and_status(self):
        store.write_profile(self.root, "linear", "work", LINEAR)
        store.write_profile(self.root, "linear", "personal", LINEAR)
        store.set_active(self.root, PROJECT, "linear", "work")
        text = "\n".join(commands.show(self.root, CWD, PROJECT, FakeClaude()).lines)
        self.assertIn("linear", text)
        self.assertIn("* work", text)
        self.assertIn("needs-auth", text)
        self.assertIn("personal", text)

    def test_filtering_to_one_provider(self):
        store.write_profile(self.root, "linear", "work", LINEAR)
        store.write_profile(self.root, "notion", "acme", LINEAR)
        text = "\n".join(commands.show(self.root, CWD, PROJECT, FakeClaude(), provider="linear").lines)
        self.assertIn("linear", text)
        self.assertNotIn("notion", text)

    def test_unknown_provider_filter_fails(self):
        result = commands.show(self.root, CWD, PROJECT, FakeClaude(), provider="ghost")
        self.assertFalse(result.ok)

    def test_columns_line_up_whatever_the_status(self):
        store.write_profile(self.root, "linear", "work", LINEAR)      # needs-auth
        store.write_profile(self.root, "linear", "spare", LINEAR)     # unregistered
        rows = [l for l in commands.show(self.root, CWD, PROJECT, FakeClaude()).lines
                if l.startswith("  ")]
        self.assertIn("not registered here", "\n".join(rows))
        starts = {row.index(LINEAR["url"]) for row in rows}
        self.assertEqual(len(starts), 1, rows)

    def test_unreadable_profile_row_lines_up_with_the_rest(self):
        store.write_profile(self.root, "linear", "work", LINEAR)
        path = store.profile_path(self.root, "linear", "broken")
        path.write_text("{oops", encoding="utf-8")
        rows = [l for l in commands.show(self.root, CWD, PROJECT, FakeClaude()).lines
                if l.startswith("  ")]
        self.assertEqual({row.index(row.strip()[0]) for row in rows}, {4})

    def test_malformed_profile_is_reported_not_raised(self):
        path = store.profile_path(self.root, "linear", "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{oops", encoding="utf-8")
        result = commands.show(self.root, CWD, PROJECT, FakeClaude())
        self.assertTrue(result.ok)
        self.assertIn("unreadable", "\n".join(result.lines))


class TestAdd(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_add_from_url_writes_an_http_profile(self):
        result = commands.add(self.root, "linear", "work",
                              url="https://mcp.linear.app/mcp")
        self.assertTrue(result.ok)
        self.assertEqual(store.read_profile(self.root, "linear", "work"), LINEAR)

    def test_add_records_transport_and_headers(self):
        commands.add(self.root, "acme", "prod", url="https://x.dev/mcp",
                     transport="sse", headers=["X-Api-Key: abc", "X-Other:  d "])
        cfg = store.read_profile(self.root, "acme", "prod")
        self.assertEqual(cfg["type"], "sse")
        self.assertEqual(cfg["headers"], {"X-Api-Key": "abc", "X-Other": "d"})

    def test_add_records_an_explicit_server_name(self):
        commands.add(self.root, "linear", "work", url="https://x.dev/mcp", server="lw")
        self.assertEqual(store.read_profile(self.root, "linear", "work")["server"], "lw")

    def test_add_from_json(self):
        commands.add(self.root, "local", "vault",
                     json_config=json.dumps({"type": "stdio", "command": "npx"}))
        self.assertEqual(store.read_profile(self.root, "local", "vault")["command"], "npx")

    def test_bad_json_fails_cleanly(self):
        result = commands.add(self.root, "local", "vault", json_config="{oops")
        self.assertFalse(result.ok)
        self.assertFalse(store.profile_path(self.root, "local", "vault").exists())

    def test_missing_url_and_json_fails(self):
        result = commands.add(self.root, "linear", "work")
        self.assertFalse(result.ok)

    def test_malformed_header_fails(self):
        result = commands.add(self.root, "linear", "work",
                              url="https://x.dev/mcp", headers=["nocolon"])
        self.assertFalse(result.ok)


class TestSave(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)

    def tearDown(self):
        self._tmp.cleanup()

    def test_save_captures_a_configured_server(self):
        result = commands.save(self.root, CWD, "notion", "acme", "some-server", FakeClaude())
        self.assertTrue(result.ok)
        cfg = store.read_profile(self.root, "notion", "acme")
        self.assertEqual(cfg["url"], "https://mcp.notion.com/mcp")
        self.assertEqual(cfg["server"], "some-server")

    def test_save_honours_an_explicit_server_name(self):
        commands.save(self.root, CWD, "notion", "acme", "some-server", FakeClaude(),
                      server="notion-acme")
        self.assertEqual(store.read_profile(self.root, "notion", "acme")["server"],
                         "notion-acme")

    def test_save_writes_no_active_state(self):
        # Only a successful `use` may write state, so that every entry names a
        # server this store itself registered and deactivation can never reach
        # one the user configured by hand.
        commands.save(self.root, CWD, "notion", "acme", "some-server", FakeClaude())
        self.assertIsNone(store.get_active(self.root, PROJECT, "notion"))
        self.assertIsNone(store.get_active_server(self.root, PROJECT, "notion"))

    def test_save_leaves_an_existing_activation_alone(self):
        store.set_active(self.root, PROJECT, "notion", "existing", "notion-existing")
        commands.save(self.root, CWD, "notion", "acme", "some-server", FakeClaude())
        self.assertEqual(store.get_active(self.root, PROJECT, "notion"), "existing")
        self.assertEqual(store.get_active_server(self.root, PROJECT, "notion"),
                         "notion-existing")

    def test_save_says_how_to_activate_what_it_captured(self):
        result = commands.save(self.root, CWD, "notion", "acme", "some-server",
                               FakeClaude())
        text = "\n".join(result.lines)
        self.assertIn("claude mcp remove some-server -s local", text)
        self.assertIn("switch.py use notion acme", text)

    def test_save_under_a_new_name_needs_no_removal_first(self):
        result = commands.save(self.root, CWD, "notion", "acme", "some-server",
                               FakeClaude(), server="notion-acme")
        self.assertNotIn("claude mcp remove", "\n".join(result.lines))

    def test_save_warns_that_headers_and_env_are_not_captured(self):
        result = commands.save(self.root, CWD, "notion", "acme",
                               "some-server", FakeClaude())
        text = "\n".join(result.lines)
        self.assertIn("headers", text)
        self.assertIn("env", text)
        self.assertIn("-H", text)

    def test_saving_a_missing_server_fails(self):
        result = commands.save(self.root, CWD, "notion", "acme", "nope",
                               FakeClaude(get_output=GET_MISSING))
        self.assertFalse(result.ok)
        self.assertIn("nope", "\n".join(result.lines))

    def test_saving_a_connector_explains_the_limit(self):
        result = commands.save(self.root, CWD, "linear", "work", "claude.ai Linear MCP",
                               FakeClaude(get_output=GET_CONNECTOR))
        self.assertFalse(result.ok)
        self.assertIn("--url", "\n".join(result.lines))


class TestRm(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        store.write_profile(self.root, "linear", "work", LINEAR)

    def tearDown(self):
        self._tmp.cleanup()

    def test_rm_deletes_the_profile(self):
        result = commands.rm(self.root, PROJECT, "linear", "work")
        self.assertTrue(result.ok)
        self.assertFalse(store.profile_path(self.root, "linear", "work").exists())

    def test_rm_refuses_while_active_here(self):
        store.set_active(self.root, PROJECT, "linear", "work")
        result = commands.rm(self.root, PROJECT, "linear", "work")
        self.assertFalse(result.ok)
        self.assertTrue(store.profile_path(self.root, "linear", "work").exists())

    def test_rm_refusal_names_the_profiles_own_server(self):
        store.write_profile(self.root, "linear", "named", dict(LINEAR, server="lw"))
        store.set_active(self.root, PROJECT, "linear", "named", "lw")
        result = commands.rm(self.root, PROJECT, "linear", "named")
        text = "\n".join(result.lines)
        self.assertIn("lw", text)
        self.assertNotIn("linear-named", text)

    def test_rm_refusal_falls_back_to_the_default_server_name(self):
        path = store.profile_path(self.root, "linear", "broken")
        path.write_text("{oops", encoding="utf-8")
        store.set_active(self.root, PROJECT, "linear", "broken")
        self.assertIn("linear-broken",
                      "\n".join(commands.rm(self.root, PROJECT, "linear", "broken").lines))

    def test_rm_refusal_only_offers_the_step_that_unblocks_it(self):
        # Unregistering the server leaves the state slot set, so `rm` would go
        # on refusing: saying otherwise sends the user down a dead end.
        store.set_active(self.root, PROJECT, "linear", "work", "linear-work")
        text = "\n".join(commands.rm(self.root, PROJECT, "linear", "work").lines)
        self.assertNotIn("claude mcp remove", text)
        self.assertIn("switch.py use linear", text)

    def test_rm_of_unknown_profile_fails(self):
        self.assertFalse(commands.rm(self.root, PROJECT, "linear", "ghost").ok)


if __name__ == "__main__":
    unittest.main()
