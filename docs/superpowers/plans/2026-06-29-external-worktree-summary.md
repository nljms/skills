# External worktree summary Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move the worktree context/summary doc out of the project repo into a non-disposable doc-server source area keyed per project/branch, written by the agent via a new `serve.py --summary-path` flag and rendered by the server as the lead CONTEXT panel.

**Architecture:** A path resolver yields `~/.claude/doc-server/_context/<project>/<branch>/worktree-summary.md`. `serve.py --summary-path` resolves the cwd's identity, ensures that dir exists, and prints the path for the agent to write to. `sync_target` reads that external file (when present), renders it to `worktree-summary.html`, and makes it the lead context — taking precedence over in-repo detection, which remains as a fallback.

**Tech Stack:** Python 3 stdlib only. Tests via `./run_tests.sh` from `skills/doc-server/` (custom unittest harness expecting a trailing `OK` per file).

## Global Constraints

- Python 3 standard library only — no third-party installs.
- All paths relative to `skills/doc-server/` unless absolute.
- The external summary lives at `<home>/_context/<project>/<branch>/worktree-summary.md`, where `<home>` is `state.doc_server_home()` and `<project>/<branch>` is the identity key. `_context/` is NEVER under the generated `<project>/<branch>/` HTML dir.
- Lead-context resolution order: external summary file → `--context` repo doc → in-repo `worktree_context`/legacy `worktree-summary.md`/`worktree_summary`. External wins when present; in-repo detection runs only when no external file exists.
- The external summary is rendered to `worktree-summary.html` in the branch's generated dir and added to the kept-files set so stale-cleanup does not delete it.
- Backward compat: with no external file, branch pages render exactly as today.
- Commit messages: no `Co-Authored-By` trailer, no AI attribution.
- Run the full suite with `./run_tests.sh`; every file must end in `OK`.

---

## File Structure

- **Modify** `docserver/state.py` — add `context_summary_path(home, key) -> Path`.
- **Modify** `docserver/app.py` — add `summary_path(cwd) -> Path` (resolve identity, mkdir, return path).
- **Modify** `serve.py` — add `--summary-path` flag that prints `app.summary_path(cwd)` and exits.
- **Modify** `docserver/sync.py` — in `sync_target`, render the external summary as the lead before in-repo detection.
- **Modify** `SKILL.md`, `hooks/session_start.py` — document the external convention; nudge the agent to write there.
- **Modify** `tests/test_state.py`, `tests/test_app.py`, `tests/test_sync.py`, `tests/test_skill_md.py` — cover the above.
- **Delete** `docs/worktree-summary.md` (repo cleanup) and seed this worktree's external summary.

---

### Task 1: path resolver in state.py

**Files:**
- Modify: `docserver/state.py` (append a function)
- Test: `tests/test_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `context_summary_path(home, key: str) -> Path` — returns `Path(home) / "_context" / key / "worktree-summary.md"`. Does not create anything.

- [ ] **Step 1: Write the failing test** (append inside `TestState`)

```python
    def test_context_summary_path(self):
        from pathlib import Path
        home = self.state.doc_server_home()
        p = self.state.context_summary_path(home, "repo/feat")
        self.assertEqual(p, Path(home) / "_context" / "repo" / "feat" / "worktree-summary.md")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_state.py`
Expected: FAIL — `AttributeError: module 'docserver.state' has no attribute 'context_summary_path'`.

- [ ] **Step 3: Write the implementation** (append to `docserver/state.py`)

```python
def context_summary_path(home, key: str) -> Path:
    """Source path of a branch's external worktree summary (outside the repo and
    outside the disposable generated HTML dir)."""
    return Path(home) / "_context" / key / "worktree-summary.md"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_state.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/state.py skills/doc-server/tests/test_state.py
