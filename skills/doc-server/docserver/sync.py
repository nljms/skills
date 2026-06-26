import base64
import os
import re
import threading
import urllib.request
from html import escape
from pathlib import Path

from . import state

_SYNC_LOCK = threading.Lock()

# Client-side renderer for doc pages: decode the embedded markdown, render it,
# add heading ids (so the table-of-contents anchors resolve), upgrade ```mermaid
# fences into live diagrams, and jump to any #hash. Lives in its own file so the
# CSP can stay strict (no inline scripts).
RENDER_JS = """\
(function () {
  function slugify(s) {
    return s.toLowerCase().trim()
      .replace(/[^\\w\\s-]/g, '')
      .replace(/\\s+/g, '-')
      .replace(/-+/g, '-');
  }
  var el = document.getElementById('md-data');
  if (!el) return;
  var raw = el.textContent;
  var bytes = Uint8Array.from(atob(raw), function (c) { return c.charCodeAt(0); });
  var md = new TextDecoder('utf-8').decode(bytes);
  var content = document.getElementById('content');
  content.innerHTML = marked.parse(md);
  content.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(function (h) {
    if (!h.id) h.id = slugify(h.textContent);
  });
  content.querySelectorAll('pre code.language-mermaid').forEach(function (code) {
    var div = document.createElement('div');
    div.className = 'mermaid';
    div.textContent = code.textContent;
    var pre = code.parentNode;
    pre.parentNode.replaceChild(div, pre);
  });
  if (window.mermaid) {
    try {
      var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      mermaid.initialize({ startOnLoad: false, theme: dark ? 'dark' : 'neutral' });
      mermaid.run({ querySelector: '.mermaid' });
    } catch (e) {}
  }
  if (location.hash) {
    var t = document.getElementById(decodeURIComponent(location.hash.slice(1)));
    if (t) t.scrollIntoView();
  }
})();
"""

# Renders the mermaid diagrams baked into generated landing pages.
LANDING_JS = """\
(function () {
  function init() {
    if (!window.mermaid) return;
    try {
      var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      mermaid.initialize({ startOnLoad: false, theme: dark ? 'dark' : 'neutral' });
      mermaid.run({ querySelector: '.mermaid' });
    } catch (e) {}
  }
  if (document.readyState !== 'loading') init();
  else document.addEventListener('DOMContentLoaded', init);
})();
"""

DEFAULT_GLOB = "docs/**/*.md"

ASSET_URLS = {
    "marked.min.js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
    "github-markdown.css": "https://cdn.jsdelivr.net/npm/github-markdown-css/github-markdown.css",
    "mermaid.min.js": "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js",
}
CDN_BASE = {
    "css": "https://cdn.jsdelivr.net/npm/github-markdown-css/github-markdown.css",
    "js": "https://cdn.jsdelivr.net/npm/marked/marked.min.js",
    "mermaid": "https://cdn.jsdelivr.net/npm/mermaid@10/dist/mermaid.min.js",
}

