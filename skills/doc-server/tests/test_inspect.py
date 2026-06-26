import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import inspect


def _write(root, rel, content=""):
    p = Path(root) / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(content, encoding="utf-8")
    return p


class TestInspect(unittest.TestCase):
    def test_node_project_with_stripe(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "package.json", json.dumps({
                "name": "shop", "main": "index.js",
                "dependencies": {"express": "^4", "stripe": "^14"},
            }))
            _write(d, "src/index.js")
            r = inspect.inspect_project(d)
            self.assertIn("JavaScript", r["overview"]["languages"])
            self.assertEqual(r["overview"]["project_type"], "Web server")  # express
            names = {s["name"] for s in r["services"]}
            self.assertIn("Stripe", names)

    def test_python_project_with_db_and_cache(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "requirements.txt", "psycopg2-binary==2.9\nredis>=5\nflask\n")
            _write(d, "app.py")
            r = inspect.inspect_project(d)
            self.assertIn("Python", r["overview"]["languages"])
            names = {s["name"] for s in r["services"]}
            self.assertIn("Postgres", names)
            self.assertIn("Redis", names)

    def test_docker_compose_services(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "docker-compose.yml",
                   "services:\n  db:\n    image: postgres:16\n  cache:\n    image: redis:7\n")
            names = {s["name"] for s in inspect.inspect_project(d)["services"]}
            self.assertIn("Postgres", names)
            self.assertIn("Redis", names)

    def test_env_example_services(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, ".env.example", "OPENAI_API_KEY=\nDATABASE_URL=\n# comment\nPORT=3000\n")
            names = {s["name"] for s in inspect.inspect_project(d)["services"]}
            self.assertIn("OpenAI", names)
            self.assertIn("Database", names)

    def test_services_deduped_by_name(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "requirements.txt", "redis\n")
            _write(d, "docker-compose.yml", "  x:\n    image: redis:7\n")
            _write(d, ".env", "REDIS_URL=\n")
            services = inspect.inspect_project(d)["services"]
            redis = [s for s in services if s["name"] == "Redis"]
            self.assertEqual(len(redis), 1)

    def test_arch_tree_excludes_noise(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "src/main.py")
            _write(d, "node_modules/foo/index.js")
            _write(d, ".git/config")
            arch = inspect.inspect_project(d)["architecture"]
            self.assertIn("src/", arch)
            self.assertFalse(any("node_modules" in a for a in arch))
            self.assertFalse(any(a.startswith(".git") for a in arch))

    def test_cli_type_detection(self):
        with tempfile.TemporaryDirectory() as d:
            _write(d, "pyproject.toml",
                   "[project]\nname='t'\ndependencies=['click']\n"
                   "[project.scripts]\nmytool = 't.cli:main'\n")
            r = inspect.inspect_project(d)
            self.assertEqual(r["overview"]["project_type"], "CLI tool")

    def test_empty_dir_is_graceful(self):
        with tempfile.TemporaryDirectory() as d:
            r = inspect.inspect_project(d)
            self.assertEqual(r["services"], [])
            self.assertEqual(r["architecture"], [])

    def test_missing_source_root(self):
        r = inspect.inspect_project("/no/such/path/xyz")
        self.assertEqual(r, {"overview": {}, "architecture": [], "services": []})

    def test_cache_reused_when_unchanged(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            _write(src, "requirements.txt", "redis\n")
            first = inspect.inspect_cached(src, dest)
            self.assertTrue((Path(dest) / ".inspect.json").exists())
            # Tamper the cached data; an unchanged fingerprint must return it verbatim.
            cache = Path(dest) / ".inspect.json"
            blob = json.loads(cache.read_text())
            blob["data"]["services"] = [{"name": "SENTINEL", "kind": "x", "via": "y"}]
            cache.write_text(json.dumps(blob))
            second = inspect.inspect_cached(src, dest)
            self.assertEqual(second["services"][0]["name"], "SENTINEL")

    def test_cache_busted_on_change(self):
        with tempfile.TemporaryDirectory() as src, tempfile.TemporaryDirectory() as dest:
            _write(src, "requirements.txt", "redis\n")
            inspect.inspect_cached(src, dest)
            time.sleep(0.01)
            # Add a new signal file -> fingerprint changes -> recompute.
            _write(src, "package.json", json.dumps({"dependencies": {"stripe": "^1"}}))
            os.utime(Path(src) / "requirements.txt", None)
            second = inspect.inspect_cached(src, dest)
            self.assertIn("Stripe", {s["name"] for s in second["services"]})


if __name__ == "__main__":
    unittest.main()
