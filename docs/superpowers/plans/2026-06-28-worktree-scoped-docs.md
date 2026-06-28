# Worktree-scoped doc rendering Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make each worktree's doc-server page show only the docs that worktree introduced (vs. its source branch), with the agent-designated context doc led and the rest demoted.

**Architecture:** A new `gitscope.py` resolves a worktree's source branch (upstream → fork-point → default merge-base) and returns the set of worktree-added doc paths. `sync_target` filters its doc glob through that set. The registry gains an optional `context` path the agent passes via `--context`; `render_branch_index` promotes the context doc to a lead panel and demotes the remaining docs into a collapsed section.

**Tech Stack:** Python 3 stdlib only (`subprocess`, `unittest`, `pathlib`). No new dependencies. Tests run via `./run_tests.sh` (custom harness expecting a trailing `OK` from `unittest`).

## Global Constraints

- Python 3 standard library only — no third-party installs.
- All paths in this plan are relative to `skills/doc-server/` unless absolute.
- Backward compatibility: a checkout with no resolvable source branch (default branch, non-git, no fork-point) MUST render exactly as today (full glob, no demotion).
- Legacy triggers `worktree-summary.md` filename and `worktree_summary: true` frontmatter MUST keep working as context-doc aliases.
- Run the full suite with `./run_tests.sh` from `skills/doc-server/`; every file must end in `OK`.
- Commit messages: no `Co-Authored-By` trailer, no AI attribution.

---

## File Structure

- **Create** `docserver/gitscope.py` — source-branch resolution + worktree-added doc set. One responsibility: "which docs did this worktree introduce?"
- **Create** `tests/test_gitscope.py` — git-backed tests for the above.
- **Modify** `docserver/state.py` — `register_target` persists optional `context`.
- **Modify** `docserver/app.py`, `serve.py` — thread a `--context` flag through `bring_up`.
- **Modify** `docserver/sync.py` — filter docs in `sync_target`; rename `is_summary_doc` → `is_context_doc` with registry-path resolution; context-first `render_branch_index`.
- **Modify** `tests/test_state.py`, `tests/test_sync.py`, `tests/test_render.py` — cover new behavior.
- **Modify** `SKILL.md`, `hooks/session_start.py` — nudge the agent to write + pass the context doc.

---

### Task 1: gitscope — source branch + worktree-added docs

**Files:**
- Create: `docserver/gitscope.py`
- Test: `tests/test_gitscope.py`

**Interfaces:**
- Consumes: nothing (stdlib `subprocess` only).
- Produces:
  - `source_branch_base(source_root: str) -> str | None` — a commit-ish to diff against, or `None` when none resolves / no divergence.
  - `worktree_added_docs(source_root: str) -> set[str] | None` — POSIX rel-paths (relative to `source_root`) of docs added on this worktree (committed-added ∪ untracked/staged-new), filtered to `*.md` under `docs/`. `None` means "show all" (no base, not git, or base == HEAD).

- [ ] **Step 1: Write the failing test**

```python
# tests/test_gitscope.py
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from docserver import gitscope  # noqa: E402


def _run(args, cwd):
    subprocess.run(args, cwd=cwd, check=True,
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def _init_repo(root):
    _run(["git", "init", "-b", "main"], root)
    _run(["git", "config", "user.email", "t@t.t"], root)
    _run(["git", "config", "user.name", "t"], root)
    os.makedirs(os.path.join(root, "docs"))
    Path(root, "docs", "base.md").write_text("# base", encoding="utf-8")
    _run(["git", "add", "."], root)
    _run(["git", "commit", "-m", "base"], root)


class TestGitscope(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = os.path.realpath(self._tmp.name)
        _init_repo(self.root)

    def tearDown(self):
        self._tmp.cleanup()

    def test_non_git_returns_none(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(gitscope.worktree_added_docs(d))

    def test_default_branch_shows_all(self):
        # On main with no divergence → None (show all).
        self.assertIsNone(gitscope.worktree_added_docs(self.root))

    def test_committed_added_doc_on_branch(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "new.md").write_text("# new", encoding="utf-8")
        _run(["git", "add", "."], self.root)
        _run(["git", "commit", "-m", "add new"], self.root)
        added = gitscope.worktree_added_docs(self.root)
        self.assertEqual(added, {"docs/new.md"})

    def test_untracked_doc_on_branch(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "wip.md").write_text("# wip", encoding="utf-8")
        added = gitscope.worktree_added_docs(self.root)
        self.assertEqual(added, {"docs/wip.md"})

    def test_base_doc_excluded(self):
        _run(["git", "checkout", "-b", "feat"], self.root)
        Path(self.root, "docs", "new.md").write_text("# new", encoding="utf-8")
        added = gitscope.worktree_added_docs(self.root)
        self.assertNotIn("docs/base.md", added)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_gitscope.py`
