import unittest
from datetime import UTC, datetime, timedelta

from k4promo.storage import price_history


class PriceHistoryTest(unittest.TestCase):
    def test_record_e_contagem(self):
        hist: dict = {}
        price_history.record(hist, "MLB1", 99.90)
        price_history.record(hist, "MLB1", 89.90)
        self.assertEqual(price_history.observation_count(hist, "MLB1", 30), 2)

    def test_min_price_pega_menor(self):
        hist: dict = {}
        price_history.record(hist, "MLB1", 150.0)
        price_history.record(hist, "MLB1", 99.0)
        price_history.record(hist, "MLB1", 120.0)
        self.assertAlmostEqual(price_history.min_price(hist, "MLB1", 30), 99.0, places=2)

    def test_janela_ignora_antigos(self):
        old = (datetime.now(UTC) - timedelta(days=40)).isoformat()
        hist = {"MLB1": [[old, 5000]]}
        self.assertEqual(price_history.observation_count(hist, "MLB1", 30), 0)
        self.assertIsNone(price_history.min_price(hist, "MLB1", 30))

    def test_item_sem_historico(self):
        self.assertEqual(price_history.observation_count({}, "MLBX", 30), 0)
        self.assertIsNone(price_history.min_price({}, "MLBX", 30))


if __name__ == "__main__":
    unittest.main()
