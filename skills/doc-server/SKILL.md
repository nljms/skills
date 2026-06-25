---
name: doc-server
description: Serve the plans, specs, and design docs the agent writes as browsable HTML on a dedicated local port so a human can review them visually and fast. Unifies docs from all projects under one folder, grouped per project and per git worktree. Use when the user wants to preview, view, open, or serve project docs/plans/specs in a browser, or when a project has a docs/ directory worth surfacing.
---

# doc-server

Serve a project's markdown docs (plans, specs, design notes) as rendered HTML on a
single shared `localhost` port. All projects live under one global folder,
`~/.claude/doc-server/`, grouped by project and git worktree:

```
http://localhost:8910/<project>/main/
http://localhost:8910/<project>/worktrees/<name>/
```

## Serve the current project's docs

Run from the project directory:

```
python3 <skill-dir>/serve.py --docs "docs/**/*.md"
```

- Resolves the git project + worktree, registers it, ensures the shared server is
  running (reusing it if already up), syncs the docs, and prints the URL.
- `--port N` forces a port; otherwise the port comes from `$DOC_SERVER_PORT`, then
  the remembered port in `~/.claude/doc-server/state.json`, then the default `8910`.
  If the chosen port is taken by another process, the next free port is used and
  remembered.
- `--open` also opens the URL in the default browser.

The server re-syncs on every page load, so edits to the docs show up on refresh.

## Auto-invoke on session start (optional, recommended)

Register the SessionStart hook so the server comes up automatically whenever you
open a session in a project that has a `docs/` directory with markdown. Add this to
`~/.claude/settings.json` (use the absolute path to this skill):

```json
{
  "hooks": {
    "SessionStart": [
      {
        "hooks": [
          {
            "type": "command",
            "command": "python3 /ABSOLUTE/PATH/TO/skills/doc-server/hooks/session_start.py"
          }
        ]
      }
    ]
  }
}
```

When no `docs/` markdown is found the hook does nothing.

## Notes

- Python 3 standard library only — no installs required.
- Markdown is rendered client-side by assets cached once in
  `~/.claude/doc-server/_assets/` (CDN fallback if the download fails).