Expected: FAIL — `ModuleNotFoundError: No module named 'docserver.gitscope'`.

- [ ] **Step 3: Write the implementation**

```python
# docserver/gitscope.py
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
        if base and base != head:
            return base
    return None


def _is_doc(path):
    return path.startswith("docs/") and path.endswith(".md")


def worktree_added_docs(source_root):
    """POSIX rel-paths of docs added on this worktree, or None for "show all"."""
    base = source_branch_base(source_root)
    if base is None:
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
            if code in ("??", "A ", "AM", "M ", " M") and _is_doc(path):
                added.add(path)
    return added
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_gitscope.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/gitscope.py skills/doc-server/tests/test_gitscope.py
git commit -m "doc-server: resolve worktree-added docs vs source branch"
```

---

### Task 2: registry stores an optional context path

**Files:**
- Modify: `docserver/state.py:47-50`
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `register_target(key, source_root, glob, context=None)` — stores `context` in the entry only when truthy (existing two-key entries are unchanged).

- [ ] **Step 1: Write the failing test** (append inside `TestState`)

```python
    def test_register_target_with_context(self):
        self.state.register_target("repo/feat", "/abs/repo", "docs/**/*.md",
                                   context="docs/worktree-context.md")
        reg = self.state.read_registry()
        self.assertEqual(reg["repo/feat"]["context"], "docs/worktree-context.md")

    def test_register_target_without_context_has_no_key(self):
        self.state.register_target("repo/main", "/abs/repo", "docs/**/*.md")
        self.assertNotIn("context", self.state.read_registry()["repo/main"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_state.py`
Expected: FAIL — `TypeError: register_target() got an unexpected keyword argument 'context'`.

- [ ] **Step 3: Write the implementation** (replace `register_target`)

```python
def register_target(key: str, source_root: str, glob: str, context: str = None) -> None:
    reg = read_registry()
    entry = {"source_root": source_root, "glob": glob}
    if context:
        entry["context"] = context
    reg[key] = entry
    _write_json(_registry_file(), reg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_state.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/state.py skills/doc-server/tests/test_state.py
git commit -m "doc-server: persist optional context doc path in registry"
```

---

### Task 3: --context flag threaded through bring_up

**Files:**
- Modify: `docserver/app.py:11-25`
- Modify: `serve.py:13-35`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `state.register_target(..., context=...)` from Task 2.
- Produces: `app.bring_up(cwd, glob, port=None, open_browser=False, context=None)` — passes `context` to `register_target`. `serve.py` accepts `--context PATH`.

- [ ] **Step 1: Write the failing test** (append a method inside the existing test class in `tests/test_app.py`)

```python
    def test_bring_up_registers_context(self):
        # bring_up registers the target before any server work; we only assert
        # the registry write, so stub the server + sync to no-ops.
        from docserver import app, server, sync, state
        server.ensure_server = lambda home, port: (port, False)
        sync.sync_all = lambda home: None
        sync.ensure_assets = lambda home: True
        app.bring_up(self._src.name, "docs/**/*.md", port=8999,
                     context="docs/worktree-context.md")
        reg = state.read_registry()
        entry = next(iter(reg.values()))
        self.assertEqual(entry["context"], "docs/worktree-context.md")
```

> If `tests/test_app.py` lacks `self._src`/registry env setup, mirror the
> `setUp`/`tearDown` from `tests/test_sync.py` (temp `DOC_SERVER_HOME`, temp
> source dir with a `docs/` folder, `DOC_SERVER_NO_FETCH=1`).

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_app.py`
Expected: FAIL — `TypeError: bring_up() got an unexpected keyword argument 'context'`.

- [ ] **Step 3: Write the implementation**

In `docserver/app.py`, update the signature and the register call:

```python
def bring_up(cwd: str, glob: str, port=None, open_browser: bool = False,
             context: str = None) -> dict:
    home = state.doc_server_home()
    ident = identity.resolve_identity(cwd)
    state.register_target(ident.key, ident.source_root, glob, context=context)
    sync.ensure_assets(home)
