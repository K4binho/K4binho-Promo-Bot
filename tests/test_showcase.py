import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

from k4promo import telegram
from k4promo.domain import topics
from k4promo.services import showcase
from k4promo.services.context import CycleContext
from k4promo.storage import showcase_store


def _cfg(**overrides):
    base = dict(
        telegram_bot_token="token",
        telegram_channel_id="channel",
        telegram_thread_id=None,
        telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        showcase_enabled=True,
        showcase_max_per_cycle=2,
        showcase_max_per_day=8,
        showcase_min_physical_discount=40,
        showcase_min_game_discount=70,
        click_tracking_enabled=False,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _ctx(**overrides):
    return CycleContext(cfg=_cfg(**overrides))


class ShowcaseStoreTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_test_showcase_state.json"
        self._orig = showcase_store.STATE_PATH
        showcase_store.STATE_PATH = self.tmp

    def tearDown(self):
        showcase_store.STATE_PATH = self._orig
        if self.tmp.exists():
            self.tmp.unlink()

    def test_mark_and_count_today(self):
        state = showcase_store.load_state()
        self.assertEqual(showcase_store.copies_today(state), 0)
        showcase_store.mark_copied(state, "ml:1")
        showcase_store.mark_copied(state, "ml:2")
        self.assertTrue(showcase_store.already_copied(state, "ml:1"))
        self.assertEqual(showcase_store.copies_today(state), 2)
        showcase_store.save_state(state)
        reloaded = showcase_store.load_state()
        self.assertTrue(showcase_store.already_copied(reloaded, "ml:2"))

    def test_prune_removes_old_entries(self):
        state = {"copied": {"old": (datetime.now(UTC) - timedelta(days=10)).isoformat()}}
        showcase_store.mark_copied(state, "new")
        showcase_store.prune(state)
        self.assertNotIn("old", state["copied"])
        self.assertIn("new", state["copied"])


class RegisterShowcaseTest(unittest.TestCase):
    def test_registers_only_eligible(self):
        ctx = _ctx()
        ok = showcase.register(
            ctx, key="ml:1", source="ml", topic=topics.TECNOLOGIA, score=80,
            text="🔥 <b>OFERTA</b>\n\nSSD", image_url="https://img", price=100,
            discount_percent=55,
        )
        weak = showcase.register(
            ctx, key="ml:2", source="ml", topic=topics.TECNOLOGIA, score=80,
            text="x", image_url="https://img", price=100, discount_percent=15,
        )
        self.assertTrue(ok)
        self.assertFalse(weak)
        self.assertEqual([c["key"] for c in ctx.showcase_candidates], ["ml:1"])

    def test_never_registers_from_showcase_itself(self):
        ctx = _ctx()
        self.assertFalse(showcase.register(
            ctx, key="ml:1", source="ml", topic=topics.MELHORES_DO_DIA, score=80,
            text="x", image_url="https://img", price=100, discount_percent=90,
        ))


class ShowcaseCycleTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(__file__).parent / "_test_showcase_cycle.json"
        self._orig = showcase_store.STATE_PATH
        showcase_store.STATE_PATH = self.tmp

    def tearDown(self):
        showcase_store.STATE_PATH = self._orig
        if self.tmp.exists():
            self.tmp.unlink()

    def _add(self, ctx, key, source, score, topic=topics.TECNOLOGIA, discount=60):
        return showcase.register(
            ctx, key=key, source=source, topic=topic, score=score,
            text=f"🔥 <b>OFERTA</b>\n\n📦 <b>{key}</b>", image_url="https://img",
            price=100 if source not in topics.GAME_STORES else 10,
            discount_percent=discount,
        )

    @mock.patch.object(showcase, "time")
    @mock.patch.object(telegram, "send_message")
    def test_copies_to_showcase_topic_with_store_priority(self, send_message, _time):
        ctx = _ctx(showcase_max_per_cycle=2)
        self.assertTrue(self._add(ctx, "ali:1", "aliexpress", score=95))
        self.assertTrue(self._add(ctx, "ml:1", "ml", score=70))
        self.assertTrue(self._add(ctx, "gmg:1", "gmg", score=99, topic=topics.JOGOS, discount=80))
        posted = showcase.run_cycle(ctx)
        self.assertEqual(posted, 2)
        calls = send_message.call_args_list
        # ML tem prioridade sobre Ali mesmo com score menor; GMG fica fora do orçamento.
        self.assertIn("ml:1", calls[0].args[2])
        self.assertIn("ali:1", calls[1].args[2])
        for call in calls:
            self.assertEqual(call.kwargs["thread_id"], 2194)
            self.assertIn("MELHORES DO DIA", call.args[2])
            # cabeçalho original removido: só um cabeçalho na cópia
            self.assertEqual(call.args[2].count("<b>OFERTA</b>"), 0)
            self.assertEqual(call.kwargs["image_url"], "https://img")

    @mock.patch.object(telegram, "send_message")
    def test_does_not_repeat_same_product(self, send_message):
        ctx = _ctx()
        self._add(ctx, "ml:1", "ml", score=70)
        self.assertEqual(showcase.run_cycle(ctx), 1)
        ctx.showcase_candidates.clear()
        self._add(ctx, "ml:1", "ml", score=70)
        self.assertEqual(showcase.run_cycle(ctx), 0)
        self.assertEqual(send_message.call_count, 1)

    @mock.patch.object(telegram, "send_message")
    def test_daily_cap(self, send_message):
        state = showcase_store.load_state()
        for i in range(8):
            showcase_store.mark_copied(state, f"old:{i}")
        showcase_store.save_state(state)
        ctx = _ctx(showcase_max_per_day=8)
        self._add(ctx, "ml:9", "ml", score=70)
        self.assertEqual(showcase.run_cycle(ctx), 0)
        send_message.assert_not_called()

    @mock.patch.object(telegram, "send_message")
    def test_dry_run_never_sends(self, send_message):
        ctx = _ctx()
        ctx.dry_run = True
        self._add(ctx, "ml:1", "ml", score=70)
        self.assertEqual(showcase.run_cycle(ctx), 0)
        send_message.assert_not_called()

    @mock.patch.object(telegram, "send_message")
    def test_disabled(self, send_message):
        ctx = _ctx(showcase_enabled=False)
        self._add(ctx, "ml:1", "ml", score=70)
        self.assertEqual(showcase.run_cycle(ctx), 0)
        send_message.assert_not_called()


class ShowcaseFormatTest(unittest.TestCase):
    def test_showcase_copy_has_single_header(self):
        original = telegram.format_deal(
            title="SSD 1TB", price=289.9, original_price=599.9, discount=52,
            link="https://x",
        )
        copy = telegram.format_showcase_copy(original, "📱 Tecnologia", "Mercado Livre")
        self.assertTrue(copy.startswith("🏆 <b>MELHORES DO DIA</b> · 📱 Tecnologia · Mercado Livre"))
        self.assertNotIn("OFERTA DESTAQUE", copy)
        self.assertIn("SSD 1TB", copy)
        self.assertIn("VER OFERTA", copy)


if __name__ == "__main__":
    unittest.main()
