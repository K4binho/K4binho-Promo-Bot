from datetime import UTC, datetime, timedelta
from unittest import mock

import bot
import deal_store as ds
import telegram


def test_record_published_tracks_best_price_and_republish_count():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0, title="Fone Bluetooth", url="https://x.test/a?ref=1")
    assert deals["x1"]["price"] == 100.0
    assert deals["x1"]["best_price"] == 100.0
    assert deals["x1"]["republish_count"] == 0
    assert deals["x1"]["last_reason"] == "published"

    ds.record_published(deals, "x1", 80.0, title="Fone Bluetooth", reason="queda_de_preco")
    assert deals["x1"]["price"] == 80.0
    assert deals["x1"]["best_price"] == 80.0
    assert deals["x1"]["republish_count"] == 1
    assert deals["x1"]["last_reason"] == "queda_de_preco"

    # preco sobe de novo: best_price nao deve piorar
    ds.record_published(deals, "x1", 95.0, reason="periodo_configurado")
    assert deals["x1"]["price"] == 95.0
    assert deals["x1"]["best_price"] == 80.0
    assert deals["x1"]["republish_count"] == 2


def test_find_duplicate_id_matches_by_normalized_url():
    deals: dict = {}
    ds.record_published(deals, "old-id", 50.0, url="https://loja.test/produto/123?utm=abc")
    dup = ds.find_duplicate_id(deals, "new-id", url="https://loja.test/produto/123")
    assert dup == "old-id"


def test_find_duplicate_id_matches_by_normalized_title():
    deals: dict = {}
    ds.record_published(deals, "old-id", 50.0, title="Furadeira de Impacto 750W")
    dup = ds.find_duplicate_id(deals, "new-id", title="furadeira de impacto 750w")
    assert dup == "old-id"


def test_find_duplicate_id_returns_none_when_id_already_known():
    deals: dict = {"same-id": {"normalized_title": "x"}}
    assert ds.find_duplicate_id(deals, "same-id", title="x") is None


def test_find_duplicate_id_returns_none_without_match():
    deals: dict = {}
    ds.record_published(deals, "old-id", 50.0, title="Notebook Gamer")
    assert ds.find_duplicate_id(deals, "new-id", title="Cadeira Gamer") is None


def test_should_republish_all_time_low():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0)
    ds.record_published(deals, "x1", 90.0)
    should, reason, prev = ds.should_republish(deals, "x1", 70.0)
    assert should is True
    assert reason == "menor_preco_historico"
    assert prev == 90.0


def test_should_republish_new_coupon_with_lower_price():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0, promotion_signature="sig-a")
    should, reason, prev = ds.should_republish(deals, "x1", 95.0, promotion_signature="sig-b")
    assert should is True
    assert reason == "novo_cupom"


def test_should_republish_price_drop_that_does_not_beat_historical_low():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0)  # best = 100
    ds.record_published(deals, "x1", 70.0)  # best = 70 (mesmo objeto, best_price acompanha o minimo)
    ds.record_published(deals, "x1", 90.0)  # sobe de novo, mas best continua 70
    should, reason, prev = ds.should_republish(deals, "x1", 80.0, min_drop_percent=10.0, min_drop_amount=999.0)
    assert should is True
    assert reason == "queda_de_preco"
    assert prev == 90.0


def test_should_republish_small_drop_is_not_enough():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0)
    should, reason, prev = ds.should_republish(deals, "x1", 99.0, min_drop_percent=10.0, min_drop_amount=20.0)
    assert should is False
    assert reason == ""


def test_should_republish_min_repost_days_elapsed():
    deals: dict = {}
    old_time = datetime.now(UTC) - timedelta(days=10)
    deals["x1"] = {"price": 100.0, "best_price": 100.0, "posted_at": old_time.isoformat(), "promotion_signature": ""}
    should, reason, prev = ds.should_republish(deals, "x1", 100.0, min_repost_days=7)
    assert should is True
    assert reason == "periodo_configurado"


def test_should_republish_min_repost_days_not_elapsed():
    deals: dict = {}
    ds.record_published(deals, "x1", 100.0)
    should, reason, prev = ds.should_republish(deals, "x1", 100.0, min_repost_days=7)
    assert should is False


def test_should_republish_unknown_item_is_not_a_republish():
    deals: dict = {}
    should, reason, prev = ds.should_republish(deals, "never-seen", 10.0)
    assert should is False
    assert reason == ""
    assert prev is None


def test_resolve_repost_known_item_is_never_treated_as_new():
    """Item purgado de `seen` no ciclo, mas ja em published_deals, nao volta como novo."""
    deals: dict = {}
    ds.record_published(deals, "ali:1", 100.0, title="Fone X", url="https://a.test/1")
    is_new, reason, record_key = bot._resolve_repost(
        deals, {}, "ali:1", 100.0, title="Fone X", url="https://a.test/1", prefix="ali:"
    )
    assert is_new is False
    assert reason == ""
    assert record_key is None


def test_resolve_repost_known_item_republishes_on_real_drop():
    deals: dict = {}
    ds.record_published(deals, "ali:1", 100.0, title="Fone X", url="https://a.test/1")
    is_new, reason, record_key = bot._resolve_repost(
        deals, {}, "ali:1", 70.0, title="Fone X", url="https://a.test/1", prefix="ali:"
    )
    assert is_new is False
    assert reason == "menor_preco_historico"
    assert record_key == "ali:1"


def test_record_published_stores_message_and_thread_id():
    deals: dict = {}
    ds.record_published(deals, "ali:1", 10.0, message_id=555, thread_id=112)
    assert deals["ali:1"]["message_id"] == 555
    assert deals["ali:1"]["thread_id"] == 112


def test_send_message_returns_message_id():
    response = mock.Mock()
    response.raise_for_status.return_value = None
    response.json.return_value = {"ok": True, "result": {"message_id": 4242}}
    with mock.patch.object(telegram._rate_limiter, "wait"), mock.patch.object(
        telegram._client, "post", return_value=response
    ):
        assert telegram.send_message("token", "-1001", "oferta") == 4242


def test_delete_previous_post_calls_telegram_with_stored_message_id():
    deals: dict = {}
    ds.record_published(deals, "ali:1", 10.0, message_id=777)
    cfg = mock.Mock(telegram_bot_token="token", telegram_channel_id="-1001")
    with mock.patch.object(bot.telegram, "delete_message", return_value=True) as delete:
        bot._delete_previous_post(cfg, deals, "ali:1")
    delete.assert_called_once_with("token", "-1001", 777)


def test_delete_previous_post_skips_when_no_message_id():
    deals: dict = {}
    ds.record_published(deals, "ali:1", 10.0)
    cfg = mock.Mock(telegram_bot_token="token", telegram_channel_id="-1001")
    with mock.patch.object(bot.telegram, "delete_message") as delete:
        bot._delete_previous_post(cfg, deals, "ali:1")
    delete.assert_not_called()
