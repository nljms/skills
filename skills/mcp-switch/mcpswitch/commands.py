"""The commands the CLI exposes, composed from the store and the claude seam.

`cwd` is where `claude mcp` runs; `project` is the main repository root that
both the CLI and the store key activation on. Every command returns a Result;
printing is the CLI's job.
"""
import json
from dataclasses import dataclass, field

from . import cli, store

RECONNECT_HINT = "run /mcp (or restart the session) for this to take effect"


@dataclass
class Result:
    ok: bool
    lines: list = field(default_factory=list)


def _profile_server(root, provider, profile):
    """The profile's registered server name, defaulting when it cannot be read."""
    try:
        config = store.read_profile(root, provider, profile)
    except store.StoreError:
        config = {}
    return store.server_name(provider, profile, config)


def _deactivate(root, project, cwd, provider, previous, claude, lines):
    """Remove the previously active server, tolerating one that is already gone."""
    # The name recorded at activation time, so a profile deleted from the store
    # since then is still unregistered under the name it really used.
    name = store.get_active_server(root, project, provider) \
        or _profile_server(root, provider, previous)
    try:
        claude.remove(name, cwd)
        lines.append(f"removed {name}")
    except cli.ClaudeError as exc:
        if "No MCP server named" in str(exc):
            lines.append(f"{name} was already gone")
        else:
            lines.append(f"could not remove {name}: {exc}")


def use(root, cwd, project, provider, profile, claude) -> Result:
    try:
        config = store.read_profile(root, provider, profile)
    except store.StoreError as exc:
        known = store.profiles(root, provider)
        hint = f"known profiles: {', '.join(known)}" if known else \
            f"no profiles for {provider} yet — add one with: switch.py add {provider} <profile> --url <url>"
        return Result(False, [str(exc), hint])

    name = store.server_name(provider, profile, config)
    lines = []

    previous = store.get_active(root, project, provider)
    if previous and previous != profile:
        _deactivate(root, project, cwd, provider, previous, claude, lines)

    # `claude mcp add-json` refuses a name that already exists, so clear it
    # first. It is usually not registered, and that failure is expected.
    try:
        claude.remove(name, cwd)
    except cli.ClaudeError:
        pass

    try:
        claude.add_json(name, store.server_config(config), cwd)
    except cli.ClaudeError as exc:
        lines.append(f"could not register {name}: {exc}")
        return Result(False, lines)

    store.set_active(root, project, provider, profile, name)
    lines.append(f"{provider} -> {profile} ({name})")

    state = cli.auth_state(claude.get(name, cwd))
    if state == cli.NEEDS_AUTH:
        lines.append(f"needs auth: claude mcp login {name}")
    elif state == cli.FAILED:
        lines.append(f"registered but not connected — check: claude mcp get {name}")
    elif state == cli.MISSING:
        lines.append("registered but not visible — check: claude mcp list")

    host = cli.host_of(config.get("url"))
    for other in cli.duplicate_hosts(claude.list(cwd), host, exclude=name):
        remedy = "disconnect it in claude.ai settings if you want only one" \
            if other.startswith("claude.ai ") else \
            f"drop it with: claude mcp remove {other} -s local"
        lines.append(
            f"warning: {other} also serves {host} — both sets of tools are live; "
            + remedy
        )

    lines.append(RECONNECT_HINT)
    return Result(True, lines)


def show(root, cwd, project, claude, provider=None) -> Result:
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
        active = store.get_active(root, project, name)
        lines.append(f"{name}:")
        for prof in store.profiles(root, name):
            mark = "*" if prof == active else " "
            try:
                config = store.read_profile(root, name, prof)
            except store.StoreError:
                lines.append(f"  {mark} {prof} — unreadable profile file")
                continue
            server = store.server_name(name, prof, config)
            status = live.get(server, "not registered here")
            target = config.get("url", config.get("command", ""))
            lines.append(f"  {mark} {prof:<12} {server:<24} {status:<20} {target}")
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


def rm(root, project, provider, profile) -> Result:
    if store.get_active(root, project, provider) == profile:
        return Result(False, [
            f"{provider}/{profile} is active in this project",
            "switch to another profile first, or unregister it with: "
            f"claude mcp remove {_profile_server(root, provider, profile)} -s local",
        ])
    if not store.delete_profile(root, provider, profile):
        return Result(False, [f'no profile "{profile}" for provider "{provider}"'])
    return Result(True, [f"deleted {provider}/{profile}",
                         "stored credentials are untouched"])
