# mcp-switch Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Ship an `mcp-switch` skill that flips an MCP provider (Linear, Notion, …) between named account profiles with one command, per project.

**Architecture:** Profiles are JSON files in `~/.claude/mcp/<project>/<provider>/<profile>.json`, keyed on the main repo's directory name so every worktree shares one profile set. Switching writes the chosen profile into Claude Code's **local scope** (`claude mcp add-json … -s local`), which is keyed on the working directory, after removing the previously active one. Every call to `claude mcp` goes through one injectable seam so the command layer is fully testable without touching the machine's real config.

**Tech Stack:** Python 3 standard library only. `unittest`, one file per module, run by `run_tests.sh` (mirrors `skills/doc-server`).

**Spec:** `docs/superpowers/specs/2026-08-27-mcp-switch-design.md`

## Global Constraints

- **Python 3 standard library only.** No pip installs, no third-party imports.
- **Every subprocess call lives in `mcpswitch/cli.py`.** No other module may import `subprocess` except `identity.py`, which shells out to `git` for project resolution.
- **Local scope only.** All `claude mcp` mutations pass `-s local`. Never `-s user`, never `-s project`.
- **Never touch OAuth credentials.** The skill never runs `claude mcp logout`, never reads the keychain, never writes credential files. Auth is always the user running `claude mcp login <server>` themselves.
- **Server names are distinct per profile.** Default `<provider>-<profile>`; overridable via a `server` key inside the profile JSON.
- **`claude mcp get` exits 0 even when the server does not exist.** Status is determined by parsing output text, never by exit code. A missing server prints `No MCP server named "<name>".`
- **Store home is overridable for tests** via the `MCP_SWITCH_HOME` environment variable; default `~/.claude/mcp`.
- Tests are `unittest` files runnable standalone (`python3 tests/test_x.py`), each ending in `OK`.

### Real `claude mcp` output formats (verified on this machine, 2026-08-28)

`claude mcp get <name>` for a local http server:

```
probe-tmp:
  Scope: Local config (private to you in this project)
  Status: ✘ Failed to connect
  Issue: ENOTFOUND: getaddrinfo ENOTFOUND example.invalid
  Type: http
  URL: https://example.invalid/mcp

To remove this server, run: claude mcp remove probe-tmp -s local
```

`claude mcp get <name>` for a claude.ai connector — note **no Type/URL lines**:

```
claude.ai Linear MCP:
  Scope: claude.ai config
  Status: ✔ Connected
```

`claude mcp get <missing>`:

```
No MCP server named "retell". Configured servers: claude.ai Excalidraw, … (and 4 more — run `claude mcp list` to see all)
```

`claude mcp list`:

```
Checking MCP server health…

claude.ai Linear MCP: https://mcp.linear.app/mcp - ✔ Connected
claude.ai Sentry: https://mcp.sentry.dev/mcp - ! Needs authentication
obsidian-vault: npx -y @modelcontextprotocol/server-filesystem /Users/me/Obsidian Vault - ✔ Connected
```

Status strings seen: `✔ Connected`, `! Needs authentication`, `✘ Failed to connect`.

---

## File Structure

| File | Responsibility |
|---|---|
| `skills/mcp-switch/switch.py` | CLI entry point: argparse subcommands, prints `Result.lines`, sets exit code |
| `skills/mcp-switch/mcpswitch/identity.py` | Resolve store home + project key (main repo dir name) from a cwd |
| `skills/mcp-switch/mcpswitch/store.py` | Read/write profile JSON and the per-cwd active-profile state |
| `skills/mcp-switch/mcpswitch/cli.py` | The single `claude mcp` subprocess seam + pure parsers for its output |
| `skills/mcp-switch/mcpswitch/commands.py` | `use` / `show` / `add` / `save` / `rm`, composed from store + cli |
| `skills/mcp-switch/tests/*.py` | One `unittest` file per module |
| `skills/mcp-switch/run_tests.sh` | Runs each test file, fails loudly |
| `skills/mcp-switch/SKILL.md` | Skill frontmatter + agent-facing usage |
| `skills/mcp-switch/README.md` | Human-facing overview |
| `.claude-plugin/marketplace.json` | New plugin entry (modify) |
| `README.md` | Skills list (modify) |

---

## Task 1: Identity — store home and project key

**Files:**
- Create: `skills/mcp-switch/mcpswitch/__init__.py` (empty)
- Create: `skills/mcp-switch/mcpswitch/identity.py`
- Test: `skills/mcp-switch/tests/test_identity.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `store_home() -> pathlib.Path`
  - `project_key(cwd: str) -> str`
  - `project_store(cwd: str) -> pathlib.Path`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_identity.py`:

