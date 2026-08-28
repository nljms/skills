import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import cli  # noqa: E402

GET_HTTP = """probe-tmp:
  Scope: Local config (private to you in this project)
  Status: ✘ Failed to connect
  Issue: ENOTFOUND: getaddrinfo ENOTFOUND example.invalid
  Type: http
  URL: https://example.invalid/mcp

To remove this server, run: claude mcp remove probe-tmp -s local"""

GET_CONNECTED = """linear-work:
  Scope: Local config (private to you in this project)
  Status: ✔ Connected
  Type: http
  URL: https://mcp.linear.app/mcp"""

GET_NEEDS_AUTH = """linear-work:
  Scope: Local config (private to you in this project)
  Status: ! Needs authentication
  Type: http
  URL: https://mcp.linear.app/mcp"""

GET_CONNECTOR = """claude.ai Linear MCP:
  Scope: claude.ai config
  Status: ✔ Connected"""

GET_MISSING = ('No MCP server named "retell". Configured servers: '
               "claude.ai Excalidraw, claude.ai Figma (and 4 more)")

GET_STDIO = """obsidian-vault:
  Scope: User config (available in all your projects)
  Status: ✔ Connected
  Type: stdio
  Command: npx
  Args: -y @modelcontextprotocol/server-filesystem /tmp/vault
  Environment:"""

LIST = """Checking MCP server health…

claude.ai Linear MCP: https://mcp.linear.app/mcp - ✔ Connected
claude.ai Sentry: https://mcp.sentry.dev/mcp - ! Needs authentication
linear-work: https://mcp.linear.app/mcp - ✔ Connected
broken-one: https://nope.invalid/mcp - ✘ Failed to connect
obsidian-vault: npx -y server-filesystem /tmp/vault - ✔ Connected"""


class FakeRunner:
    def __init__(self, result=(0, "ok")):
        self.calls = []
        self.result = result

    def __call__(self, args, cwd):
        self.calls.append((args, cwd))
        return self.result


class TestSeam(unittest.TestCase):
    def test_add_json_passes_local_scope_and_serialised_config(self):
        fake = FakeRunner()
        claude = cli.Claude(runner=fake)
        claude.add_json("linear-work", {"type": "http", "url": "u"}, "/cwd")
        args, cwd = fake.calls[0]
        self.assertEqual(args[0], "add-json")
        self.assertEqual(args[1], "linear-work")
        self.assertEqual(json.loads(args[2]), {"type": "http", "url": "u"})
        self.assertEqual(args[3:], ["-s", "local"])
        self.assertEqual(cwd, "/cwd")

    def test_remove_passes_local_scope(self):
        fake = FakeRunner()
        cli.Claude(runner=fake).remove("linear-work", "/cwd")
        self.assertEqual(fake.calls[0][0], ["remove", "linear-work", "-s", "local"])

    def test_get_and_list_shell_out_without_scope(self):
        fake = FakeRunner()
        claude = cli.Claude(runner=fake)
        claude.get("linear-work", "/cwd")
        claude.list("/cwd")
        self.assertEqual(fake.calls[0][0], ["get", "linear-work"])
        self.assertEqual(fake.calls[1][0], ["list"])

    def test_nonzero_exit_on_mutation_raises(self):
        fake = FakeRunner(result=(1, "boom"))
        with self.assertRaises(cli.ClaudeError):
            cli.Claude(runner=fake).remove("gone", "/cwd")

    def test_get_tolerates_nonzero_exit(self):
        fake = FakeRunner(result=(1, GET_MISSING))
        self.assertEqual(cli.Claude(runner=fake).get("gone", "/cwd"), GET_MISSING)


class TestParsers(unittest.TestCase):
    def test_auth_states(self):
        self.assertEqual(cli.auth_state(GET_CONNECTED), "connected")
        self.assertEqual(cli.auth_state(GET_NEEDS_AUTH), "needs-auth")
        self.assertEqual(cli.auth_state(GET_HTTP), "failed")
        self.assertEqual(cli.auth_state(GET_MISSING), "missing")
        self.assertEqual(cli.auth_state(""), "missing")

    def test_parse_http_server(self):
        self.assertEqual(cli.parse_server(GET_HTTP),
                         {"type": "http", "url": "https://example.invalid/mcp"})

    def test_parse_stdio_server(self):
        self.assertEqual(
            cli.parse_server(GET_STDIO),
            {"type": "stdio", "command": "npx",
             "args": ["-y", "@modelcontextprotocol/server-filesystem", "/tmp/vault"]},
        )

    def test_parse_connector_is_refused_with_guidance(self):
        with self.assertRaises(cli.ClaudeError) as ctx:
            cli.parse_server(GET_CONNECTOR)
        self.assertIn("--url", str(ctx.exception))

    def test_statuses_from_list(self):
        got = cli.statuses(LIST)
        self.assertEqual(got["linear-work"], "connected")
        self.assertEqual(got["claude.ai Sentry"], "needs-auth")
        self.assertEqual(got["broken-one"], "failed")
        self.assertEqual(got["claude.ai Linear MCP"], "connected")
        self.assertNotIn("Checking MCP server health…", got)

    def test_host_of(self):
        self.assertEqual(cli.host_of("https://mcp.linear.app/mcp"), "mcp.linear.app")
        self.assertEqual(cli.host_of(""), "")
        self.assertEqual(cli.host_of(None), "")

    def test_duplicate_hosts_finds_the_connector_and_skips_ourselves(self):
        dupes = cli.duplicate_hosts(LIST, "mcp.linear.app", exclude="linear-work")
        self.assertEqual(dupes, ["claude.ai Linear MCP"])

    def test_duplicate_hosts_empty_when_host_is_unique(self):
        self.assertEqual(cli.duplicate_hosts(LIST, "mcp.notion.com", "x"), [])

    def test_duplicate_hosts_empty_for_blank_host(self):
        self.assertEqual(cli.duplicate_hosts(LIST, "", "x"), [])


if __name__ == "__main__":
    unittest.main()
