# doc-server skill — design

**Date:** 2026-06-25
**Status:** Approved design, pending implementation plan

## Purpose

Serve the plans, specs, and design docs the agent writes over `localhost` on a
dedicated port, rendered as HTML, so a human reviewer can read them visually and
fast instead of scrolling raw markdown in a terminal. All docs across a project
(and any of its git worktrees) are unified under one global folder, with each
worktree's docs grouped into its own subfolder so they never mix with the main
checkout's.

## Goals

- One command spins up (or reuses) a local HTTP server that renders the project's
  markdown docs as browsable HTML.
- Docs always reflect the latest on-disk content (the agent keeps editing while a
  human reads).
- A single global folder unifies all projects; worktrees are grouped separately
  within their project.
- Zero external runtime dependencies — Python 3 stdlib only; markdown rendered
  client-side by vendored assets.

## Non-goals

- No file-watcher / browser live-reload push (freshness is achieved by
  re-syncing on each page request, not by pushing to the browser).
- No editing of docs through the server (read-only viewer).
- No authentication / remote exposure — localhost only.

## Architecture

A single self-contained Python 3 script, `serve.py` (stdlib only), with three
responsibilities:

1. **Resolve** — determine project identity and whether the current working dir
   is a linked git worktree.
2. **Sync** — scan the configured docs glob and wrap each `.md` file in a
   self-contained `.html` page plus generate `index.html` landing pages.
3. **Serve** — a custom `http.server` request handler bound to a dedicated port
   that **re-syncs on every page load**, so served HTML is always current.

Markdown is rendered **client-side**: each generated `.html` embeds the raw
markdown and loads a vendored `marked.min.js` + `github-markdown.css` from
`_assets/`. Those assets are downloaded once on first run (CDN fallback if the
download fails) and cached, so the viewer works offline afterward.

## Folder layout (served root)

Global root: `~/.claude/doc-server/`

```
~/.claude/doc-server/
├── _assets/                         # shared, downloaded once
│   ├── marked.min.js
│   └── github-markdown.css
├── registry.json                    # project/worktree -> source root + glob
├── index.html                       # top landing: lists every project
└── <project-name>/                  # basename of the MAIN worktree root
    ├── index.html                   # project landing: links main + each worktree
    ├── main/                        # docs from the primary checkout
    │   ├── index.html
    │   └── <doc>.html
    └── worktrees/
        └── <worktree-dir-name>/     # one subfolder per linked worktree
            ├── index.html
            └── <doc>.html
```

### Identity resolution (git)

- **Project name** = basename of the parent of `git rev-parse --git-common-dir`
  (the main worktree root). Stable across all worktrees of the same repo.
- **Current tree** = `git rev-parse --show-toplevel`.
  - If it equals the main worktree root → docs go under `main/`.
  - If it is a linked worktree → docs go under `worktrees/<basename-of-toplevel>/`.
- **Not a git repo** → fall back to `<cwd-basename>/main/`.

## Freshness model

Live re-sync on each load. The long-running server reads `registry.json` on every
request and regenerates the requested project/worktree's HTML from its recorded
source root + glob before serving. No manual re-run, no watcher process.

## Server & port behavior

- A **single global server** serves the entire `~/.claude/doc-server/` root, so
  one process covers all projects and worktrees.
- **Port resolution order** on launch:
  1. Explicit `--port` flag, else `$DOC_SERVER_PORT`, else the **remembered
     port** from state (see below), else the default **`8910`**.
  2. Check whether that port is free.
     - If it is free → bind to it and **persist it** as the remembered port.
     - If it is occupied by **our own already-running doc-server** → reuse it
       (singleton) and print the URL; do not start a second process.
     - If it is occupied by **some other process** → scan upward for the next
       free port (e.g. `8910 → 8911 → …`, bounded range), bind to the first
       free one, and **persist that** as the new remembered port.
- **Remembered port (persisted in memory):** the chosen port is stored in a
  small state file, `~/.claude/doc-server/state.json` (e.g.
  `{ "port": 8912 }`) — the **single source of truth**. Subsequent runs read it
  first so the server stays at a stable URL across invocations until the port
  becomes unavailable. An explicit `--port` overrides and updates the remembered
  value. The script deliberately does **not** write to `~/.zshrc` or any shell
  config: `state.json` can be rewritten instantly when an auto-scan picks a new
  port, whereas a shell export only affects newly opened shells and would drift.
  `$DOC_SERVER_PORT` remains a purely optional manual override read at launch.
