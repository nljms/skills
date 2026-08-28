"""Resolve the project a working directory belongs to, and where its profiles live.

Everything is keyed on the *main* repository, resolved through
`git rev-parse --git-common-dir`, so a subdirectory and a linked worktree both
resolve to the same project as the repo root. That matches how Claude Code keys
local-scope MCP config, which is also on the main repository root. A non-git
directory is its own project.
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


def project_root(cwd: str) -> str:
    """The main repository's directory, or the directory itself outside a repo."""
    # realpath so macOS symlinks (/var -> /private/var) match git's own output
    cwd = os.path.realpath(cwd)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if not common:
        return cwd
    common = os.path.realpath(os.path.join(cwd, common))
    return os.path.dirname(common.rstrip(os.sep))


def project_key(cwd: str) -> str:
    return os.path.basename(project_root(cwd).rstrip(os.sep))


def project_store(cwd: str) -> Path:
    root = store_home() / project_key(cwd)
    root.mkdir(parents=True, exist_ok=True)
    return root
