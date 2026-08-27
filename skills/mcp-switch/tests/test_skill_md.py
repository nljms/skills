import json
import os
import unittest

HERE = os.path.dirname(__file__)
SKILL_MD = os.path.abspath(os.path.join(HERE, "..", "SKILL.md"))
MARKETPLACE = os.path.abspath(
    os.path.join(HERE, "..", "..", "..", ".claude-plugin", "marketplace.json"))


class TestSkillMd(unittest.TestCase):
    def _text(self):
        with open(SKILL_MD) as f:
            return f.read()

    def test_frontmatter(self):
        text = self._text()
        self.assertTrue(text.startswith("---"))
        head = text.split("---", 2)[1]
        self.assertIn("name: mcp-switch", head)
        self.assertIn("description:", head)

    def test_documents_the_commands(self):
        text = self._text()
        for command in ("switch.py use", "switch.py add", "switch.py list",
                        "switch.py save", "switch.py rm"):
            self.assertIn(command, text)

    def test_documents_the_two_gotchas(self):
        text = self._text()
        self.assertIn("/mcp", text)                 # reconnect after switching
        self.assertIn("claude mcp login", text)     # auth recovery

    def test_marketplace_lists_the_skill(self):
        with open(MARKETPLACE) as f:
            data = json.load(f)
        entry = [p for p in data["plugins"] if p["name"] == "mcp-switch"]
        self.assertEqual(len(entry), 1)
        self.assertIn("./skills/mcp-switch", entry[0]["skills"])


if __name__ == "__main__":
    unittest.main()
