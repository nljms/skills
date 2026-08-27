import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from mcpswitch import store  # noqa: E402

HTTP = {"type": "http", "url": "https://mcp.linear.app/mcp"}


class TestStore(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.project = "/tmp/some/project"

    def tearDown(self):
        self._tmp.cleanup()

    def test_server_name_defaults_to_provider_profile(self):
        self.assertEqual(store.server_name("linear", "work", {}), "linear-work")

    def test_server_name_honours_explicit_override(self):
        self.assertEqual(store.server_name("linear", "work", {"server": "lw"}), "lw")

    def test_server_config_strips_the_server_key(self):
        cfg = dict(HTTP, server="linear-work")
        self.assertEqual(store.server_config(cfg), HTTP)

    def test_profile_round_trip(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        self.assertEqual(store.read_profile(self.root, "linear", "work"), HTTP)

    def test_read_missing_profile_raises_named_error(self):
        with self.assertRaises(store.StoreError) as ctx:
            store.read_profile(self.root, "linear", "nope")
        self.assertIn("nope", str(ctx.exception))
        self.assertIn("linear", str(ctx.exception))

    def test_malformed_profile_raises_readable_error(self):
        path = store.profile_path(self.root, "linear", "broken")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("{not json", encoding="utf-8")
        with self.assertRaises(store.StoreError) as ctx:
            store.read_profile(self.root, "linear", "broken")
        self.assertIn(str(path), str(ctx.exception))

    def test_non_object_profile_raises(self):
        path = store.profile_path(self.root, "linear", "listy")
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("[1, 2]", encoding="utf-8")
        with self.assertRaises(store.StoreError):
            store.read_profile(self.root, "linear", "listy")

    def test_listing_providers_and_profiles(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        store.write_profile(self.root, "linear", "personal", HTTP)
        store.write_profile(self.root, "notion", "acme", HTTP)
        self.assertEqual(store.providers(self.root), ["linear", "notion"])
        self.assertEqual(store.profiles(self.root, "linear"), ["personal", "work"])

    def test_listing_empty_store_is_empty(self):
        self.assertEqual(store.providers(self.root), [])
        self.assertEqual(store.profiles(self.root, "linear"), [])

    def test_state_json_is_not_listed_as_a_provider(self):
        store.set_active(self.root, self.project, "linear", "work")
        self.assertEqual(store.providers(self.root), [])

    def test_delete_profile_reports_whether_it_existed(self):
        store.write_profile(self.root, "linear", "work", HTTP)
        self.assertTrue(store.delete_profile(self.root, "linear", "work"))
        self.assertFalse(store.delete_profile(self.root, "linear", "work"))
        self.assertFalse((self.root / "linear").exists())

    def test_active_profile_is_keyed_per_project(self):
        other = "/tmp/other/project"
        store.set_active(self.root, self.project, "linear", "work")
        store.set_active(self.root, other, "linear", "personal")
        self.assertEqual(store.get_active(self.root, self.project, "linear"), "work")
        self.assertEqual(store.get_active(self.root, other, "linear"), "personal")

    def test_active_is_none_when_unset(self):
        self.assertIsNone(store.get_active(self.root, self.project, "linear"))

    def test_set_active_records_the_server_name(self):
        store.set_active(self.root, self.project, "linear", "work", "lw")
        self.assertEqual(store.get_active(self.root, self.project, "linear"), "work")
        self.assertEqual(store.get_active_server(self.root, self.project, "linear"), "lw")

    def test_active_server_is_none_when_it_was_never_recorded(self):
        store.set_active(self.root, self.project, "linear", "work")
        self.assertIsNone(store.get_active_server(self.root, self.project, "linear"))

    def test_a_bare_string_state_entry_still_reads_as_the_active_profile(self):
        (self.root / "state.json").write_text(
            json.dumps({self.project: {"linear": "work"}}), encoding="utf-8")
        self.assertEqual(store.get_active(self.root, self.project, "linear"), "work")
        self.assertIsNone(store.get_active_server(self.root, self.project, "linear"))

    def test_clear_active_removes_the_provider_entry(self):
        store.set_active(self.root, self.project, "linear", "work", "lw")
        store.clear_active(self.root, self.project, "linear")
        self.assertIsNone(store.get_active(self.root, self.project, "linear"))
        self.assertIsNone(store.get_active_server(self.root, self.project, "linear"))

    def test_clear_active_is_safe_when_unset(self):
        store.clear_active(self.root, self.project, "linear")  # must not raise

    def test_corrupt_state_file_degrades_to_empty(self):
        (self.root / "state.json").write_text("{oops", encoding="utf-8")
        self.assertIsNone(store.get_active(self.root, self.project, "linear"))
        store.set_active(self.root, self.project, "linear", "work")
        self.assertEqual(store.get_active(self.root, self.project, "linear"), "work")

    def test_state_file_is_readable_json(self):
        store.set_active(self.root, self.project, "linear", "work", "linear-work")
        data = json.loads((self.root / "state.json").read_text(encoding="utf-8"))
        self.assertEqual(data[self.project]["linear"],
                         {"profile": "work", "server": "linear-work"})


if __name__ == "__main__":
    unittest.main()
