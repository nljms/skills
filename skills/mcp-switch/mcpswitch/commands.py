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