- **Distinguishing our server from a stranger:** the running doc-server exposes a
  health endpoint (e.g. `GET /__doc_server_health__` returning a known JSON
  marker). A probe that returns the marker means "reuse"; a refused connection
  means "free"; any other response means "occupied by a stranger → try next
  port."
- **Registry:** `registry.json` maps each project/worktree key to its source root
  and glob. Registering a project adds/updates its entry; the server uses it to
  re-sync on demand.
- The script prints a clickable URL to the current project/worktree landing page,
  e.g. `http://localhost:8910/myrepo/main/`.

## Invocation interface

One script. The SKILL.md instructs the agent to run:

```
python3 <skill>/serve.py [--docs "docs/**/*.md"] [--port 8910] [--open]
```

Behavior:
1. Resolve git identity (project + main/worktree).
2. Register/update the project/worktree entry in `registry.json`.
3. Ensure the global server is running (start in background if not).
4. Perform an initial sync.
5. Print the landing-page URL; `--open` also opens the default browser.

- Default glob: `docs/**/*.md` (configurable per run).

## Auto-invocation (SessionStart hook)

The skill ships a hook so the doc server starts automatically whenever you open a
session in a project that has docs, without the agent having to remember to invoke
it.

- **Mechanism:** a `SessionStart` hook entry in `~/.claude/settings.json` runs a
  small script, `hooks/session_start.py`, shipped with the skill.
- **Detection:** the hook checks whether the project's dedicated docs directory
  (the `docs/` dir, the same root the default glob targets) exists and contains at
  least one `.md` file. The check resolves relative to the session's working
  directory / git toplevel.
- **Action when docs are found:** the hook invokes the same logic as
  `serve.py` (resolve identity → register → ensure server running → sync) and
  surfaces the project's landing-page URL as session context, so the URL is
  available immediately. When no docs are found it exits silently and does
  nothing.
- **Idempotent:** because the server is a singleton keyed on the remembered port,
  repeated SessionStart firings reuse the already-running server.
- **Setup:** installing the skill includes a one-time step that adds the
  `SessionStart` hook to `~/.claude/settings.json`. The hook entry and the manual
  `serve.py` invocation share the same underlying code path, so behavior is
  identical whether triggered automatically or by hand.

## Repo layout (this repo, matching `anthropics/skills` template)

```
skills/                       (repo root)
├── .claude-plugin/
│   └── marketplace.json      # registers the plugin + skills
├── README.md                 # marketplace add / install instructions
├── template/
│   └── SKILL.md              # canonical blank skill template
└── skills/
    └── doc-server/
        ├── SKILL.md
        ├── serve.py             # CLI entry: resolve, register, ensure server, sync
        ├── docserver/           # shared core imported by serve.py and the hook
        │   ├── __init__.py
        │   ├── identity.py      # git project/worktree resolution
        │   ├── sync.py          # md -> html generation + landing pages
        │   ├── server.py        # http.server handler + singleton/port logic
        │   └── state.py         # state.json + registry.json read/write
        └── hooks/
            └── session_start.py # SessionStart hook: detect docs, reuse core
```

This makes the repo installable as a Claude Code plugin marketplace
(`/plugin marketplace add <repo>`), the same way the Anthropic repo works. The
`serve.py` CLI and `hooks/session_start.py` both call into the shared `docserver`
package so manual and automatic invocation are identical.

## Testing strategy

- **Identity resolution:** unit-test the git-resolution logic against a temp repo
  with and without a linked worktree, and a non-git dir.
- **Sync:** given a temp source tree of `.md` files, assert the expected `.html`
  and `index.html` files are produced under the right `main/` vs
  `worktrees/<name>/` grouping.
- **Server:** start the server on an ephemeral port, request a doc URL, assert the
  response contains the rendered wrapper and that editing the source `.md` then
  re-requesting reflects the change (live re-sync).
- **Singleton:** a second launch detects our running server (via the health
  marker) and reuses it rather than crashing or starting a duplicate.
- **Port resolution:** with the default/remembered port occupied by a stranger,
  the script picks the next free port and writes it to `state.json`; a following
  run reads `state.json` and reuses that port.
- **SessionStart hook:** in a temp project containing `docs/*.md` the hook starts
  the server and emits the URL; in a project with no docs dir / no `.md` files it
  exits silently and starts nothing.

## Error handling

- Port already in use by a non-doc-server process → automatically scan upward for
  the next free port and remember it (see Server & port behavior). Only fail if no
  free port is found within the bounded range, with a clear message suggesting
  `--port`.
- Asset download failure → fall back to CDN URLs in the generated HTML and warn.
- Glob matches nothing → still start the server and render an empty landing page
  noting no docs were found.
- Non-git directory → fall back to cwd-basename project naming (documented above).