```

(Leave the rest of `bring_up` unchanged.)

In `serve.py`, add the argument and pass it:

```python
    parser.add_argument("--context", default=None,
                        help="path (relative to repo root) of the worktree's lead context doc")
```

and change the `bring_up` call:

```python
    result = app.bring_up(os.getcwd(), args.docs, port=args.port,
                          open_browser=args.open, context=args.context)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_app.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/app.py skills/doc-server/serve.py skills/doc-server/tests/test_app.py
git commit -m "doc-server: add --context flag to designate the lead doc"
```

---

### Task 4: sync_target filters docs to the worktree-added set

**Files:**
- Modify: `docserver/sync.py` (`sync_target` at lines ~1170-1229; `sync_all` at ~1252-1260)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `gitscope.worktree_added_docs(source_root)` from Task 1.
- Produces: `sync_target(home, key, source_root, glob, nav=None, context=None)` — when `worktree_added_docs` returns a set, only docs whose POSIX rel-path is in it are rendered; when it returns `None`, all docs render (today's behavior).

- [ ] **Step 1: Write the failing test** (append inside `TestSync`)

```python
    def test_sync_target_filters_to_added_docs(self):
        # Monkeypatch the git scope so the test stays filesystem-only.
        self.sync.gitscope.worktree_added_docs = lambda root: {"docs/a.md"}
        names = self.sync.sync_target(self.home, "repo/feat", self._src.name,
                                      self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html"])
        self.assertFalse((self.home / "repo" / "feat" / "docs__sub__b.html").exists())

    def test_sync_target_none_shows_all(self):
        self.sync.gitscope.worktree_added_docs = lambda root: None
        names = self.sync.sync_target(self.home, "repo/main", self._src.name,
                                      self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html", "docs__sub__b.html"])
```

> Add `from docserver import gitscope` access via `self.sync.gitscope`; ensure
> `sync.py` imports `gitscope` (Step 3) so the attribute exists to patch.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: FAIL — `AttributeError: module 'docserver.sync' has no attribute 'gitscope'` (or the filter assertion fails).

- [ ] **Step 3: Write the implementation**

In `docserver/sync.py`, extend the imports at the top:

```python
from . import gitscope, inspect, state
```

In `sync_target`, update the signature to accept `context`:

```python
def sync_target(home: Path, key: str, source_root: str, glob: str, nav=None, context=None):
```

Immediately before the `for md in find_docs(...)` loop, compute the filter set:

```python
    added = gitscope.worktree_added_docs(source_root)
```

Inside the loop, right after `rel = md.relative_to(source_root)`, skip non-worktree docs:

```python
        rel = md.relative_to(source_root)
        if added is not None and rel.as_posix() not in added:
            continue
        flat = _flatten(rel)
```

In `sync_all`, pass the registry's context through:

```python
        for key, info in reg.items():
            sync_target(home, key, info["source_root"], info["glob"],
                        nav=nav, context=info.get("context"))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_sync.py
git commit -m "doc-server: render only worktree-added docs per branch"
```

---

### Task 5: context-doc resolution (rename is_summary_doc → is_context_doc)

**Files:**
- Modify: `docserver/sync.py:479-484` (`is_summary_doc`); loop at ~1200-1208
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `context` param from Task 4.
- Produces: `is_context_doc(rel: str, meta: dict, context_path: str = None) -> bool` — True when `rel` equals the registry-designated `context_path`, OR `meta` has `worktree_context: true`, OR the legacy `worktree-summary.md` name / `worktree_summary: true`. In `sync_target`, the resolved doc is captured into a `context_doc` dict (same shape as today's `summary`).

- [ ] **Step 1: Write the failing test** (append inside `TestSync`)

```python
    def test_is_context_doc_registry_path(self):
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {}, "docs/x.md"))
        self.assertFalse(self.sync.is_context_doc("docs/y.md", {}, "docs/x.md"))

    def test_is_context_doc_frontmatter(self):
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {"worktree_context": True}))

    def test_is_context_doc_legacy_aliases(self):
        self.assertTrue(self.sync.is_context_doc("docs/worktree-summary.md", {}))
        self.assertTrue(self.sync.is_context_doc("docs/x.md", {"worktree_summary": True}))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: FAIL — `AttributeError: module 'docserver.sync' has no attribute 'is_context_doc'`.

