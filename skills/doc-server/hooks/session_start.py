#!/usr/bin/env python3
"""SessionStart hook: if the project has docs, bring up the doc server.

When the checkout is a feature branch or a linked worktree that has no
``worktree-summary.md`` yet, it also nudges the agent to write one so the
branch page can lead with a 'what this worktree is doing' panel.
"""
import json
import os
import re
import subprocess
import sys

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _has_markdown(docs_dir: str) -> bool:
    if not os.path.isdir(docs_dir):
        return False
    for _root, _dirs, files in os.walk(docs_dir):
        if any(f.endswith(".md") for f in files):
            return True
    return False


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def _is_linked_worktree(cwd: str) -> bool:
    git_dir = _git(["rev-parse", "--git-dir"], cwd)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    if not git_dir or not common:
        return False
    return os.path.realpath(os.path.join(cwd, git_dir)) != os.path.realpath(os.path.join(cwd, common))


def _has_summary(docs_dir: str) -> bool:
    if not os.path.isdir(docs_dir):
        return False
    for root, _dirs, files in os.walk(docs_dir):
        for f in files:
            if f.lower() == "worktree-summary.md":
                return True
            if f.endswith(".md"):
                try:
                    with open(os.path.join(root, f), encoding="utf-8", errors="replace") as fh:
                        head = fh.read(500)
                    if re.search(r"^worktree_summary\s*:\s*(true|yes)", head, re.M | re.I):
                        return True
                except Exception:
                    pass
    return False


def summary_nudge(cwd: str, url=None):
    """Return a nudge string if this worktree should write a summary, else None."""
    branch = _git(["rev-parse", "--abbrev-ref", "HEAD"], cwd)
    if not branch:  # not a git repo
        return None
    if branch in ("main", "master", "HEAD") and not _is_linked_worktree(cwd):
        return None
    if _has_summary(os.path.join(cwd, "docs")):
        return None
    return (
        "Write this worktree's context summary OUTSIDE the repo: run "
        "`serve.py --summary-path` to get the path "
        "(~/.claude/doc-server/_context/<project>/<branch>/worktree-summary.md) "
        "and write it there (context summary → solution → before/after Mermaid "
        "flow → plans). The server renders it as the lead context."
    )


def run(cwd: str):
    docs_dir = os.path.join(cwd, "docs")
    if not _has_markdown(docs_dir):
        return None
    sys.path.insert(0, _SKILL_DIR)
    from docserver.app import bring_up
    return bring_up(cwd, "docs/**/*.md")


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        data = {}
    cwd = data.get("cwd") or os.getcwd()
    result = run(cwd)
    if result:
        context = f"Project docs are being served at {result['url']}"
        nudge = summary_nudge(cwd, result["url"])
        if nudge:
            context += "\n\n" + nudge
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": context,
            }
        }))


if __name__ == "__main__":
    main()
