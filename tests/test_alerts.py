import unittest
from datetime import UTC, datetime, timedelta
from unittest import mock

import alert_store


class AlertStoreTest(unittest.TestCase):
    def test_add_and_get(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "rtx 5070", max_price=4000.0)
        result = alert_store.get_alerts(alerts, "123")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["keywords"], "rtx 5070")
        self.assertEqual(result[0]["max_price"], 4000.0)

    def test_add_multiple(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.add_alert(alerts, "123", "monitor")
        self.assertEqual(len(alert_store.get_alerts(alerts, "123")), 2)

    def test_remove_alert(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.add_alert(alerts, "123", "monitor")
        self.assertTrue(alert_store.remove_alert(alerts, "123", 0))
        remaining = alert_store.get_alerts(alerts, "123")
        self.assertEqual(len(remaining), 1)
        self.assertEqual(remaining[0]["keywords"], "monitor")

    def test_remove_invalid_index(self):
        alerts: dict = {}
        self.assertFalse(alert_store.remove_alert(alerts, "123", 0))

    def test_remove_last_cleans_user(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.remove_alert(alerts, "123", 0)
        self.assertNotIn("123", alerts)

    def test_match_by_keyword(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "rtx 5070")
        matches = alert_store.match_deal(alerts, "Placa de Video RTX 5070 12GB", 3500.0, "ml")
        self.assertEqual(len(matches), 1)
        self.assertEqual(matches[0][0], "123")

    def test_match_no_match(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "rtx 5070")
        matches = alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml")
        self.assertEqual(len(matches), 0)

    def test_match_price_filter(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "rtx 5070", max_price=4000.0)
        above = alert_store.match_deal(alerts, "RTX 5070 Placa Video", 4500.0, "ml")
        self.assertEqual(len(above), 0)
        below = alert_store.match_deal(alerts, "RTX 5070 Placa Video", 3800.0, "ml")
        self.assertEqual(len(below), 1)

    def test_match_source_filter(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "cyberpunk", source="steam")
        ml = alert_store.match_deal(alerts, "Cyberpunk 2077", 65.0, "ml")
        self.assertEqual(len(ml), 0)
        steam = alert_store.match_deal(alerts, "Cyberpunk 2077", 65.0, "steam")
        self.assertEqual(len(steam), 1)

    def test_match_accent_insensitive(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "memória ram")
        matches = alert_store.match_deal(alerts, "Memoria RAM DDR5 16GB", 250.0, "ml")
        self.assertEqual(len(matches), 1)

    def test_get_empty(self):
        alerts: dict = {}
        self.assertEqual(alert_store.get_alerts(alerts, "999"), [])

    def test_multiple_users(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "111", "ssd")
        alert_store.add_alert(alerts, "222", "ssd")
        matches = alert_store.match_deal(alerts, "SSD NVMe 1TB", 300.0, "ml")
        chat_ids = {m[0] for m in matches}
        self.assertEqual(chat_ids, {"111", "222"})

    def test_dedup_same_product_blocked(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        first = alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml", product_id="MLB123")
        self.assertEqual(len(first), 1)
        second = alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml", product_id="MLB123")
        self.assertEqual(len(second), 0)

    def test_dedup_different_product_allowed(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml", product_id="MLB123")
        second = alert_store.match_deal(alerts, "SSD Samsung 2TB", 399.0, "ml", product_id="MLB456")
        self.assertEqual(len(second), 1)

    def test_dedup_price_drop_bypasses_cooldown(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.match_deal(alerts, "SSD Kingston 1TB", 300.0, "ml", product_id="MLB123")
        drop = alert_store.match_deal(alerts, "SSD Kingston 1TB", 250.0, "ml", product_id="MLB123")
        self.assertEqual(len(drop), 1)

    def test_dedup_expires_after_cooldown(self):
        alerts: dict = {}
        alert_store.add_alert(alerts, "123", "ssd")
        alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml", product_id="MLB123")
        expired_time = (datetime.now(UTC) - timedelta(hours=25)).isoformat()
        alerts["123"][0]["notified"]["MLB123"]["at"] = expired_time
        after_cooldown = alert_store.match_deal(alerts, "SSD Kingston 1TB", 289.0, "ml", product_id="MLB123")
        self.assertEqual(len(after_cooldown), 1)


if __name__ == "__main__":
    unittest.main()
