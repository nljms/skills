# doc-server — routing fix, branch naming & UI refresh

**Date:** 2026-06-25
**Status:** Implemented

This plan covers four changes to the `doc-server` skill and, crucially, **how to
migrate any docs already generated under the previous scheme**.

## What changed

### 1. Routing fix

Document pages previously linked "back" with a relative `../index.html`. That
resolved to the wrong page for the main checkout and produced a 404 inside
worktree folders (which sat one level deeper). All internal links are now
**absolute paths from the server root** (`/<project>/<branch>/index.html`,
`/<project>/index.html`, `/_assets/…`), which resolves correctly at every depth —
including branch names that contain slashes.

### 2. Branch-based naming: `<project>/<branch>/**`

Identity resolution now groups every checkout by its **git branch** instead of the
`main` vs `worktrees/<name>` split:

| Before                              | After                          |
| ----------------------------------- | ------------------------------ |
| `<project>/main/`                   | `<project>/<branch>/` (e.g. `main`) |
| `<project>/worktrees/<dir-name>/`   | `<project>/<branch>/` (e.g. `feat/login`) |

- The branch is `git rev-parse --abbrev-ref HEAD`; a detached HEAD falls back to a
  slash-free `detached-<short-sha>`; a non-git directory falls back to `main`.
- Registry keys are `"<project>/<branch>"`; the project is the first path segment,
  the branch is everything after it (so slashes in branch names are preserved).

### 3. Modern UI

A shared HTML shell with a sticky **sidebar navigator** (projects → branches),
light/dark aware styling, Mermaid structure diagrams, and per-document
table-of-contents summary cards. See `SKILL.md` for the full description.

### 4. Auto-generated analysis & summaries

- **Root** page: an end-to-end Mermaid pipeline diagram plus a project → branch map.
- **Branch** page: a Mermaid diagram of the document tree, and — because the source
  markdown has no served HTML index of its own — a summary card per document whose
  table of contents links straight to each heading anchor.

## Migration

The generated HTML under `~/.claude/doc-server/` is a **disposable cache**: it is
always reproducible from `registry.json` + the live source docs. Two things,
however, do not self-heal and must be migrated:

1. **Registry keys** still point at the old scheme
   (`<project>/worktrees/<name>`), so a re-sync would keep emitting old paths.
2. **Stale generated directories** from the old layout (e.g. `repo/worktrees/…`,
   or a `repo/main/` whose branch is actually `master`) linger and never get
   overwritten.

### Automated path (recommended)

```
python3 skills/doc-server/serve.py --migrate
```

`docserver/migrate.py::migrate_home` performs, in order:

1. **Re-key the registry** — for each entry, re-resolve identity from its recorded
   `source_root`, producing the new `<project>/<branch>` key. Entries whose source
   directory no longer exists on disk are **dropped**.
2. **Purge generated directories** — remove every child of the home except
   `_assets/` and the JSON state files. (The cache is fully regenerable.)
3. **Regenerate** — `ensure_assets` + `sync_all` rebuild the new-layout HTML.

It prints a summary of every remap and drop, and is **idempotent** — running it on
an already-migrated home simply regenerates the HTML.

```
doc-server migrated: /home/you/.claude/doc-server
  remapped  repo/worktrees/legacy  ->  repo/main
  dropped   oldproj/main  (source no longer on disk)
```

### What is preserved

- `state.json` (the remembered port) is untouched, so the server URL stays stable.
- `_assets/` (vendored `marked`, `github-markdown-css`, `mermaid`) is reused; no
  re-download needed.

### Manual fallback

If you prefer not to run the migrator, deleting the cache is equally safe — the
next `serve.py` run regenerates everything for the current checkout:

```
rm -rf ~/.claude/doc-server/<project>     # drop one project's stale output
# or, to reset everything but keep the port + assets:
find ~/.claude/doc-server -mindepth 1 -maxdepth 1 \
  -not -name _assets -not -name '*.json' -exec rm -rf {} +
```

Then re-run `serve.py` from each project you want served (or just reopen a session
if the SessionStart hook is installed).

### Rollback

Nothing in migration is destructive to **source** docs — only the regenerable cache
is touched. To roll back, check out the previous version of the skill and run
`serve.py` again; it will rebuild the old-layout cache from the same sources.

## Tests

- `tests/test_identity.py` — branch-based keys, including a worktree whose branch
  name differs from its directory and contains a slash.
- `tests/test_render.py` — slugify/TOC extraction, absolute back link + sidebar on
  doc pages, Mermaid + per-doc TOC on branch indexes, root overview diagram.
- `tests/test_migrate.py` — old `worktrees/*` key re-keyed to its branch, stale
  directory removed, and entries with missing sources dropped.
- The existing `test_sync.py`, `test_handler.py`, `test_app.py`, etc. continue to
  pass against the new layout.
