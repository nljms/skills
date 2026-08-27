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