- [ ] **Step 3: Write the implementation**

Replace `is_summary_doc` with:

```python
def is_context_doc(rel: str, meta: dict, context_path: str = None) -> bool:
    """The worktree's lead context doc: the registry-designated path, or
    frontmatter ``worktree_context: true``, or the legacy worktree-summary
    name / ``worktree_summary: true`` aliases."""
    if context_path and rel == context_path:
        return True
    if meta.get("worktree_context"):
        return True
    if Path(rel).name.lower() == "worktree-summary.md":
        return True
    return bool(meta.get("worktree_summary"))
```

In `sync_target`, rename the `summary` local to `context_doc` and update the capture block:

```python
    context_doc = None
```

```python
        # The agent's context doc is promoted to the lead panel, not a card.
        if context_doc is None and is_context_doc(str(rel), meta, context):
            context_doc = {
                "title": doc_title(body, str(rel)),
                "lede": _first_paragraph(body),
                "mermaid": _first_mermaid(body),
                "href": f"/{key}/{flat}",
            }
            continue
```

Update the `render_branch_index` call to pass `context=context_doc` (renamed kwarg lands in Task 6):

```python
        render_branch_index(project, branch, docs_meta, nav, local,
                            inspect_data=inspect_data, context=context_doc),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: `OK`.

> Note: `render_branch_index` still has the `summary=` kwarg until Task 6. To
> keep the suite green between commits, temporarily call it with `summary=context_doc`
> here and switch to `context=` in Task 6, OR do Tasks 5 and 6 back-to-back
> before running the full suite. Prefer the latter.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_sync.py
git commit -m "doc-server: resolve lead context doc via flag, frontmatter, or legacy alias"
```

---

### Task 6: context-first branch layout with demoted "Other documents"

**Files:**
- Modify: `docserver/sync.py` — `_summary_panel_html` (~847-870), `render_branch_index` (~922-1011)
- Test: `tests/test_render.py`

**Interfaces:**
- Consumes: `context` dict from Task 5.
- Produces: `render_branch_index(project, branch, docs, nav, assets_local, inspect_data=None, context=None) -> str`. When `context` is set and `docs` is non-empty, the STRUCTURE map + DOCUMENTS cards are wrapped in a collapsed `<details>` titled "Other documents (N)"; the context panel + code-scan stay above it. When `context` is None, layout is unchanged from today.

- [ ] **Step 1: Write the failing test** (append inside the test class in `tests/test_render.py`)

```python
    def test_branch_index_demotes_other_docs_when_context(self):
        from docserver import sync
        docs = [{"flat": "docs__p.html", "rel": "docs/p.md", "title": "P", "toc": []}]
        context = {"title": "Ctx", "lede": "lead", "mermaid": "", "href": "/r/feat/docs__c.html"}
        html = sync.render_branch_index("r", "feat", docs, {"r": ["feat"]}, False,
                                        context=context)
        self.assertIn("CONTEXT", html)
        self.assertIn("Other documents", html)
        self.assertIn("<details", html)

    def test_branch_index_no_context_has_no_details(self):
        from docserver import sync
        docs = [{"flat": "docs__p.html", "rel": "docs/p.md", "title": "P", "toc": []}]
        html = sync.render_branch_index("r", "feat", docs, {"r": ["feat"]}, False)
        self.assertNotIn("Other documents", html)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_render.py`
Expected: FAIL — `TypeError: render_branch_index() got an unexpected keyword argument 'context'` (or assertion on "Other documents").

- [ ] **Step 3: Write the implementation**

Rename `_summary_panel_html` → `_context_panel_html` and relabel its section + button:

