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

    def test_render_doc_uses_external_render_js_not_inline(self):
        html = sync.render_doc_html("a.md", "# Hello", assets_local=True)
        # Must reference the external render.js
        self.assertIn("/_assets/render.js", html)
        # Must NOT contain an inline marked.parse call
        self.assertNotIn("marked.parse", html)

    def test_ensure_assets_no_fetch_writes_render_js(self):
        with tempfile.TemporaryDirectory() as d:
            home = Path(d)
            os.environ["DOC_SERVER_NO_FETCH"] = "1"
            try:
                sync.ensure_assets(home)
            finally:
                os.environ.pop("DOC_SERVER_NO_FETCH", None)
            render_js = home / "_assets" / "render.js"
            self.assertTrue(render_js.exists())
            self.assertIn("marked.parse", render_js.read_text(encoding="utf-8"))

    def test_slugify_matches_github_style(self):
        self.assertEqual(sync.slugify("Hello World"), "hello-world")
        self.assertEqual(sync.slugify("API & Routing!"), "api-routing")
        self.assertEqual(sync.slugify("  Multiple   Spaces  "), "multiple-spaces")

    def test_extract_toc_skips_code_fences(self):
        md = "# Title\n\n```\n# not a heading\n```\n\n## Section A\n### Deep\n"
        toc = sync.extract_toc(md)
        self.assertEqual(
            toc,
            [(1, "Title", "title"), (2, "Section A", "section-a"), (3, "Deep", "deep")],
        )

    def test_doc_title_prefers_first_h1(self):
        self.assertEqual(sync.doc_title("# Real Title\n## Sub", "fallback.md"), "Real Title")
        self.assertEqual(sync.doc_title("no heading here", "fallback.md"), "fallback.md")

    def test_doc_page_has_sidebar_and_absolute_back_link(self):
        nav = {"repo": ["main"]}
        sidebar = sync.render_sidebar(nav, "repo/main")
        html = sync.render_doc_html(
            "docs/a.md", "# A", assets_local=True,
            back_href="/repo/main/index.html", sidebar_html=sidebar,
        )
        # Routing: the back link is an absolute path, not a fragile ../ relative.
        self.assertIn('href="/repo/main/index.html"', html)
        self.assertNotIn('href="../index.html"', html)
        # Sidebar nav is present on the doc page.
        self.assertIn('class="sidebar"', html)

    def test_branch_index_has_mermaid_and_per_doc_toc(self):
        docs = [{
            "flat": "docs__a.html",
            "rel": "docs/a.md",
            "title": "A Doc",
            "toc": [(1, "A Doc", "a-doc"), (2, "Usage", "usage")],
        }]
        html = sync.render_branch_index("repo", "main", docs, {"repo": ["main"]}, assets_local=True)
        self.assertIn('class="mermaid"', html)              # structure diagram
        self.assertIn(">A Doc<", html)                       # doc title
        self.assertIn('href="/repo/main/docs__a.html#usage"', html)  # TOC anchor link
        self.assertIn("/_assets/mermaid.min.js", html)       # local mermaid asset

    def test_branch_index_card_is_not_a_nested_anchor(self):
        # The summary card holds TOC section links, so it must NOT itself be an
        # <a>: nesting <a> in <a> is invalid HTML and the browser force-closes the
        # outer anchor, spilling the TOC + "Open document" out of the card grid.
        docs = [{
            "flat": "docs__a.html",
            "rel": "docs/a.md",
            "title": "A Doc",
            "toc": [(1, "A Doc", "a-doc"), (2, "Usage", "usage")],
        }]
        html = sync.render_branch_index("repo", "main", docs, {"repo": ["main"]}, assets_local=True)
        self.assertNotIn('<a class="card"', html)             # card is a <div>, not an anchor
        self.assertIn('<div class="card">', html)
        # The whole card stays clickable via a single "Open document" link.
        self.assertIn('<a class="open" href="/repo/main/docs__a.html"', html)

    def test_doc_breadcrumb_keeps_slash_in_branch(self):
        # Branch names can contain slashes; the breadcrumb must not truncate them.
        branch = "claude/doc-server-routing-ui-osov2g"
        back = f"/skills/{branch}/index.html"
        html = sync.render_doc_html("docs/x.md", "# T", assets_local=False, back_href=back)
        self.assertIn(branch, html)
        self.assertIn(f'href="{back}"', html)

    def test_project_branch_escaped_in_hrefs(self):
        # Branch/repo names are attacker-influenceable (git ref-format permits
        # " < > & '); they must be HTML-escaped in hrefs so a crafted name can't
        # break out of the attribute and inject markup that renders on every page.
        evil = 'x"><b>PWNED'
        side = sync.render_sidebar({"repo": [evil]}, f"repo/{evil}")
        root = sync.render_root_index({evil: ["main"]}, assets_local=False)
        self.assertNotIn('"><b>PWNED', side)
        self.assertNotIn('"><b>PWNED', root)
        # Escaped form is present instead.
        self.assertIn("&quot;&gt;&lt;b&gt;PWNED", side)
        # Normal and slash-containing branches still produce working links.
        ok = sync.render_sidebar({"skills": ["main", "feat/login"]}, "skills/main")
        self.assertIn('href="/skills/main/index.html"', ok)
        self.assertIn('href="/skills/feat/login/index.html"', ok)

    def test_root_index_has_overview_diagram(self):
        html = sync.render_root_index({"repo": ["main", "feat/x"]}, assets_local=False)
        self.assertIn('class="mermaid"', html)
        self.assertIn("HOW IT WORKS", html)  # redesign uses uppercase eyebrow labels
        self.assertIn('href="/repo/index.html"', html)


if __name__ == "__main__":
    unittest.main()