# Shared chrome: a fixed left sidebar listing projects/branches and a scrollable
# main column. Inline styles are allowed by the CSP (style-src 'unsafe-inline').
SHELL_CSS = """\
:root {
  --bg: #ffffff; --panel: #f6f8fa; --border: #d0d7de; --text: #1f2328;
  --muted: #636c76; --accent: #0969da; --accent-bg: #ddf4ff;
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0d1117; --panel: #161b22; --border: #30363d; --text: #e6edf3;
    --muted: #8b949e; --accent: #4493f8; --accent-bg: #163056;
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--text); background: var(--bg);
  font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", system-ui, sans-serif;
  -webkit-font-smoothing: antialiased;
}
.layout { display: flex; min-height: 100vh; }
.sidebar {
  width: 270px; flex: 0 0 270px; background: var(--panel);
  border-right: 1px solid var(--border); padding: 18px 14px;
  position: sticky; top: 0; align-self: flex-start; height: 100vh; overflow-y: auto;
}
.brand a {
  display: flex; align-items: center; gap: 8px; font-weight: 600; font-size: 15px;
  color: var(--text); text-decoration: none; padding: 4px 8px; margin-bottom: 14px;
}
.nav details { margin-bottom: 2px; }
.nav summary {
  list-style: none; cursor: pointer; padding: 6px 8px; border-radius: 6px;
  font-weight: 600; font-size: 13px; color: var(--text);
}
.nav summary::-webkit-details-marker { display: none; }
.nav summary::before { content: "▸"; color: var(--muted); margin-right: 6px; font-size: 11px; }
.nav details[open] > summary::before { content: "▾"; }
.nav summary:hover { background: var(--accent-bg); }
.nav summary a { color: inherit; text-decoration: none; }
.nav ul { list-style: none; margin: 2px 0 6px; padding-left: 18px; }
.nav li a {
  display: block; padding: 5px 8px; border-radius: 6px; font-size: 13px;
  color: var(--muted); text-decoration: none; word-break: break-all;
}
.nav li a:hover { background: var(--accent-bg); color: var(--text); }
.nav li.active a { background: var(--accent-bg); color: var(--accent); font-weight: 600; }
.main { flex: 1 1 auto; min-width: 0; padding: 32px 40px; max-width: 1100px; }
.main h1 { font-size: 24px; margin: 0 0 4px; }
.main h2 { font-size: 18px; margin: 28px 0 10px; padding-bottom: 6px; border-bottom: 1px solid var(--border); }
.crumbs { color: var(--muted); font-size: 13px; margin-bottom: 18px; }
.crumbs a { color: var(--accent); text-decoration: none; }
.empty { color: var(--muted); font-style: italic; }
.cards { display: grid; gap: 14px; grid-template-columns: repeat(auto-fill, minmax(300px, 1fr)); }
.card {
  border: 1px solid var(--border); border-radius: 10px; padding: 16px 18px;
  background: var(--bg);
}
.card h3 { margin: 0 0 8px; font-size: 15px; }
.card h3 a { color: var(--accent); text-decoration: none; }
.card .path { color: var(--muted); font-size: 12px; margin: -4px 0 10px; word-break: break-all; }
.toc { list-style: none; margin: 0; padding: 0; }
.toc li { margin: 2px 0; }
.toc a { color: var(--text); text-decoration: none; font-size: 13px; border-radius: 4px; padding: 1px 4px; display: inline-block; }
.toc a:hover { background: var(--accent-bg); color: var(--accent); }
.tiles { display: grid; gap: 12px; grid-template-columns: repeat(auto-fill, minmax(220px, 1fr)); }
.tile {
  border: 1px solid var(--border); border-radius: 10px; padding: 16px;
  text-decoration: none; color: var(--text); background: var(--bg); display: block;
}
.tile:hover { border-color: var(--accent); }
.tile .name { font-weight: 600; font-size: 14px; word-break: break-all; }
.tile .meta { color: var(--muted); font-size: 12px; margin-top: 6px; }
.diagram {
  border: 1px solid var(--border); border-radius: 10px; padding: 18px;
  background: var(--bg); overflow-x: auto;
}
.diagram .mermaid { display: flex; justify-content: center; }
.topbar { font-size: 13px; margin-bottom: 16px; }
.topbar a { color: var(--accent); text-decoration: none; }
.markdown-body { max-width: 900px; }
"""


# ---------------------------------------------------------------------------
# Discovery + assets
# ---------------------------------------------------------------------------

def find_docs(source_root: str, glob: str):
    root = Path(source_root)
    return sorted(p for p in root.glob(glob) if p.is_file())


def assets_available(home: Path) -> bool:
    a = home / "_assets"
    return all((a / name).exists() for name in ASSET_URLS)


