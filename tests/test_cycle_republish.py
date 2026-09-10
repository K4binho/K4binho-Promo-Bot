"""Fase 4, ponta a ponta: um item já visto (em ``ctx.seen``) mas cujo preço
caiu o bastante é republicado de novo pelo ciclo, o post anterior é apagado
(best effort) e o ``deal_store`` é atualizado com o novo ``message_id``."""

from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest import mock

from k4promo import telegram
from k4promo.domain import topics
from k4promo.providers import kabum, shopee
from k4promo.services import analytics, publisher
from k4promo.services.context import CycleContext
from k4promo.services.cycles import kabum as kabum_cycle
from k4promo.services.cycles import shopee as shopee_cycle
from k4promo.storage import deal_store as ds


def _cfg(**overrides):
    base = dict(
        telegram_bot_token="token", telegram_channel_id="channel",
        telegram_thread_id=None, telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        click_tracking_enabled=False, promotions_file="promotions.missing.json",
        showcase_min_physical_discount=40, showcase_min_game_discount=70,
        repost_min_days=0, repost_min_drop_percent=10, repost_min_drop_amount=20.0,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(**overrides):
    return CycleContext(cfg=_cfg(**overrides))


class KabumRepublishTest(unittest.TestCase):
    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "delete_message")
    @mock.patch.object(telegram, "send_message", return_value=999)
    @mock.patch.object(kabum, "generate_affiliate_link", side_effect=lambda t, p, url: url)
    @mock.patch.object(kabum, "fetch_deals")
    def test_queda_de_preco_republica_e_apaga_post_anterior(
        self, fetch, _gen, send_message, delete_message, _rec, _time,
    ):
        fetch.return_value = [
            kabum.KabumDeal("10", "Placa de Video RTX 4060 8GB", 1500.0, 2599.0, 27,
                             "https://kabum/10", "https://img/10"),
        ]
        # min_discount alto o bastante pra essa oferta NUNCA passar como
        # candidata nova — só entra via republicação.
        ctx = _ctx(kabum_awin_token="tok", kabum_publisher_id=123,
                   kabum_min_discount_percent=90, kabum_max_posts_per_cycle=3)
        ctx.seen["kabum:10"] = "2026-01-01T00:00:00"
        ds.record_published(ctx.published_deals, "kabum:10", 1200.0)  # piso histórico
        ds.record_published(ctx.published_deals, "kabum:10", 1899.0, message_id=777, thread_id=2197)

        posted = kabum_cycle.run(ctx)

        self.assertEqual(posted, 1)
        delete_message.assert_called_once_with("token", "channel", 777)
        entry = ctx.published_deals["kabum:10"]
        self.assertEqual(entry["message_id"], 999)
        self.assertEqual(entry["last_reason"], "queda_de_preco")
        self.assertEqual(entry["republish_count"], 2)
        self.assertEqual(entry["price"], 1500.0)


class ShopeeRepublishTest(unittest.TestCase):
    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "delete_message")
    @mock.patch.object(telegram, "send_message", return_value=1234)
    @mock.patch.object(shopee, "fetch_deals")
    def test_menor_preco_historico_republica(
        self, fetch_deals, send_message, delete_message, record_deal, _time,
    ):
        fetch_deals.return_value = [
            shopee.ShopeeDeal("s1", "Air Fryer Philco 5L", 79.9, 199.9, 60,
                               "https://s.shopee/1", "https://img/1",
                               sales_count=1500, rating=4.8),
        ]
        ctx = _ctx(shopee_app_id="id", shopee_app_secret="sec", shopee_searches=["casa"],
                   shopee_min_discount_percent=90, shopee_min_sales=0,
                   shopee_max_posts_per_cycle=3)
        ctx.seen["shopee:s1"] = "2026-01-01T00:00:00"
        ds.record_published(ctx.published_deals, "shopee:s1", 99.9, message_id=555, thread_id=2198)

        posted = shopee_cycle.run(ctx)

        self.assertEqual(posted, 1)
        delete_message.assert_called_once_with("token", "channel", 555)
        entry = ctx.published_deals["shopee:s1"]
        self.assertEqual(entry["message_id"], 1234)
        self.assertEqual(entry["last_reason"], "menor_preco_historico")
        self.assertEqual({c.kwargs["action"] for c in record_deal.call_args_list},
                          {"menor_preco_historico"})

    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", return_value=1)
    @mock.patch.object(shopee, "fetch_deals")
    def test_sem_mudanca_nao_republica(self, fetch_deals, _send, _rec, _time):
        fetch_deals.return_value = [
            shopee.ShopeeDeal("s1", "Air Fryer Philco 5L", 99.9, 199.9, 50,
                               "https://s.shopee/1", "https://img/1",
                               sales_count=1500, rating=4.8),
        ]
        ctx = _ctx(shopee_app_id="id", shopee_app_secret="sec", shopee_searches=["casa"],
                   shopee_min_discount_percent=90, shopee_min_sales=0,
                   shopee_max_posts_per_cycle=3)
        ctx.seen["shopee:s1"] = "2026-01-01T00:00:00"
        ds.record_published(ctx.published_deals, "shopee:s1", 99.9, message_id=555, thread_id=2198)

        posted = shopee_cycle.run(ctx)

        self.assertEqual(posted, 0)


if __name__ == "__main__":
    unittest.main()
