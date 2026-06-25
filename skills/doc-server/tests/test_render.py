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

    def test_render_index_lists_entries(self):
        html = sync.render_index_html("repo", [("main/index.html", "main")])
        self.assertIn('href="main/index.html"', html)
        self.assertIn("main", html)


if __name__ == "__main__":
    unittest.main()
