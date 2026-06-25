# doc-server Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a `doc-server` skill that serves a project's markdown plans/specs as browsable HTML on a single shared localhost port, unified under one global folder and grouped per project and per git worktree.

**Architecture:** A stdlib-only Python package (`docserver`) provides identity resolution, markdown→HTML sync, and a singleton HTTP server that re-syncs on every request. A thin `serve.py` CLI and a `SessionStart` hook both call one orchestrator (`app.bring_up`). The repo is laid out as a Claude Code plugin marketplace mirroring `anthropics/skills`.

**Tech Stack:** Python 3 standard library only (`http.server`, `urllib`, `socket`, `subprocess`, `pathlib`, `json`, `base64`). Tests use stdlib `unittest`. Markdown is rendered client-side by a vendored `marked.min.js` + `github-markdown.css`.

## Global Constraints

- Runtime uses the Python 3 **standard library only** — no third-party runtime dependencies (Python 3.8+).
- Markdown is rendered **client-side**; the server only emits HTML wrappers + serves cached assets.
- Global served root is `~/.claude/doc-server/`, overridable by `$DOC_SERVER_HOME` (used by tests).
- Default port is `8910`; resolution order: `--port` → `$DOC_SERVER_PORT` → remembered port in `state.json` → `8910`.
- Persisted port lives ONLY in `~/.claude/doc-server/state.json`; never write to shell config.
- Default docs glob is `docs/**/*.md`.
- A project is keyed by `<project>/<group>` where group is `main` or `worktrees/<name>`.
- Health endpoint path is `/__doc_server_health__`; marker JSON is `{"doc_server": true}`.
- Tests must not require network: set `DOC_SERVER_NO_FETCH=1` to skip asset downloads.
- Commit messages: imperative subject, NO `Co-Authored-By` trailer (per repo owner preference).
- Each test file is self-runnable: it inserts the skill dir on `sys.path` and ends with `unittest.main()`. Run a file with `python3 skills/doc-server/tests/<file>.py -v`.

---

### Task 1: Repo scaffold as a plugin marketplace

**Files:**
- Create: `.claude-plugin/marketplace.json`
- Create: `README.md`
- Create: `template/SKILL.md`
- Create: `.gitignore`
- Create: `skills/doc-server/tests/test_scaffold.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `marketplace.json` with a `plugins[0]` named `doc-server` whose `skills` array contains `./skills/doc-server`.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_scaffold.py`:

```python
import json
import os
import unittest

REPO = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


class TestScaffold(unittest.TestCase):
    def test_marketplace_registers_doc_server(self):
        path = os.path.join(REPO, ".claude-plugin", "marketplace.json")
        with open(path) as f:
            data = json.load(f)
        names = [p["name"] for p in data["plugins"]]
        self.assertIn("doc-server", names)
        plugin = next(p for p in data["plugins"] if p["name"] == "doc-server")
        self.assertIn("./skills/doc-server", plugin["skills"])

    def test_template_skill_exists(self):
        path = os.path.join(REPO, "template", "SKILL.md")
        self.assertTrue(os.path.isfile(path))
        with open(path) as f:
            self.assertTrue(f.read().startswith("---"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_scaffold.py -v`
Expected: FAIL — `FileNotFoundError` for `.claude-plugin/marketplace.json`.

- [ ] **Step 3: Create the scaffold files**

Create `.claude-plugin/marketplace.json`:

```json
{
  "name": "nljms-skills",
  "owner": {
    "name": "Neil Monzales",
    "email": "neiljames97@gmail.com"
  },
  "metadata": {
    "description": "Neil's personal Claude skills",
    "version": "0.1.0"
  },
  "plugins": [
    {
      "name": "doc-server",
      "description": "Serve project plans and docs as browsable HTML on a local port, grouped by project and git worktree.",
      "source": "./",
      "strict": false,
      "skills": [
        "./skills/doc-server"
      ]
    }
  ]
}
```

Create `template/SKILL.md`:

```markdown
---
name: template-skill
description: Replace with description of the skill and when Claude should use it.
---

# Insert instructions below
```

Create `.gitignore`:

```gitignore
__pycache__/
*.pyc
.DS_Store
```

Create `README.md`:

```markdown
# nljms skills

Personal collection of Claude skills, structured as a Claude Code plugin marketplace.

## Install in Claude Code

```
/plugin marketplace add <this-repo>
```

Then install the `doc-server` plugin from the marketplace browser.

## Skills

- [`doc-server`](./skills/doc-server) — serve project plans and docs as browsable HTML on a local port, grouped by project and git worktree.
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_scaffold.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add .claude-plugin/marketplace.json template/SKILL.md .gitignore README.md skills/doc-server/tests/test_scaffold.py
git commit -m "Scaffold skills repo as plugin marketplace"
```

---

### Task 2: Git identity resolution (`docserver/identity.py`)

**Files:**
- Create: `skills/doc-server/docserver/__init__.py`
- Create: `skills/doc-server/docserver/identity.py`
- Test: `skills/doc-server/tests/test_identity.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `Identity` dataclass: fields `project: str`, `group: str`, `source_root: str`, `is_git: bool`; property `key -> str` returns `f"{project}/{group}"`.
  - `resolve_identity(cwd: str) -> Identity`.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_identity.py`:

