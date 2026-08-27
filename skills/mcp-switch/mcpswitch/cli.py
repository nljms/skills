"""The one place that shells out to `claude mcp`, plus parsers for its output.

`claude mcp get` exits 0 even when the server does not exist, so status is
always decided by reading the text, never the exit code.
"""
import json
import subprocess
from urllib.parse import urlparse

CONNECTED = "connected"
NEEDS_AUTH = "needs-auth"
FAILED = "failed"
MISSING = "missing"


class ClaudeError(Exception):
    """A `claude mcp` command failed, or its output could not be understood."""


def _subprocess_runner(args, cwd):
    proc = subprocess.run(
        ["claude", "mcp"] + args, cwd=cwd,
        capture_output=True, text=True, timeout=120,
    )
    return proc.returncode, (proc.stdout + proc.stderr).strip()


class Claude:
    def __init__(self, runner=None):
        self._run = runner or _subprocess_runner

    def add_json(self, name: str, config: dict, cwd: str) -> str:
        code, out = self._run(["add-json", name, json.dumps(config), "-s", "local"], cwd)
        if code != 0:
            raise ClaudeError(out)
        return out

    def remove(self, name: str, cwd: str) -> str:
        code, out = self._run(["remove", name, "-s", "local"], cwd)
        if code != 0:
            raise ClaudeError(out)
        return out

    def get(self, name: str, cwd: str) -> str:
        # Read-only: exit code is unreliable here, the caller parses the text.
        return self._run(["get", name], cwd)[1]

    def list(self, cwd: str) -> str:
        return self._run(["list"], cwd)[1]


def _status_from_text(text: str) -> str:
    if "Needs authentication" in text:
        return NEEDS_AUTH
    if "Connected" in text:
        return CONNECTED
    return FAILED


def auth_state(get_output: str) -> str:
    if not get_output or get_output.lstrip().startswith("No MCP server named"):
        return MISSING
    for line in get_output.splitlines():
        stripped = line.strip()
        if stripped.startswith("Status:"):
            return _status_from_text(stripped)
    return FAILED


def _fields(get_output: str) -> dict:
    """Indented `Key: value` lines from `claude mcp get` output."""
    out = {}
    for line in get_output.splitlines():
        if not line.startswith("  ") or ":" not in line:
            continue
        key, value = line.strip().split(":", 1)
        out[key.strip().lower()] = value.strip()
    return out


def parse_server(get_output: str) -> dict:
    fields = _fields(get_output)
    kind = fields.get("type")
    if kind in ("http", "sse"):
        url = fields.get("url")
        if not url:
            raise ClaudeError("server reports no URL; define the profile with --url or --json")
        return {"type": kind, "url": url}
    if kind == "stdio" or "command" in fields:
        config = {"type": "stdio", "command": fields.get("command", "")}
        args = fields.get("args")
        if args:
            # Whitespace split: paths containing spaces need --json instead.
            config["args"] = args.split()
        return config
    raise ClaudeError(
        "no server definition in that output — claude.ai connectors expose no "
        "URL. Define the profile with --url or --json instead."
    )


def statuses(list_output: str) -> dict:
    out = {}
    for line in list_output.splitlines():
        if ": " not in line or " - " not in line:
            continue
        name, rest = line.split(": ", 1)
        out[name.strip()] = _status_from_text(rest.rsplit(" - ", 1)[1])
    return out


def host_of(url) -> str:
    if not url:
        return ""
    return urlparse(url).netloc


def duplicate_hosts(list_output: str, host: str, exclude: str) -> list:
    if not host:
        return []
    out = []
    for line in list_output.splitlines():
        if ": " not in line or " - " not in line:
            continue
        name, rest = line.split(": ", 1)
        name = name.strip()
        target = rest.rsplit(" - ", 1)[0].strip()
        if name != exclude and host_of(target) == host:
            out.append(name)
    return out
