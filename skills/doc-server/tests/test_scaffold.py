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
