"""Garante que cada ciclo publica no tópico certo do fórum."""

import unittest
from types import SimpleNamespace
from unittest import mock

from k4promo import telegram
from k4promo.domain import topics
from k4promo.providers import aliexpress, kabum, shopee
from k4promo.services import analytics, publisher, router
from k4promo.services.context import CycleContext
from k4promo.services.cycles import aliexpress as ali_cycle
from k4promo.services.cycles import kabum as kabum_cycle
from k4promo.services.cycles import shopee as shopee_cycle


def _cfg(**overrides):
    base = dict(
        telegram_bot_token="token",
        telegram_channel_id="channel",
        telegram_thread_id=None,
        telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        click_tracking_enabled=False,
        promotions_file="promotions.missing.json",
        showcase_min_physical_discount=40,
        showcase_min_game_discount=70,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(**overrides):
    return CycleContext(cfg=_cfg(**overrides))


class TopicThreadTest(unittest.TestCase):
    def test_uses_topic_ids_or_general_fallback(self):
        cfg = _cfg(telegram_topic_ids={topics.JOGOS: None}, telegram_thread_id=112)
        self.assertEqual(router.topic_thread_id(cfg, topics.JOGOS), 112)
        self.assertEqual(router.topic_thread_id(_cfg(), topics.JOGOS), 2195)

    def test_campaign_routing(self):
        self.assertEqual(router.campaign_thread_id(_cfg(), "steam"), 2195)
        self.assertEqual(router.campaign_thread_id(_cfg(), "aliexpress"), 2194)


class AliexpressRoutingTest(unittest.TestCase):
    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    @mock.patch.object(aliexpress, "fetch_deals")
    def test_each_deal_goes_to_its_topic(self, fetch_deals, send_message, record_deal, _time):
        fetch_deals.return_value = [
            aliexpress.AliDeal("1", "Furadeira Parafusadeira 21V", 150.0, 300.0, 50, "https://a/1", "https://img/1", 5.0, 2000),
            aliexpress.AliDeal("2", "Vestido Feminino Floral", 60.0, 120.0, 50, "https://a/2", "https://img/2", 5.0, 900),
            aliexpress.AliDeal("3", "SSD NVMe 1TB", 250.0, 500.0, 50, "https://a/3", "https://img/3", 5.0, 3000),
        ]
        ctx = _ctx(
            aliexpress_app_key="k", aliexpress_app_secret="s", aliexpress_tracking_id="t",
            aliexpress_searches=[("", "")], aliexpress_min_discount_percent=30,
            aliexpress_max_posts_per_cycle=3,
        )
        posted = ali_cycle.run(ctx)
        self.assertEqual(posted, 3)
        threads = {c.args[2].split("\n")[2]: c.kwargs["thread_id"] for c in send_message.call_args_list}
        self.assertEqual(threads["📦 <b>Furadeira Parafusadeira 21V</b>"], 2202)
        self.assertEqual(threads["📦 <b>Vestido Feminino Floral</b>"], 2201)
        self.assertEqual(threads["📦 <b>SSD NVMe 1TB</b>"], 2197)
        recorded = {c.kwargs["title"]: c.kwargs["topic"] for c in record_deal.call_args_list}
        self.assertEqual(recorded["SSD NVMe 1TB"], topics.TECNOLOGIA)
        # 50% off com imagem -> candidatos à vitrine
        self.assertEqual(len(ctx.showcase_candidates), 3)


class KabumCycleTest(unittest.TestCase):
    def _deals(self):
        return [
            kabum.KabumDeal("10", "Placa de Vídeo RTX 4060 8GB", 1899.0, 2599.0, 27, "https://kabum/10", "https://img/10"),
            kabum.KabumDeal("11", "Air Fryer Philco 5L", 299.0, 499.0, 40, "https://kabum/11", "https://img/11"),
        ]

    def test_skips_without_credentials(self):
        ctx = _ctx(kabum_awin_token="", kabum_publisher_id=0)
        self.assertEqual(kabum_cycle.run(ctx), 0)

    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    @mock.patch.object(kabum, "generate_affiliate_link", side_effect=lambda t, p, url: url + "?awin=1")
    @mock.patch.object(kabum, "fetch_deals")
    def test_routes_and_uses_affiliate_link(self, fetch, _gen, send_message, record_deal, _time):
        fetch.return_value = self._deals()
        ctx = _ctx(kabum_awin_token="tok", kabum_publisher_id=123,
                   kabum_min_discount_percent=20, kabum_max_posts_per_cycle=3)
        posted = kabum_cycle.run(ctx)
        self.assertEqual(posted, 2)
        self.assertIn("kabum:10", ctx.seen)
        by_title = {c.args[2].split("\n")[2]: c for c in send_message.call_args_list}
        gpu = by_title["📦 <b>Placa de Vídeo RTX 4060 8GB</b>"]
        fryer = by_title["📦 <b>Air Fryer Philco 5L</b>"]
        self.assertEqual(gpu.kwargs["thread_id"], 2197)
        self.assertEqual(fryer.kwargs["thread_id"], 2198)
        self.assertIn("awin=1", gpu.args[2])
        self.assertTrue(all(c.kwargs["affiliate"] for c in record_deal.call_args_list))

    @mock.patch.object(telegram, "send_message")
    @mock.patch.object(kabum, "generate_affiliate_link", return_value=None)
    @mock.patch.object(kabum, "fetch_deals")
    def test_no_affiliate_link_no_publish(self, fetch, _gen, send_message):
        fetch.return_value = self._deals()
        ctx = _ctx(kabum_awin_token="tok", kabum_publisher_id=123,
                   kabum_min_discount_percent=20, kabum_max_posts_per_cycle=3)
        self.assertEqual(kabum_cycle.run(ctx), 0)
        send_message.assert_not_called()


class ShopeeCycleTest(unittest.TestCase):
    def test_skips_without_credentials(self):
        ctx = _ctx(shopee_app_id="", shopee_app_secret="")
        self.assertEqual(shopee_cycle.run(ctx), 0)

    @mock.patch.object(publisher, "time")
    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    @mock.patch.object(shopee, "fetch_deals")
    def test_routes_shopee_deals(self, fetch_deals, send_message, record_deal, _time):
        fetch_deals.return_value = [
            shopee.ShopeeDeal("s1", "Kit Organizador de Cozinha 10 peças", 39.9, 79.9, 50, "https://s.shopee/1", "https://img/1", sales_count=1500, rating=4.8),
            shopee.ShopeeDeal("s2", "Batom Matte Vermelho", 19.9, 39.9, 50, "https://s.shopee/2", "https://img/2", sales_count=500, rating=4.6),
            shopee.ShopeeDeal("s3", "Produto com poucas vendas", 19.9, 39.9, 50, "https://s.shopee/3", "https://img/3", sales_count=2),
        ]
        ctx = _ctx(shopee_app_id="id", shopee_app_secret="sec", shopee_searches=["cozinha"],
                   shopee_min_discount_percent=30, shopee_min_sales=20,
                   shopee_max_posts_per_cycle=3)
        posted = shopee_cycle.run(ctx)
        self.assertEqual(posted, 2)
        self.assertNotIn("shopee:s3", ctx.seen)
        by_title = {c.args[2].split("\n")[2]: c for c in send_message.call_args_list}
        self.assertEqual(by_title["📦 <b>Kit Organizador de Cozinha 10 peças</b>"].kwargs["thread_id"], 2198)
        self.assertEqual(by_title["📦 <b>Batom Matte Vermelho</b>"].kwargs["thread_id"], 2201)
        self.assertIn("SHOPEE", by_title["📦 <b>Batom Matte Vermelho</b>"].args[2])
        self.assertEqual({c.kwargs["source"] for c in record_deal.call_args_list}, {"shopee"})


class ShopeeParserTest(unittest.TestCase):
    def test_parse_offers_defensive(self):
        nodes = [
            {"itemId": 123, "productName": "Fone Bluetooth", "priceMin": "59.90", "priceDiscountRate": 40,
             "commissionRate": "0.08", "sales": "1200", "imageUrl": "https://i", "ratingStar": "4.7",
             "offerLink": "https://s.shopee.com.br/abc", "productLink": "https://shopee.com.br/x"},
            {"itemId": 456, "productName": "Sem link", "priceMin": "10"},
            {"itemId": 789, "productName": "Sem preco", "offerLink": "https://s.shopee/2"},
            "lixo",
        ]
        deals = shopee.parse_offers(nodes)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.item_id, "123")
        self.assertEqual(d.discount_percent, 40)
        self.assertAlmostEqual(d.original_price, 99.83, places=2)
        self.assertEqual(d.sales_count, 1200)
        self.assertAlmostEqual(d.commission_rate, 8.0)
        self.assertEqual(d.permalink, "https://s.shopee.com.br/abc")

    def test_build_query_escapes_keyword(self):
        q = shopee.build_query('fone "bluetooth"', sort_type=2, page=1, limit=20)
        self.assertIn('keyword:"fone \\"bluetooth\\""', q)
        self.assertIn("productOfferV2", q)


if __name__ == "__main__":
    unittest.main()
