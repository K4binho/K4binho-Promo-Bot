"""Garante que a validação de link/imagem (link_validation.py), já ativa no
Shopee, também bloqueia publicação de link quebrado nas fontes comerciais
mais antigas (ML e AliExpress) e no GMG."""
from unittest.mock import MagicMock, patch

import aliexpress
import bot
import link_validation


def _ali_config():
    cfg = MagicMock()
    cfg.aliexpress_app_key = "key"
    cfg.aliexpress_app_secret = "secret"
    cfg.aliexpress_tracking_id = "track"
    cfg.aliexpress_searches = [("", "")]
    cfg.aliexpress_min_discount_percent = 10
    cfg.aliexpress_max_posts_per_cycle = 3
    cfg.telegram_aliexpress_thread_id = None
    cfg.telegram_thread_id = None
    cfg.promotions_file = "promotions.json"
    cfg.click_tracking_enabled = False
    return cfg


def _ali_deal():
    return aliexpress.AliDeal(
        product_id="1", title="Produto Teste", price=90.0, original_price=100.0,
        discount_percent=10, permalink="https://aliexpress.com/item/1.html",
        image_url="https://img/1.jpg", commission_rate=5.0, sales_count=50,
    )


def test_ali_cycle_skips_broken_link_and_does_not_post():
    cfg = _ali_config()
    deal = _ali_deal()
    with patch.object(aliexpress, "fetch_deals", return_value=[deal]), \
            patch.object(link_validation, "link_is_broken", return_value=True), \
            patch("bot.telegram.send_message") as send:
        posted = bot.run_aliexpress_cycle(cfg, {}, {}, {}, dry_run=False)
    assert posted == 0
    send.assert_not_called()


def test_ali_cycle_posts_when_link_is_valid():
    cfg = _ali_config()
    deal = _ali_deal()
    with patch.object(aliexpress, "fetch_deals", return_value=[deal]), \
            patch.object(link_validation, "link_is_broken", return_value=False), \
            patch.object(link_validation, "image_is_reachable", return_value=True), \
            patch("bot.telegram.send_message", return_value=222) as send, \
            patch("bot.analytics.record_deal"):
        posted = bot.run_aliexpress_cycle(cfg, {}, {}, {}, dry_run=False)
    assert posted == 1
    send.assert_called_once()