git commit -m "doc-server: add external worktree-summary path resolver"
```

---

### Task 2: app.summary_path + serve.py --summary-path

**Files:**
- Modify: `docserver/app.py`
- Modify: `serve.py`
- Test: `tests/test_app.py`

**Interfaces:**
- Consumes: `state.context_summary_path` (Task 1); `identity.resolve_identity` (existing).
- Produces: `app.summary_path(cwd: str) -> Path` — resolves identity for `cwd`, computes the external summary path, creates its parent dir, returns the path. `serve.py --summary-path` prints it and exits.

- [ ] **Step 1: Write the failing test** (append inside `TestApp` in `tests/test_app.py`)

```python
    def test_summary_path_resolves_and_creates_dir(self):
        # self._src is a non-git temp dir → identity branch is "main",
        # project is the dir basename.
        p = self.app.summary_path(self._src.name)
        self.assertEqual(p.name, "worktree-summary.md")
        self.assertIn("_context", str(p))
        self.assertTrue(p.parent.is_dir())  # parent dir created
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_app.py`
Expected: FAIL — `AttributeError: module 'docserver.app' has no attribute 'summary_path'`.

- [ ] **Step 3: Write the implementation**

In `docserver/app.py`, add (the module already imports `identity, server, state, sync`):

```python
def summary_path(cwd: str):
    home = state.doc_server_home()
    ident = identity.resolve_identity(cwd)
    p = state.context_summary_path(home, ident.key)
    p.parent.mkdir(parents=True, exist_ok=True)
    return p
```

In `serve.py`, add the flag after the `--context` argument:

```python
    parser.add_argument("--summary-path", action="store_true",
                        help="print the external worktree-summary.md path for this project/branch, then exit")
```

and handle it early in `main`, before the `app.bring_up(...)` call (after the `--daemon` block):

```python
    if args.summary_path:
        print(app.summary_path(os.getcwd()))
        return
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_app.py`
Expected: `OK`.

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/app.py skills/doc-server/serve.py skills/doc-server/tests/test_app.py
git commit -m "doc-server: add --summary-path to resolve the external summary location"
```

---

### Task 3: sync_target renders the external summary as the lead

**Files:**
- Modify: `docserver/sync.py` (`sync_target`, between lines 1224 and 1225)
- Test: `tests/test_sync.py`

**Interfaces:**
- Consumes: `state.context_summary_path` (Task 1); existing `split_frontmatter`, `render_doc_html`, `doc_title`, `_first_paragraph`, `_first_mermaid`.
- Produces: when `<home>/_context/<key>/worktree-summary.md` exists, `sync_target` writes `<dest>/worktree-summary.html`, sets `context_doc` from it (href `/<key>/worktree-summary.html`), keeps it from cleanup, and skips in-repo context detection (because `context_doc` is already non-None).

- [ ] **Step 1: Write the failing test** (append inside `TestSync`)

```python
    def test_external_summary_is_lead_context(self):
        # Seed an external summary for repo/main.
        ext = self.state.context_summary_path(self.home, "repo/main")
        ext.parent.mkdir(parents=True, exist_ok=True)
        ext.write_text("# My Worktree\n\nDoing the thing.\n", encoding="utf-8")
        # No worktree filter for this non-git source.
        self.sync.gitscope.worktree_added_docs = lambda root: None
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        dest = self.home / "repo" / "main"
        self.assertTrue((dest / "worktree-summary.html").exists())
        index = (dest / "index.html").read_text(encoding="utf-8")
        self.assertIn("CONTEXT", index)
        self.assertIn("My Worktree", index)
        self.assertIn("Read full context", index)

    def test_external_summary_survives_cleanup(self):
        ext = self.state.context_summary_path(self.home, "repo/main")
        ext.parent.mkdir(parents=True, exist_ok=True)
        ext.write_text("# Ext\n\nlede.\n", encoding="utf-8")
        self.sync.gitscope.worktree_added_docs = lambda root: None
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        # Second sync must keep the rendered summary, not unlink it.
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.assertTrue((self.home / "repo" / "main" / "worktree-summary.html").exists())

    def test_external_summary_beats_in_repo_context(self):
        # An in-repo doc designated via --context must NOT win over the external file.
        from pathlib import Path
        Path(self._src.name, "docs", "spec.md").write_text("# Spec doc\n\nspec lede.\n", encoding="utf-8")
        ext = self.state.context_summary_path(self.home, "repo/main")
        ext.parent.mkdir(parents=True, exist_ok=True)
        ext.write_text("# External wins\n\next lede.\n", encoding="utf-8")
        self.sync.gitscope.worktree_added_docs = lambda root: None
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB,
                              context="docs/spec.md")
        index = (self.home / "repo" / "main" / "index.html").read_text(encoding="utf-8")
        self.assertIn("External wins", index)
        self.assertNotIn("Spec doc", index.split("Other documents")[0])  # spec not in the lead panel
```