```python
import os
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver.identity import resolve_identity


def _git(args, cwd):
    subprocess.run(
        ["git", "-c", "user.email=t@t", "-c", "user.name=t"] + args,
        cwd=cwd, check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )


class TestIdentity(unittest.TestCase):
    def test_non_git_dir_falls_back_to_cwd_basename(self):
        with tempfile.TemporaryDirectory() as d:
            proj = os.path.join(d, "myproj")
            os.makedirs(proj)
            ident = resolve_identity(proj)
            self.assertEqual(ident.project, "myproj")
            self.assertEqual(ident.group, "main")
            self.assertFalse(ident.is_git)
            self.assertEqual(ident.key, "myproj/main")

    def test_main_worktree(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            os.makedirs(repo)
            _git(["init"], repo)
            open(os.path.join(repo, "f.txt"), "w").close()
            _git(["add", "."], repo)
            _git(["commit", "-m", "init"], repo)
            ident = resolve_identity(repo)
            self.assertEqual(ident.project, "repo")
            self.assertEqual(ident.group, "main")
            self.assertTrue(ident.is_git)

    def test_linked_worktree_is_grouped(self):
        with tempfile.TemporaryDirectory() as d:
            repo = os.path.join(d, "repo")
            os.makedirs(repo)
            _git(["init"], repo)
            open(os.path.join(repo, "f.txt"), "w").close()
            _git(["add", "."], repo)
            _git(["commit", "-m", "init"], repo)
            wt = os.path.join(d, "feature-x")
            _git(["worktree", "add", wt, "-b", "feature-x"], repo)
            ident = resolve_identity(wt)
            self.assertEqual(ident.project, "repo")
            self.assertEqual(ident.group, "worktrees/feature-x")
            self.assertEqual(ident.key, "repo/worktrees/feature-x")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_identity.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'docserver'`.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/docserver/__init__.py` (empty file):

```python
```

Create `skills/doc-server/docserver/identity.py`:

```python
import os
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class Identity:
    project: str
    group: str          # "main" or "worktrees/<name>"
    source_root: str    # absolute path whose docs glob is scanned
    is_git: bool

    @property
    def key(self) -> str:
        return f"{self.project}/{self.group}"


def _git(args, cwd):
    try:
        out = subprocess.run(
            ["git"] + args, cwd=cwd, check=True,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL,
        )
        return out.stdout.decode().strip()
    except Exception:
        return None


