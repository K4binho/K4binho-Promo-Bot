import json
import unittest
from pathlib import Path
from unittest.mock import patch

import analytics


class AnalyticsTest(unittest.TestCase):
    def setUp(self):
        self.tmp_path = Path(__file__).parent / "_test_analytics.jsonl"
        self._orig = analytics.STORE_PATH
        analytics.STORE_PATH = self.tmp_path

    def tearDown(self):
        analytics.STORE_PATH = self._orig
        if self.tmp_path.exists():
            self.tmp_path.unlink()

    def test_record_deal_returns_deal_id(self):
        deal_id = analytics.record_deal(
            source="ml",
            product_id="MLB123",
            title="Produto Teste",
            price=99.90,
            discount_percent=30,
            action="published",
        )
        self.assertEqual(len(deal_id), 12)

    def test_record_deal_writes_jsonl(self):
        analytics.record_deal(
            source="steam",
            product_id="app_440",
            title="Team Fortress 2",
            price=0.0,
            discount_percent=100,
            deal_type="plus",
            affiliate=False,
            action="published",
        )
        lines = self.tmp_path.read_text(encoding="utf-8").strip().split("\n")
        self.assertEqual(len(lines), 1)
        entry = json.loads(lines[0])
        self.assertEqual(entry["source"], "steam")
        self.assertEqual(entry["product_id"], "app_440")
        self.assertEqual(entry["deal_type"], "plus")
        self.assertFalse(entry["affiliate"])

    def test_multiple_records_append(self):
        analytics.record_deal(source="ml", product_id="A", title="A", price=10.0)
        analytics.record_deal(source="steam", product_id="B", title="B", price=20.0)
        analytics.record_deal(source="nuuvem", product_id="C", title="C", price=30.0)
        entries = analytics.load_entries()
        self.assertEqual(len(entries), 3)
        self.assertEqual([e["source"] for e in entries], ["ml", "steam", "nuuvem"])

    def test_load_entries_limit(self):
        for i in range(5):
            analytics.record_deal(source="ml", product_id=str(i), title=str(i), price=float(i))
        entries = analytics.load_entries(limit=2)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0]["product_id"], "3")
        self.assertEqual(entries[1]["product_id"], "4")

    def test_load_entries_empty(self):
        self.assertEqual(analytics.load_entries(), [])


if __name__ == "__main__":
    unittest.main()
