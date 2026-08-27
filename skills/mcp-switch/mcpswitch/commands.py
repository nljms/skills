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
    """The name a profile would register as. For display only — the "server"
    key is user-editable, so it is never evidence that we registered it."""
    try:
        config = store.read_profile(root, provider, profile)
    except store.StoreError:
        config = {}
    return store.server_name(provider, profile, config)


def _target(config) -> tuple:
    """What a server points at — enough to tell two definitions apart."""
    if config is None:
        return None
    return (config.get("url") or "", config.get("command") or "")


def _live_config(name, cwd, claude):
    """The registered server's definition, or None if it cannot be read."""
    try:
        return cli.parse_server(claude.get(name, cwd))
    except cli.ClaudeError:
        return None


def _refuse(name, why, lines) -> bool:
    lines.append(f"a server named {name} is already registered in this project "
                 f"and {why} — left untouched")
    lines.append("replace it yourself if that is what you meant: "
                 f"claude mcp remove {name} -s local")
    return False


def _deactivate(cwd, name, claude, lines):
    """Remove the previously active server, tolerating one that is already gone."""
    try:
        claude.remove(name, cwd)
        lines.append(f"removed {name}")
    except cli.ClaudeError as exc:
        if "No MCP server named" in str(exc):
            lines.append(f"{name} was already gone")
        else:
            lines.append(f"could not remove {name}: {exc}")


def _register(root, project, cwd, provider, profile, name, config, claude, lines) -> bool:
    """Register the profile's server, replacing only a registration of our own.

    `claude mcp add-json` refuses a name that already exists, and that refusal
    is the only way to learn something is there. What is there may be a server
    the user configured by hand, holding headers or env this store never
    captured, so the sole registration we will overwrite is the one state says
    we made for this same profile — which is what keeps re-activation working.

    Only a successful `use` writes state, so a recorded name is always one we
    registered ourselves — but the user may have removed it and put their own
    server there since, so what is live is compared against the profile too.
    """
    try:
        claude.add_json(name, store.server_config(config), cwd)
        return True
    except cli.ClaudeError as exc:
        if "already exists" not in str(exc):
            lines.append(f"could not register {name}: {exc}")
            return False

    ours = (store.get_active(root, project, provider) == profile
            and store.get_active_server(root, project, provider) == name)
    if not ours:
        return _refuse(name, "is not this profile's registration", lines)

    # The name is one we registered, but the user may have removed it and put
    # their own server there since — SKILL.md tells them how to. Compare what
    # is live against the profile before replacing it.
    if _target(_live_config(name, cwd, claude)) != _target(store.server_config(config)):
        return _refuse(name, "no longer holds this profile's definition", lines)

    try:
        claude.remove(name, cwd)
        claude.add_json(name, store.server_config(config), cwd)
    except cli.ClaudeError as exc:
        lines.append(f"could not re-register {name}: {exc}")
        return False
    return True


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
        # Only the name recorded at activation time, which by construction is
        # one this skill registered. A profile's own "server" key is a
        # user-editable string and proves nothing, so with nothing recorded we
        # leave a possible orphan rather than delete someone else's server.
        stale = store.get_active_server(root, project, provider)
        if not stale:
            lines.append(f"no registration recorded for {provider}/{previous}, so "
                         "nothing was removed — check: claude mcp list")
        elif stale != name:
            # When the outgoing registration *is* the name we are about to add,
            # leave it standing and let _register decide whether it is ours to
            # replace — removing it first would destroy it either way.
            _deactivate(cwd, stale, claude, lines)

    if not _register(root, project, cwd, provider, profile, name, config, claude, lines):
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

    name = server or from_server
    config["server"] = name
    path = store.write_profile(root, provider, profile, config)
    # Deliberately no activation: only a successful `use` writes state, so every
    # entry names a server this store registered, and deactivating one can never
    # reach a server the user configured by hand.
    lines = [f"saved {from_server} as {provider}/{profile}", f"wrote {path}"]

    lines.append(
        "note: claude mcp get does not print headers or env, so this copy has "
        "neither — if the server used any, add them with: "
        f'switch.py add {provider} {profile} --url <url> -H "Name: value", '
        f"or edit {path}")

    if name == from_server:
        # The profile registers under the name that is already registered, and
        # `use` will not replace a server it did not register itself.
        lines.append(
            f"{name} is registered already, so activating this profile means "
            f"replacing it — once the profile is complete: "
            f"claude mcp remove {name} -s local, then: "
            f"switch.py use {provider} {profile}")
    return Result(True, lines)


def rm(root, project, provider, profile) -> Result:
    if store.get_active(root, project, provider) == profile:
        # Unregistering the server would not help: the state slot would stay
        # set and rm would go on refusing. Switching away is the only way out.
        name = store.get_active_server(root, project, provider) \
            or _profile_server(root, provider, profile)
        return Result(False, [
            f"{provider}/{profile} is active in this project — it registered {name}",
            f"switch to another profile first: switch.py use {provider} <other>, "
            f"then: switch.py rm {provider} {profile}",
        ])
    if not store.delete_profile(root, provider, profile):
        return Result(False, [f'no profile "{profile}" for provider "{provider}"'])
    return Result(True, [f"deleted {provider}/{profile}",
                         "stored credentials are untouched"])