def resolve_identity(cwd: str) -> Identity:
    cwd = os.path.abspath(cwd)
    toplevel = _git(["rev-parse", "--show-toplevel"], cwd)
    if not toplevel:
        return Identity(os.path.basename(cwd.rstrip(os.sep)), "main", cwd, False)

    toplevel = os.path.abspath(toplevel)
    common = _git(["rev-parse", "--git-common-dir"], cwd)
    common = os.path.abspath(os.path.join(cwd, common)) if common else os.path.join(toplevel, ".git")
    main_root = os.path.dirname(common)
    project = os.path.basename(main_root.rstrip(os.sep))

    if toplevel == main_root:
        group = "main"
    else:
        group = f"worktrees/{os.path.basename(toplevel.rstrip(os.sep))}"

    return Identity(project, group, toplevel, True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_identity.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/__init__.py skills/doc-server/docserver/identity.py skills/doc-server/tests/test_identity.py
git commit -m "Add git identity resolution for doc-server"
```

---

### Task 3: State + registry persistence (`docserver/state.py`)

**Files:**
- Create: `skills/doc-server/docserver/state.py`
- Test: `skills/doc-server/tests/test_state.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `doc_server_home() -> pathlib.Path` (honors `$DOC_SERVER_HOME`, creates the dir).
  - `get_remembered_port() -> int | None`
  - `set_remembered_port(port: int) -> None`
  - `read_registry() -> dict` (maps `key -> {"source_root": str, "glob": str}`)
  - `register_target(key: str, source_root: str, glob: str) -> None`

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_state.py`:

```python
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestState(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._tmp.name
        # import after env is set so module-level paths are not cached wrongly
        from docserver import state
        self.state = state

    def tearDown(self):
        self._tmp.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)

    def test_home_is_created_from_env(self):
        home = self.state.doc_server_home()
        self.assertEqual(str(home), self._tmp.name)
        self.assertTrue(home.is_dir())

    def test_port_round_trips(self):
        self.assertIsNone(self.state.get_remembered_port())
        self.state.set_remembered_port(8912)
        self.assertEqual(self.state.get_remembered_port(), 8912)

    def test_register_target(self):
        self.state.register_target("repo/main", "/abs/repo", "docs/**/*.md")
        reg = self.state.read_registry()
        self.assertEqual(reg["repo/main"], {"source_root": "/abs/repo", "glob": "docs/**/*.md"})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_state.py -v`
Expected: FAIL — `ImportError: cannot import name 'state'`.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/docserver/state.py`:

```python
import json
import os
from pathlib import Path


def doc_server_home() -> Path:
    base = os.environ.get("DOC_SERVER_HOME")
    home = Path(base) if base else Path.home() / ".claude" / "doc-server"
    home.mkdir(parents=True, exist_ok=True)
    return home


def _state_file() -> Path:
    return doc_server_home() / "state.json"


def _registry_file() -> Path:
    return doc_server_home() / "registry.json"


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return default


def _write_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_remembered_port():
    port = _read_json(_state_file(), {}).get("port")
    return int(port) if isinstance(port, int) else None


def set_remembered_port(port: int) -> None:
    data = _read_json(_state_file(), {})
    data["port"] = int(port)
    _write_json(_state_file(), data)


def read_registry() -> dict:
    return _read_json(_registry_file(), {})


def register_target(key: str, source_root: str, glob: str) -> None:
    reg = read_registry()
    reg[key] = {"source_root": source_root, "glob": glob}
    _write_json(_registry_file(), reg)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_state.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/state.py skills/doc-server/tests/test_state.py
git commit -m "Add state and registry persistence for doc-server"
```

---

### Task 4: Markdown→HTML rendering + doc discovery (`docserver/sync.py` part 1)

**Files:**
- Create: `skills/doc-server/docserver/sync.py`
- Test: `skills/doc-server/tests/test_render.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `DEFAULT_GLOB = "docs/**/*.md"`
  - `find_docs(source_root: str, glob: str) -> list[pathlib.Path]` (sorted, files only)
  - `assets_available(home: pathlib.Path) -> bool`
  - `ensure_assets(home: pathlib.Path) -> bool` (downloads to `_assets/`, skips on `$DOC_SERVER_NO_FETCH`, returns availability)
  - `render_doc_html(title: str, markdown_text: str, assets_local: bool) -> str` (base64-embeds markdown)
  - `render_index_html(title: str, entries: list[tuple[str, str]]) -> str` (entries are `(href, label)`)

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_render.py`:

```python
import base64
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import sync


class TestRender(unittest.TestCase):
    def test_find_docs_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "docs", "sub"))
            open(os.path.join(d, "docs", "a.md"), "w").close()
            open(os.path.join(d, "docs", "sub", "b.md"), "w").close()
            open(os.path.join(d, "docs", "ignore.txt"), "w").close()
            found = sync.find_docs(d, sync.DEFAULT_GLOB)
            names = sorted(p.name for p in found)
            self.assertEqual(names, ["a.md", "b.md"])

    def test_render_doc_embeds_markdown_as_base64(self):
        html = sync.render_doc_html("a.md", "# Hello", assets_local=False)
        m = re.search(r'id="md-data"[^>]*>([^<]+)<', html)
        self.assertIsNotNone(m)
        decoded = base64.b64decode(m.group(1)).decode("utf-8")
        self.assertEqual(decoded, "# Hello")
        self.assertIn("cdn.jsdelivr.net", html)  # CDN fallback when not local

    def test_render_doc_uses_local_assets_when_available(self):
        html = sync.render_doc_html("a.md", "x", assets_local=True)
        self.assertIn("/_assets/marked.min.js", html)

    def test_render_index_lists_entries(self):
        html = sync.render_index_html("repo", [("main/index.html", "main")])
        self.assertIn('href="main/index.html"', html)
        self.assertIn("main", html)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_render.py -v`
Expected: FAIL — `ImportError: cannot import name 'sync'`.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/docserver/sync.py`:

```python
import base64
import os
import urllib.request
from html import escape
from pathlib import Path

DEFAULT_GLOB = "docs/**/*.md"

ASSET_URLS = {
    "marked.min.js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
    "github-markdown.css": "https://cdn.jsdelivr.net/npm/github-markdown-css/github-markdown.css",
}
CDN_BASE = {
    "css": "https://cdn.jsdelivr.net/npm/github-markdown-css/github-markdown.css",
    "js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
}


def find_docs(source_root: str, glob: str):
    root = Path(source_root)
    return sorted(p for p in root.glob(glob) if p.is_file())


def assets_available(home: Path) -> bool:
    a = home / "_assets"
    return all((a / name).exists() for name in ASSET_URLS)


def ensure_assets(home: Path) -> bool:
    if os.environ.get("DOC_SERVER_NO_FETCH"):
        return assets_available(home)
    a = home / "_assets"
    a.mkdir(parents=True, exist_ok=True)
    for name, url in ASSET_URLS.items():
        if (a / name).exists():
            continue
        try:
            with urllib.request.urlopen(url, timeout=10) as r:
                (a / name).write_bytes(r.read())
        except Exception:
            pass
    return assets_available(home)


def render_doc_html(title: str, markdown_text: str, assets_local: bool) -> str:
    b64 = base64.b64encode(markdown_text.encode("utf-8")).decode("ascii")
    css = "/_assets/github-markdown.css" if assets_local else CDN_BASE["css"]
    js = "/_assets/marked.min.js" if assets_local else CDN_BASE["js"]
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<link rel="stylesheet" href="{css}">
<style>
  body {{ margin:0; color-scheme: light dark; }}
  .markdown-body {{ box-sizing:border-box; max-width:980px; margin:0 auto; padding:32px 24px; }}
  .topbar {{ font-family: system-ui, sans-serif; padding:8px 24px; opacity:0.6; font-size:13px; }}
</style>
</head>
<body>
<div class="topbar"><a href="../index.html">&larr; back</a></div>
<article class="markdown-body" id="content">Loading&hellip;</article>
<script id="md-data" type="application/base64">{b64}</script>
<script src="{js}"></script>
<script>
  (function () {{
    var raw = document.getElementById('md-data').textContent;
    var bytes = Uint8Array.from(atob(raw), function (c) {{ return c.charCodeAt(0); }});
    var md = new TextDecoder('utf-8').decode(bytes);
    document.getElementById('content').innerHTML = marked.parse(md);
  }})();
</script>
</body>
</html>"""


def render_index_html(title: str, entries) -> str:
    if entries:
        items = "\n".join(
            f'<li><a href="{escape(href)}">{escape(label)}</a></li>' for href, label in entries
        )
    else:
        items = "<li><em>No documents found.</em></li>"
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
<style>
  body {{ font-family: system-ui, sans-serif; max-width:820px; margin:40px auto; padding:0 24px; color-scheme: light dark; }}
  h1 {{ font-size:20px; }}
  li {{ margin:6px 0; }}
</style>
</head>
<body>
<h1>{escape(title)}</h1>
<ul>
{items}
</ul>
</body>
</html>"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_render.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_render.py
git commit -m "Add markdown rendering and doc discovery for doc-server"
```

---

### Task 5: Target sync + index aggregation (`docserver/sync.py` part 2)

**Files:**
- Modify: `skills/doc-server/docserver/sync.py` (append functions)
- Test: `skills/doc-server/tests/test_sync.py`

**Interfaces:**
- Consumes: `find_docs`, `render_doc_html`, `render_index_html`, `assets_available` (Task 4); `read_registry` (Task 3).
- Produces:
  - `sync_target(home: Path, key: str, source_root: str, glob: str) -> list[tuple[str, str]]` — writes `<home>/<key>/<flat>.html` per doc (path separators flattened to `__`) plus `<home>/<key>/index.html`; clears stale `*.html` first; returns `(flat_name, rel_label)` list.
  - `write_project_index(home: Path, project: str) -> None`
  - `write_root_index(home: Path) -> None`
  - `sync_all(home: Path) -> None` — re-syncs every registered target, then all project indexes, then the root index.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_sync.py`:

```python
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


class TestSync(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import sync, state
        self.sync = sync
        self.state = state
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs", "sub"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")
        Path(self._src.name, "docs", "sub", "b.md").write_text("# B", encoding="utf-8")

    def tearDown(self):
        self._home.cleanup()
        self._src.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)
        os.environ.pop("DOC_SERVER_NO_FETCH", None)

    def test_sync_target_writes_flat_html_and_index(self):
        names = self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        flat = sorted(n for n, _ in names)
        self.assertEqual(flat, ["docs__a.html", "docs__sub__b.html"])
        self.assertTrue((self.home / "repo" / "main" / "docs__a.html").exists())
        self.assertTrue((self.home / "repo" / "main" / "index.html").exists())

    def test_sync_target_removes_stale_docs(self):
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        os.remove(os.path.join(self._src.name, "docs", "a.md"))
        self.sync.sync_target(self.home, "repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.assertFalse((self.home / "repo" / "main" / "docs__a.html").exists())

    def test_sync_all_builds_project_and_root_indexes(self):
        self.state.register_target("repo/main", self._src.name, self.sync.DEFAULT_GLOB)
        self.state.register_target("repo/worktrees/feat", self._src.name, self.sync.DEFAULT_GLOB)
        self.sync.sync_all(self.home)
        proj_index = (self.home / "repo" / "index.html").read_text(encoding="utf-8")
        self.assertIn("main/index.html", proj_index)
        self.assertIn("worktrees/feat/index.html", proj_index)
        root_index = (self.home / "index.html").read_text(encoding="utf-8")
        self.assertIn("repo/index.html", root_index)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_sync.py -v`
Expected: FAIL — `AttributeError: module 'docserver.sync' has no attribute 'sync_target'`.

- [ ] **Step 3: Append the implementation to `sync.py`**

Add to the top imports of `skills/doc-server/docserver/sync.py` (the `from . import state` line):

```python
from . import state
```

Append these functions to `skills/doc-server/docserver/sync.py`:

```python
def _flatten(rel: Path) -> str:
    return str(rel.with_suffix("")).replace(os.sep, "__") + ".html"


def sync_target(home: Path, key: str, source_root: str, glob: str):
    dest = home / key
    dest.mkdir(parents=True, exist_ok=True)
    for old in dest.glob("*.html"):
        old.unlink()

    local = assets_available(home)
    names = []
    for md in find_docs(source_root, glob):
        rel = md.relative_to(source_root)
        flat = _flatten(rel)
        text = md.read_text(encoding="utf-8", errors="replace")
        (dest / flat).write_text(render_doc_html(str(rel), text, local), encoding="utf-8")
        names.append((flat, str(rel)))

    entries = [(flat, label) for flat, label in names]
    (dest / "index.html").write_text(render_index_html(key, entries), encoding="utf-8")
    return names


def write_project_index(home: Path, project: str) -> None:
    base = home / project
    base.mkdir(parents=True, exist_ok=True)
    entries = []
    if (base / "main").is_dir():
        entries.append(("main/index.html", "main"))
    wt = base / "worktrees"
    if wt.is_dir():
        for d in sorted(wt.iterdir()):
            if d.is_dir():
                entries.append((f"worktrees/{d.name}/index.html", f"worktrees/{d.name}"))
    (base / "index.html").write_text(render_index_html(project, entries), encoding="utf-8")


def write_root_index(home: Path) -> None:
    entries = []
    for d in sorted(home.iterdir()):
        if d.is_dir() and d.name != "_assets":
            entries.append((f"{d.name}/index.html", d.name))
    (home / "index.html").write_text(render_index_html("doc-server", entries), encoding="utf-8")


def sync_all(home: Path) -> None:
    reg = state.read_registry()
    projects = set()
    for key, info in reg.items():
        sync_target(home, key, info["source_root"], info["glob"])
        projects.add(key.split("/", 1)[0])
    for project in sorted(projects):
        write_project_index(home, project)
    write_root_index(home)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_sync.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/sync.py skills/doc-server/tests/test_sync.py
git commit -m "Add target sync and index aggregation for doc-server"
```

---

### Task 6: Port helpers (`docserver/server.py` part 1)

**Files:**
- Create: `skills/doc-server/docserver/server.py`
- Test: `skills/doc-server/tests/test_port.py`

**Interfaces:**
- Consumes: nothing.
- Produces:
  - `HEALTH_PATH = "/__doc_server_health__"`, `HEALTH_MARKER = {"doc_server": True}`, `PORT_SCAN_RANGE = 50`
  - `is_port_free(port: int) -> bool`
  - `probe_health(port: int, timeout: float = 0.5) -> bool`
  - `resolve_port(preferred: int) -> tuple[int, str]` — second element is `"bind"` or `"reuse"`; raises `RuntimeError` if no free port within range.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_port.py`:

```python
import os
import socket
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import server


def _free_port():
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestPort(unittest.TestCase):
    def test_free_port_is_free(self):
        p = _free_port()
        self.assertTrue(server.is_port_free(p))

    def test_occupied_port_not_free(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            self.assertFalse(server.is_port_free(port))
        finally:
            s.close()

    def test_resolve_port_binds_when_free(self):
        p = _free_port()
        port, action = server.resolve_port(p)
        self.assertEqual(port, p)
        self.assertEqual(action, "bind")

    def test_resolve_port_scans_past_stranger(self):
        s = socket.socket()
        s.bind(("127.0.0.1", 0))
        s.listen(1)
        port = s.getsockname()[1]
        try:
            chosen, action = server.resolve_port(port)
            self.assertNotEqual(chosen, port)
            self.assertEqual(action, "bind")
        finally:
            s.close()

    def test_probe_health_false_when_nothing_listening(self):
        self.assertFalse(server.probe_health(_free_port()))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_port.py -v`
Expected: FAIL — `ImportError: cannot import name 'server'`.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/docserver/server.py`:

```python
import json
import socket
import urllib.request

HEALTH_PATH = "/__doc_server_health__"
HEALTH_MARKER = {"doc_server": True}
PORT_SCAN_RANGE = 50


def is_port_free(port: int) -> bool:
    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        s.bind(("127.0.0.1", port))
        return True
    except OSError:
        return False
    finally:
        s.close()


def probe_health(port: int, timeout: float = 0.5) -> bool:
    url = f"http://127.0.0.1:{port}{HEALTH_PATH}"
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = json.loads(r.read().decode("utf-8"))
            return data.get("doc_server") is True
    except Exception:
        return False


def resolve_port(preferred: int):
    if is_port_free(preferred):
        return preferred, "bind"
    if probe_health(preferred):
        return preferred, "reuse"
    for p in range(preferred + 1, preferred + 1 + PORT_SCAN_RANGE):
        if is_port_free(p):
            return p, "bind"
        if probe_health(p):
            return p, "reuse"
    raise RuntimeError(
        f"No free port found in range {preferred}-{preferred + PORT_SCAN_RANGE}; pass --port."
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_port.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/server.py skills/doc-server/tests/test_port.py
git commit -m "Add port resolution helpers for doc-server"
```

---

### Task 7: HTTP handler with live re-sync (`docserver/server.py` part 2)

**Files:**
- Modify: `skills/doc-server/docserver/server.py` (append handler + server factory)
- Test: `skills/doc-server/tests/test_handler.py`

**Interfaces:**
- Consumes: `HEALTH_PATH`, `HEALTH_MARKER` (Task 6); `sync.sync_all` (Task 5); `state` (Task 3).
- Produces:
  - `DocHandler` (subclass of `http.server.SimpleHTTPRequestHandler`): serves the health marker at `HEALTH_PATH`; on any other non-`/_assets/` GET calls `sync.sync_all(home)` before serving; silences logging.
  - `make_server(home: pathlib.Path, port: int) -> http.server.ThreadingHTTPServer`
  - `run_server_forever(home: pathlib.Path, port: int) -> None`

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_handler.py`:

```python
import base64
import json
import os
import re
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _get(port, path):
    with urllib.request.urlopen(f"http://127.0.0.1:{port}{path}", timeout=2) as r:
        return r.read().decode("utf-8")


class TestHandler(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state, sync
        self.server = server
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs"))
        self._doc = Path(self._src.name, "docs", "a.md")
        self._doc.write_text("# Hello", encoding="utf-8")
        state.register_target("repo/main", self._src.name, sync.DEFAULT_GLOB)
        sync.sync_all(self.home)

        self.port = _free_port()
        self.httpd = server.make_server(self.home, self.port)
        self.t = threading.Thread(target=self.httpd.serve_forever, daemon=True)
        self.t.start()
        for _ in range(40):
            if server.probe_health(self.port):
                break
            time.sleep(0.05)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._home.cleanup()
        self._src.cleanup()
        os.environ.pop("DOC_SERVER_HOME", None)
        os.environ.pop("DOC_SERVER_NO_FETCH", None)

    def test_health_marker(self):
        body = _get(self.port, self.server.HEALTH_PATH)
        self.assertEqual(json.loads(body), {"doc_server": True})

    def test_serves_doc_and_live_resyncs_on_edit(self):
        def decoded():
            html = _get(self.port, "/repo/main/docs__a.html")
            b64 = re.search(r'id="md-data"[^>]*>([^<]+)<', html).group(1)
            return base64.b64decode(b64).decode("utf-8")

        self.assertEqual(decoded(), "# Hello")
        self._doc.write_text("# Updated", encoding="utf-8")
        self.assertEqual(decoded(), "# Updated")


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_handler.py -v`
Expected: FAIL — `AttributeError: module 'docserver.server' has no attribute 'make_server'`.

- [ ] **Step 3: Append the implementation to `server.py`**

Add these imports to the top of `skills/doc-server/docserver/server.py`:

```python
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

from . import sync
```

Append to `skills/doc-server/docserver/server.py`:

```python
class DocHandler(SimpleHTTPRequestHandler):
    def do_GET(self):
        if self.path == HEALTH_PATH:
            body = json.dumps(HEALTH_MARKER).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)
            return
        if not self.path.startswith("/_assets/"):
            try:
                sync.sync_all(Path(self.directory))
            except Exception:
                pass
        return super().do_GET()

    def log_message(self, *args):
        pass


def make_server(home: Path, port: int) -> ThreadingHTTPServer:
    handler = partial(DocHandler, directory=str(home))
    return ThreadingHTTPServer(("127.0.0.1", port), handler)


def run_server_forever(home: Path, port: int) -> None:
    make_server(home, port).serve_forever()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_handler.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/server.py skills/doc-server/tests/test_handler.py
git commit -m "Add HTTP handler with live re-sync for doc-server"
```

---

### Task 8: Server lifecycle + orchestrator (`ensure_server` + `app.bring_up`)

**Files:**
- Modify: `skills/doc-server/docserver/server.py` (append `ensure_server`)
- Create: `skills/doc-server/docserver/app.py`
- Test: `skills/doc-server/tests/test_app.py`

**Interfaces:**
- Consumes: `resolve_port`, `probe_health`, `make_server`/`run_server_forever` (Tasks 6-7); `state.*` (Task 3); `sync.*` (Tasks 4-5); `identity.resolve_identity` (Task 2).
- Produces:
  - `server.ensure_server(home: Path, preferred: int) -> tuple[int, bool]` — returns `(port, started)`; on `"reuse"` returns `started=False` without spawning; on `"bind"` spawns `serve.py --daemon --port <port>` detached, waits for health, then returns `started=True`. Persists the chosen port via `state.set_remembered_port`.
  - `app.bring_up(cwd: str, glob: str, port: int | None = None, open_browser: bool = False) -> dict` — returns `{"url", "port", "key", "started"}`.

> **Note on testing the daemon spawn:** the subprocess-spawn branch of `ensure_server` is verified manually (Task 9 smoke test) to avoid leaking detached processes in the unit suite. The unit test below exercises the `"reuse"` branch by starting a thread-server first, which is the deterministic path.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_app.py`:

```python
import os
import sys
import tempfile
import threading
import time
import unittest
import urllib.request
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestApp(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        self._src = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state, app
        self.server = server
        self.state = state
        self.app = app
        self.home = Path(self._home.name)
        os.makedirs(os.path.join(self._src.name, "docs"))
        Path(self._src.name, "docs", "a.md").write_text("# A", encoding="utf-8")

        # Start a real doc-server on a known port so bring_up reuses it.
        self.port = _free_port()
        self.httpd = server.make_server(self.home, self.port)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        for _ in range(40):
            if server.probe_health(self.port):
                break
            time.sleep(0.05)
        state.set_remembered_port(self.port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._home.cleanup()
        self._src.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def test_bring_up_reuses_running_server(self):
        result = self.app.bring_up(self._src.name, "docs/**/*.md")
        self.assertEqual(result["port"], self.port)
        self.assertFalse(result["started"])
        self.assertTrue(result["url"].endswith("/main/"))
        # the registered target is now reachable
        with urllib.request.urlopen(result["url"] + "index.html", timeout=2) as r:
            self.assertEqual(r.status, 200)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_app.py -v`
Expected: FAIL — `ImportError: cannot import name 'app'`.

- [ ] **Step 3: Write the implementations**

Add these imports to the top of `skills/doc-server/docserver/server.py`:

```python
import subprocess
import sys
import time

from . import state
```

Append `ensure_server` to `skills/doc-server/docserver/server.py`:

```python
def ensure_server(home: Path, preferred: int):
    port, action = resolve_port(preferred)
    if action == "reuse":
        state.set_remembered_port(port)
        return port, False

    serve_py = Path(__file__).resolve().parent.parent / "serve.py"
    subprocess.Popen(
        [sys.executable, str(serve_py), "--daemon", "--port", str(port)],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    for _ in range(100):
        if probe_health(port):
            break
        time.sleep(0.05)
    state.set_remembered_port(port)
    return port, True
```

Create `skills/doc-server/docserver/app.py`:

```python
import os

from . import identity, server, state, sync


def _env_port():
    val = os.environ.get("DOC_SERVER_PORT")
    return int(val) if val and val.isdigit() else None


def bring_up(cwd: str, glob: str, port=None, open_browser: bool = False) -> dict:
    home = state.doc_server_home()
    ident = identity.resolve_identity(cwd)
    state.register_target(ident.key, ident.source_root, glob)
    sync.ensure_assets(home)

    preferred = port or _env_port() or state.get_remembered_port() or 8910
    chosen, started = server.ensure_server(home, preferred)
    sync.sync_all(home)

    url = f"http://localhost:{chosen}/{ident.key}/"
    if open_browser:
        import webbrowser
        webbrowser.open(url)
    return {"url": url, "port": chosen, "key": ident.key, "started": started}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_app.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/docserver/server.py skills/doc-server/docserver/app.py skills/doc-server/tests/test_app.py
git commit -m "Add server lifecycle and bring_up orchestrator for doc-server"
```

---

### Task 9: CLI entrypoint (`serve.py`)

**Files:**
- Create: `skills/doc-server/serve.py`
- Test: `skills/doc-server/tests/test_cli.py`

**Interfaces:**
- Consumes: `app.bring_up`, `server.run_server_forever`, `state.doc_server_home` (Tasks 3, 7, 8).
- Produces: a command-line program:
  - `python3 serve.py [--docs GLOB] [--port N] [--open]` → resolves cwd identity, brings up the server, prints the URL.
  - `python3 serve.py --daemon --port N` → runs the server forever (used by `ensure_server`).

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_cli.py`:

```python
import os
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
SERVE = os.path.join(SKILL_DIR, "serve.py")


def _probe(port):
    try:
        with urllib.request.urlopen(
            f"http://127.0.0.1:{port}/__doc_server_health__", timeout=0.5
        ) as r:
            return r.status == 200
    except Exception:
        return False


class TestCli(unittest.TestCase):
    def test_serve_brings_up_and_prints_url(self):
        home = tempfile.mkdtemp()
        src = tempfile.mkdtemp()
        os.makedirs(os.path.join(src, "docs"))
        Path(src, "docs", "a.md").write_text("# A", encoding="utf-8")
        env = dict(os.environ, DOC_SERVER_HOME=home, DOC_SERVER_NO_FETCH="1")
        proc = subprocess.run(
            [sys.executable, SERVE, "--docs", "docs/**/*.md"],
            cwd=src, env=env, capture_output=True, text=True, timeout=30,
        )
        self.assertEqual(proc.returncode, 0, proc.stderr)
        url = proc.stdout.strip().splitlines()[-1]
        self.assertIn("/main/", url)
        port = int(url.split(":")[2].split("/")[0])
        # the daemon spawned by ensure_server should answer health
        ok = any(_probe(port) or time.sleep(0.1) for _ in range(30))
        self.assertTrue(_probe(port), "daemon did not come up")
        # cleanup the detached daemon
        subprocess.run(["pkill", "-f", f"serve.py --daemon --port {port}"])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_cli.py -v`
Expected: FAIL — `FileNotFoundError`/non-zero return because `serve.py` does not exist.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/serve.py`:

```python
#!/usr/bin/env python3
"""doc-server CLI: serve project docs as HTML on a shared local port."""
import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from docserver import app, server, state  # noqa: E402


def main(argv=None):
    parser = argparse.ArgumentParser(description="Serve project docs as HTML.")
    parser.add_argument("--docs", default="docs/**/*.md", help="glob of docs to serve")
    parser.add_argument("--port", type=int, default=None, help="preferred port")
    parser.add_argument("--open", action="store_true", help="open the browser")
    parser.add_argument("--daemon", action="store_true", help=argparse.SUPPRESS)
    args = parser.parse_args(argv)

    if args.daemon:
        if args.port is None:
            parser.error("--daemon requires --port")
        server.run_server_forever(state.doc_server_home(), args.port)
        return

    result = app.bring_up(os.getcwd(), args.docs, port=args.port, open_browser=args.open)
    print(result["url"])


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_cli.py -v`
Expected: PASS (1 test). (The test kills the detached daemon it spawned.)

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/serve.py skills/doc-server/tests/test_cli.py
git commit -m "Add serve.py CLI entrypoint for doc-server"
```

---

### Task 10: SessionStart hook (`hooks/session_start.py`)

**Files:**
- Create: `skills/doc-server/hooks/session_start.py`
- Test: `skills/doc-server/tests/test_hook.py`

**Interfaces:**
- Consumes: `app.bring_up` (Task 8).
- Produces:
  - `run(cwd: str) -> dict | None` — returns `bring_up` result when `cwd/docs` contains at least one `.md`; returns `None` otherwise.
  - `main()` — reads SessionStart JSON from stdin (`{"cwd": ...}`), calls `run`, and on a result prints `{"hookSpecificOutput": {"hookEventName": "SessionStart", "additionalContext": "..."}}`.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_hook.py`:

```python
import importlib.util
import os
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path

SKILL_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
sys.path.insert(0, SKILL_DIR)
HOOK = os.path.join(SKILL_DIR, "hooks", "session_start.py")


def _load_hook():
    spec = importlib.util.spec_from_file_location("session_start", HOOK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _free_port():
    import socket
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


class TestHook(unittest.TestCase):
    def setUp(self):
        self._home = tempfile.TemporaryDirectory()
        os.environ["DOC_SERVER_HOME"] = self._home.name
        os.environ["DOC_SERVER_NO_FETCH"] = "1"
        from docserver import server, state
        self.port = _free_port()
        self.httpd = server.make_server(Path(self._home.name), self.port)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        for _ in range(40):
            if server.probe_health(self.port):
                break
            time.sleep(0.05)
        state.set_remembered_port(self.port)

    def tearDown(self):
        self.httpd.shutdown()
        self.httpd.server_close()
        self._home.cleanup()
        for k in ("DOC_SERVER_HOME", "DOC_SERVER_NO_FETCH"):
            os.environ.pop(k, None)

    def test_run_returns_none_without_docs(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            self.assertIsNone(hook.run(d))

    def test_run_brings_up_with_docs(self):
        hook = _load_hook()
        with tempfile.TemporaryDirectory() as d:
            os.makedirs(os.path.join(d, "docs"))
            Path(d, "docs", "a.md").write_text("# A", encoding="utf-8")
            result = hook.run(d)
            self.assertIsNotNone(result)
            self.assertEqual(result["port"], self.port)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_hook.py -v`
Expected: FAIL — `FileNotFoundError` loading `hooks/session_start.py`.

- [ ] **Step 3: Write the implementation**

Create `skills/doc-server/hooks/session_start.py`:

```python
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_hook.py -v`
Expected: PASS (2 tests).

- [ ] **Step 5: Commit**

```bash
git add skills/doc-server/hooks/session_start.py skills/doc-server/tests/test_hook.py
git commit -m "Add SessionStart hook for doc-server auto-invoke"
```

---

### Task 11: SKILL.md + full-suite verification

**Files:**
- Create: `skills/doc-server/SKILL.md`
- Test: `skills/doc-server/tests/test_skill_md.py`

**Interfaces:**
- Consumes: everything above.
- Produces: `SKILL.md` with valid frontmatter (`name: doc-server`, a `description` mentioning docs/plans, serving, HTML, and worktrees) and usage + hook-setup instructions.

- [ ] **Step 1: Write the failing test**

Create `skills/doc-server/tests/test_skill_md.py`:

```python
import os
import unittest

SKILL_MD = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "SKILL.md"))


class TestSkillMd(unittest.TestCase):
    def test_frontmatter_and_keywords(self):
        with open(SKILL_MD) as f:
            text = f.read()
        self.assertTrue(text.startswith("---"))
        head = text.split("---", 2)[1]
        self.assertIn("name: doc-server", head)
        self.assertIn("description:", head)
        lower = text.lower()
        for kw in ("serve.py", "worktree", "docs", "html"):
            self.assertIn(kw, lower)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 skills/doc-server/tests/test_skill_md.py -v`
Expected: FAIL — `FileNotFoundError` for `SKILL.md`.

- [ ] **Step 3: Write `SKILL.md`**

Create `skills/doc-server/SKILL.md`:

```markdown
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 skills/doc-server/tests/test_skill_md.py -v`
Expected: PASS (1 test).

- [ ] **Step 5: Run the full suite**

Run:
```bash
for t in skills/doc-server/tests/test_*.py; do python3 "$t" -v || exit 1; done
```
Expected: every test file passes.

- [ ] **Step 6: Manual smoke test (daemon spawn path)**

Run (from a real git repo that has `docs/*.md`):
```bash
python3 skills/doc-server/serve.py --docs "docs/**/*.md"
```
Expected: prints a URL like `http://localhost:8910/<repo>/main/`; opening it lists the docs and renders them. Confirm `~/.claude/doc-server/state.json` contains the chosen port. Stop the daemon when done:
```bash
pkill -f "serve.py --daemon"
```

- [ ] **Step 7: Commit**

```bash
git add skills/doc-server/SKILL.md skills/doc-server/tests/test_skill_md.py
git commit -m "Add SKILL.md and full-suite verification for doc-server"
```

---

## Self-Review

**1. Spec coverage:**
- Serve docs on a dedicated port → Tasks 6-9 (port resolution, handler, lifecycle, CLI). ✓
- Convert docs to HTML → Task 4 (`render_doc_html`). ✓
- Unify all docs in one folder → `~/.claude/doc-server/` via `state.doc_server_home` (Task 3) + `sync_all` (Task 5). ✓
- Worktree subfolder grouping → Task 2 (`identity`) + Task 5 (`sync_target`/indexes). ✓
- Live freshness → Task 7 (`DocHandler` re-syncs each GET). ✓
- Default port + free-port scan + persistence in state.json → Tasks 3, 6, 8. ✓
- `$DOC_SERVER_PORT` as override, no shell writes → Task 8 (`_env_port`, resolution order). ✓
- Auto-invoke when docs present → Task 10 (SessionStart hook). ✓
- Repo as plugin marketplace mirroring anthropics/skills → Task 1. ✓
- Zero runtime deps / client-side markdown → enforced throughout; assets in Task 4. ✓
- Singleton via health marker → Tasks 6-8. ✓

**2. Placeholder scan:** No TBD/TODO; every code step contains complete code. The one explicitly untested path (detached daemon spawn) is documented and covered by a manual smoke test (Task 9 test + Task 11 Step 6). ✓

**3. Type consistency:** `Identity.key`, `resolve_identity`, `register_target(key, source_root, glob)`, `read_registry`, `find_docs`, `render_doc_html(title, text, assets_local)`, `render_index_html(title, entries)`, `sync_target`/`sync_all`, `is_port_free`/`probe_health`/`resolve_port`, `make_server`/`run_server_forever`/`ensure_server`, `app.bring_up` signatures are used identically across producing and consuming tasks. ✓
