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
_MERMAID_CONFIG_JS = """\
  function mermaidConfig(dark) {
    return {
      startOnLoad: false,
      theme: 'base',
      themeVariables: {
        fontFamily: "ui-sans-serif, -apple-system, 'Segoe UI', system-ui, sans-serif",
        primaryColor: dark ? '#1b1b2c' : '#eef0ff',
        primaryBorderColor: dark ? '#322f55' : '#e0e1fb',
        primaryTextColor: dark ? '#f3f3f5' : '#18181b',
        lineColor: dark ? '#6e6e77' : '#b9b9c2',
        secondaryColor: dark ? '#101014' : '#ffffff',
        tertiaryColor: dark ? '#101014' : '#fafafa'
      }
    };
  }
"""

RENDER_JS = """\
(function () {
""" + _MERMAID_CONFIG_JS + """\
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
      mermaid.initialize(mermaidConfig(dark));
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
""" + _MERMAID_CONFIG_JS + """\
  function init() {
    if (!window.mermaid) return;
    try {
      var dark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
      mermaid.initialize(mermaidConfig(dark));
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
# main column with a sticky topbar. Inline styles are allowed by the CSP
# (style-src 'unsafe-inline'); the design system below is driven by CSS custom
# properties so light/dark stay in sync via a single prefers-color-scheme switch.
#
# Type: the design calls for Geist, but the strict CSP (font-src 'self'
# cdn.jsdelivr.net) blocks Google Fonts, so we use a Geist-leaning system stack
# that degrades cleanly — the same fallback the design itself declares.
SHELL_CSS = """\
:root {
  --font: 'Geist', ui-sans-serif, -apple-system, BlinkMacSystemFont, 'Segoe UI', system-ui, sans-serif;
  --mono: 'Geist Mono', ui-monospace, SFMono-Regular, 'SF Mono', Menlo, Consolas, monospace;
  --bg: #fafafa; --page: #ffffff; --panel: #ffffff; --canvas: #f6f6f7;
  --border: #ececee; --border-strong: #e2e2e5;
  --text: #18181b; --secondary: #51515a; --muted: #8c8c94; --faint: #c2c2c9;
  --accent: #4f46e5; --accent-soft: #eef0ff; --accent-border: #e0e1fb; --accent-press: #4338ca;
  --chip-bg: #f3f3f5; --chip-border: #e6e6ea;
  --success: #16a34a; --success-soft: #ecfdf3; --success-border: #c9efd6;
  --warning: #c2410c;
  --shadow-sm: 0 1px 2px rgba(17,17,20,.05);
  --shadow-md: 0 6px 22px rgba(17,17,20,.10);
  --dots: radial-gradient(#e9e9ec 1px, transparent 1px);
}
@media (prefers-color-scheme: dark) {
  :root {
    --bg: #0a0a0c; --page: #0d0d10; --panel: #101014; --canvas: #050507;
    --border: #232327; --border-strong: #2e2e33;
    --text: #f3f3f5; --secondary: #a9a9b2; --muted: #6e6e77; --faint: #3a3a40;
    --accent: #818cf8; --accent-soft: #1b1b2c; --accent-border: #322f55; --accent-press: #6e78e0;
    --chip-bg: #17171b; --chip-border: #2a2a30;
    --success: #4ade80; --success-soft: #0f2419; --success-border: #1c3a2a;
    --warning: #fb923c;
    --shadow-sm: none; --shadow-md: 0 6px 22px rgba(0,0,0,.45);
    --dots: radial-gradient(#1a1a1f 1px, transparent 1px);
  }
}
* { box-sizing: border-box; }
body {
  margin: 0; color: var(--text); background: var(--page);
  font-family: var(--font); -webkit-font-smoothing: antialiased;
  text-rendering: optimizeLegibility;
}
svg { display: block; }
a { color: var(--accent); }

.layout { display: flex; min-height: 100vh; }

/* ---- Sidebar ------------------------------------------------------------ */
.sidebar {
  width: 256px; flex: 0 0 256px; background: var(--bg);
  border-right: 1px solid var(--border);
  position: sticky; top: 0; align-self: flex-start; height: 100vh;
  display: flex; flex-direction: column; overflow: hidden;
}
.sb-brand { display: flex; align-items: center; gap: 9px; padding: 15px 14px 13px; }
.sb-logo {
  width: 27px; height: 27px; border-radius: 8px; background: var(--accent);
  color: #fff; display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
}
.sb-brand .name { font-size: 14.5px; font-weight: 650; letter-spacing: -.01em; color: var(--text); }
.sb-search {
  margin: 0 12px 12px; height: 34px; border-radius: 9px; border: 1px solid var(--border);
  background: var(--panel); display: flex; align-items: center; gap: 8px; padding: 0 10px;
  color: var(--muted); font-size: 12.5px;
}
.sb-search .grow { flex: 1; }
.sb-search kbd {
  font-family: var(--mono); font-size: 10.5px; color: var(--muted);
  border: 1px solid var(--border); border-radius: 5px; padding: 1px 5px;
}
.sb-scroll { flex: 1; overflow-y: auto; padding: 2px 8px; }
.sb-label {
  font-size: 10.5px; font-weight: 600; letter-spacing: .07em; color: var(--muted);
  padding: 6px 8px 7px;
}
.nav details { margin-bottom: 2px; }
.nav summary {
  list-style: none; cursor: pointer; display: flex; align-items: center; gap: 7px;
  padding: 6px 8px; border-radius: 8px; font-size: 13.5px; font-weight: 600; color: var(--text);
}
.nav summary::-webkit-details-marker { display: none; }
.nav summary .chev { color: var(--muted); display: flex; transition: transform .15s ease; flex: 0 0 auto; }
.nav details[open] > summary .chev { transform: rotate(90deg); }
.nav summary .ic { color: var(--muted); display: flex; flex: 0 0 auto; }
.nav summary a { color: inherit; text-decoration: none; flex: 1; min-width: 0; }
.nav summary:hover { background: var(--accent-soft); }
.nav summary .count {
  font-family: var(--mono); font-size: 10.5px; font-weight: 500; color: var(--muted);
  background: var(--chip-bg); border-radius: 5px; padding: 1px 6px;
}
.nav details.active > summary { background: var(--accent-soft); color: var(--accent); }
.nav details.active > summary .ic, .nav details.active > summary .chev { color: var(--accent); }
.branches { margin: 3px 0 6px 11px; padding-left: 10px; border-left: 1px solid var(--border); }
.chip {
  display: flex; align-items: flex-start; gap: 7px; padding: 7px 9px; border-radius: 8px;
  margin-top: 3px; text-decoration: none; border: 1px solid var(--chip-border);
  background: var(--chip-bg);
}
.chip .ic { color: var(--muted); display: flex; flex: 0 0 auto; margin-top: 1px; }
.chip .bname {
  font-family: var(--mono); font-size: 11.5px; line-height: 1.4; word-break: break-all;
  font-weight: 500; color: var(--secondary);
}
.chip:hover { border-color: var(--accent-border); }
.chip.active { border-color: var(--accent-border); background: var(--accent-soft); }
.chip.active .ic, .chip.active .bname { color: var(--accent); }
.sb-foot {
  border-top: 1px solid var(--border); padding: 11px 14px;
  display: flex; align-items: center; gap: 8px;
}
.sb-foot .dot { width: 7px; height: 7px; border-radius: 50%; background: var(--success); flex: 0 0 auto; }
.sb-foot .host { font-family: var(--mono); font-size: 11px; color: var(--muted); }
.sb-empty { color: var(--muted); font-size: 12.5px; padding: 8px; }

/* ---- Main column + topbar ----------------------------------------------- */
.main { flex: 1 1 auto; min-width: 0; display: flex; flex-direction: column; background: var(--page); }
.topbar {
  height: 53px; flex: 0 0 53px; border-bottom: 1px solid var(--border);
  display: flex; align-items: center; gap: 12px; padding: 0 22px;
  position: sticky; top: 0; background: var(--page); z-index: 5;
}
.topbar .spacer { flex: 1; }
.crumbs { display: flex; align-items: center; gap: 7px; font-size: 13px; color: var(--muted); min-width: 0; }
.crumbs a { color: var(--secondary); text-decoration: none; font-weight: 500; white-space: nowrap; }
.crumbs a:hover { color: var(--accent); }
.crumbs .sep { color: var(--faint); }
.crumbs .here { color: var(--text); font-weight: 600; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.crumbs .mono { font-family: var(--mono); font-size: 12px; color: var(--accent); }
.btn {
  display: inline-flex; align-items: center; gap: 7px; text-decoration: none;
  font-size: 13px; font-weight: 550; padding: 7px 13px; border-radius: 8px;
  border: 1px solid var(--border); color: var(--secondary); background: var(--panel);
}
.btn:hover { border-color: var(--accent-border); color: var(--accent); }
.btn.primary { background: var(--accent); color: #fff; border-color: var(--accent); }
.btn.primary:hover { background: var(--accent-press); color: #fff; }
.content { flex: 1; min-width: 0; padding: 32px 38px; max-width: 1180px; }

/* ---- Headings / hero / sections ----------------------------------------- */
.hero { display: flex; align-items: flex-start; gap: 15px; margin-bottom: 18px; }
.hero-icon {
  width: 42px; height: 42px; border-radius: 12px; background: var(--accent); color: #fff;
  display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
}
.hero h1 { font-size: 27px; font-weight: 680; letter-spacing: -.02em; color: var(--text); line-height: 1.1; margin: 0; }
.lede { font-size: 14.5px; color: var(--secondary); margin: 6px 0 0; max-width: 640px; line-height: 1.5; }
.content > h1 { font-size: 24px; font-weight: 650; letter-spacing: -.015em; margin: 0 0 6px; color: var(--text); }
.section-label { display: flex; align-items: center; gap: 12px; margin: 30px 0 16px; }
.section-label .t { font-size: 12px; font-weight: 600; letter-spacing: .08em; color: var(--muted); }
.section-label .n { font-family: var(--mono); font-size: 11px; color: var(--faint); }
.section-label .rule { flex: 1; height: 1px; background: var(--border); }
.badges { display: flex; flex-wrap: wrap; gap: 9px; margin-bottom: 6px; }
.badge {
  font-size: 12px; color: var(--secondary); background: var(--canvas);
  border: 1px solid var(--border); border-radius: 7px; padding: 4px 10px;
}
.badge.ok {
  display: flex; align-items: center; gap: 6px; color: var(--success);
  background: var(--success-soft); border-color: var(--success-border);
}
.badge.ok i { width: 6px; height: 6px; border-radius: 50%; background: var(--success); }
.empty { color: var(--muted); font-style: italic; }

/* ---- Diagram container --------------------------------------------------- */
.diagram {
  position: relative; background: var(--canvas); border: 1px solid var(--border);
  border-radius: 14px; padding: 22px; overflow-x: auto;
}
.diagram.dotted { background-color: var(--canvas); background-image: var(--dots); background-size: 18px 18px; }
.diagram .mermaid { display: flex; justify-content: center; }
.diagram-cap { font-size: 11.5px; color: var(--muted); margin: 8px 2px 0; }

/* ---- Project / branch tiles --------------------------------------------- */
.tiles { display: grid; gap: 16px; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); }
.tile {
  display: block; text-decoration: none; color: inherit; background: var(--panel);
  border: 1px solid var(--border); border-radius: 14px; padding: 17px 18px; box-shadow: var(--shadow-sm);
}
.tile:hover { border-color: var(--accent-border); }
.tile-head { display: flex; align-items: center; gap: 11px; margin-bottom: 14px; }
.tile-ic {
  width: 34px; height: 34px; border-radius: 9px; background: var(--accent-soft); color: var(--accent);
  display: flex; align-items: center; justify-content: center; flex: 0 0 auto;
}
.tile .name { font-size: 16.5px; font-weight: 650; letter-spacing: -.01em; color: var(--text); }
.tile .meta { font-size: 12px; color: var(--muted); margin-top: 2px; }
.tile .grow { flex: 1; }
.tile .go { color: var(--faint); display: flex; }
.tile-branch {
  display: flex; align-items: center; gap: 7px; padding: 8px 10px; border-radius: 8px;
  background: var(--canvas); border: 1px solid var(--border);
}
.tile-branch .ic { color: var(--muted); display: flex; flex: 0 0 auto; }
.tile-branch .bn {
  font-family: var(--mono); font-size: 11px; color: var(--secondary); flex: 1;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.tile-branch .tag {
  font-size: 10.5px; color: var(--accent); background: var(--accent-soft);
  border-radius: 5px; padding: 1px 7px; font-weight: 500;
}
.tile-foot { display: flex; align-items: center; justify-content: space-between; margin-top: 13px; }
.tile-foot .upd { font-size: 11.5px; color: var(--faint); }
.tile-foot .view { display: flex; align-items: center; gap: 5px; font-size: 12.5px; color: var(--accent); font-weight: 600; }

/* ---- Document summary cards (branch index) ------------------------------ */
.cards { display: grid; gap: 18px; grid-template-columns: repeat(auto-fill, minmax(330px, 1fr)); }
.card {
  display: flex; flex-direction: column; text-decoration: none; color: inherit;
  background: var(--panel); border: 1px solid var(--border); border-radius: 14px;
  padding: 18px 18px 16px; box-shadow: var(--shadow-sm);
}
.card:hover { border-color: var(--accent-border); }
.card-head { display: flex; align-items: center; gap: 9px; margin-bottom: 11px; }
.card-ic { width: 30px; height: 30px; border-radius: 8px; display: flex; align-items: center; justify-content: center; flex: 0 0 auto; }
.card .tag { font-family: var(--mono); font-size: 10px; font-weight: 600; letter-spacing: .06em; border-radius: 5px; padding: 2px 7px; }
.tag-accent { color: var(--accent); background: var(--accent-soft); }
.tag-accent.card-ic { color: var(--accent); background: var(--accent-soft); }
.tag-success { color: var(--success); background: var(--success-soft); }
.tag-success.card-ic { color: var(--success); background: var(--success-soft); }
.card .sections { font-size: 11.5px; color: var(--muted); }
.card .title { font-size: 15.5px; font-weight: 650; line-height: 1.3; letter-spacing: -.01em; color: var(--text); }
.card .path { font-family: var(--mono); font-size: 11px; color: var(--muted); margin-top: 5px; word-break: break-all; line-height: 1.45; }
.card .div { height: 1px; background: var(--border); margin: 14px 0 11px; }
.card .otp { font-size: 10.5px; font-weight: 600; letter-spacing: .06em; color: var(--muted); margin-bottom: 6px; }
.toc { list-style: none; margin: 0; padding: 0; }
.toc li { display: flex; align-items: center; gap: 7px; padding: 4px 0; }
.toc .hash { font-family: var(--mono); color: var(--faint); font-size: 11px; }
.toc a { font-size: 12.5px; color: var(--secondary); text-decoration: none; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.toc a:hover { color: var(--accent); }
.toc .more { font-size: 12px; color: var(--muted); padding: 5px 0 0 16px; }
.card .open { display: flex; align-items: center; gap: 6px; color: var(--accent); font-size: 13px; font-weight: 600; margin-top: auto; padding-top: 13px; }
.card .open .div2 { display: none; }

/* ---- Document reader ----------------------------------------------------- */
.content.doc { display: grid; grid-template-columns: minmax(0, 1fr) 200px; gap: 44px; align-items: start; max-width: 1180px; }
.markdown-body { min-width: 0; max-width: 768px; color: var(--text); }
.onthispage { position: sticky; top: 85px; align-self: start; }
.onthispage .otp { font-size: 10.5px; font-weight: 600; letter-spacing: .06em; color: var(--muted); margin-bottom: 8px; }
.onthispage a {
  display: block; font-size: 12.5px; color: var(--secondary); text-decoration: none;
  padding: 3px 0 3px 11px; border-left: 2px solid transparent; line-height: 1.4;
}
.onthispage a:hover { color: var(--accent); border-left-color: var(--accent-border); }
@media (max-width: 960px) {
  .content.doc { grid-template-columns: minmax(0, 1fr); }
  .onthispage { display: none; }
}
@media (max-width: 720px) {
  .sidebar { display: none; }
  .content { padding: 24px 20px; }
}
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
# Inline-SVG icons (no external requests; safe under a strict CSP)
# ---------------------------------------------------------------------------

_ICON_PATHS = {
    "layers": '<polygon points="12 2 2 7 12 12 22 7 12 2"></polygon>'
              '<polyline points="2 17 12 22 22 17"></polyline>'
              '<polyline points="2 12 12 17 22 12"></polyline>',
    "package": '<path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"></path>'
               '<polyline points="3.27 6.96 12 12.01 20.73 6.96"></polyline>'
               '<line x1="12" y1="22.08" x2="12" y2="12"></line>',
    "branch": '<line x1="6" y1="3" x2="6" y2="15"></line>'
              '<circle cx="18" cy="6" r="3"></circle><circle cx="6" cy="18" r="3"></circle>'
              '<path d="M18 9a9 9 0 0 1-9 9"></path>',
    "file": '<path d="M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z"></path>'
            '<polyline points="14 2 14 8 20 8"></polyline>',
    "search": '<circle cx="11" cy="11" r="8"></circle>'
              '<line x1="21" y1="21" x2="16.65" y2="16.65"></line>',
    "arrow": '<line x1="5" y1="12" x2="19" y2="12"></line>'
             '<polyline points="12 5 19 12 12 19"></polyline>',
    "arrow-left": '<line x1="19" y1="12" x2="5" y2="12"></line>'
                  '<polyline points="12 19 5 12 12 5"></polyline>',
    "home": '<path d="M3 9l9-7 9 7v11a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2z"></path>'
            '<polyline points="9 22 9 12 15 12 15 22"></polyline>',
    "chevron": '<polyline points="9 18 15 12 9 6"></polyline>',
    "sitemap": '<rect x="3" y="3" width="18" height="18" rx="2"></rect>'
               '<line x1="9" y1="3" x2="9" y2="21"></line>',
}


def _icon(name: str, size: int = 15) -> str:
    return (
        f'<svg width="{size}" height="{size}" viewBox="0 0 24 24" fill="none" '
        'stroke="currentColor" stroke-width="2" stroke-linecap="round" '
        f'stroke-linejoin="round">{_ICON_PATHS[name]}</svg>'
    )


def doc_tag(rel: str) -> tuple:
    """Classify a doc by its path → (LABEL, css-kind) for the summary card tag."""
    low = rel.lower()
    if "/specs/" in low or "spec" in low or "design" in low:
        return ("SPEC", "success")
    if "/plans/" in low or "plan" in low:
        return ("PLAN", "accent")
    return ("DOC", "accent")


# ---------------------------------------------------------------------------
# HTML shell + page builders
# ---------------------------------------------------------------------------

def render_sidebar(nav, active_key: str = "") -> str:
    active_project = active_key.split("/", 1)[0] if active_key else ""
    parts = [
        '<div class="sb-brand">'
        f'<span class="sb-logo">{_icon("layers", 15)}</span>'
        '<a class="name" href="/index.html" style="text-decoration:none;color:inherit">doc-server</a>'
        '</div>',
        '<div class="sb-search">'
        f'{_icon("search", 14)}<span class="grow">Search projects…</span><kbd>⌘K</kbd>'
        '</div>',
        '<div class="sb-scroll">',
        '<div class="sb-label">PROJECTS</div>',
        '<nav class="nav">',
    ]
    for project in sorted(nav):
        is_active_proj = project == active_project
        det_cls = " class=\"active\"" if is_active_proj else ""
        open_attr = " open" if is_active_proj else ""
        n = len(nav[project])
        parts.append(f"<details{det_cls}{open_attr}>")
        parts.append(
            "<summary>"
            f'<span class="chev">{_icon("chevron", 12)}</span>'
            f'<span class="ic">{_icon("package", 14)}</span>'
            f'<a href="/{project}/index.html">{escape(project)}</a>'
            f'<span class="count">{n}</span>'
            "</summary>"
        )
        parts.append('<div class="branches">')
        for branch in nav[project]:
            key = f"{project}/{branch}"
            chip_cls = "chip active" if key == active_key else "chip"
            parts.append(
                f'<a class="{chip_cls}" href="/{project}/{branch}/index.html">'
                f'<span class="ic">{_icon("branch", 13)}</span>'
                f'<span class="bname">{escape(branch)}</span></a>'
            )
        parts.append("</div></details>")
    if not nav:
        parts.append('<div class="sb-empty">No projects yet.</div>')
    parts.append("</nav>")        # close .nav
    parts.append("</div>")        # close .sb-scroll
    parts.append(
        '<div class="sb-foot">'
        '<span class="dot"></span><span class="host">localhost</span>'
        '</div>'
    )
    return "\n".join(parts)


def _topbar(crumbs_html: str, actions_html: str = "") -> str:
    return (
        '<header class="topbar">'
        f'<div class="crumbs">{crumbs_html}</div>'
        '<span class="spacer"></span>'
        f'{actions_html}'
        '</header>'
    )


def render_shell(title: str, sidebar_html: str, main_html: str,
                 head_extra: str = "", body_scripts: str = "",
                 topbar_html: str = "", content_class: str = "content") -> str:
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
<div class="main">
{topbar_html}
<main class="{content_class}">
{main_html}
</main>
</div>
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


def _doc_crumbs(back_href: str, here: str) -> str:
    """Build a project / branch / doc breadcrumb from an index back-href.

    back_href is `/<project>/<branch>/index.html`; the branch may itself contain
    slashes (e.g. `claude/doc-server-routing-ui-osov2g`), so everything between
    the project and the trailing index.html is the branch.
    """
    segs = [s for s in back_href.split("/") if s and s != "index.html"]
    parts = [f'<a href="/index.html">{_icon("home", 14)}</a>']
    if len(segs) >= 1:
        project = segs[0]
        parts.append('<span class="sep">/</span>')
        parts.append(f'<a href="/{project}/index.html">{escape(project)}</a>')
    if len(segs) >= 2:
        branch = "/".join(segs[1:])
        parts.append('<span class="sep">/</span>')
        parts.append(
            f'<a class="mono" href="{escape(back_href)}">{escape(branch)}</a>'
        )
    parts.append('<span class="sep">/</span>')
    parts.append(f'<span class="here">{escape(here)}</span>')
    return "".join(parts)


def _onthispage_html(markdown_text: str) -> str:
    toc = [t for t in extract_toc(markdown_text) if t[0] >= 2]
    if not toc:
        return ""
    rows = ['<div class="otp">ON THIS PAGE</div>']
    min_level = min(level for level, _t, _s in toc)
    for level, text, slug in toc:
        indent = (level - min_level) * 11
        rows.append(
            f'<a href="#{escape(slug)}" style="padding-left:{11 + indent}px">'
            f'{escape(text)}</a>'
        )
    return '<aside class="onthispage">' + "\n".join(rows) + "</aside>"


def render_doc_html(title: str, markdown_text: str, assets_local: bool,
                    back_href: str = "/index.html", sidebar_html: str = "") -> str:
    b64 = base64.b64encode(markdown_text.encode("utf-8")).decode("ascii")
    css = _asset(assets_local, "github-markdown.css", "css")
    js = _asset(assets_local, "marked.min.js", "js")
    mer = _asset(assets_local, "mermaid.min.js", "mermaid")
    head_extra = (
        f'<link rel="stylesheet" href="{css}">\n'
        "<style>\n"
        "  .markdown-body { color: var(--text); background: transparent;\n"
        "    font-family: var(--font); font-size: 15px; }\n"
        "  .markdown-body pre, .markdown-body code { font-family: var(--mono); }\n"
        "</style>"
    )
    here = doc_title(markdown_text, title)
    crumbs = _doc_crumbs(back_href, here)
    actions = f'<a class="btn" href="{escape(back_href)}">{_icon("arrow-left", 14)}Back to branch</a>'
    topbar = _topbar(crumbs, actions)
    main_html = (
        '<article class="markdown-body" id="content">Loading&hellip;</article>\n'
        + _onthispage_html(markdown_text) + "\n"
        + f'<script id="md-data" type="application/base64">{b64}</script>'
    )
    body_scripts = (
        f'<script src="{js}"></script>\n'
        f'<script src="{mer}"></script>\n'
        '<script src="/_assets/render.js"></script>'
    )
    return render_shell(title, sidebar_html, main_html, head_extra, body_scripts,
                        topbar_html=topbar, content_class="content doc")


def _toc_list_html(base_href: str, toc, cap: int = 9) -> str:
    """Compact 'On this page' list for a document summary card."""
    if not toc:
        return '<p class="empty">No headings.</p>'
    shown = toc[:cap]
    items = []
    for _level, text, slug in shown:
        href = f"{base_href}#{slug}"
        items.append(
            '<li><span class="hash">#</span>'
            f'<a href="{escape(href)}">{escape(text)}</a></li>'
        )
    html = '<ul class="toc">\n' + "\n".join(items) + "\n</ul>"
    if len(toc) > cap:
        html += f'<div class="more">+ {len(toc) - cap} more headings</div>'
    return html


def render_branch_index(project: str, branch: str, docs, nav,
                        assets_local: bool) -> str:
    """Landing page for one served branch.

    `docs` = [{flat, rel, title, toc}]. Because the source docs are plain
    markdown with no served HTML index of their own, we synthesise a structure
    diagram plus a per-document table-of-contents summary.
    """
    key = f"{project}/{branch}"
    crumbs = (
        f'<a href="/index.html">{_icon("home", 14)}</a>'
        '<span class="sep">/</span>'
        f'<a href="/{project}/index.html">{escape(project)}</a>'
        '<span class="sep">/</span>'
        f'<span class="here">{escape(branch)}</span>'
    )
    topbar = _topbar(crumbs)
    n = len(docs)
    parts = [
        '<div class="hero">'
        f'<span class="hero-icon">{_icon("branch", 22)}</span>'
        '<div>'
        f'<h1>{escape(branch)}</h1>'
        f'<p class="lede">Documents on <strong>{escape(project)}</strong> · '
        'structure map and per-document table of contents.</p>'
        '</div></div>',
        '<div class="badges">'
        f'<span class="badge">{n} document{"s" if n != 1 else ""}</span>'
        '<span class="badge ok"><i></i>live</span>'
        '</div>',
    ]
    if not docs:
        parts.append('<p class="empty">No documents found for this branch.</p>')
        return render_shell(key, render_sidebar(nav, key), "\n".join(parts),
                            body_scripts=_mermaid_scripts(assets_local),
                            topbar_html=topbar)

    rels = [d["rel"] for d in docs]
    parts.append(
        '<div class="section-label"><span class="t">STRUCTURE</span>'
        '<span class="rule"></span></div>'
    )
    parts.append(
        '<div class="diagram dotted"><pre class="mermaid">'
        + escape(build_tree_mermaid(branch, rels))
        + "</pre></div>"
        '<div class="diagram-cap">Auto-generated from the docs in this branch · zoom to inspect</div>'
    )

    parts.append(
        '<div class="section-label"><span class="t">DOCUMENTS</span>'
        f'<span class="n">{n}</span><span class="rule"></span></div>'
    )
    parts.append('<div class="cards">')
    for d in docs:
        doc_href = f"/{key}/{d['flat']}"
        label, kind = doc_tag(d["rel"])
        sections = len(d["toc"])
        parts.append(f'<a class="card" href="{escape(doc_href)}">')
        parts.append(
            '<div class="card-head">'
            f'<span class="card-ic tag-{kind}">{_icon("file", 15)}</span>'
            f'<span class="tag tag-{kind}">{label}</span>'
            '<span class="grow" style="flex:1"></span>'
            f'<span class="sections">{sections} section{"s" if sections != 1 else ""}</span>'
            '</div>'
        )
        parts.append(f'<div class="title">{escape(d["title"])}</div>')
        parts.append(f'<div class="path">{escape(d["rel"])}</div>')
        parts.append('<div class="div"></div>')
        parts.append('<div class="otp">ON THIS PAGE</div>')
        parts.append(_toc_list_html(doc_href, d["toc"]))
        parts.append(
            f'<div class="open">Open document {_icon("arrow", 14)}</div>'
        )
        parts.append("</a>")
    parts.append("</div>")
    return render_shell(key, render_sidebar(nav, key), "\n".join(parts),
                        body_scripts=_mermaid_scripts(assets_local),
                        topbar_html=topbar)


def render_project_index(project: str, branches, nav, assets_local: bool) -> str:
    crumbs = (
        f'<a href="/index.html">{_icon("home", 14)}</a>'
        '<span class="sep">/</span>'
        f'<span class="here">{escape(project)}</span>'
    )
    topbar = _topbar(crumbs)
    n = len(branches)
    parts = [
        '<div class="hero">'
        f'<span class="hero-icon">{_icon("package", 22)}</span>'
        '<div>'
        f'<h1>{escape(project)}</h1>'
        f'<p class="lede">{n} branch{"es" if n != 1 else ""} with served '
        'documentation. Pick a branch to view its docs.</p>'
        '</div></div>',
    ]
    if branches:
        parts.append(
            '<div class="section-label"><span class="t">BRANCH MAP</span>'
            '<span class="rule"></span></div>'
        )
        parts.append(
            '<div class="diagram dotted"><pre class="mermaid">'
            + escape(build_project_mermaid(project, branches))
            + "</pre></div>"
        )
        parts.append(
            '<div class="section-label"><span class="t">BRANCHES</span>'
            f'<span class="n">{n}</span><span class="rule"></span></div>'
        )
        parts.append('<div class="tiles">')
        for branch in branches:
            href = f"/{project}/{branch}/index.html"
            parts.append(
                f'<a class="tile" href="{escape(href)}">'
                '<div class="tile-head">'
                f'<span class="tile-ic">{_icon("branch", 17)}</span>'
                f'<div class="grow"><div class="name">{escape(branch)}</div>'
                f'<div class="meta">{escape(project)}/{escape(branch)}</div></div>'
                f'<span class="go">{_icon("chevron", 17)}</span>'
                '</div>'
                '<div class="tile-foot">'
                '<span class="upd">View documents</span>'
                f'<span class="view">Open {_icon("arrow", 13)}</span>'
                '</div></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No branches yet.</p>')
    return render_shell(project, render_sidebar(nav, f"{project}/"),
                        "\n".join(parts), body_scripts=_mermaid_scripts(assets_local),
                        topbar_html=topbar)


def render_root_index(nav, assets_local: bool) -> str:
    n_projects = len(nav)
    total_branches = sum(len(v) for v in nav.values())
    crumbs = (
        f'<a href="/index.html">{_icon("home", 14)}</a>'
        '<span class="sep">/</span>'
        '<span class="here">overview</span>'
    )
    topbar = _topbar(crumbs)
    parts = [
        '<div class="hero">'
        f'<span class="hero-icon">{_icon("layers", 23)}</span>'
        '<div>'
        '<h1>doc-server</h1>'
        '<p class="lede">A unified, live-rendered view of every project\'s plans, '
        'specs, and design docs &mdash; grouped by project and git branch.</p>'
        '</div></div>',
        '<div class="badges">'
        f'<span class="badge">{n_projects} project{"s" if n_projects != 1 else ""}</span>'
        f'<span class="badge">{total_branches} branch{"es" if total_branches != 1 else ""}</span>'
        '<span class="badge ok"><i></i>live</span>'
        '</div>',
        '<div class="section-label"><span class="t">HOW IT WORKS</span>'
        '<span class="rule"></span></div>',
        '<div class="diagram dotted"><pre class="mermaid">'
        + escape(_HOW_IT_WORKS_MERMAID)
        + "</pre></div>"
        '<div class="diagram-cap">Live re-sync runs on every page request — the '
        'viewer always reflects the latest markdown.</div>',
    ]
    if nav:
        parts.append(
            '<div class="section-label"><span class="t">PROJECTS</span>'
            f'<span class="n">{n_projects}</span><span class="rule"></span></div>'
        )
        parts.append('<div class="tiles">')
        for project in sorted(nav):
            n = len(nav[project])
            parts.append(
                f'<a class="tile" href="/{project}/index.html">'
                '<div class="tile-head">'
                f'<span class="tile-ic">{_icon("package", 17)}</span>'
                f'<div class="grow"><div class="name">{escape(project)}</div>'
                f'<div class="meta">{n} branch{"es" if n != 1 else ""}</div></div>'
                f'<span class="go">{_icon("chevron", 17)}</span>'
                '</div>'
                '<div class="tile-foot">'
                '<span class="upd">Open project</span>'
                f'<span class="view">View {_icon("arrow", 13)}</span>'
                '</div></a>'
            )
        parts.append("</div>")
    else:
        parts.append('<p class="empty">No projects registered yet. Run '
                     "<code>serve.py</code> from a project with docs.</p>")
    return render_shell("doc-server", render_sidebar(nav, ""),
                        "\n".join(parts), body_scripts=_mermaid_scripts(assets_local),
                        topbar_html=topbar)


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