```python
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import identity  # noqa: E402


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


class TestIdentity(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.tmp = os.path.realpath(self._tmp.name)
        self._home = tempfile.TemporaryDirectory()
        os.environ["MCP_SWITCH_HOME"] = self._home.name

    def tearDown(self):
        os.environ.pop("MCP_SWITCH_HOME", None)
        self._tmp.cleanup()
        self._home.cleanup()

    def _repo(self, name):
        root = os.path.join(self.tmp, name)
        os.makedirs(root)
        _run(["git", "init", "-b", "main"], root)
        _run(["git", "config", "user.email", "t@t.t"], root)
        _run(["git", "config", "user.name", "t"], root)
        Path(root, "f.txt").write_text("x", encoding="utf-8")
        _run(["git", "add", "."], root)
        _run(["git", "commit", "-m", "init"], root)
        return root

    def test_home_honours_env_override(self):
        self.assertEqual(identity.store_home(), Path(self._home.name))

    def test_home_is_created(self):
        target = os.path.join(self.tmp, "nested", "home")
        os.environ["MCP_SWITCH_HOME"] = target
        self.assertTrue(identity.store_home().is_dir())

    def test_project_key_is_repo_dir_name(self):
        root = self._repo("myrepo")
        self.assertEqual(identity.project_key(root), "myrepo")

    def test_subdirectory_resolves_to_repo_name(self):
        root = self._repo("myrepo")
        sub = os.path.join(root, "deep", "dir")
        os.makedirs(sub)
        self.assertEqual(identity.project_key(sub), "myrepo")

    def test_worktree_shares_the_main_repo_key(self):
        root = self._repo("myrepo")
        wt = os.path.join(self.tmp, "elsewhere", "feature-checkout")
        os.makedirs(os.path.dirname(wt))
        _run(["git", "worktree", "add", "-b", "feat", wt], root)
        self.assertEqual(identity.project_key(wt), "myrepo")

    def test_non_git_falls_back_to_directory_name(self):
        plain = os.path.join(self.tmp, "loose-folder")
        os.makedirs(plain)
        self.assertEqual(identity.project_key(plain), "loose-folder")

    def test_project_store_is_created_under_home(self):
        root = self._repo("myrepo")
        store = identity.project_store(root)
        self.assertEqual(store, Path(self._home.name) / "myrepo")
        self.assertTrue(store.is_dir())


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_identity.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'mcpswitch'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/mcp-switch/mcpswitch/__init__.py` as an empty file, then `skills/mcp-switch/mcpswitch/identity.py`:

```python
"""Resolve where a project's MCP profiles live.

Profiles are keyed on the *main* repository's directory name, resolved through
`git rev-parse --git-common-dir`, so every linked worktree of a repo shares one
profile set. A non-git directory falls back to its own basename.
"""
import os
import subprocess
from pathlib import Path


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def store_home() -> Path:
    base = os.environ.get("MCP_SWITCH_HOME")
    home = Path(base) if base else Path.home() / ".claude" / "mcp"
    home.mkdir(parents=True, exist_ok=True)
    return home


def project_key(cwd: str) -> str:
    # realpath so macOS symlinks (/var -> /private/var) match git's own output
    cwd = os.path.realpath(cwd)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if not common:
        return os.path.basename(cwd.rstrip(os.sep))
    common = os.path.realpath(os.path.join(cwd, common))
    return os.path.basename(os.path.dirname(common).rstrip(os.sep))


def project_store(cwd: str) -> Path:
    root = store_home() / project_key(cwd)
    root.mkdir(parents=True, exist_ok=True)
    return root
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/mcp-switch/tests/test_identity.py`
Expected: PASS — `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/mcpswitch/__init__.py skills/mcp-switch/mcpswitch/identity.py skills/mcp-switch/tests/test_identity.py
git commit -m "mcp-switch: resolve the per-project profile store"
```

---

## Task 2: Store — profiles and active state

**Files:**
- Create: `skills/mcp-switch/mcpswitch/store.py`
- Test: `skills/mcp-switch/tests/test_store.py`

**Interfaces:**
- Consumes: nothing (takes `root: Path` as an argument; `identity` is wired in by `switch.py`)
- Produces:
  - `class StoreError(Exception)`
  - `server_name(provider: str, profile: str, config: dict) -> str`
  - `server_config(config: dict) -> dict`
  - `profile_path(root, provider, profile) -> Path`
  - `read_profile(root, provider, profile) -> dict` (raises `StoreError`)
  - `write_profile(root, provider, profile, config: dict) -> Path`
  - `delete_profile(root, provider, profile) -> bool`
  - `providers(root) -> list[str]`
  - `profiles(root, provider) -> list[str]`
  - `get_active(root, cwd, provider) -> str | None`
  - `set_active(root, cwd, provider, profile) -> None`
  - `clear_active(root, cwd, provider) -> None`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_store.py`:

```python
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import store  # noqa: E402