def ensure_assets(home: Path) -> bool:
    a = home / "_assets"
    a.mkdir(parents=True, exist_ok=True)
    # Always write OUR code; it must exist even offline.
    (a / "render.js").write_text(RENDER_JS, encoding="utf-8")
    (a / "landing.js").write_text(LANDING_JS, encoding="utf-8")
    if os.environ.get("DOC_SERVER_NO_FETCH"):
        return assets_available(home)
    for name, url in ASSET_URLS.items():
        if (a / name).exists():
            continue
        try:
            with urllib.request.urlopen(url, timeout=15) as r:
                (a / name).write_bytes(r.read())
        except Exception:
            pass
    return assets_available(home)


def _asset(local: bool, name: str, cdn_key: str) -> str:
    return f"/_assets/{name}" if local else CDN_BASE[cdn_key]


# ---------------------------------------------------------------------------
# Markdown analysis (titles + table of contents)
# ---------------------------------------------------------------------------

def slugify(text: str) -> str:
    """GitHub-ish heading slug; must match slugify() in RENDER_JS."""
    s = text.lower().strip()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"\s+", "-", s)
    s = re.sub(r"-+", "-", s)
    return s


def extract_toc(markdown_text: str):
    """Return [(level, text, slug)] for ATX headings, skipping fenced code."""
    toc = []
    in_fence = False
    for line in markdown_text.splitlines():
        if line.lstrip().startswith("```"):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        m = re.match(r"^(#{1,6})\s+(.*\S)\s*$", line)
        if m:
            text = m.group(2).strip().rstrip("#").strip()
            toc.append((len(m.group(1)), text, slugify(text)))
    return toc


def doc_title(markdown_text: str, fallback: str) -> str:
    for level, text, _slug in extract_toc(markdown_text):
        if level == 1:
            return text
    return fallback


# ---------------------------------------------------------------------------
# Mermaid diagram builders
# ---------------------------------------------------------------------------

def _mid(s: str) -> str:
    return "n_" + re.sub(r"\W", "_", s)


def _mlabel(s: str) -> str:
    return s.replace('"', "'")


def build_tree_mermaid(root_label: str, rels) -> str:
    """A top-down flowchart of the document tree (dirs + files)."""
    lines = ["graph TD"]
    root = "n_root"
    lines.append(f'{root}["📁 {_mlabel(root_label)}"]')
    seen = {root}
    edges = []
    for rel in rels:
        parts = Path(rel).parts
        parent, acc = root, ""
        for i, seg in enumerate(parts):
            acc = f"{acc}/{seg}" if acc else seg
            nid = _mid(acc)
            if nid not in seen:
                seen.add(nid)
                leaf = i == len(parts) - 1
                label = ("📄 " if leaf else "📁 ") + _mlabel(seg)
                lines.append(f'{nid}["{label}"]')
            edge = f"{parent} --> {nid}"
            if edge not in edges:
                edges.append(edge)
            parent = nid
    lines.extend(edges)
    return "\n".join(lines)


def build_overview_mermaid(nav) -> str:
    """Left-right map of the whole server: server -> projects -> branches."""
    lines = ["graph LR", 'srv(["📚 doc-server"])']
    for project in sorted(nav):
        pid = _mid("p/" + project)
        lines.append(f'{pid}["📦 {_mlabel(project)}"]')
        lines.append(f"srv --> {pid}")
        for branch in nav[project]:
            bid = _mid(f"b/{project}/{branch}")
            lines.append(f'{bid}["🌿 {_mlabel(branch)}"]')
            lines.append(f"{pid} --> {bid}")
    return "\n".join(lines)


def build_project_mermaid(project: str, branches) -> str:
    lines = ["graph LR", f'p(["📦 {_mlabel(project)}"])']
    for branch in branches:
        bid = _mid(f"b/{branch}")
        lines.append(f'{bid}["🌿 {_mlabel(branch)}"]')
        lines.append(f"p --> {bid}")
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# HTML shell + page builders
# ---------------------------------------------------------------------------