> The save/restore of `self.sync.gitscope.worktree_added_docs` is already handled by this test class's setUp/tearDown (added in the worktree-scoped-docs work). If not, add it.

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: FAIL — `worktree-summary.html` does not exist / `CONTEXT` not found (external file is ignored today).

- [ ] **Step 3: Write the implementation**

In `docserver/sync.py`, in `sync_target`, insert this block immediately after
`    current_flats: set = set()` (line 1224) and before
`    added = gitscope.worktree_added_docs(source_root)` (line 1225):

```python
    # An external worktree summary (outside the repo) is the highest-priority
    # lead context. Render it and short-circuit in-repo context detection.
    ext_summary = state.context_summary_path(home, key)
    if ext_summary.exists():
        ext_text = ext_summary.read_text(encoding="utf-8", errors="replace")
        _, ext_body = split_frontmatter(ext_text)
        _atomic_write_text(
            dest / "worktree-summary.html",
            render_doc_html("worktree-summary.md", ext_body, local,
                            back_href=back_href, sidebar_html=sidebar),
        )
        current_flats.add("worktree-summary.html")
        context_doc = {
            "title": doc_title(ext_body, "worktree-summary.md"),
            "lede": _first_paragraph(ext_body),
            "mermaid": _first_mermaid(ext_body),
            "href": f"/{key}/worktree-summary.html",
        }
```

No other change is needed: the existing in-repo loop guards detection with
`if context_doc is None and is_context_doc(...)`, so a non-None `context_doc`
from the external file naturally suppresses in-repo detection.

- [ ] **Step 4: Run test to verify it passes**

Run: `cd skills/doc-server && python3 tests/test_sync.py`
Expected: `OK`.

- [ ] **Step 5: Run the full suite (no regressions)**

Run: `cd skills/doc-server && ./run_tests.sh`
Expected: every line `ok:`.

- [ ] **Step 6: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_sync.py
git commit -m "doc-server: render external worktree summary as the lead context"
```

---

### Task 4: SKILL.md + session hook point to the external summary

**Files:**
- Modify: `SKILL.md`
- Modify: `hooks/session_start.py`
- Test: `tests/test_skill_md.py`

**Interfaces:**
- Consumes: `serve.py --summary-path` (Task 2).
- Produces: documentation only.

- [ ] **Step 1: Write the failing test** (append inside the test class in `tests/test_skill_md.py`)

```python
    def test_skill_documents_summary_path(self):
        from pathlib import Path
        text = Path(__file__).resolve().parents[1].joinpath("SKILL.md").read_text(encoding="utf-8")
        self.assertIn("--summary-path", text)
        self.assertIn("_context", text)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd skills/doc-server && python3 tests/test_skill_md.py`
Expected: FAIL — `--summary-path` not present.

- [ ] **Step 3: Write the implementation**

In `SKILL.md`, in the "Serve the current project's docs" section, add (after the `--context` block):

```markdown
- `--summary-path` prints the external worktree-summary path for the current
  project/branch — `~/.claude/doc-server/_context/<project>/<branch>/worktree-summary.md`
  — creating its directory if needed, then exits. Write the worktree's context
  doc THERE (not in the repo), following: context summary → solution →
  before/after Mermaid flow → plans. The server renders it as the lead CONTEXT
  panel. Keeping it outside the repo keeps the project branch clean.
```

In `hooks/session_start.py`, update the nudge string so it points at the external
path + flow instead of an in-repo file. Locate the nudge text in `summary_nudge`
and replace its guidance with:

```python
        "Write this worktree's context summary OUTSIDE the repo: run "
        "`serve.py --summary-path` to get the path "
        "(~/.claude/doc-server/_context/<project>/<branch>/worktree-summary.md) "
        "and write it there (context summary → solution → before/after Mermaid "
        "flow → plans). The server renders it as the lead context."
