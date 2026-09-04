import unittest
from datetime import UTC, datetime, timedelta

from k4promo.services import scoring
from k4promo.storage import seen_store


class ScoreAliexpressTest(unittest.TestCase):
    def test_high_sales_scores_higher(self):
        high = scoring.score_aliexpress(
            title="Teclado Mecanico Gamer RGB",
            price=150.0, original_price=300.0, discount_percent=50,
            sales_count=5000,
        )
        low = scoring.score_aliexpress(
            title="Acessorio Tatico Especifico",
            price=50.0, original_price=100.0, discount_percent=50,
            sales_count=2,
        )
        self.assertGreater(high.total, low.total)

    def test_tech_category_boosted(self):
        tech = scoring.score_aliexpress(
            title="Mouse Gamer RGB 12000 DPI",
            price=80.0, original_price=160.0, discount_percent=50,
            sales_count=500,
        )
        generic = scoring.score_aliexpress(
            title="Colar Feminino Prata Delicado",
            price=80.0, original_price=160.0, discount_percent=50,
            sales_count=500,
        )
        self.assertGreater(tech.total, generic.total)

    def test_zero_sales_penalized(self):
        r = scoring.score_aliexpress(
            title="Produto Aleatorio", price=50.0, original_price=100.0,
            discount_percent=50, sales_count=0,
        )
        self.assertIn("sem vendas ali", " ".join(r.reasons))

    def test_uses_commercial_weights(self):
        r = scoring.score_aliexpress(
            title="SSD NVMe 1TB", price=200.0, original_price=400.0,
            discount_percent=50, sales_count=3000,
        )
        self.assertGreater(r.conversion, 0)


class AliDedupTest(unittest.TestCase):
    def test_dedup_keeps_cheapest(self):
        from k4promo.providers.aliexpress import AliDeal
        deals = [
            AliDeal("1", "K61 Teclado Mecanico", 101.47, 200.0, 49, "link1", "", 5.0, 100),
            AliDeal("2", "K61 Teclado Mecanico", 100.99, 200.0, 50, "link2", "", 5.0, 200),
            AliDeal("3", "Mouse Gamer RGB", 80.0, 160.0, 50, "link3", "", 3.0, 50),
        ]
        deduped: dict[str, AliDeal] = {}
        for d in deals:
            key = scoring._normalize(d.title)[:60]
            existing = deduped.get(key)
            if existing is None or d.price < existing.price:
                deduped[key] = d
        result = list(deduped.values())
        self.assertEqual(len(result), 2)
        kbd = [d for d in result if "k61" in d.title.lower()][0]
        self.assertEqual(kbd.price, 100.99)

    def test_different_titles_kept_separate(self):
        from k4promo.providers.aliexpress import AliDeal
        deals = [
            AliDeal("1", "SSD NVMe 1TB Kingston", 200.0, 400.0, 50, "l1", "", 5.0, 100),
            AliDeal("2", "SSD NVMe 2TB Samsung", 350.0, 700.0, 50, "l2", "", 5.0, 100),
        ]
        deduped: dict[str, AliDeal] = {}
        for d in deals:
            key = scoring._normalize(d.title)[:60]
            existing = deduped.get(key)
            if existing is None or d.price < existing.price:
                deduped[key] = d
        self.assertEqual(len(deduped), 2)


class SeenStoreTest(unittest.TestCase):
    def test_mark_and_check(self):
        seen: dict[str, str] = {}
        seen_store.mark_seen(seen, "MLB123")
        self.assertIn("MLB123", seen)

    def test_backward_compat_list(self):
        import json, tempfile
        from pathlib import Path
        from unittest import mock
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        p = Path(tmp.name)
        p.write_text(json.dumps(["MLB1", "steam:123"]), encoding="utf-8")
        with mock.patch.object(seen_store, "STORE_PATH", p):
            loaded = seen_store.load_seen()
        self.assertIn("MLB1", loaded)
        self.assertIn("steam:123", loaded)
        p.unlink(missing_ok=True)

    def test_expire_plus_removes_old(self):
        old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
        recent = datetime.now(UTC).isoformat()
        seen = {
            "steam:111": old,
            "steam:222": recent,
            "nuuvem:333": old,
            "MLB999": old,
        }
        expired = seen_store.expire_plus(seen, days=7)
        self.assertEqual(expired, 2)
        self.assertNotIn("steam:111", seen)
        self.assertNotIn("nuuvem:333", seen)
        self.assertIn("steam:222", seen)
        self.assertIn("MLB999", seen)

    def test_expire_plus_no_expiry_for_ml(self):
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        seen = {"MLB123": old, "ali:456": old}
        expired = seen_store.expire_plus(seen, days=7)
        self.assertEqual(expired, 0)
        self.assertIn("MLB123", seen)
        self.assertIn("ali:456", seen)


if __name__ == "__main__":
    unittest.main()
