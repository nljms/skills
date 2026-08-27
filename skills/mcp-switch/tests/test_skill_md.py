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

    def test_save_usage_documents_the_server_flag(self):
        usage = [l for l in self._text().splitlines() if l.startswith("switch.py save")]
        self.assertTrue(usage)
        self.assertIn("--server", usage[0])

    def test_documents_that_rm_refuses_an_active_profile(self):
        text = self._text()
        self.assertIn("refuses", text)
        self.assertIn("switch.py rm", text)

    def test_activation_is_described_as_per_project(self):
        text = self._text()
        self.assertIn("per project", text)
        self.assertNotIn("per working directory", text)
        self.assertNotIn("different accounts at once", text)

    def test_marketplace_lists_the_skill(self):
        with open(MARKETPLACE) as f:
            data = json.load(f)
        entry = [p for p in data["plugins"] if p["name"] == "mcp-switch"]
        self.assertEqual(len(entry), 1)
        self.assertIn("./skills/mcp-switch", entry[0]["skills"])


if __name__ == "__main__":
    unittest.main()
