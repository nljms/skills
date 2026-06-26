import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    project: str
    branch: str         # git branch name (may contain "/"), or "main" for non-git
    source_root: str    # absolute path whose docs glob is scanned
    is_git: bool

    @property
    def key(self) -> str:
        return f"{self.project}/{self.branch}"


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def _branch_name(cwd: str) -> str:
    name = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if name and name != "HEAD":
        return name
    # Detached HEAD: fall back to a stable short-sha label (kept slash-free).
    sha = _git(["rev-parse", "--short", "HEAD"], cwd)
    return f"detached-{sha}" if sha else "main"


def resolve_identity(cwd: str) -> Identity:
    # realpath (not abspath) so macOS symlinked paths (/var -> /private/var) match git's output
    cwd = os.path.realpath(cwd)
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return Identity(os.path.basename(cwd.rstrip(os.sep)), "main", cwd, False)

    toplevel = os.path.realpath(toplevel)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    common = os.path.realpath(os.path.join(cwd, common)) if common else os.path.realpath(os.path.join(toplevel, ".git"))
    main_root = os.path.dirname(common)
    project = os.path.basename(main_root.rstrip(os.sep))

    # Group every checkout — the main worktree and each linked worktree — by its
    # git branch, so docs land at a stable, readable <project>/<branch>/ path.
    branch = _branch_name(cwd)

    return Identity(project, branch, toplevel, True)
