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