HTTP = {"type": "http", "url": "https://mcp.linear.app/mcp"}


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.cwd = "/tmp/some/project"

    def tearDown(self):
        self._tmp.cleanup()

    def test_server_name_defaults_to_provider_profile(self):
        self.assertEqual(store.server_name("linear", "work", {}), "linear-work")

    def test_server_name_honours_explicit_override(self):
        self.assertEqual(store.server_name("linear", "work", {"server": "lw"}), "lw")

    def test_server_config_strips_the_server_key(self):
        cfg = dict(HTTP, server="linear-work")
        self.assertEqual(store.server_config(cfg), HTTP)

    def test_profile_round_trip(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        self.assertEqual(store.read_profile(self.root, "linear", "work"), HTTP)

    def test_read_missing_profile_raises_named_error(self):
        with self.assertRaises(store.StoreError) as ctx:
            store.read_profile(self.root, "linear", "nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertIn("linear", str(ctx.exception))

    def test_malformed_profile_raises_readable_error(self):
        path = store.profile_path(self.root, "linear", "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.read_profile(self.root, "linear", "broken")
        self.assertIn(str(path), str(ctx.exception))

    def test_non_object_profile_raises(self):
        path = store.profile_path(self.root, "linear", "listy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            store.read_profile(self.root, "linear", "listy")

    def test_listing_providers_and_profiles(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        store.write_profile(self.root, "linear", "personal", HTTP)
        store.write_profile(self.root, "notion", "acme", HTTP)
        self.assertEqual(store.providers(self.root), ["linear", "notion"])
        self.assertEqual(store.profiles(self.root, "linear"), ["personal", "work"])

    def test_listing_empty_store_is_empty(self):
        self.assertEqual(store.providers(self.root), [])
        self.assertEqual(store.profiles(self.root, "linear"), [])

    def test_state_json_is_not_listed_as_a_provider(self):
        store.set_active(self.root, self.cwd, "linear", "work")
        self.assertEqual(store.providers(self.root), [])

    def test_delete_profile_reports_whether_it_existed(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        self.assertTrue(store.delete_profile(self.root, "linear", "work"))
        self.assertFalse(store.delete_profile(self.root, "linear", "work"))
        self.assertFalse((self.root / "linear").exists())

    def test_active_profile_is_keyed_per_cwd(self):
        other = "/tmp/other/worktree"
        store.set_active(self.root, self.cwd, "linear", "work")
        store.set_active(self.root, other, "linear", "personal")
        self.assertEqual(store.get_active(self.root, self.cwd, "linear"), "work")
        self.assertEqual(store.get_active(self.root, other, "linear"), "personal")

    def test_active_is_none_when_unset(self):
        self.assertIsNone(store.get_active(self.root, self.cwd, "linear"))

    def test_clear_active_removes_the_provider_entry(self):
        store.set_active(self.root, self.cwd, "linear", "work")
        store.clear_active(self.root, self.cwd, "linear")
        self.assertIsNone(store.get_active(self.root, self.cwd, "linear"))

    def test_clear_active_is_safe_when_unset(self):
        store.clear_active(self.root, self.cwd, "linear")  # must not raise

    def test_corrupt_state_file_degrades_to_empty(self):
        (self.root / "state.json").write_text("{oops", encoding="utf-8")
        self.assertIsNone(store.get_active(self.root, self.cwd, "linear"))
        store.set_active(self.root, self.cwd, "linear", "work")
        self.assertEqual(store.get_active(self.root, self.cwd, "linear"), "work")

    def test_state_file_is_readable_json(self):
        store.set_active(self.root, self.cwd, "linear", "work")
        data = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(data[os.path.realpath(self.cwd)]["linear"], "work")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_store.py`
Expected: FAIL — `ImportError: cannot import name 'store'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/mcp-switch/mcpswitch/store.py`:

```python
"""Profile files and the per-cwd record of which profile is active.

Layout under the project's store root:

    <root>/state.json            {"<cwd>": {"<provider>": "<profile>"}}
    <root>/<provider>/<profile>.json

A profile file is the JSON handed to `claude mcp add-json`, plus an optional
"server" key naming the registered server (default "<provider>-<profile>").
"""
import json
import os
from pathlib import Path

STATE_FILE = "state.json"


class StoreError(Exception):
    """A profile could not be read, parsed, or found."""


def server_name(provider: str, profile: str, config: dict) -> str:
    return config.get("server") or f"{provider}-{profile}"


def server_config(config: dict) -> dict:
    """The profile minus our own bookkeeping key."""
    return {k: v for k, v in config.items() if k != "server"}


def profile_path(root, provider: str, profile: str) -> Path:
    return Path(root) / provider / f"{profile}.json"


def read_profile(root, provider: str, profile: str) -> dict:
    path = profile_path(root, provider, profile)
    if not path.exists():
        raise StoreError(f'no profile "{profile}" for provider "{provider}"')
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except ValueError as exc:
        raise StoreError(f"{path} is not valid JSON: {exc}")
    if not isinstance(data, dict):
        raise StoreError(f"{path} must contain a JSON object")
    return data


def write_profile(root, provider: str, profile: str, config: dict) -> Path:
    path = profile_path(root, provider, profile)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, indent=2) + "\n", encoding="utf-8")
    return path


def delete_profile(root, provider: str, profile: str) -> bool:
    path = profile_path(root, provider, profile)
    if not path.exists():
        return False
    path.unlink()
    if not any(path.parent.iterdir()):
        path.parent.rmdir()
    return True


def providers(root) -> list:
    root = Path(root)
    if not root.exists():
        return []
    return sorted(p.name for p in root.iterdir() if p.is_dir())


def profiles(root, provider: str) -> list:
    d = Path(root) / provider
    if not d.exists():
        return []
    return sorted(p.stem for p in d.glob("*.json"))


def _state_file(root) -> Path:
    return Path(root) / STATE_FILE


def _read_state(root) -> dict:
    try:
        data = json.loads(_state_file(root).read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _write_state(root, data) -> None:
    path = _state_file(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_active(root, cwd: str, provider: str):
    return _read_state(root).get(os.path.realpath(cwd), {}).get(provider)


def set_active(root, cwd: str, provider: str, profile: str) -> None:
    data = _read_state(root)
    data.setdefault(os.path.realpath(cwd), {})[provider] = profile
    _write_state(root, data)


def clear_active(root, cwd: str, provider: str) -> None:
    data = _read_state(root)
    key = os.path.realpath(cwd)
    if data.get(key, {}).pop(provider, None) is None:
        return
    if not data[key]:
        del data[key]
    _write_state(root, data)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/mcp-switch/tests/test_store.py`
Expected: PASS — `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/mcpswitch/store.py skills/mcp-switch/tests/test_store.py
git commit -m "mcp-switch: profile store and per-cwd active state"
```

---

## Task 3: The `claude mcp` seam and its output parsers

**Files:**
- Create: `skills/mcp-switch/mcpswitch/cli.py`
- Test: `skills/mcp-switch/tests/test_cli_seam.py`

**Interfaces:**
- Consumes: nothing
- Produces:
  - `class ClaudeError(Exception)`
  - `class Claude` with `__init__(self, runner=None)`, `add_json(name, config, cwd) -> str`, `remove(name, cwd) -> str`, `get(name, cwd) -> str`, `list(cwd) -> str`. A `runner` is any callable `(args: list[str], cwd: str) -> (returncode: int, output: str)`; `args` excludes the leading `claude mcp`.
  - `auth_state(get_output: str) -> str` — one of `"connected"`, `"needs-auth"`, `"failed"`, `"missing"`
  - `statuses(list_output: str) -> dict[str, str]` — server name → same four values
  - `parse_server(get_output: str) -> dict` (raises `ClaudeError`)
  - `host_of(url: str) -> str`
  - `duplicate_hosts(list_output: str, host: str, exclude: str) -> list[str]`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_cli_seam.py`:

```python
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import cli  # noqa: E402

GET_HTTP = """probe-tmp:
  Scope: Local config (private to you in this project)
  Status: \u2718 Failed to connect
  Issue: ENOTFOUND: getaddrinfo ENOTFOUND example.invalid
  Type: http
  URL: https://example.invalid/mcp

To remove this server, run: claude mcp remove probe-tmp -s local"""

GET_CONNECTED = """linear-work:
  Scope: Local config (private to you in this project)
  Status: \u2714 Connected
  Type: http
  URL: https://mcp.linear.app/mcp"""

GET_NEEDS_AUTH = """linear-work:
  Scope: Local config (private to you in this project)
  Status: ! Needs authentication
  Type: http
  URL: https://mcp.linear.app/mcp"""

GET_CONNECTOR = """claude.ai Linear MCP:
  Scope: claude.ai config
  Status: \u2714 Connected"""

GET_MISSING = ('No MCP server named "retell". Configured servers: '
               "claude.ai Excalidraw, claude.ai Figma (and 4 more)")

GET_STDIO = """obsidian-vault:
  Scope: User config (available in all your projects)
  Status: \u2714 Connected
  Type: stdio
  Command: npx
  Args: -y @modelcontextprotocol/server-filesystem /tmp/vault
  Environment:"""

LIST = """Checking MCP server health\u2026

claude.ai Linear MCP: https://mcp.linear.app/mcp - \u2714 Connected
claude.ai Sentry: https://mcp.sentry.dev/mcp - ! Needs authentication
linear-work: https://mcp.linear.app/mcp - \u2714 Connected
broken-one: https://nope.invalid/mcp - \u2718 Failed to connect
obsidian-vault: npx -y server-filesystem /tmp/vault - \u2714 Connected"""


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
        self.assertNotIn("Checking MCP server health\u2026", got)

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_cli_seam.py`
Expected: FAIL — `ImportError: cannot import name 'cli'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/mcp-switch/mcpswitch/cli.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/mcp-switch/tests/test_cli_seam.py`
Expected: PASS — `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/mcpswitch/cli.py skills/mcp-switch/tests/test_cli_seam.py
git commit -m "mcp-switch: claude mcp seam and output parsers"
```

---

## Task 4: `use` — the switch itself

**Files:**
- Create: `skills/mcp-switch/mcpswitch/commands.py`
- Test: `skills/mcp-switch/tests/test_use.py`

**Interfaces:**
- Consumes: `store` (Task 2), `cli` (Task 3)
- Produces:
  - `@dataclass class Result: ok: bool; lines: list`
  - `use(root, cwd, provider, profile, claude) -> Result`
  - `RECONNECT_HINT = "run /mcp (or restart the session) for this to take effect"`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_use.py`:

```python
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

CONNECTED = "n:\n  Status: \u2714 Connected\n  Type: http\n  URL: https://mcp.linear.app/mcp"
NEEDS_AUTH = "n:\n  Status: ! Needs authentication\n  Type: http\n  URL: https://mcp.linear.app/mcp"
BROKEN = "n:\n  Status: \u2718 Failed to connect\n  Type: http\n  URL: https://mcp.linear.app/mcp"

LIST_WITH_CONNECTOR = (
    "claude.ai Linear MCP: https://mcp.linear.app/mcp - \u2714 Connected\n"
    "linear-personal: https://mcp.linear.app/mcp - \u2714 Connected"
)
LIST_CLEAN = "linear-personal: https://mcp.linear.app/mcp - \u2714 Connected"


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_use.py`
Expected: FAIL — `ImportError: cannot import name 'commands'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/mcp-switch/mcpswitch/commands.py`:

```python
"""The commands the CLI exposes, composed from the store and the claude seam.

Every command returns a Result; printing is the CLI's job.
"""
from dataclasses import dataclass, field

from . import cli, store

RECONNECT_HINT = "run /mcp (or restart the session) for this to take effect"


@dataclass
class Result:
    ok: bool
    lines: list = field(default_factory=list)


def _deactivate(root, cwd, provider, previous, claude, lines):
    """Remove the previously active server, tolerating one that is already gone."""
    try:
        config = store.read_profile(root, provider, previous)
    except store.StoreError:
        config = {}          # profile file deleted since it was activated
    name = store.server_name(provider, previous, config)
    try:
        claude.remove(name, cwd)
        lines.append(f"removed {name}")
    except cli.ClaudeError:
        lines.append(f"{name} was already gone")


def use(root, cwd, provider, profile, claude) -> Result:
    try:
        config = store.read_profile(root, provider, profile)
    except store.StoreError as exc:
        known = store.profiles(root, provider)
        hint = f"known profiles: {', '.join(known)}" if known else \
            f"no profiles for {provider} yet — add one with: switch.py add {provider} <profile> --url <url>"
        return Result(False, [str(exc), hint])

    name = store.server_name(provider, profile, config)
    lines = []

    previous = store.get_active(root, cwd, provider)
    if previous and previous != profile:
        _deactivate(root, cwd, provider, previous, claude, lines)

    try:
        claude.add_json(name, store.server_config(config), cwd)
    except cli.ClaudeError as exc:
        lines.append(f"could not register {name}: {exc}")
        return Result(False, lines)

    store.set_active(root, cwd, provider, profile)
    lines.append(f"{provider} -> {profile} ({name})")

    state = cli.auth_state(claude.get(name, cwd))
    if state == cli.NEEDS_AUTH:
        lines.append(f"needs auth: claude mcp login {name}")
    elif state == cli.FAILED:
        lines.append(f"registered but not connected — check: claude mcp get {name}")
    elif state == cli.MISSING:
        lines.append(f"registered but not visible — check: claude mcp list")

    host = cli.host_of(config.get("url"))
    for other in cli.duplicate_hosts(claude.list(cwd), host, exclude=name):
        lines.append(
            f"warning: {other} also serves {host} — both sets of tools are live; "
            "disconnect it in claude.ai settings if you want only one"
        )

    lines.append(RECONNECT_HINT)
    return Result(True, lines)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/mcp-switch/tests/test_use.py`
Expected: PASS — `OK`

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/mcpswitch/commands.py skills/mcp-switch/tests/test_use.py
git commit -m "mcp-switch: use command switches the active profile"
```

---

## Task 5: `show`, `add`, `save`, `rm`

**Files:**
- Modify: `skills/mcp-switch/mcpswitch/commands.py` (append the four functions)
- Test: `skills/mcp-switch/tests/test_commands.py`

**Interfaces:**
- Consumes: `Result`, `RECONNECT_HINT` (Task 4); `store` (Task 2); `cli` (Task 3)
- Produces:
  - `show(root, cwd, claude, provider=None) -> Result`
  - `add(root, provider, profile, url=None, transport="http", headers=(), json_config=None, server=None) -> Result`
  - `save(root, cwd, provider, profile, from_server, claude, server=None) -> Result`
  - `rm(root, cwd, provider, profile) -> Result`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_commands.py`:

```python
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
        "linear-personal: https://mcp.linear.app/mcp - \u2714 Connected")

GET_HTTP = ("some-server:\n  Scope: Local config (private to you in this project)\n"
            "  Status: \u2714 Connected\n  Type: http\n  URL: https://mcp.notion.com/mcp")
GET_CONNECTOR = "claude.ai Linear MCP:\n  Scope: claude.ai config\n  Status: \u2714 Connected"
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_commands.py`
Expected: FAIL — `AttributeError: module 'mcpswitch.commands' has no attribute 'show'`

- [ ] **Step 3: Write minimal implementation**

Append to `skills/mcp-switch/mcpswitch/commands.py` (keep the existing imports; add `import json` at the top of the file):

```python
def show(root, cwd, claude, provider=None) -> Result:
    known = store.providers(root)
    if provider and provider not in known:
        return Result(False, [f'no profiles for provider "{provider}"',
                              f"known providers: {', '.join(known)}" if known else
                              "the store is empty"])
    wanted = [provider] if provider else known
    if not wanted:
        return Result(True, [
            "no profiles yet",
            "add one with: switch.py add <provider> <profile> --url <url>",
        ])

    live = cli.statuses(claude.list(cwd))
    lines = []
    for name in wanted:
        active = store.get_active(root, cwd, name)
        lines.append(f"{name}:")
        for prof in store.profiles(root, name):
            try:
                config = store.read_profile(root, name, prof)
            except store.StoreError:
                lines.append(f"    {prof} — unreadable profile file")
                continue
            server = store.server_name(name, prof, config)
            mark = "*" if prof == active else " "
            status = live.get(server, "not registered here")
            target = config.get("url", config.get("command", ""))
            lines.append(f"  {mark} {prof:<12} {server:<24} {status:<18} {target}")
    return Result(True, lines)


def _headers(pairs) -> dict:
    out = {}
    for pair in pairs:
        if ":" not in pair:
            raise ValueError(f'header "{pair}" must look like "Name: value"')
        key, value = pair.split(":", 1)
        out[key.strip()] = value.strip()
    return out


def add(root, provider, profile, url=None, transport="http", headers=(),
        json_config=None, server=None) -> Result:
    if json_config:
        try:
            config = json.loads(json_config)
        except ValueError as exc:
            return Result(False, [f"--json is not valid JSON: {exc}"])
        if not isinstance(config, dict):
            return Result(False, ["--json must be a JSON object"])
    elif url:
        config = {"type": transport, "url": url}
        try:
            parsed = _headers(headers)
        except ValueError as exc:
            return Result(False, [str(exc)])
        if parsed:
            config["headers"] = parsed
    else:
        return Result(False, ["give either --url or --json"])

    if server:
        config["server"] = server
    path = store.write_profile(root, provider, profile, config)
    return Result(True, [
        f"wrote {path}",
        f"activate it with: switch.py use {provider} {profile}",
    ])


def save(root, cwd, provider, profile, from_server, claude, server=None) -> Result:
    output = claude.get(from_server, cwd)
    if cli.auth_state(output) == cli.MISSING:
        return Result(False, [f'no MCP server named "{from_server}"',
                              "see what is configured with: claude mcp list"])
    try:
        config = cli.parse_server(output)
    except cli.ClaudeError as exc:
        return Result(False, [str(exc)])

    config["server"] = server or from_server
    path = store.write_profile(root, provider, profile, config)
    return Result(True, [
        f"saved {from_server} as {provider}/{profile}",
        f"wrote {path}",
    ])


def rm(root, cwd, provider, profile) -> Result:
    if store.get_active(root, cwd, provider) == profile:
        return Result(False, [
            f"{provider}/{profile} is active in this directory",
            "switch to another profile first, or unregister it with: "
            f"claude mcp remove {store.server_name(provider, profile, {})} -s local",
        ])
    if not store.delete_profile(root, provider, profile):
        return Result(False, [f'no profile "{profile}" for provider "{provider}"'])
    return Result(True, [f"deleted {provider}/{profile}",
                         "stored credentials are untouched"])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/mcp-switch/tests/test_commands.py && python3 skills/mcp-switch/tests/test_use.py`
Expected: PASS — `OK` twice (the second run proves Task 4 still passes)

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/mcpswitch/commands.py skills/mcp-switch/tests/test_commands.py
git commit -m "mcp-switch: list, add, save and remove profiles"
```

---

## Task 6: CLI entry point and test runner

**Files:**
- Create: `skills/mcp-switch/switch.py`
- Create: `skills/mcp-switch/run_tests.sh`
- Test: `skills/mcp-switch/tests/test_switch_cli.py`

**Interfaces:**
- Consumes: `identity.project_store` (Task 1), `cli.Claude` (Task 3), all `commands` (Tasks 4-5)
- Produces: `main(argv=None, claude=None) -> int` — returns the process exit code (`0` ok, `1` failure), prints `Result.lines`

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_switch_cli.py`:

```python
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import switch  # noqa: E402
from mcpswitch import identity, store  # noqa: E402

LINEAR_URL = "https://mcp.linear.app/mcp"
CONNECTED = f"n:\n  Status: \u2714 Connected\n  Type: http\n  URL: {LINEAR_URL}"


class FakeClaude:
    def __init__(self):
        self.calls = []

    def add_json(self, name, config, cwd):
        self.calls.append(("add", name))

    def remove(self, name, cwd):
        self.calls.append(("remove", name))

    def get(self, name, cwd):
        return CONNECTED

    def list(self, cwd):
        return f"linear-work: {LINEAR_URL} - \u2714 Connected"


class TestSwitchCli(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["MCP_SWITCH_HOME"] = self._home.name
        self.claude = FakeClaude()
        # Same resolution the CLI uses: the main repo's name, not the cwd's.
        self.root = identity.project_store(os.getcwd())

    def tearDown(self):
        os.environ.pop("MCP_SWITCH_HOME", None)
        self._home.cleanup()

    def _run(self, argv):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = switch.main(argv, claude=self.claude)
        return code, buf.getvalue()

    def test_add_then_use_then_list(self):
        code, _ = self._run(["add", "linear", "work", "--url", LINEAR_URL])
        self.assertEqual(code, 0)

        code, out = self._run(["use", "linear", "work"])
        self.assertEqual(code, 0)
        self.assertIn("linear-work", out)
        self.assertIn("/mcp", out)
        self.assertIn(("add", "linear-work"), self.claude.calls)

        code, out = self._run(["list"])
        self.assertEqual(code, 0)
        self.assertIn("* work", out)

    def test_use_unknown_profile_exits_nonzero(self):
        code, out = self._run(["use", "linear", "ghost"])
        self.assertEqual(code, 1)
        self.assertIn("ghost", out)

    def test_add_with_headers_and_transport(self):
        self._run(["add", "acme", "prod", "--url", "https://x.dev/mcp",
                   "--transport", "sse", "-H", "X-Api-Key: abc"])
        cfg = store.read_profile(self.root, "acme", "prod")
        self.assertEqual(cfg["type"], "sse")
        self.assertEqual(cfg["headers"], {"X-Api-Key": "abc"})

    def test_add_with_json(self):
        self._run(["add", "local", "vault", "--json",
                   json.dumps({"type": "stdio", "command": "npx"})])
        self.assertEqual(store.read_profile(self.root, "local", "vault")["command"], "npx")

    def test_save_captures_from_a_live_server(self):
        code, _ = self._run(["save", "linear", "work", "--from", "linear-work"])
        self.assertEqual(code, 0)
        self.assertEqual(store.read_profile(self.root, "linear", "work")["url"], LINEAR_URL)

    def test_rm_deletes_an_inactive_profile(self):
        self._run(["add", "linear", "spare", "--url", LINEAR_URL])
        code, _ = self._run(["rm", "linear", "spare"])
        self.assertEqual(code, 0)
        self.assertFalse(store.profile_path(self.root, "linear", "spare").exists())

    def test_list_filtered_by_provider(self):
        self._run(["add", "linear", "work", "--url", LINEAR_URL])
        code, out = self._run(["list", "linear"])
        self.assertEqual(code, 0)
        self.assertIn("linear", out)

    def test_no_subcommand_exits_nonzero(self):
        buf = io.StringIO()
        with redirect_stdout(buf):
            with self.assertRaises(SystemExit):
                switch.main([], claude=self.claude)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_switch_cli.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'switch'`

- [ ] **Step 3: Write minimal implementation**

Create `skills/mcp-switch/switch.py`:

```python
#!/usr/bin/env python3
"""mcp-switch CLI: flip an MCP provider between named account profiles."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from mcpswitch import cli, commands, identity  # noqa: E402


def _parser():
    parser = argparse.ArgumentParser(
        description="Switch an MCP provider between named account profiles.")
    subs = parser.add_subparsers(dest="command", required=True)

    show = subs.add_parser("list", help="show profiles and which one is active here")
    show.add_argument("provider", nargs="?", default=None)

    use = subs.add_parser("use", help="activate a profile in this directory")
    use.add_argument("provider")
    use.add_argument("profile")

    add = subs.add_parser("add", help="define a profile")
    add.add_argument("provider")
    add.add_argument("profile")
    add.add_argument("--url", default=None, help="server URL (http/sse)")
    add.add_argument("--transport", default="http", choices=["http", "sse"])
    add.add_argument("-H", "--header", action="append", default=[],
                     help='header, e.g. -H "X-Api-Key: abc"')
    add.add_argument("--json", dest="json_config", default=None,
                     help="raw server JSON, for stdio or anything unusual")
    add.add_argument("--server", default=None,
                     help="registered server name (default <provider>-<profile>)")

    save = subs.add_parser("save", help="capture an already-configured server")
    save.add_argument("provider")
    save.add_argument("profile")
    save.add_argument("--from", dest="from_server", required=True)
    save.add_argument("--server", default=None)

    remove = subs.add_parser("rm", help="delete a profile from the store")
    remove.add_argument("provider")
    remove.add_argument("profile")

    return parser


def main(argv=None, claude=None) -> int:
    args = _parser().parse_args(argv)
    cwd = os.getcwd()
    root = identity.project_store(cwd)
    claude = claude or cli.Claude()

    if args.command == "list":
        result = commands.show(root, cwd, claude, provider=args.provider)
    elif args.command == "use":
        result = commands.use(root, cwd, args.provider, args.profile, claude)
    elif args.command == "add":
        result = commands.add(root, args.provider, args.profile, url=args.url,
                              transport=args.transport, headers=args.header,
                              json_config=args.json_config, server=args.server)
    elif args.command == "save":
        result = commands.save(root, cwd, args.provider, args.profile,
                               args.from_server, claude, server=args.server)
    else:
        result = commands.rm(root, cwd, args.provider, args.profile)

    for line in result.lines:
        print(line)
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main())
```

Create `skills/mcp-switch/run_tests.sh`:

```bash
#!/usr/bin/env bash
# Run all mcp-switch tests (tests/ has no __init__, so run each file).
cd "$(dirname "$0")"
fail=0
for f in tests/test_*.py; do
  out=$(python3 "$f" 2>&1)
  res=$(echo "$out" | tail -1)
  if [ "$res" != "OK" ]; then
    echo "FAIL: $f"; echo "$out" | tail -20; fail=1
  else
    echo "ok:   $f"
  fi
done
exit $fail
```

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `chmod +x skills/mcp-switch/run_tests.sh && ./skills/mcp-switch/run_tests.sh`
Expected: every line reads `ok:   tests/test_*.py`, exit code 0

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/switch.py skills/mcp-switch/run_tests.sh skills/mcp-switch/tests/test_switch_cli.py
git commit -m "mcp-switch: CLI entry point and test runner"
```

---

## Task 7: Skill documentation and marketplace wiring

**Files:**
- Create: `skills/mcp-switch/SKILL.md`
- Create: `skills/mcp-switch/README.md`
- Modify: `.claude-plugin/marketplace.json`
- Modify: `README.md`
- Test: `skills/mcp-switch/tests/test_skill_md.py`

**Interfaces:**
- Consumes: the CLI surface from Task 6
- Produces: nothing further tasks depend on

- [ ] **Step 1: Write the failing test**

Create `skills/mcp-switch/tests/test_skill_md.py`:

```python
import json
import os
import unittest

HERE = os.path.dirname(__file__)
SKILL_MD = os.path.abspath(os.path.join(HERE, "..", "SKILL.md"))
MARKETPLACE = os.path.abspath(
    os.path.join(HERE, "..", "..", "..", ".claude-plugin", "marketplace.json"))


class TestSkillMd(unittest.TestCase):
    def _text(self):
        with open(SKILL_MD) as f:
            return f.read()

    def test_frontmatter(self):
        text = self._text()
        self.assertTrue(text.startswith("---"))
        head = text.split("---", 2)[1]
        self.assertIn("name: mcp-switch", head)
        self.assertIn("description:", head)

    def test_documents_the_commands(self):
        text = self._text()
        for command in ("switch.py use", "switch.py add", "switch.py list",
                        "switch.py save", "switch.py rm"):
            self.assertIn(command, text)

    def test_documents_the_two_gotchas(self):
        text = self._text()
        self.assertIn("/mcp", text)                 # reconnect after switching
        self.assertIn("claude mcp login", text)     # auth recovery

    def test_marketplace_lists_the_skill(self):
        with open(MARKETPLACE) as f:
            data = json.load(f)
        entry = [p for p in data["plugins"] if p["name"] == "mcp-switch"]
        self.assertEqual(len(entry), 1)
        self.assertIn("./skills/mcp-switch", entry[0]["skills"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/mcp-switch/tests/test_skill_md.py`
Expected: FAIL — `FileNotFoundError: … SKILL.md`

- [ ] **Step 3: Write the docs and wiring**

Create `skills/mcp-switch/SKILL.md`:

````markdown
---
name: mcp-switch
description: Switch an MCP provider between named account profiles — a work Linear workspace and a personal one, two Notion accounts, two Sentry orgs — with one command, scoped to the current project. Profiles are stored per repository and activated per working directory, so two worktrees can sit on different accounts at once. Use when the user wants to change which account or workspace an MCP server points at, register a second account for a provider, or see which profile is active here.
---

# mcp-switch

Named profiles per MCP provider, stored per repository, activated per working
directory. Run everything from the project directory:

```
python3 <skill-dir>/switch.py <command>
```

## Commands

```
switch.py list [provider]                       profiles, active marker, live status
switch.py use <provider> <profile>              activate a profile here
switch.py add <provider> <profile> --url <url> [-H "Name: value"] [--transport http|sse] [--server <name>]
switch.py add <provider> <profile> --json '<server json>'
switch.py save <provider> <profile> --from <server>    capture a configured server
switch.py rm <provider> <profile>               delete a profile from the store
```

## Where things live

```
~/.claude/mcp/<project>/
  state.json                   active profile per provider, keyed by working directory
  <provider>/<profile>.json    the server JSON, plus an optional "server" name
```

`<project>` is the main repository's directory name, so every worktree of a repo
shares one set of profiles while each activates its own.

## Two things to tell the user every time

1. **A switch needs a reconnect.** MCP servers load at session start. After
   `use`, the user runs `/mcp` (or restarts the session) for it to take effect.
2. **Auth may need one browser round-trip.** Each profile owns its own server
   name, so credentials normally survive a switch. When they do not, `use`
   prints the exact command: `claude mcp login <server>`.

## Setting up a provider with two accounts

```
switch.py add linear work --url https://mcp.linear.app/mcp
switch.py add linear personal --url https://mcp.linear.app/mcp
switch.py use linear work
claude mcp login linear-work        # once, in an interactive terminal
```

Then switching later is one command plus `/mcp`.

## Limits worth stating up front

- **claude.ai connectors cannot be switched.** A connector's account is set in
  claude.ai settings, not on disk. If one is live on the same host as the active
  profile, `use` warns that both sets of tools are visible.
- The skill never touches stored credentials — no `logout`, no keychain access.
- Everything is written to **local scope** (`-s local`), never user or project scope.

## Tests

```
./run_tests.sh
```
````

Create `skills/mcp-switch/README.md`:

```markdown
# mcp-switch

One provider, several accounts. `mcp-switch` keeps named profiles for an MCP
provider — a work Linear workspace and a personal one, two Notion accounts — and
flips between them with one command, per project.

```
switch.py add linear work --url https://mcp.linear.app/mcp
switch.py add linear personal --url https://mcp.linear.app/mcp
switch.py use linear personal
```

Profiles live in `~/.claude/mcp/<project>/`, keyed on the main repository's
directory name, so every worktree of a repo shares them. Activation is per
working directory: two worktrees can sit on different workspaces at the same
time.

Each profile owns its own registered server name (`linear-work`,
`linear-personal`), which is what lets both stay authenticated — Claude Code
keys OAuth credentials per server name. A switch removes the previously active
server from local scope, adds the chosen one, then verifies it, printing
`claude mcp login <server>` if authentication is missing.

Two things it will not do: switch a claude.ai account connector (their account
is set in claude.ai settings, not on disk — the skill warns when one shadows
your profile), and touch stored credentials.

After switching, run `/mcp` or restart the session — MCP servers load at session
start.

See [`SKILL.md`](./SKILL.md) for the full command surface.
```

Modify `.claude-plugin/marketplace.json` — add a second entry to `plugins`:

```json
    {
      "name": "mcp-switch",
      "description": "Switch an MCP provider between named account profiles — work and personal Linear workspaces, two Notion accounts — with one command, per project.",
      "source": "./",
      "strict": false,
      "skills": [
        "./skills/mcp-switch"
      ]
    }
```

Modify the root `README.md` — add to the Skills list, under the `doc-server` bullet:

```markdown
- [`mcp-switch`](./skills/mcp-switch) — switch an MCP provider between named account profiles (work vs personal Linear workspaces) with one command, per project.
```

- [ ] **Step 4: Run the whole suite to verify it passes**

Run: `./skills/mcp-switch/run_tests.sh && python3 -c "import json; json.load(open('.claude-plugin/marketplace.json'))"`
Expected: every test file `ok:`, exit code 0, and the marketplace JSON parses

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/SKILL.md skills/mcp-switch/README.md skills/mcp-switch/tests/test_skill_md.py .claude-plugin/marketplace.json README.md
git commit -m "mcp-switch: skill docs and marketplace entry"
```

---

## Task 8: End-to-end smoke test against the real CLI

**Files:**
- Test: `skills/mcp-switch/tests/test_smoke.py`

**Interfaces:**
- Consumes: everything above
- Produces: nothing

This is the one test that runs the real `claude mcp` binary. It works entirely
inside a temporary directory, so it only ever writes local-scope config for a
path that is deleted afterwards. It **skips** when `claude` is not on `PATH`.

- [ ] **Step 1: Write the test**

Create `skills/mcp-switch/tests/test_smoke.py`:

```python
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

SWITCH = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "switch.py"))
URL = "https://example.invalid/mcp"


@unittest.skipIf(shutil.which("claude") is None, "claude CLI not on PATH")
class TestSmoke(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._cwd = tempfile.TemporaryDirectory()
        self.env = dict(os.environ, MCP_SWITCH_HOME=self._home.name)

    def tearDown(self):
        # Leave no local-scope server behind for the temp cwd.
        subprocess.run(["claude", "mcp", "remove", "smoke-one", "-s", "local"],
                       cwd=self._cwd.name, capture_output=True, text=True)
        subprocess.run(["claude", "mcp", "remove", "smoke-two", "-s", "local"],
                       cwd=self._cwd.name, capture_output=True, text=True)
        self._home.cleanup()
        self._cwd.cleanup()

    def _switch(self, *args):
        return subprocess.run([sys.executable, SWITCH, *args], cwd=self._cwd.name,
                              env=self.env, capture_output=True, text=True, timeout=180)

    def test_add_use_switch_and_list(self):
        self.assertEqual(self._switch("add", "smoke", "one", "--url", URL,
                                      "--server", "smoke-one").returncode, 0)
        self.assertEqual(self._switch("add", "smoke", "two", "--url", URL,
                                      "--server", "smoke-two").returncode, 0)

        first = self._switch("use", "smoke", "one")
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("smoke-one", first.stdout)

        second = self._switch("use", "smoke", "two")
        self.assertEqual(second.returncode, 0, second.stdout + second.stderr)
        self.assertIn("removed smoke-one", second.stdout)

        listing = self._switch("list", "smoke")
        self.assertIn("* two", listing.stdout)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run it**

Run: `python3 skills/mcp-switch/tests/test_smoke.py`
Expected: PASS — `OK` (or `OK (skipped=1)` where the `claude` CLI is absent)

The servers point at `example.invalid`, so `claude mcp get` reports
`✘ Failed to connect`. That is expected: the test asserts the switch mechanics,
not connectivity.

- [ ] **Step 3: Confirm nothing leaked into the real config**

Run: `claude mcp list | grep -c smoke-`
Expected: `0`

- [ ] **Step 4: Run the full suite**

Run: `./skills/mcp-switch/run_tests.sh`
Expected: every file `ok:`, exit code 0

- [ ] **Step 5: Commit**

```bash
git add skills/mcp-switch/tests/test_smoke.py
git commit -m "mcp-switch: end-to-end smoke test against the real CLI"
```

---

## Manual verification (after Task 8)

Not automatable — it needs a browser and your real Linear accounts.

- [ ] From this repo: `python3 skills/mcp-switch/switch.py add linear work --url https://mcp.linear.app/mcp`
- [ ] `python3 skills/mcp-switch/switch.py add linear personal --url https://mcp.linear.app/mcp`
- [ ] `python3 skills/mcp-switch/switch.py use linear work`
- [ ] In an interactive terminal: `claude mcp login linear-work`, authorize the work workspace
- [ ] `python3 skills/mcp-switch/switch.py use linear personal`, then `claude mcp login linear-personal`, authorize the personal workspace
- [ ] `python3 skills/mcp-switch/switch.py use linear work` — confirm it reports connected **without** asking for a login. This is the assumption the design flagged: that removing a server does not clear its credentials. If it does ask, the skill still works, it just costs a browser round-trip per switch — note the result in the spec.
- [ ] Run `/mcp` and confirm the Linear tools answer from the expected workspace.
