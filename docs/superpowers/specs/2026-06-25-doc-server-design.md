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
- Default port **`8910`**; override via `--port` or `$DOC_SERVER_PORT`.
- **Singleton:** on launch the script probes the port. If our server is already
  running, it reuses it and prints the URL; otherwise it starts one in the
  background.
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
        └── serve.py
```

This makes the repo installable as a Claude Code plugin marketplace
(`/plugin marketplace add <repo>`), the same way the Anthropic repo works.

## Testing strategy

- **Identity resolution:** unit-test the git-resolution logic against a temp repo
  with and without a linked worktree, and a non-git dir.
- **Sync:** given a temp source tree of `.md` files, assert the expected `.html`
  and `index.html` files are produced under the right `main/` vs
  `worktrees/<name>/` grouping.
- **Server:** start the server on an ephemeral port, request a doc URL, assert the
  response contains the rendered wrapper and that editing the source `.md` then
  re-requesting reflects the change (live re-sync).
- **Singleton:** second launch on a busy port reuses rather than crashes.

## Error handling

- Port already in use by a non-doc-server process → fail with a clear message
  suggesting `--port`.
- Asset download failure → fall back to CDN URLs in the generated HTML and warn.
- Glob matches nothing → still start the server and render an empty landing page
  noting no docs were found.
- Non-git directory → fall back to cwd-basename project naming (documented above).
