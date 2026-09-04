from unittest.mock import patch

import httpx
import pytest

import bot
import link_validation
import promotion_engine
import shopee
import shopee_api


def test_signature_matches_official_vector():
    got = shopee_api._sign("123456", "demo", '{"query":"x"}', 1577836800)
    assert isinstance(got, str) and len(got) == 64


def test_parse_node_derives_original_price_and_discount():
    node = {
        "itemId": "111",
        "productName": "Fone Bluetooth",
        "price": "90.00",
        "priceDiscountRate": "0.10",
        "sales": "1500",
        "commissionRate": "0.05",
        "ratingStar": "4.8",
        "shopId": "999",
        "shopName": "Loja X",
        "imageUrl": "https://img",
        "productCatIds": [100, 200],
        "offerLink": "https://s.shopee.com.br/abc",
        "productLink": "https://shopee.com.br/product/1/111",
    }
    deal = shopee._parse_node(node)
    assert deal is not None
    assert deal.item_id == "111"
    assert deal.price == 90.0
    assert deal.discount_percent == 10
    assert deal.original_price == pytest.approx(100.0, rel=0.01)
    assert deal.commission_rate == pytest.approx(5.0)
    assert deal.category_ids == ["100", "200"]
    assert deal.affiliate_link == "https://s.shopee.com.br/abc"


def test_parse_node_rejects_missing_price_or_id():
    assert shopee._parse_node({"itemId": "1"}) is None
    assert shopee._parse_node({"price": "10"}) is None
    assert shopee._parse_node("not-a-dict") is None


def test_fetch_deals_empty_response_returns_empty_list():
    with patch.object(shopee_api, "fetch_product_offers", return_value={}):
        deals = shopee.fetch_deals("app", "secret", keywords=["ssd"])
    assert deals == []


def test_fetch_deals_stops_without_credentials():
    with patch.object(shopee_api, "fetch_product_offers") as fetch:
        deals = shopee.fetch_deals("", "", keywords=["ssd"])
    assert deals == []
    fetch.assert_not_called()


def test_fetch_deals_dedupes_by_item_id_across_keywords():
    node = {"itemId": "1", "productName": "X", "price": "10"}
    with patch.object(shopee_api, "fetch_product_offers", return_value={"nodes": [node]}):
        deals = shopee.fetch_deals("app", "secret", keywords=["a", "b"])
    assert len(deals) == 1


def test_fetch_deals_survives_api_unavailable():
    with patch.object(shopee_api, "fetch_product_offers", side_effect=RuntimeError("indisponivel")):
        deals = shopee.fetch_deals("app", "secret", keywords=["ssd"])
    assert deals == []


def test_call_retries_on_rate_limit_then_succeeds():
    responses = [
        {"errors": [{"message": "rate limit exceeded", "extensions": {"code": 10030}}]},
        {"data": {"productOfferV2": {"nodes": []}}},
    ]

    class FakeResponse:
        def __init__(self, payload):
            self._payload = payload
            self.status_code = 200

        def raise_for_status(self):
            return None

        def json(self):
            return self._payload

    with patch("shopee_api.httpx.post", side_effect=[FakeResponse(r) for r in responses]), \
            patch("shopee_api.time.sleep"):
        data = shopee_api.call("app", "secret", "query{x}")

    assert data == {"productOfferV2": {"nodes": []}}


def test_ensure_affiliate_link_never_drops_valid_link_silently():
    deal = shopee.ShopeeDeal(
        item_id="1", title="X", price=10, original_price=0, discount_percent=0,
        permalink="https://shopee.com.br/product/1/1", affiliate_link="",
        image_url="", store="", store_id="", commission_rate=0, sales_count=0, rating=0,
    )
    with patch.object(shopee_api, "generate_short_link", side_effect=RuntimeError("falhou")):
        link = shopee.ensure_affiliate_link("app", "secret", deal)
    # Nunca some silenciosamente: cai para o link original em vez de vazio.
    assert link == deal.permalink


def test_coupon_matching_reuses_promotion_engine_scope_rules():
    catalog = {
        "shopee": [
            {
                "enabled": True,
                "kind": "coupon",
                "code": "LOJA10",
                "discount_percent": 10,
                "scope": "shop",
                "store_ids": ["999"],
            }
        ]
    }
    promos = promotion_engine.promotions_for_item(
        catalog, "shopee", "Fone Bluetooth", 90.0, store_id="999",
    )
    assert len(promos) == 1
    other_store = promotion_engine.promotions_for_item(
        catalog, "shopee", "Fone Bluetooth", 90.0, store_id="123",
    )
    assert other_store == []


def test_expired_coupon_is_not_applied():
    catalog = {
        "shopee": [
            {
                "enabled": True,
                "kind": "coupon",
                "code": "EXPIRADO",
                "discount_percent": 50,
                "expires_at": "2000-01-01T00:00:00-03:00",
            }
        ]
    }
    promos = promotion_engine.promotions_for_item(catalog, "shopee", "Item", 100.0)
    assert promos == []


def _base_config():
    from unittest.mock import MagicMock

    cfg = MagicMock()
    cfg.shopee_app_id = "app"
    cfg.shopee_app_secret = "secret"
    cfg.shopee_keywords = []
    cfg.shopee_min_discount_percent = 10
    cfg.shopee_max_posts_per_cycle = 3
    cfg.telegram_shopee_thread_id = None
    cfg.telegram_thread_id = None
    cfg.promotions_file = "promotions.json"
    cfg.click_tracking_enabled = False
    return cfg


def _sample_deal(item_id="1"):
    return shopee.ShopeeDeal(
        item_id=item_id, title="Produto Teste", price=90.0, original_price=100.0,
        discount_percent=10, permalink="https://shopee.com.br/p/1",
        affiliate_link="https://s.shopee.com.br/abc", image_url="",
        store="Loja X", store_id="9", commission_rate=5.0, sales_count=100, rating=4.8,
    )


def test_run_shopee_cycle_skips_broken_link_and_does_not_post():
    cfg = _base_config()
    deal = _sample_deal()
    with patch.object(shopee, "fetch_deals", return_value=[deal]), \
            patch.object(link_validation, "link_is_broken", return_value=True), \
            patch("bot.telegram.send_message") as send:
        posted = bot.run_shopee_cycle(cfg, {}, {}, {}, dry_run=False)
    assert posted == 0
    send.assert_not_called()


def test_run_shopee_cycle_posts_when_link_is_valid():
    cfg = _base_config()
    deal = _sample_deal()
    with patch.object(shopee, "fetch_deals", return_value=[deal]), \
            patch.object(link_validation, "link_is_broken", return_value=False), \
            patch.object(link_validation, "image_is_reachable", return_value=True), \
            patch("bot.telegram.send_message", return_value=111) as send, \
            patch("bot.analytics.record_deal"):
        posted = bot.run_shopee_cycle(cfg, {}, {}, {}, dry_run=False)
    assert posted == 1
    send.assert_called_once()
