"""Testes dos serviços compartilhados que substituíram a duplicação dos ciclos."""

import os
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

import httpx

from k4promo import telegram
from k4promo.domain import topics
from k4promo.domain.models import Offer
from k4promo.services import analytics, dedup
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.scoring import ScoreResult
from k4promo.storage import paths


def _cfg(**overrides):
    base = dict(
        telegram_bot_token="token",
        telegram_channel_id="channel",
        telegram_thread_id=None,
        telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        click_tracking_enabled=False,
        showcase_min_physical_discount=40,
        showcase_min_game_discount=70,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _result():
    return ScoreResult(total=80, price_subtotal=30, reasons=[], quality=70,
                       conversion=60, retention=40, confidence=50, final=80.0)


def _offer(**overrides):
    base = dict(
        source="shopee", offer_id="1", title="Air Fryer", price=99.0,
        permalink="https://loja/1", original_price=199.0, image_url="https://img",
        discount_percent=50,
    )
    base.update(overrides)
    return Offer(**base)


class DedupTest(unittest.TestCase):
    def test_release_stale_frees_only_matching_prefix(self):
        seen = {"steam:1": "t", "steam:2": "t", "gmg:1": "t", "MLB9": "t"}
        freed = dedup.release_stale(seen, "steam:", {"steam:1"}, log_tag="Steam")
        self.assertEqual(freed, 1)
        self.assertEqual(set(seen), {"steam:1", "gmg:1", "MLB9"})

    def test_dedupe_by_title_keeps_cheapest(self):
        items = [
            SimpleNamespace(title="Fone Bluetooth XYZ", price=100.0),
            SimpleNamespace(title="FONE BLUETOOTH XYZ", price=80.0),
            SimpleNamespace(title="Outro produto", price=50.0),
        ]
        kept = dedup.dedupe_by_title(items)
        self.assertEqual(len(kept), 2)
        self.assertIn(80.0, [i.price for i in kept])
        self.assertNotIn(100.0, [i.price for i in kept])


class OfferModelTest(unittest.TestCase):
    def test_key_prefixes_every_source_except_ml(self):
        self.assertEqual(_offer(source="shopee", offer_id="1").key, "shopee:1")
        self.assertEqual(_offer(source="steam", offer_id="app_1").key, "steam:app_1")
        # O ML mantém a chave sem prefixo para não invalidar o estado gravado.
        self.assertEqual(_offer(source="ml", offer_id="MLB123").key, "MLB123")

    def test_keeps_the_discount_the_store_reported(self):
        # A loja diz 50%; o modelo não recalcula por conta própria.
        self.assertEqual(_offer(discount_percent=50).discount_percent, 50)

    def test_discount_from_effective_price(self):
        offer = _offer(price=100.0, original_price=200.0, discount_percent=50)
        self.assertEqual(offer.discount_from(50.0), 75)

    def test_discount_from_falls_back_without_reference(self):
        offer = _offer(original_price=None, discount_percent=30)
        self.assertEqual(offer.discount_from(99.0), 30)

    def test_is_free(self):
        self.assertTrue(_offer(price=0.0).is_free)
        self.assertFalse(_offer(price=0.01).is_free)


class PublisherTest(unittest.TestCase):
    def setUp(self):
        self.ctx = CycleContext(cfg=_cfg())
        self.publisher = Publisher(self.ctx)

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    def test_publish_derives_everything_from_the_offer(self, send_message, record_deal):
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
            analytics_kwargs={"deal_type": "commercial", "affiliate": True},
        )
        self.assertTrue(ok)
        self.assertIn("shopee:1", self.ctx.seen)
        self.assertEqual(send_message.call_args.kwargs["thread_id"], 2198)
        self.assertEqual(send_message.call_args.kwargs["image_url"], "https://img")
        recorded = record_deal.call_args.kwargs
        self.assertEqual(recorded["topic"], topics.CASA_COZINHA)
        self.assertEqual(recorded["source"], "shopee")
        self.assertEqual(recorded["product_id"], "1")
        self.assertEqual(recorded["title"], "Air Fryer")
        self.assertEqual(recorded["price"], 99.0)
        self.assertEqual(recorded["original_price"], 199.0)
        self.assertEqual(recorded["discount_percent"], 50)
        self.assertEqual(recorded["quality_score"], 70)
        self.assertEqual([c["key"] for c in self.ctx.showcase_candidates], ["shopee:1"])

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    def test_effective_price_overrides_listed_price(self, _send, record_deal):
        self.publisher.publish(
            _offer(price=100.0, original_price=200.0, discount_percent=50),
            topic=topics.CASA_COZINHA, text="msg", result=_result(), score=80,
            link="https://l", log_tag="Shopee", price=50.0,
            analytics_kwargs={"discount_percent": 75},
        )
        recorded = record_deal.call_args.kwargs
        self.assertEqual(recorded["price"], 50.0)
        self.assertEqual(recorded["discount_percent"], 75)

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", side_effect=httpx.HTTPError("boom"))
    def test_failed_send_leaves_no_trace(self, _send, record_deal):
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        )
        self.assertFalse(ok)
        self.assertEqual(self.ctx.seen, {})
        self.assertEqual(self.ctx.showcase_candidates, [])
        record_deal.assert_not_called()

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    def test_showcase_key_can_differ_from_seen_key(self, _send, _rec):
        offer = _offer(source="ml", offer_id="MLB123", discount_percent=60)
        self.publisher.publish(
            offer, topic=topics.TECNOLOGIA, text="msg", result=_result(), score=80,
            link="https://l", log_tag="ML", showcase_key="ml:MLB123",
        )
        self.assertIn("MLB123", self.ctx.seen)
        self.assertEqual([c["key"] for c in self.ctx.showcase_candidates], ["ml:MLB123"])

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message")
    def test_game_lowest_price_reaches_the_showcase(self, _send, _rec):
        # Sem review, o que qualifica a Steam na vitrine é o menor preço
        # histórico. O publisher deriva esse sinal do próprio Offer.
        at_low = _offer(source="steam", offer_id="app_1", price=9.0,
                        original_price=90.0, discount_percent=90, lowest_price=9.0)
        self.publisher.publish(
            at_low, topic=topics.JOGOS, text="msg", result=_result(), score=80,
            link="https://l", log_tag="Steam",
        )
        self.assertIn("forte valor editorial", self.ctx.showcase_candidates[0]["reasons"])

        above_low = _offer(source="steam", offer_id="app_2", price=20.0,
                           original_price=90.0, discount_percent=78, lowest_price=9.0)
        self.publisher.publish(
            above_low, topic=topics.JOGOS, text="msg", result=_result(), score=80,
            link="https://l", log_tag="Steam",
        )
        self.assertEqual(len(self.ctx.showcase_candidates), 1)

    def test_affiliate_link_is_transparent_without_tracking(self):
        offer = _offer()
        self.assertEqual(self.publisher.affiliate_link(offer), "https://loja/1")
        self.assertEqual(self.publisher.affiliate_link(offer, "https://awin"), "https://awin")


class DataPathTest(unittest.TestCase):
    def test_defaults_to_cwd(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop("K4PROMO_DATA_DIR", None)
            self.assertEqual(paths.data_path("seen.json"), Path.cwd() / "seen.json")

    def test_env_override(self):
        with mock.patch.dict(os.environ, {"K4PROMO_DATA_DIR": "/tmp/k4"}):
            self.assertEqual(paths.data_path("seen.json"), Path("/tmp/k4") / "seen.json")


class CycleContextTest(unittest.TestCase):
    def test_reset_clears_only_cycle_queues(self):
        ctx = CycleContext(cfg=_cfg(), seen={"a": "t"})
        ctx.plus_candidates.append({"x": 1})
        ctx.showcase_candidates.append({"y": 2})
        ctx.reset_cycle_queues()
        self.assertEqual(ctx.plus_candidates, [])
        self.assertEqual(ctx.showcase_candidates, [])
        self.assertEqual(ctx.seen, {"a": "t"})


if __name__ == "__main__":
    unittest.main()
