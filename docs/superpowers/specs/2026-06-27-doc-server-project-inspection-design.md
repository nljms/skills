# doc-server: project inspection + worktree summary

Branch landing pages gain two new things: an **auto code-scan** (overview /
architecture / external services) and an **agent-written worktree summary**
(prose + end-to-end Mermaid) surfaced as the lead panel. Pure stdlib, additive,
degrades gracefully — a project with no signals just shows today's docs view.

## Part 1 — auto code-scan (`docserver/inspect.py`)

`inspect_project(source_root) -> dict`:

```python
{
  "overview": {"languages": [...], "project_type": "CLI tool", "entry_points": [...]},
  "architecture": ["<top-level rels>"],          # feeds build_arch_mermaid
  "services": [{"name": "Postgres", "kind": "database", "via": "docker-compose.yml"}],
}
```

Sources (each `try/except`, never raises, reads capped ~64KB):

- **Manifests** → language/deps/entry points/type: `package.json` (JSON),
  `pyproject.toml`/`setup.py`/`requirements.txt`, `go.mod`, `Cargo.toml`,
  `Gemfile` (light regex/line scans — no TOML dep, works on older Python).
- **`docker-compose.yml`** → services from `image:` names.
- **`.env` / `.env.example`** → services from key patterns.
- Two built-in maps: dependency-name→service and env-key→service. Deduped by name.
- **Architecture tree**: top-level entries + one nested level, capped per dir,
  excluding `.git node_modules dist build __pycache__ .venv venv target .next coverage`.

`project_type` heuristic: `bin`→CLI, web framework dep→web server, `main`/lib
packaging→library, else app.

**Fingerprint cache** — `inspect_cached(source_root, dest)`: hash of
`(relpath, mtime, size)` over signal files **plus** the top-level dir listing,
stored at `dest/.inspect.json` (`{fingerprint, data}`). Unchanged fingerprint
returns cached data, so the per-request re-sync only stats ~10 files + one
`listdir`. Missing/invalid `source_root` → empty result → section hidden.

## Part 2 — worktree summary (`sync.py`)

- `split_frontmatter(text) -> (meta, body)`: leading `---`…`---` block of
  `key: value` lines parsed to `meta` and **stripped from the rendered body**
  (fixes raw-frontmatter rendering for all docs). Booleans/quotes handled.
- A doc is the summary if filename is `worktree-summary.md` **or**
  `meta.worktree_summary` is true. It is **promoted out of** the DOCUMENTS card
  grid (keeps its own rendered doc page).
- **Lead panel** "WHAT THIS WORKTREE IS DOING" above all other sections: summary
  title + intro paragraph + **first Mermaid block inlined** (rendered by
  `landing.js`) + a "Read full summary →" button to the doc page.

## Part 3 — SessionStart nudge (`hooks/session_start.py`)

After bring-up, if the checkout is git on a **non-default branch or a linked
worktree** with **no summary doc**, append to `additionalContext` a nudge to
write `docs/worktree-summary.md` — a short narrative of what this worktree is
doing (feature/bugfix/debug/research) with an **e2e Mermaid diagram**. Present →
no nudge. Staleness re-nudging is **out of scope** for the MVP.

## Branch-page order

1. Hero + badges
2. **What this worktree is doing** (if summary present)
3. **Overview & architecture** + **external services** (code-scan)
4. **Structure** (doc tree) — existing
5. **Documents** cards — existing, minus the promoted summary

## Testing

- `tests/test_inspect.py`: Node+Stripe → service; Python+psycopg/redis →
  Postgres/Redis; compose + `.env.example` parsed; arch tree excludes
  `node_modules`/`.git`; fingerprint reused on no-change, busted on change;
  empty dir → graceful empty.
- `tests/test_render.py`: `split_frontmatter` strips/parses; summary recognized
  by filename and flag, excluded from cards; lead panel renders title + lede +
  Mermaid + link; no-data omits the section (UI intact).
- `tests/test_hook.py`: nudge present when summary missing on a branch; absent
  when present.
- Docs: `SKILL.md` + `README.md` updated.

## Backwards compatibility

All additive. Frontmatter strip only triggers on a leading `---`…`---` key:value
block (real plan/spec docs start with `# Title`). `.inspect.json` is ignored by
the `*.html` cleanup. No migration needed.
