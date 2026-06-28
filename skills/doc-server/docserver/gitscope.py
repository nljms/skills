"""Resolve a worktree's source branch and the docs it introduced.

A doc is "this worktree's" when it does not exist on the source branch. We
diff the worktree against a base commit-ish, taking newly-added committed files
plus untracked / staged-new files in the working tree. Everything here is
best-effort: any git failure degrades to "show all" (None) so the viewer never
breaks on a non-git or unusual checkout.
"""
import os
import subprocess


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def _default_branch(cwd):
    head = _git(["rev-parse", "--abbrev-ref", "origin/HEAD"], cwd)
    if head and "/" in head:
        return head  # e.g. "origin/main"
    for cand in ("main", "master"):
        if _git(["rev-parse", "--verify", "--quiet", cand], cwd) is not None:
            return cand
    return None


def source_branch_base(source_root):
    """A commit-ish to diff the worktree against, or None if none resolves."""
    head = _git(["rev-parse", "HEAD"], source_root)
    if head is None:
        return None
    upstream = _git(
        ["rev-parse", "--abbrev-ref", "--symbolic-full-name", "@{upstream}"],
        source_root,
    )
    candidates = []
    if upstream:
        candidates.append(_git(["merge-base", "HEAD", upstream], source_root))
    default = _default_branch(source_root)
    if default:
        candidates.append(_git(["merge-base", "--fork-point", default, "HEAD"], source_root))
        candidates.append(_git(["merge-base", default, "HEAD"], source_root))
    for base in candidates:
        if base:
            return base
    return None


def _is_doc(path):
    return path.startswith("docs/") and path.endswith(".md")


def worktree_added_docs(source_root):
    """POSIX rel-paths of docs added on this worktree, or None for "show all"."""
    base = source_branch_base(source_root)
    if base is None:
        return None

    # Check if we're on the default branch
    current = _git(["rev-parse", "--abbrev-ref", "HEAD"], source_root)
    default = _default_branch(source_root)
    head = _git(["rev-parse", "HEAD"], source_root)

    # If on the default branch and no divergence, show all
    if current == default and base == head:
        return None

    added = set()
    committed = _git(
        ["diff", "--name-only", "--diff-filter=A", f"{base}...HEAD"], source_root
    )
    if committed:
        added.update(p for p in committed.splitlines() if _is_doc(p))
    status = _git(["status", "--porcelain", "--untracked-files=all"], source_root)
    if status:
        for line in status.splitlines():
            code, _, path = line[:2], line[2], line[3:].strip()
            if code in ("??", "A ", "AM") and _is_doc(path):
                added.add(path)
    return added
