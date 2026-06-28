import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from docserver import version


class TestVersion(unittest.TestCase):
    def test_returns_short_stable_hash(self):
        v1 = version.code_version()
        v2 = version.code_version()
        self.assertEqual(v1, v2)
        self.assertIsInstance(v1, str)
        self.assertTrue(0 < len(v1) <= 16)

    def test_hash_changes_when_a_source_file_changes(self):
        files = {"a.py": b"print(1)", "b.py": b"print(2)"}
        v1 = version.fingerprint(files)
        files["b.py"] = b"print(3)"
        v2 = version.fingerprint(files)
        self.assertNotEqual(v1, v2)

    def test_hash_is_order_independent(self):
        a = version.fingerprint({"a.py": b"x", "b.py": b"y"})
        b = version.fingerprint({"b.py": b"y", "a.py": b"x"})
        self.assertEqual(a, b)


if __name__ == "__main__":
    unittest.main()
