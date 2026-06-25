#!/usr/bin/env python3
"""SessionStart hook: if the project has docs, bring up the doc server."""
import json
import os
import sys

_SKILL_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _has_markdown(docs_dir: str) -> bool:
    if not os.path.isdir(docs_dir):
        return False
    for _root, _dirs, files in os.walk(docs_dir):
        if any(f.endswith(".md") for f in files):
            return True
    return False


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
        print(json.dumps({
            "hookSpecificOutput": {
                "hookEventName": "SessionStart",
                "additionalContext": f"Project docs are being served at {result['url']}",
            }
        }))


if __name__ == "__main__":
    main()