```python
def _context_panel_html(context) -> str:
    """Lead 'context' panel built from the agent's worktree context doc."""
    if not context:
        return ""
    parts = [
        '<div class="section-label"><span class="t">CONTEXT</span>'
        '<span class="rule"></span></div>',
        '<div class="tile" style="cursor:default">'
        f'<div class="name" style="margin-bottom:6px">{escape(context["title"])}</div>',
    ]
    if context.get("lede"):
        parts.append(f'<p class="lede" style="margin:0">{escape(context["lede"])}</p>')
    parts.append("</div>")
    if context.get("mermaid"):
        parts.append(
            '<div class="diagram dotted" style="margin-top:14px"><pre class="mermaid">'
            + escape(context["mermaid"]) + "</pre></div>"
            '<div class="diagram-cap">Problem / context, end to end.</div>'
        )
    parts.append(
        f'<a class="btn primary" href="{escape(context["href"])}" '
        f'style="margin-top:14px">Read full context {_icon("arrow", 14)}</a>'
    )
    return "\n".join(parts)
```

Change `render_branch_index`'s signature and the panel call:

```python
def render_branch_index(project: str, branch: str, docs, nav,
                        assets_local: bool, inspect_data=None, context=None) -> str:
```

```python
    panel = _context_panel_html(context)
    if panel:
        parts.append(panel)
```

Wrap the STRUCTURE + DOCUMENTS region in a collapsed `<details>` when a context
doc exists. Replace the block that starts at `parts.append(` for STRUCTURE
through the final `parts.append("</div>")` of the cards with:

```python
    body = []
    body.append(
        '<div class="section-label"><span class="t">STRUCTURE</span>'
        '<span class="rule"></span></div>'
    )
    body.append(
        '<div class="diagram dotted"><pre class="mermaid">'
        + escape(build_tree_mermaid(branch, rels))
        + "</pre></div>"
        '<div class="diagram-cap">Auto-generated from the docs in this branch · zoom to inspect</div>'
    )
    body.append(
        '<div class="section-label"><span class="t">DOCUMENTS</span>'
        f'<span class="n">{n}</span><span class="rule"></span></div>'
    )
    body.append('<div class="cards">')
    for d in docs:
        doc_href = f"/{key}/{d['flat']}"
        label, kind = doc_tag(d["rel"])
        sections = len(d["toc"])
        body.append('<div class="card">')
        body.append(
            '<div class="card-head">'
            f'<span class="card-ic tag-{kind}">{_icon("file", 15)}</span>'
            f'<span class="tag tag-{kind}">{label}</span>'
            '<span class="grow" style="flex:1"></span>'
            f'<span class="sections">{sections} section{"s" if sections != 1 else ""}</span>'
            '</div>'
        )
        body.append(f'<div class="title">{escape(d["title"])}</div>')
        body.append(f'<div class="path">{escape(d["rel"])}</div>')
        body.append('<div class="div"></div>')
        body.append('<div class="otp">ON THIS PAGE</div>')
        body.append(_toc_list_html(doc_href, d["toc"]))
        body.append(
            f'<a class="open" href="{escape(doc_href)}">Open document {_icon("arrow", 14)}</a>'
        )
        body.append("</div>")
    body.append("</div>")

    if context:
        parts.append(
            f'<details class="other-docs"><summary>Other documents '
            f'<span class="n">{n}</span></summary>'
            + "\n".join(body) + "</details>"
        )
    else:
        parts.extend(body)

    return render_shell(key, render_sidebar(nav, key), "\n".join(parts),
                        body_scripts=_mermaid_scripts(assets_local),
                        topbar_html=topbar)
```

- [ ] **Step 4: Run the render + sync tests to verify they pass**

Run: `cd skills/doc-server && python3 tests/test_render.py && python3 tests/test_sync.py`
Expected: `OK` for both.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_render.py
git commit -m "doc-server: lead with context doc, demote other docs into a collapsed section"
```

---

### Task 7: SKILL.md + session-start hook nudge

**Files:**
- Modify: `SKILL.md`
- Modify: `hooks/session_start.py`
- Test: `tests/test_skill_md.py`, `tests/test_hook.py`

**Interfaces:**
- Consumes: the `--context` flag (Task 3) and `worktree_context` frontmatter (Task 5).
- Produces: documentation only — no new code interfaces.

- [ ] **Step 1: Write the failing test** (append inside the test class in `tests/test_skill_md.py`)

```python
    def test_skill_documents_context_flag(self):
        text = self._skill_text()  # reuse the file-reading helper in this class
        self.assertIn("--context", text)
        self.assertIn("worktree_context", text)
