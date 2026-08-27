import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import commands, store  # noqa: E402

CWD = "/tmp/project"
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
        result = commands.show(self.root, CWD, FakeClaude())
        self.assertTrue(result.ok)
        self.assertIn("add", "\n".join(result.lines))

    def test_lists_profiles_with_active_marker_and_status(self):
        store.write_profile(self.root, "linear", "work", LINEAR)
        store.write_profile(self.root, "linear", "personal", LINEAR)
        store.set_active(self.root, CWD, "linear", "work")
        text = "\n".join(commands.show(self.root, CWD, FakeClaude()).lines)
        self.assertIn("linear", text)
        self.assertIn("* work", text)
        self.assertIn("needs-auth", text)
        self.assertIn("personal", text)

    def test_filtering_to_one_provider(self):
        store.write_profile(self.root, "linear", "work", LINEAR)
        store.write_profile(self.root, "notion", "acme", LINEAR)
        text = "\n".join(commands.show(self.root, CWD, FakeClaude(), provider="linear").lines)
        self.assertIn("linear", text)
        self.assertNotIn("notion", text)

    def test_unknown_provider_filter_fails(self):
        result = commands.show(self.root, CWD, FakeClaude(), provider="ghost")
        self.assertFalse(result.ok)

    def test_malformed_profile_is_reported_not_raised(self):
        path = store.profile_path(self.root, "linear", "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{oops", encoding="utf-8")
        result = commands.show(self.root, CWD, FakeClaude())
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
        result = commands.rm(self.root, CWD, "linear", "work")
        self.assertTrue(result.ok)
        self.assertFalse(store.profile_path(self.root, "linear", "work").exists())

    def test_rm_refuses_while_active_here(self):
        store.set_active(self.root, CWD, "linear", "work")
        result = commands.rm(self.root, CWD, "linear", "work")
        self.assertFalse(result.ok)
        self.assertTrue(store.profile_path(self.root, "linear", "work").exists())

    def test_rm_of_unknown_profile_fails(self):
        self.assertFalse(commands.rm(self.root, CWD, "linear", "ghost").ok)


if __name__ == "__main__":
    unittest.main()
