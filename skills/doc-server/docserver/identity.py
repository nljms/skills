import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    project: str
    group: str          # "main" or "worktrees/<name>"
    source_root: str    # absolute path whose docs glob is scanned
    is_git: bool

    @property
    def key(self) -> str:
        return f"{self.project}/{self.group}"


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def resolve_identity(cwd: str) -> Identity:
    cwd = os.path.realpath(cwd)
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return Identity(os.path.basename(cwd.rstrip(os.sep)), "main", cwd, False)

    toplevel = os.path.realpath(toplevel)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    common = os.path.realpath(os.path.join(cwd, common)) if common else os.path.join(toplevel, ".git")
    main_root = os.path.dirname(common)
    project = os.path.basename(main_root.rstrip(os.sep))

    if toplevel == main_root:
        group = "main"
    else:
        group = f"worktrees/{os.path.basename(toplevel.rstrip(os.sep))}"

    return Identity(project, group, toplevel, True)
