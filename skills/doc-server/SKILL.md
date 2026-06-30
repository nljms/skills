---
name: doc-server
description: Serve the plans, specs, and design docs the agent writes as browsable HTML on a dedicated local port so a human can review them visually and fast. Unifies docs from all projects under one folder, grouped per project and per git branch, with a sidebar navigator, auto-generated structure diagrams, and per-document tables of contents. Use when the user wants to preview, view, open, or serve project docs/plans/specs in a browser, or when a project has a docs/ directory worth surfacing.
---

# doc-server

Serve a project's markdown docs (plans, specs, design notes) as rendered HTML on a
single shared `localhost` port. All projects live under one global folder,
`~/.claude/doc-server/`, grouped by project and by **git branch** — every checkout,
whether the main worktree or a linked worktree, lands at one stable, readable path:

```
http://localhost:8910/<project>/<branch>/
```

For example `myrepo` on branch `main` is at `/myrepo/main/`, and a worktree checked
out on `feat/login` is at `/myrepo/feat/login/`. Branches replace the older
`main` / `worktrees/<name>` split so the URL always matches the branch you are on.

## What the viewer looks like

- A **sidebar navigator** lists every project; expand one to see its branches and
  jump to any of them or any document.
- Each **landing page** is auto-generated:
  - The **root** explains how the server works end-to-end and shows a Mermaid map
    of every project → branch.
  - A **branch page** leads with an optional **"what this worktree is doing"**
    panel (from an agent-written `docs/worktree-summary.md`, or any doc with
    frontmatter `worktree_summary: true`), then an auto **overview / architecture /
    external-services** block scanned from the project's code, then a Mermaid
    diagram of the branch's document structure and a per-document summary card with
    a **table of contents** linking straight to each heading.
- **Document pages** render the markdown (GitHub styling), add heading anchors so
  the tables of contents resolve, and turn ```mermaid fenced blocks into diagrams.
- All internal links are absolute (`/<project>/<branch>/…`), so navigation never
  breaks regardless of how deep a branch name nests.

## Serve the current project's docs

Run from the project directory:

```
python3 <skill-dir>/serve.py --docs "docs/**/*.md"
```

- Resolves the git project + branch, registers it, ensures the shared server is
  running (reusing it if already up), syncs the docs, and prints the URL.
- `--port N` forces a port; otherwise the port comes from `$DOC_SERVER_PORT`, then
  the remembered port in `~/.claude/doc-server/state.json`, then the default `8910`.
  If the chosen port is taken by another process, the next free port is used and
  remembered.
- `--open` also opens the URL in the default browser.
- `--context <path>` designates the worktree's **lead context document** (path
  relative to the repo root). On a worktree, the branch page leads with this doc
  and shows only the docs this worktree added relative to its source branch;
  everything else is demoted into a collapsed "Other documents" section. If you
  do not pass `--context`, a doc with frontmatter `worktree_context: true` (or the
  legacy `worktree-summary.md` / `worktree_summary: true`) is used instead.

  The context doc should follow: context summary → solution → before/after flow
  (a Mermaid flowchart) → plans related to the context. Update it as the work
  evolves; the server re-syncs on refresh.

- `--summary-path` prints the external worktree-summary path for the current
  project/branch — `~/.claude/doc-server/_context/<project>/<branch>/worktree-summary.md`
  — creating its directory if needed, then exits. Write the worktree's context
  doc THERE (not in the repo), following: context summary → solution →
  before/after Mermaid flow → plans. The server renders it as the lead CONTEXT
  panel. Keeping it outside the repo keeps the project branch clean.

The server re-syncs on every page load, so edits to the docs show up on refresh.

## Migrating an existing doc-server home

If you generated docs under the older `main` / `worktrees/<name>` layout, re-key and
regenerate them in one step:

```
python3 <skill-dir>/serve.py --migrate
```

This re-resolves every registered project to its `<project>/<branch>` path, drops
entries whose source is gone, removes the stale generated directories, and rebuilds
the HTML. The generated HTML is a disposable cache, so the operation is safe and
idempotent. See [`docs/superpowers/plans/2026-06-25-doc-server-routing-ui.md`](../../docs/superpowers/plans/2026-06-25-doc-server-routing-ui.md)
for the full migration plan.

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

When no `docs/` markdown is found the hook does nothing. On a feature branch or a
linked worktree that has no summary doc yet, the hook also nudges the agent to
write `docs/worktree-summary.md` — a short narrative of what the worktree is
working on (feature / bugfix / debug / research) with an end-to-end Mermaid diagram
of the problem and context, which the branch page then promotes to its lead panel.

## Updating the skill

The shared server runs as a long-lived daemon, so a plain edit to the skill code
would otherwise keep serving the old version from memory. To avoid that, every
`serve.py` / SessionStart run fingerprints the skill's runtime source
(`docserver/*.py` + `serve.py`) and the daemon advertises that fingerprint on its
health endpoint. When the fingerprint changes, the next run automatically:

1. stops the running daemon (recorded PID, then the port frees),
2. clears the generated HTML cache (the per-`<project>/<branch>` directories and
   `.inspect.json`), keeping the registry, remembered port, and downloaded assets,
3. starts a fresh daemon on the same port running the updated code.

No manual restart is needed — just edit the skill and open a new session (or rerun
`serve.py`). The cache is disposable and rebuilt on the first page load.

## Notes

- **Code scan.** The overview / architecture / external-services block is detected
  heuristically from dependency manifests (`package.json`, `pyproject.toml`,
  `requirements.txt`, `go.mod`, `Cargo.toml`, `Gemfile`), `docker-compose.yml`, and
  `.env*`. Results are cached per-branch (`.inspect.json`) and only recomputed when
  those signal files change, so the live re-sync stays fast.

- Python 3 standard library only — no installs required.
- Markdown and Mermaid are rendered client-side by assets cached once in
  `~/.claude/doc-server/_assets/` (`marked`, `github-markdown-css`, `mermaid`), with
  a CDN fallback if the one-time download fails.
