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