def render_sidebar(nav, active_key: str = "") -> str:
    active_project = active_key.split("/", 1)[0] if active_key else ""
    parts = [
        '<div class="brand"><a href="/index.html">📚 doc-server</a></div>',
        '<nav class="nav">',
    ]
    for project in sorted(nav):
        is_active_proj = project == active_project
        open_attr = " open" if is_active_proj else ""
        parts.append(f"<details{open_attr}>")
        parts.append(
            f'<summary><a href="/{project}/index.html">{escape(project)}</a></summary>'
        )
        parts.append("<ul>")
        for branch in nav[project]:
            key = f"{project}/{branch}"
            li_cls = ' class="active"' if key == active_key else ""
            parts.append(
                f'<li{li_cls}><a href="/{project}/{branch}/index.html">{escape(branch)}</a></li>'
            )
        parts.append("</ul></details>")
    if not nav:
        parts.append('<p class="empty">No projects yet.</p>')
    parts.append("</nav>")
    return "\n".join(parts)


def render_shell(title: str, sidebar_html: str, main_html: str,
                 head_extra: str = "", body_scripts: str = "") -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{escape(title)}</title>
{head_extra}
<style>
{SHELL_CSS}
</style>
</head>
<body>
<div class="layout">
<aside class="sidebar">
{sidebar_html}
</aside>
<main class="main">
{main_html}
</main>
</div>
{body_scripts}
</body>
</html>"""


def _mermaid_scripts(local: bool) -> str:
    mer = _asset(local, "mermaid.min.js", "mermaid")
    return (
        f'<script src="{mer}"></script>\n'
        '<script src="/_assets/landing.js"></script>'
    )


def render_doc_html(title: str, markdown_text: str, assets_local: bool,
                    back_href: str = "/index.html", sidebar_html: str = "") -> str:
    b64 = base64.b64encode(markdown_text.encode("utf-8")).decode("ascii")
    css = _asset(assets_local, "github-markdown.css", "css")
    js = _asset(assets_local, "marked.min.js", "js")
    mer = _asset(assets_local, "mermaid.min.js", "mermaid")
    head_extra = (
        f'<link rel="stylesheet" href="{css}">\n'
        "<style> .markdown-body { color: var(--text); } </style>"
    )
    main_html = (
        f'<div class="topbar"><a href="{escape(back_href)}">&larr; back to index</a></div>\n'
        '<article class="markdown-body" id="content">Loading&hellip;</article>\n'
        f'<script id="md-data" type="application/base64">{b64}</script>'
    )
    body_scripts = (
        f'<script src="{js}"></script>\n'
        f'<script src="{mer}"></script>\n'
        '<script src="/_assets/render.js"></script>'
    )
    return render_shell(title, sidebar_html, main_html, head_extra, body_scripts)


def _toc_list_html(base_href: str, toc) -> str:
    if not toc:
        return '<p class="empty">No headings.</p>'
    # Normalise indentation so the shallowest heading sits at the left margin.
    min_level = min(level for level, _t, _s in toc)
    items = []
    for level, text, slug in toc:
        indent = (level - min_level) * 14
        href = f"{base_href}#{slug}"
        items.append(
            f'<li style="margin-left:{indent}px">'
            f'<a href="{escape(href)}">{escape(text)}</a></li>'
        )
    return '<ul class="toc">\n' + "\n".join(items) + "\n</ul>"


def render_branch_index(project: str, branch: str, docs, nav,
                        assets_local: bool) -> str:
    """Landing page for one served branch.

    `docs` = [{flat, rel, title, toc}]. Because the source docs are plain
    markdown with no served HTML index of their own, we synthesise a structure
    diagram plus a per-document table-of-contents summary.
    """
    key = f"{project}/{branch}"
    crumbs = (
        f'<a href="/index.html">doc-server</a> / '
        f'<a href="/{project}/index.html">{escape(project)}</a> / '
        f"{escape(branch)}"
    )
    parts = [
        f'<div class="crumbs">{crumbs}</div>',
        f"<h1>{escape(project)} · {escape(branch)}</h1>",
    ]
    if not docs:
        parts.append('<p class="empty">No documents found for this branch.</p>')
        return render_shell(key, render_sidebar(nav, key), "\n".join(parts),
                            body_scripts=_mermaid_scripts(assets_local))

    rels = [d["rel"] for d in docs]
    parts.append("<h2>Structure</h2>")
    parts.append(
        '<div class="diagram"><pre class="mermaid">'
        + escape(build_tree_mermaid(branch, rels))
        + "</pre></div>"
    )

    parts.append("<h2>Documents</h2>")
    parts.append('<div class="cards">')
    for d in docs:
        doc_href = f"/{key}/{d['flat']}"
        parts.append('<section class="card">')
        parts.append(
            f'<h3><a href="{escape(doc_href)}">{escape(d["title"])}</a></h3>'
        )
        parts.append(f'<div class="path">{escape(d["rel"])}</div>')
        parts.append(_toc_list_html(doc_href, d["toc"]))
        parts.append("</section>")
    parts.append("</div>")
    return render_shell(key, render_sidebar(nav, key), "\n".join(parts),
                        body_scripts=_mermaid_scripts(assets_local))


def render_project_index(project: str, branches, nav, assets_local: bool) -> str:
    crumbs = f'<a href="/index.html">doc-server</a> / {escape(project)}'
    parts = [
        f'<div class="crumbs">{crumbs}</div>',
        f"<h1>{escape(project)}</h1>",
        "<h2>Branches</h2>",
    ]
    if branches:
        parts.append(
            '<div class="diagram"><pre class="mermaid">'
            + escape(build_project_mermaid(project, branches))
            + "</pre></div>"
        )
        parts.append('<div class="tiles">')
        for branch in branches:
            href = f"/{project}/{branch}/index.html"
            parts.append(
                f'<a class="tile" href="{escape(href)}">'
                f'<div class="name">🌿 {escape(branch)}</div>'
                f'<div class="meta">{escape(project)}/{escape(branch)}</div></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No branches yet.</p>')
    return render_shell(project, render_sidebar(nav, f"{project}/"),
                        "\n".join(parts), body_scripts=_mermaid_scripts(assets_local))


def render_root_index(nav, assets_local: bool) -> str:
    total_branches = sum(len(v) for v in nav.values())
    parts = [
        "<h1>📚 doc-server</h1>",
        '<p class="crumbs">A unified, live-rendered view of every project\'s '
        "plans, specs, and design docs &mdash; grouped by project and git branch.</p>",
        "<h2>How it works</h2>",
        '<div class="diagram"><pre class="mermaid">'
        + escape(_HOW_IT_WORKS_MERMAID)
        + "</pre></div>",
    ]
    parts.append("<h2>Projects</h2>")
    if nav:
        parts.append(
            '<div class="diagram"><pre class="mermaid">'
            + escape(build_overview_mermaid(nav))
            + "</pre></div>"
        )
        parts.append('<div class="tiles">')
        for project in sorted(nav):
            n = len(nav[project])
            parts.append(
                f'<a class="tile" href="/{project}/index.html">'
                f'<div class="name">📦 {escape(project)}</div>'
                f'<div class="meta">{n} branch{"es" if n != 1 else ""}</div></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No projects registered yet. Run '
                     "<code>serve.py</code> from a project with docs.</p>")
    return render_shell("doc-server", render_sidebar(nav, ""),
                        "\n".join(parts), body_scripts=_mermaid_scripts(assets_local))


_HOW_IT_WORKS_MERMAID = """\
graph LR
  A["📁 project docs/**/*.md"] --> B["serve.py or SessionStart hook"]
  B --> C["resolve identity: project + git branch"]
  C --> D["registry.json"]
  D --> E["sync: markdown to HTML"]
  E --> F["~/.claude/doc-server/ project/branch/"]
  F --> G(["🌐 localhost viewer"])
  H["page request"] -. live re-sync .-> E"""


# ---------------------------------------------------------------------------
# Filesystem sync
# ---------------------------------------------------------------------------

def _flatten(rel: Path) -> str:
    return str(rel.with_suffix("")).replace(os.sep, "__") + ".html"


def _atomic_write_text(dest_file: Path, content: str) -> None:
    """Write content to dest_file atomically via a same-dir temp + os.replace."""
    tmp = dest_file.with_suffix(".tmp")
    tmp.write_text(content, encoding="utf-8")
    os.replace(tmp, dest_file)


def build_nav(reg) -> dict:
    """project -> sorted list of branches, derived from registry keys."""
    nav: dict = {}
    for key in reg:
        project, _, branch = key.partition("/")
        if not branch:
            continue
        nav.setdefault(project, [])
        if branch not in nav[project]:
            nav[project].append(branch)
    for project in nav:
        nav[project].sort()
    return nav


def sync_target(home: Path, key: str, source_root: str, glob: str, nav=None):
    project, _, branch = key.partition("/")
    if nav is None:
        nav = build_nav(state.read_registry())
        nav.setdefault(project, [])
        if branch and branch not in nav[project]:
            nav[project].append(branch)
            nav[project].sort()
    sidebar = render_sidebar(nav, key)

    dest = home / key
    dest.mkdir(parents=True, exist_ok=True)
    back_href = f"/{key}/index.html"

    local = assets_available(home)
    names = []
    docs_meta = []
    current_flats: set = set()
    for md in find_docs(source_root, glob):
        rel = md.relative_to(source_root)
        flat = _flatten(rel)
        current_flats.add(flat)
        text = md.read_text(encoding="utf-8", errors="replace")
        _atomic_write_text(
            dest / flat,
            render_doc_html(str(rel), text, local, back_href=back_href, sidebar_html=sidebar),
        )
        names.append((flat, str(rel)))
        docs_meta.append({
            "flat": flat,
            "rel": str(rel),
            "title": doc_title(text, str(rel)),
            "toc": extract_toc(text),
        })

    _atomic_write_text(
        dest / "index.html",
        render_branch_index(project, branch, docs_meta, nav, local),
    )
    current_flats.add("index.html")

    # Remove stale HTML files AFTER writing new content.
    for old in dest.glob("*.html"):
        if old.name not in current_flats:
            old.unlink()

    return names


def write_project_index(home: Path, project: str, nav=None) -> None:
    if nav is None:
        nav = build_nav(state.read_registry())
    branches = nav.get(project, [])
    base = home / project
    base.mkdir(parents=True, exist_ok=True)
    local = assets_available(home)
    _atomic_write_text(
        base / "index.html",
        render_project_index(project, branches, nav, local),
    )


def write_root_index(home: Path, nav=None) -> None:
    if nav is None:
        nav = build_nav(state.read_registry())
    local = assets_available(home)
    _atomic_write_text(home / "index.html", render_root_index(nav, local))


def sync_all(home: Path) -> None:
    # Ensure our own assets exist even if ensure_assets wasn't called (daemon path).
    assets_dir = home / "_assets"
    if assets_dir.is_dir():
        _atomic_write_text(assets_dir / "render.js", RENDER_JS)
        _atomic_write_text(assets_dir / "landing.js", LANDING_JS)
    with _SYNC_LOCK:
        reg = state.read_registry()
        nav = build_nav(reg)
        for key, info in reg.items():
            sync_target(home, key, info["source_root"], info["glob"], nav=nav)
        for project in sorted(nav):
            write_project_index(home, project, nav=nav)
        write_root_index(home, nav=nav)
