import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from k4promo.storage import deal_store as ds


class DealStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        self.tmp.close()
        self.patcher = mock.patch.object(ds, "STORE_PATH", Path(self.tmp.name))
        self.patcher.start()
        Path(self.tmp.name).write_text("{}", encoding="utf-8")

    def tearDown(self):
        self.patcher.stop()
        Path(self.tmp.name).unlink(missing_ok=True)

    def test_record_and_load(self):
        deals = ds.load_deals()
        ds.record_published(deals, "MLB123", 299.90)
        ds.save_deals(deals)

        loaded = ds.load_deals()
        self.assertIn("MLB123", loaded)
        self.assertAlmostEqual(loaded["MLB123"]["price"], 299.90)
        self.assertIn("posted_at", loaded["MLB123"])

    def test_check_price_drop_no_previous(self):
        deals = {}
        is_drop, prev = ds.check_price_drop(deals, "MLB999", 100.0)
        self.assertFalse(is_drop)
        self.assertIsNone(prev)

    def test_check_price_drop_no_drop(self):
        deals = {"MLB1": {"price": 200.0, "posted_at": "2026-01-01T00:00:00"}}
        is_drop, prev = ds.check_price_drop(deals, "MLB1", 200.0)
        self.assertFalse(is_drop)

    def test_check_price_drop_small_drop_ignored(self):
        deals = {"MLB1": {"price": 200.0, "posted_at": "2026-01-01T00:00:00"}}
        is_drop, prev = ds.check_price_drop(deals, "MLB1", 195.0)
        self.assertFalse(is_drop)

    def test_check_price_drop_significant_percent(self):
        deals = {"MLB1": {"price": 200.0, "posted_at": "2026-01-01T00:00:00"}}
        is_drop, prev = ds.check_price_drop(deals, "MLB1", 170.0)
        self.assertTrue(is_drop)
        self.assertEqual(prev, 200.0)

    def test_check_price_drop_significant_amount(self):
        deals = {"MLB1": {"price": 500.0, "posted_at": "2026-01-01T00:00:00"}}
        is_drop, prev = ds.check_price_drop(deals, "MLB1", 475.0)
        self.assertTrue(is_drop)
        self.assertEqual(prev, 500.0)

    def test_record_updates_price(self):
        deals = {}
        ds.record_published(deals, "MLB1", 300.0)
        self.assertEqual(deals["MLB1"]["price"], 300.0)
        ds.record_published(deals, "MLB1", 250.0)
        self.assertEqual(deals["MLB1"]["price"], 250.0)


if __name__ == "__main__":
    unittest.main()