```

- [ ] **Step 4: Run the doc tests**

Run: `cd skills/doc-server && python3 tests/test_skill_md.py && python3 tests/test_hook.py`
Expected: `OK` for both. If `test_hook.py` asserts on the old wording, update that assertion to match the new string (it must still assert a nudge is produced and now mentions `--summary-path` / `_context`).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/SKILL.md skills/doc-server/hooks/session_start.py skills/doc-server/tests/test_skill_md.py skills/doc-server/tests/test_hook.py
git commit -m "doc-server: document external worktree-summary convention"
```

---

### Task 5: repo cleanup + dogfood this worktree

**Files:**
- Delete: `docs/worktree-summary.md`
- Create (external, outside the repo): `~/.claude/doc-server/_context/skills/worktree-scoped-docs/worktree-summary.md`

**Interfaces:** none (operational).

- [ ] **Step 1: Capture the current summary content**

Run: `cat docs/worktree-summary.md`
Keep its body (drop the frontmatter — the external file does not need it).

- [ ] **Step 2: Write it to the external location**

Run: `python3 skills/doc-server/serve.py --summary-path`
Write the captured body (minus frontmatter) to the printed path using file tools.

- [ ] **Step 3: Delete the in-repo summary**

```bash
git rm docs/worktree-summary.md
```

- [ ] **Step 4: Verify the lead still renders from the external file**

Run:
```bash
pkill -f "serve.py --daemon" 2>/dev/null; sleep 1
URL=$(python3 skills/doc-server/serve.py --docs "docs/**/*.md")
sleep 1
curl -s "${URL}index.html" | grep -c "CONTEXT"
curl -s "${URL}index.html" | grep -c "worktree-summary.html"
```
Expected: `CONTEXT` count ≥ 1 and `worktree-summary.html` referenced ≥ 1, with no `docs/worktree-summary.md` in the repo.

- [ ] **Step 5: Commit**

```bash
git add -A
git commit -m "doc-server: move this worktree's summary out of the repo"
```

---

### Task 6: full suite + smoke check

**Files:** none (verification only).

- [ ] **Step 1: Full suite**

Run: `cd skills/doc-server && ./run_tests.sh`
Expected: every line `ok:`; exit 0.

- [ ] **Step 2: Smoke check (fresh daemon)**

Run:
```bash
pkill -f "serve.py --daemon" 2>/dev/null; sleep 1
URL=$(python3 skills/doc-server/serve.py --docs "docs/**/*.md")
sleep 1
HTML=$(curl -s "${URL}index.html")
echo "CONTEXT: $(echo "$HTML" | grep -c '>CONTEXT<')"
echo "summary html linked: $(echo "$HTML" | grep -c 'worktree-summary.html')"
ls docs/worktree-summary.md 2>&1 | grep -c "No such file"
```
Expected: CONTEXT ≥ 1, summary html linked ≥ 1, and `docs/worktree-summary.md` absent (the `grep -c "No such file"` prints 1).

---

## Self-Review

**Spec coverage:**
- Dedicated non-disposable storage path → Task 1.
- `serve.py --summary-path` write mechanism → Task 2.
- Server renders external file as lead, kept from cleanup → Task 3.
- Lead-context precedence (external > --context > in-repo) → Task 3 (`context_doc` set before the loop; `test_external_summary_beats_in_repo_context`).
- In-repo fallback still works when no external file → unchanged loop, covered by existing sync/render tests.
- SKILL.md + hook updated → Task 4.
- Repo cleanup + dogfood → Task 5.
- Full verification → Task 6.

**Placeholder scan:** No TBD/TODO; every code step has complete code. The only conditional guidance (test_hook wording update) is explicit.

**Type consistency:** `context_summary_path(home, key) -> Path` is used identically in Task 2 (`app.summary_path`) and Task 3 (`sync_target`). The `context_doc` dict shape `{title, lede, mermaid, href}` matches what `render_branch_index`/`_context_panel_html` already consume. `app.summary_path(cwd) -> Path` matches the serve.py call site.
