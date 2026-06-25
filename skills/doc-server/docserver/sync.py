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
