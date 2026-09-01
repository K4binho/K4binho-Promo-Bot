from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import bot
import deal_store
import ml_playwright
import promotion_engine
from scoring import ScoreResult


def _result(total=50, quality=45, conversion=35, confidence=40):
    return ScoreResult(
        total=total,
        price_subtotal=30,
        reasons=[],
        quality=quality,
        conversion=conversion,
        retention=20,
        confidence=confidence,
        final=float(total),
    )


def test_commercial_fallback_does_not_depend_on_incomplete_history():
    assert bot._ml_commercial_fallback_eligible(
        _result(),
        has_price_evidence=True,
        signal_points=2,
        already_seen=False,
        guaranteed_promotion=False,
        score_min=70,
    )


def test_commercial_fallback_rejects_low_quality():
    assert not bot._ml_commercial_fallback_eligible(
        _result(quality=20),
        has_price_evidence=True,
        signal_points=4,
        already_seen=False,
        guaranteed_promotion=False,
        score_min=70,
    )


def test_signal_points_rating_alone_is_not_strong():
    deal = SimpleNamespace(sales_count=120, rating=4.9, official_store=False)
    assert bot._ml_signal_points(
        deal,
        is_best_seller=False,
        is_trending=False,
        guaranteed_promotion=False,
    ) == 1


def test_signal_points_best_seller_is_strong():
    deal = SimpleNamespace(sales_count=0, rating=0, official_store=False)
    assert bot._ml_signal_points(
        deal,
        is_best_seller=True,
        is_trending=False,
        guaranteed_promotion=False,
    ) >= 2


def test_promotion_fingerprint_changes_with_coupon():
    a = promotion_engine.Promotion(source="mercadolivre", code="VANTAGEMJA", discount_amount=100)
    b = promotion_engine.Promotion(source="mercadolivre", code="OPORTUNIDADE", discount_amount=100)
    assert promotion_engine.promotion_fingerprint(a) != promotion_engine.promotion_fingerprint(b)


def test_promotion_revival_requires_new_benefit_and_real_drop():
    now = datetime.now(UTC)
    deals = {
        "MLB1": {
            "price": 1000.0,
            "posted_at": (now - timedelta(hours=8)).isoformat(),
            "promotion_signature": "old",
        }
    }
    ok, previous = deal_store.check_promotion_revival(
        deals,
        "MLB1",
        930.0,
        "new",
        cooldown_hours=6,
        now=now,
    )
    assert ok
    assert previous == 1000.0


def test_promotion_revival_blocks_same_coupon():
    now = datetime.now(UTC)
    deals = {
        "MLB1": {
            "price": 1000.0,
            "posted_at": (now - timedelta(hours=8)).isoformat(),
            "promotion_signature": "same",
        }
    }
    ok, _ = deal_store.check_promotion_revival(
        deals, "MLB1", 900.0, "same", now=now
    )
    assert not ok


def test_positive_promotion_cache_expires_faster():
    promo = promotion_engine.Promotion(source="mercadolivre", code="TESTE", discount_amount=50)
    cache = {
        "ml:1": {
            "checked_at": (datetime.now(UTC) - timedelta(hours=3)).isoformat(),
            "promotions": [promotion_engine.promotion_to_dict(promo)],
        }
    }
    assert promotion_engine.get_cached_promotions(
        cache, "ml:1", 6, promotion_max_age_hours=2
    ) is None


def test_empty_cache_keeps_normal_ttl():
    cache = {
        "ml:1": {
            "checked_at": (datetime.now(UTC) - timedelta(hours=3)).isoformat(),
            "promotions": [],
        }
    }
    assert promotion_engine.get_cached_promotions(
        cache, "ml:1", 6, promotion_max_age_hours=2
    ) == []


def test_interactive_scanner_never_treats_buy_button_as_safe():
    assert ml_playwright._is_safe_promo_trigger("Ver cupons")
    assert not ml_playwright._is_safe_promo_trigger("Comprar com cupom")
    assert not ml_playwright._is_safe_promo_trigger("Adicionar ao carrinho")
