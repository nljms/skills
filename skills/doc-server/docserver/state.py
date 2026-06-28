import json
import os
from pathlib import Path


def doc_server_home() -> Path:
    base = os.environ.get("DOC_SERVER_HOME")
    home = Path(base) if base else Path.home() / ".claude" / "doc-server"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _state_file() -> Path:
    return doc_server_home() / "state.json"


def _registry_file() -> Path:
    return doc_server_home() / "registry.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_remembered_port():
    port = _read_json(_state_file(), {}).get("port")
    return int(port) if isinstance(port, int) else None


def set_remembered_port(port: int) -> None:
    data = _read_json(_state_file(), {})
    data["port"] = int(port)
    _write_json(_state_file(), data)


def get_code_version():
    return _read_json(_state_file(), {}).get("code_version")


def set_code_version(version: str) -> None:
    data = _read_json(_state_file(), {})
    data["code_version"] = version
    _write_json(_state_file(), data)


def get_daemon_pid():
    pid = _read_json(_state_file(), {}).get("daemon_pid")
    return int(pid) if isinstance(pid, int) else None


def set_daemon_pid(pid: int) -> None:
    data = _read_json(_state_file(), {})
    data["daemon_pid"] = int(pid)
    _write_json(_state_file(), data)


def read_registry() -> dict:
    return _read_json(_registry_file(), {})


def register_target(key: str, source_root: str, glob: str) -> None:
    reg = read_registry()
    reg[key] = {"source_root": source_root, "glob": glob}
    _write_json(_registry_file(), reg)
