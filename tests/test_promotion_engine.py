import unittest
from datetime import UTC, datetime

import promotion_engine
import scoring
import telegram
from mercadolivre import Deal


class PromotionEngineTest(unittest.TestCase):
    def test_fixed_coupon_applies_above_minimum(self):
        promo = promotion_engine.Promotion(
            source="aliexpress", code="BRFS5", discount_amount=140, minimum_spend=1200
        )
        result = promotion_engine.evaluate_price(1350, [promo], title="Ryzen 7")
        self.assertEqual(result.guaranteed_price, 1210.0)
        self.assertEqual(result.guaranteed_savings, 140.0)
        self.assertEqual(result.display_promotion.code, "BRFS5")

    def test_coupon_below_minimum_does_not_apply(self):
        promo = promotion_engine.Promotion(
            source="aliexpress", code="BRFS5", discount_amount=140, minimum_spend=1200
        )
        result = promotion_engine.evaluate_price(1100, [promo], title="Ryzen 7")
        self.assertEqual(result.guaranteed_price, 1100.0)
        self.assertIsNone(result.display_promotion)

    def test_percent_coupon_respects_cap(self):
        promo = promotion_engine.Promotion(
            source="mercadolivre", code="VANTAGEMJA", discount_percent=10, max_discount=200
        )
        result = promotion_engine.evaluate_price(2500, [promo], title="RTX 5060")
        self.assertEqual(result.guaranteed_savings, 200.0)
        self.assertEqual(result.guaranteed_price, 2300.0)

    def test_selected_users_is_not_used_for_scoring_price(self):
        promo = promotion_engine.Promotion(
            source="shopee", discount_amount=100, selected_users_only=True
        )
        result = promotion_engine.evaluate_price(2200, [promo], title="Galaxy")
        self.assertEqual(result.scoring_price, 2200.0)
        self.assertEqual(result.potential_price, 2100.0)
        self.assertTrue(result.display_promotion.selected_users_only)

    def test_rescue_page_is_preserved_without_numeric_discount(self):
        promo = promotion_engine.Promotion(
            source="shopee", kind="coupon_rescue", rescue_url="https://example.com/cupons"
        )
        result = promotion_engine.evaluate_price(499, [promo], title="Monitor")
        self.assertIsNotNone(result.display_promotion)
        text = telegram.format_shopee_deal(
            "Monitor Gamer", 499, "https://example.com/item", promotion=result
        )
        self.assertIn("RESGATAR CUPONS", text)

    def test_parse_ml_coupon_code_and_percent(self):
        text = "Use o cupom VANTAGEMJA e ganhe 10% OFF em compras acima de R$ 1.000"
        promos = promotion_engine.parse_mercadolivre_text(text)
        self.assertTrue(promos)
        promo = promos[0]
        self.assertEqual(promo.code, "VANTAGEMJA")
        self.assertEqual(promo.discount_percent, 10.0)
        self.assertEqual(promo.minimum_spend, 1000.0)

    def test_parse_ml_selected_users(self):
        text = "Cupom R$ 100 OFF disponível apenas para usuários selecionados"
        promos = promotion_engine.parse_mercadolivre_text(text)
        self.assertTrue(promos)
        self.assertTrue(promos[0].selected_users_only)
        self.assertEqual(promos[0].discount_amount, 100.0)

    def test_catalog_picks_only_matching_keyword_and_minimum(self):
        catalog = {
            "mercadolivre": [
                {
                    "kind": "coupon",
                    "code": "GPU10",
                    "discount_amount": 100,
                    "minimum_spend": 1000,
                    "match_keywords": ["rtx", "radeon"],
                }
            ]
        }
        matched = promotion_engine.promotions_for_item(
            catalog, "mercadolivre", "Placa RTX 5060", 2200
        )
        missed = promotion_engine.promotions_for_item(
            catalog, "mercadolivre", "Air Fryer", 2200
        )
        self.assertEqual(len(matched), 1)
        self.assertEqual(missed, [])

    def test_due_campaign_only_once(self):
        now = datetime(2026, 9, 1, 2, 0, tzinfo=UTC)
        catalog = {
            "campaigns": [
                {
                    "id": "ali-midnight",
                    "enabled": True,
                    "source": "aliexpress",
                    "title": "Festival",
                    "starts_at": "2026-09-01T00:00:00-03:00",
                    "notice_hours_before": 4,
                }
            ]
        }
        state = {"announced_campaigns": {}}
        due = promotion_engine.due_campaigns(catalog, state, now=now)
        self.assertEqual(len(due), 1)
        state["announced_campaigns"]["ali-midnight"] = now.isoformat()
        self.assertEqual(promotion_engine.due_campaigns(catalog, state, now=now), [])


class PromotionScoringTest(unittest.TestCase):
    def _deal(self):
        return Deal(
            item_id="MLB1",
            title="Placa de Video RTX 5060",
            price=2300.0,
            original_price=2500.0,
            permalink="https://example.com",
            thumbnail="",
            sales_count=1000,
            rating=4.8,
            official_store=True,
        )

    def test_coupon_improves_ml_score_and_price_evidence(self):
        deal = self._deal()
        base = scoring.score(
            deal, min_price_30d=None, obs_count=1,
            is_best_seller=False, is_trending=False,
        )
        promo = scoring.score(
            deal, min_price_30d=None, obs_count=1,
            is_best_seller=False, is_trending=False,
            effective_price=2100.0, promotion_savings=200.0,
            promotion_code="VANTAGEMJA",
        )
        self.assertGreater(promo.total, base.total)
        self.assertGreater(promo.price_subtotal, base.price_subtotal)
        self.assertIn("VANTAGEMJA", " ".join(promo.reasons))

    def test_coupon_message_shows_effective_price_and_code(self):
        promo = promotion_engine.Promotion(
            source="mercadolivre", code="VANTAGEMJA", discount_amount=200
        )
        evaluation = promotion_engine.evaluate_price(2300, [promo], title="RTX")
        text = telegram.format_deal(
            title="RTX 5060",
            price=2300,
            original_price=2500,
            discount=8,
            link="https://example.com",
            promotion=evaluation,
        )
        self.assertIn("VANTAGEMJA", text)
        self.assertIn("2.100,00", text)
        self.assertIn("Com promoção", text)

    def test_conditional_message_is_explicit(self):
        promo = promotion_engine.Promotion(
            source="shopee", discount_amount=100, selected_users_only=True
        )
        evaluation = promotion_engine.evaluate_price(2308, [promo], title="Galaxy")
        text = telegram.format_shopee_deal(
            "Galaxy A37", 2308, "https://example.com", promotion=evaluation
        )
        self.assertIn("Pode chegar", text)
        self.assertIn("usuários selecionados", text)


if __name__ == "__main__":
    unittest.main()
