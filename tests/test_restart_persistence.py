"""Reproduz o bug do 'The Escapists 2 - Season Pass' duplicado: o item era
marcado como visto e publicado em memoria, mas so ia pro disco no fim do
ciclo inteiro. Se o processo reiniciava entre o post e o fim do ciclo, o
proximo processo carregava o seen.json velho (sem o item) e republicava.

Usa AliExpress como fonte de teste (interface de fetch mais simples), mas
o mecanismo testado -- persistencia a cada post, nao so no fim do ciclo --
e o mesmo pra todas as 7 fontes.
"""

from unittest.mock import MagicMock, patch

import aliexpress
import deal_store as ds
import seen_store


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
    cfg.repost_min_days = None
    cfg.repost_min_drop_percent = 10.0
    cfg.repost_min_drop_amount = 20.0
    return cfg


def _ali_deal():
    return aliexpress.AliDeal(
        product_id="escapists-2-season-pass", title="The Escapists 2 - Season Pass",
        price=18.00, original_price=59.99, discount_percent=70,
        permalink="https://aliexpress.test/escapists-2-season-pass",
        image_url="https://img/1.jpg", commission_rate=5.0, sales_count=50,
    )


def test_post_survives_restart_between_source_and_end_of_cycle(tmp_path, monkeypatch):
    import bot
    import link_validation

    seen_path = tmp_path / "seen.json"
    deals_path = tmp_path / "deal_store.json"
    monkeypatch.setattr(seen_store, "STORE_PATH", seen_path)
    monkeypatch.setattr(ds, "STORE_PATH", deals_path)

    cfg = _ali_config()
    with patch.object(aliexpress, "fetch_deals", return_value=[_ali_deal()]), \
            patch.object(link_validation, "link_is_broken", return_value=False), \
            patch.object(link_validation, "image_is_reachable", return_value=True), \
            patch("bot.telegram.send_message", return_value=999), \
            patch("bot.analytics.record_deal"):
        posted = bot.run_aliexpress_cycle(cfg, {}, {}, {}, dry_run=False)

    assert posted == 1

    # "Processo reinicia" aqui: NAO chamamos save_seen/ds.save_deals do fim
    # de ciclo (main() faria isso so depois que as 7 fontes terminassem).
    # Um processo novo carregaria o estado do zero neste ponto.
    reloaded_seen = seen_store.load_seen()
    reloaded_deals = ds.load_deals()

    assert "ali:escapists-2-season-pass" in reloaded_seen
    assert "ali:escapists-2-season-pass" in reloaded_deals


def test_run_aliexpress_cycle_does_not_repost_without_a_reason_after_restart(tmp_path, monkeypatch):
    """Continuacao do cenario acima: o 'processo novo' roda de novo com o
    estado recarregado do disco e NAO deve republicar o mesmo item."""
    import bot
    import link_validation

    seen_path = tmp_path / "seen.json"
    deals_path = tmp_path / "deal_store.json"
    monkeypatch.setattr(seen_store, "STORE_PATH", seen_path)
    monkeypatch.setattr(ds, "STORE_PATH", deals_path)

    cfg = _ali_config()
    with patch.object(aliexpress, "fetch_deals", return_value=[_ali_deal()]), \
            patch.object(link_validation, "link_is_broken", return_value=False), \
            patch.object(link_validation, "image_is_reachable", return_value=True), \
            patch("bot.telegram.send_message", return_value=999), \
            patch("bot.analytics.record_deal"):
        bot.run_aliexpress_cycle(cfg, {}, {}, {}, dry_run=False)

    # processo novo: recarrega do disco (como load_seen()/ds.load_deals() no main())
    fresh_seen = seen_store.load_seen()
    fresh_published_deals = ds.load_deals()

    with patch.object(aliexpress, "fetch_deals", return_value=[_ali_deal()]), \
            patch.object(link_validation, "link_is_broken", return_value=False), \
            patch.object(link_validation, "image_is_reachable", return_value=True), \
            patch("bot.telegram.send_message", return_value=1000) as send, \
            patch("bot.analytics.record_deal"):
        posted_again = bot.run_aliexpress_cycle(cfg, fresh_seen, fresh_published_deals, {}, dry_run=False)

    assert posted_again == 0
    send.assert_not_called()
