import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import click_tracker
import click_server


class ClickTrackerTest(unittest.TestCase):
    def setUp(self):
        self.tmp_links = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp_clicks = tempfile.NamedTemporaryFile(suffix=".jsonl", delete=False)
        self.tmp_links.close()
        self.tmp_clicks.close()
        self.patch_links = mock.patch.object(click_tracker, "LINKS_PATH", Path(self.tmp_links.name))
        self.patch_clicks = mock.patch.object(click_tracker, "CLICKS_PATH", Path(self.tmp_clicks.name))
        self.patch_links.start()
        self.patch_clicks.start()
        Path(self.tmp_links.name).write_text("{}", encoding="utf-8")
        Path(self.tmp_clicks.name).write_text("", encoding="utf-8")

    def tearDown(self):
        self.patch_links.stop()
        self.patch_clicks.stop()
        Path(self.tmp_links.name).unlink(missing_ok=True)
        Path(self.tmp_clicks.name).unlink(missing_ok=True)

    def test_register_and_resolve(self):
        links = {}
        click_tracker.register_link(links, "abc123", "https://example.com/product", source="ml", title="SSD 1TB")
        self.assertIn("abc123", links)
        self.assertEqual(click_tracker.resolve_link(links, "abc123"), "https://example.com/product")

    def test_resolve_missing(self):
        self.assertIsNone(click_tracker.resolve_link({}, "nonexistent"))

    def test_record_and_load_click(self):
        click_tracker.record_click("deal1", source="ml")
        click_tracker.record_click("deal1", source="ml")
        click_tracker.record_click("deal2", source="steam")
        clicks = click_tracker.load_clicks()
        self.assertEqual(len(clicks), 3)
        self.assertEqual(clicks[0]["deal_id"], "deal1")

    def test_load_clicks_limit(self):
        for i in range(10):
            click_tracker.record_click(f"deal{i}")
        clicks = click_tracker.load_clicks(limit=3)
        self.assertEqual(len(clicks), 3)
        self.assertEqual(clicks[0]["deal_id"], "deal7")

    def test_click_stats(self):
        click_tracker.record_click("deal1", source="ml")
        click_tracker.record_click("deal1", source="ml")
        click_tracker.record_click("deal2", source="steam")
        stats = click_tracker.click_stats()
        self.assertEqual(stats["deal1"]["clicks"], 2)
        self.assertEqual(stats["deal2"]["clicks"], 1)

    def test_save_and_load_links(self):
        links = {}
        click_tracker.register_link(links, "x1", "https://example.com", source="ml")
        click_tracker.save_links(links)
        loaded = click_tracker.load_links()
        self.assertEqual(click_tracker.resolve_link(loaded, "x1"), "https://example.com")

    def test_load_empty(self):
        Path(self.tmp_clicks.name).write_text("", encoding="utf-8")
        self.assertEqual(click_tracker.load_clicks(), [])

    def test_tracking_url(self):
        url = click_server.tracking_url("http://localhost:8321", "abc123")
        self.assertEqual(url, "http://localhost:8321/go/abc123")

    def test_tracking_url_strips_trailing_slash(self):
        url = click_server.tracking_url("http://localhost:8321/", "abc123")
        self.assertEqual(url, "http://localhost:8321/go/abc123")


if __name__ == "__main__":
    unittest.main()
