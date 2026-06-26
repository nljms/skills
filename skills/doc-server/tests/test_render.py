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

    def test_split_frontmatter_parses_and_strips(self):
        meta, body = sync.split_frontmatter("---\nworktree_summary: true\nx: hi\n---\n# Title\nbody")
        self.assertEqual(meta["worktree_summary"], True)
        self.assertEqual(meta["x"], "hi")
        self.assertTrue(body.startswith("# Title"))
        self.assertNotIn("worktree_summary", body)

    def test_split_frontmatter_leaves_plain_docs_alone(self):
        meta, body = sync.split_frontmatter("# Just a doc\n\n---\na horizontal rule above")
        self.assertEqual(meta, {})
        self.assertTrue(body.startswith("# Just a doc"))

    def test_summary_recognized_by_filename_or_flag(self):
        self.assertTrue(sync.is_summary_doc("docs/worktree-summary.md", {}))
        self.assertTrue(sync.is_summary_doc("docs/notes.md", {"worktree_summary": True}))
        self.assertFalse(sync.is_summary_doc("docs/plan.md", {}))

    def test_branch_index_renders_summary_panel(self):
        summary = {
            "title": "Building login",
            "lede": "Adds OAuth login end to end.",
            "mermaid": "graph TD\n A-->B",
            "href": "/repo/main/docs__worktree-summary.html",
        }
        html = sync.render_branch_index("repo", "main", [], {"repo": ["main"]},
                                        assets_local=True, summary=summary)
        self.assertIn("WHAT THIS WORKTREE IS DOING", html)
        self.assertIn("Building login", html)
        self.assertIn("Adds OAuth login end to end.", html)
        self.assertIn("Read full summary", html)
        self.assertIn("A--&gt;B", html)  # mermaid embedded + escaped

    def test_branch_index_renders_inspect_section(self):
        data = {
            "overview": {"languages": ["Python"], "project_type": "CLI tool",
                         "entry_points": ["serve.py"]},
            "architecture": ["docserver/", "docserver/app.py"],
            "services": [{"name": "Postgres", "kind": "database", "via": "x"}],
        }
        html = sync.render_branch_index("repo", "main", [], {"repo": ["main"]},
                                        assets_local=True, inspect_data=data)
        self.assertIn("OVERVIEW &amp; ARCHITECTURE", html)
        self.assertIn("EXTERNAL SERVICES", html)
        self.assertIn("Postgres", html)
        self.assertIn("CLI tool", html)
        self.assertIn("serve.py", html)

    def test_branch_index_unchanged_when_no_inspect_or_summary(self):
        # Backward compat: existing call shape still produces the docs view intact.
        docs = [{"flat": "docs__a.html", "rel": "docs/a.md", "title": "A",
                 "toc": [(1, "A", "a")]}]
        html = sync.render_branch_index("repo", "main", docs, {"repo": ["main"]},
                                        assets_local=True)
        self.assertNotIn("WHAT THIS WORKTREE IS DOING", html)
        self.assertNotIn("OVERVIEW &amp; ARCHITECTURE", html)
        self.assertIn("STRUCTURE", html)  # existing section still present


if __name__ == "__main__":
    unittest.main()