```

> If there is no `_skill_text()` helper, read `SKILL.md` directly:
> `text = Path(__file__).resolve().parents[1].joinpath("SKILL.md").read_text()`.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_skill_md.py`
Expected: FAIL — assertion error, `--context` not present.

- [ ] **Step 3: Write the implementation**

In `SKILL.md`, in the "Serve the current project's docs" section, document the flag and the convention (insert after the existing `--port`/`--open` notes):

```markdown
- `--context <path>` designates the worktree's **lead context document** (path
  relative to the repo root). On a worktree, the branch page leads with this doc
  and shows only the docs this worktree added relative to its source branch;
  everything else is demoted into a collapsed "Other documents" section. If you
  do not pass `--context`, a doc with frontmatter `worktree_context: true` (or the
  legacy `worktree-summary.md` / `worktree_summary: true`) is used instead.

  The context doc should follow: context summary → solution → before/after flow
  (a Mermaid flowchart) → plans related to the context. Update it as the work
  evolves; the server re-syncs on refresh.
```

In `hooks/session_start.py`, update the nudge text so it points at the context
doc + flow (locate the existing string that mentions `worktree-summary.md` and
replace its guidance with):

```python
        "Write docs/worktree-context.md — a short context doc for this worktree "
        "(context summary → solution → before/after Mermaid flow → plans) and "
        "serve it with --context docs/worktree-context.md so the branch page "
        "leads with it."
```

- [ ] **Step 4: Run the doc tests to verify they pass**

Run: `cd skills/doc-server && python3 tests/test_skill_md.py && python3 tests/test_hook.py`
Expected: `OK` for both. If `test_hook.py` asserts on the old wording, update that assertion to match the new string.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/SKILL.md skills/doc-server/hooks/session_start.py skills/doc-server/tests/test_skill_md.py skills/doc-server/tests/test_hook.py
git commit -m "doc-server: document context doc convention in skill and session hook"
```

---

### Task 8: full suite + manual smoke check

**Files:** none (verification only).

- [ ] **Step 1: Run the full suite**

Run: `cd skills/doc-server && ./run_tests.sh`
Expected: every line `ok:`; exit code 0.

- [ ] **Step 2: Manual smoke check on this worktree**

Run: `cd <repo root> && python3 skills/doc-server/serve.py --docs "docs/**/*.md" --context docs/superpowers/specs/2026-06-28-worktree-scoped-docs-design.md`
Expected: prints a URL. Open it: the page leads with a **CONTEXT** panel (the design spec), and the older `docs/superpowers/plans/*` and `specs/*` from before this branch are **not** listed — only worktree-added docs, with the structure map + cards inside a collapsed "Other documents".

- [ ] **Step 3: Commit (only if smoke check required a fix)**

```bash
git add -A
git commit -m "doc-server: fix issues found in worktree-scoped docs smoke check"
```

---

## Self-Review

**Spec coverage:**
- Source-branch resolution (upstream → fork-point → default merge-base) → Task 1.
- Worktree-added doc set (committed-added ∪ untracked) → Task 1, applied in Task 4.
- Show-all fallback (default branch / non-git) → Task 1 (`None`), Task 4, Task 6 (no demotion).
- Context doc designation (flag → frontmatter → legacy alias) → Tasks 2, 3, 5.
- Context-first layout + collapsed "Other documents" → Task 6.
- Code-scan stays in lead area → Task 6 (inspect block untouched, above the `<details>`).
- Global sidebar unchanged → no task touches `render_sidebar`.
- SKILL.md + hook nudge → Task 7.
- Tests for all of the above → each task + Task 8.

**Placeholder scan:** No TBD/TODO; all code blocks are complete. The only conditional guidance (test_app setUp, _skill_text helper, hook wording) is explicit about the fallback.

**Type consistency:** `context` is a dict `{title, lede, mermaid, href}` everywhere (Tasks 5, 6). `worktree_added_docs` returns `set[str] | None`, consumed as such in Task 4. `is_context_doc(rel, meta, context_path=None)` signature matches its call site. `register_target(..., context=None)` matches `app.bring_up` and `sync_all`'s `info.get("context")`.
