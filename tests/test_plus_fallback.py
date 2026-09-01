import unittest
from types import SimpleNamespace
from unittest import mock

import bot
import gmg_cj
import nuuvem
import scoring
import steam


class PlusFallbackTest(unittest.TestCase):
    def setUp(self):
        bot._plus_candidates.clear()
        self.cfg = SimpleNamespace(
            plus_editorial_min_score=25,
            plus_editorial_hours_without=24,
            click_tracking_enabled=False,
            telegram_bot_token="token",
            telegram_channel_id="channel",
        )
        self.result = scoring.score_game(
            title="Jogo Teste", price=9.0, original_price=90.0,
            discount_percent=90, source="steam",
        )

    def _candidate(self, score=30, source="steam", seen_key="steam:1"):
        return {
            "score": score,
            "source": source,
            "seen_key": seen_key,
            "title": "Jogo Teste",
            "price": 9.0,
            "original_price": 90.0,
            "discount_percent": 90,
            "link": "https://example.com/game",
            "lowest_price": None,
            "image_url": "",
            "game_id": "1",
            "result": self.result,
            "thread_id": None,
        }

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=30)
    @mock.patch.object(bot.analytics, "record_deal")
    @mock.patch.object(bot.telegram, "send_message")
    def test_publishes_candidate_above_editorial_floor(self, send_message, record_deal, _hours):
        bot._plus_candidates.append(self._candidate(score=30))
        seen = {}
        posted = bot.run_plus_fallback(self.cfg, seen, {}, dry_run=False)
        self.assertEqual(posted, 1)
        self.assertIn("steam:1", seen)
        send_message.assert_called_once()
        self.assertEqual(record_deal.call_args.kwargs["action_reason"], "plus_editorial_fallback")
        self.assertEqual(record_deal.call_args.kwargs["deal_type"], "plus")

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=30)
    @mock.patch.object(bot.telegram, "send_message")
    def test_rejects_candidate_below_editorial_floor(self, send_message, _hours):
        bot._plus_candidates.append(self._candidate(score=24))
        posted = bot.run_plus_fallback(self.cfg, {}, {}, dry_run=False)
        self.assertEqual(posted, 0)
        send_message.assert_not_called()

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=3)
    @mock.patch.object(bot.telegram, "send_message")
    def test_does_not_use_fallback_when_plus_was_recent(self, send_message, _hours):
        bot._plus_candidates.append(self._candidate(score=50))
        posted = bot.run_plus_fallback(self.cfg, {}, {}, dry_run=False)
        self.assertEqual(posted, 0)
        send_message.assert_not_called()

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=30)
    @mock.patch.object(bot.telegram, "send_message")
    def test_respects_seen(self, send_message, _hours):
        bot._plus_candidates.append(self._candidate(score=50))
        posted = bot.run_plus_fallback(self.cfg, {"steam:1": "2026-08-31T00:00:00+00:00"}, {}, dry_run=False)
        self.assertEqual(posted, 0)
        send_message.assert_not_called()

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=30)
    @mock.patch.object(bot.telegram, "send_message")
    def test_dry_run_never_sends(self, send_message, _hours):
        bot._plus_candidates.append(self._candidate(score=50))
        posted = bot.run_plus_fallback(self.cfg, {}, {}, dry_run=True)
        self.assertEqual(posted, 0)
        send_message.assert_not_called()

    @mock.patch.object(bot, "_last_plus_publish_hours_ago", return_value=30)
    @mock.patch.object(bot.analytics, "record_deal")
    @mock.patch.object(bot.telegram, "send_message")
    def test_selects_highest_scored_candidate(self, send_message, record_deal, _hours):
        low = self._candidate(score=28, seen_key="steam:1")
        high = self._candidate(score=45, seen_key="steam:2")
        high["game_id"] = "2"
        high["title"] = "Melhor Jogo"
        bot._plus_candidates.extend([low, high])
        seen = {}
        posted = bot.run_plus_fallback(self.cfg, seen, {}, dry_run=False)
        self.assertEqual(posted, 1)
        self.assertIn("steam:2", seen)
        self.assertNotIn("steam:1", seen)
        self.assertEqual(record_deal.call_args.kwargs["title"], "Melhor Jogo")


class PlusCandidateCollectionTest(unittest.TestCase):
    def setUp(self):
        bot._plus_candidates.clear()

    @mock.patch.object(nuuvem, "is_most_wanted", return_value=False)
    @mock.patch.object(nuuvem, "enrich_with_popularity")
    @mock.patch.object(nuuvem, "fetch_deals")
    def test_nuuvem_collects_editorial_candidate_even_if_normal_gate_rejects(
        self, fetch_deals, _enrich, _wanted
    ):
        fetch_deals.return_value = [
            nuuvem.NuuvemDeal(
                game_id="n1", title="Nuuvem Deal", price=10.0,
                original_price=100.0, discount_percent=90,
                permalink="https://example.com/n1", image_url="",
                waitlisted=10,
            )
        ]
        cfg = SimpleNamespace(
            itad_api_key="key", nuuvem_min_discount_percent=20,
            nuuvem_min_waitlisted=300, nuuvem_max_posts_per_cycle=3,
            telegram_nuuvem_thread_id=None,
        )
        posted = bot.run_nuuvem_cycle(cfg, {}, {}, dry_run=True)
        self.assertEqual(posted, 0)
        self.assertEqual(len(bot._plus_candidates), 1)
        self.assertEqual(bot._plus_candidates[0]["source"], "nuuvem")


    @mock.patch.object(steam, "fetch_specials")
    def test_steam_discovered_bundle_enters_editorial_pool(self, fetch_specials):
        fetch_specials.return_value = [
            steam.GameDeal(
                game_id="bundle_23667",
                title="Pacote Disco Elysium - The Final Cut + Control Ultimate Edition",
                price=8.99, original_price=89.99, discount_percent=90,
                permalink="https://store.steampowered.com/bundle/23667/",
                header_image="https://example.com/header.jpg",
                store_type="bundle", store_id="23667",
            )
        ]
        cfg = SimpleNamespace(
            itad_api_key="", steam_bundle_scan_apps=24,
            steam_min_discount_percent=20, steam_min_review_score=80,
            steam_min_review_count=500, steam_min_waitlisted=1000,
            steam_max_posts_per_cycle=3, telegram_steam_thread_id=None,
        )
        posted = bot.run_steam_cycle(cfg, {}, {}, dry_run=True)
        self.assertEqual(posted, 0)
        self.assertEqual(len(bot._plus_candidates), 1)
        c = bot._plus_candidates[0]
        self.assertEqual(c["seen_key"], "steam:bundle_23667")
        self.assertEqual(c["discount_percent"], 90)
        self.assertGreaterEqual(c["score"], 25)
        fetch_specials.assert_called_once_with("", bundle_scan_apps=24)

    @mock.patch.object(gmg_cj, "fetch_promo_codes", return_value=[])
    @mock.patch.object(gmg_cj, "fetch_catalog_items")
    def test_gmg_collects_below_normal_discount_for_editorial_fallback(self, fetch_items, _codes):
        fetch_items.return_value = [{
            "CatalogItemId": "g1", "Name": "GMG Deal", "CurrentPrice": 10,
            "OriginalPrice": 100, "DiscountPercentage": 25,
            "Url": "https://example.com/g1", "ImageUrl": "",
        }]
        cfg = SimpleNamespace(
            cj_account_sid="sid", cj_auth_token="token", gmg_program_id="p",
            gmg_catalog_id="c", gmg_min_discount_percent=30,
            gmg_max_posts_per_cycle=3, telegram_gmg_thread_id=None,
        )
        posted = bot.run_gmg_cycle(cfg, {}, {}, dry_run=True)
        self.assertEqual(posted, 0)
        self.assertEqual(len(bot._plus_candidates), 1)
        self.assertEqual(bot._plus_candidates[0]["source"], "gmg")


if __name__ == "__main__":
    unittest.main()
