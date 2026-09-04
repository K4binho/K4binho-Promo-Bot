import os
import unittest
from unittest import mock

from k4promo import config
from k4promo.providers import gmg as gmg_impact
from k4promo.domain import topics


class ConfigTopicsTest(unittest.TestCase):
    def test_default_topic_ids(self):
        with mock.patch.dict(os.environ, {}, clear=False):
            for key in list(os.environ):
                if key.startswith("TELEGRAM_TOPIC_"):
                    os.environ.pop(key)
            cfg = config.Config()
        self.assertEqual(cfg.topic_thread_id(topics.JOGOS), 2195)
        self.assertEqual(cfg.topic_thread_id(topics.MELHORES_DO_DIA), 2194)

    def test_topic_override_and_disable(self):
        env = {"TELEGRAM_TOPIC_JOGOS": "999", "TELEGRAM_TOPIC_ACHADINHOS": "0", "TELEGRAM_THREAD_ID": "112"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = config.Config()
        self.assertEqual(cfg.topic_thread_id(topics.JOGOS), 999)
        self.assertEqual(cfg.topic_thread_id(topics.ACHADINHOS), 112)

    def test_impact_aliases(self):
        env = {"IMPACT_ACCOUNT_SID": "", "IMPACT_AUTH_TOKEN": "", "CJ_ACCOUNT_SID": "legacy-sid", "CJ_AUTH_TOKEN": "legacy-token"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = config.Config()
        self.assertEqual(cfg.impact_account_sid, "legacy-sid")
        self.assertEqual(cfg.cj_account_sid, "legacy-sid")
        self.assertEqual(cfg.cj_auth_token, "legacy-token")

        env = {"IMPACT_ACCOUNT_SID": "new-sid", "CJ_ACCOUNT_SID": "legacy-sid"}
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = config.Config()
        self.assertEqual(cfg.impact_account_sid, "new-sid")

    def test_kabum_and_shopee_config(self):
        env = {
            "KABUM_AWIN_TOKEN": "tok", "KABUM_PUBLISHER_ID": "4242",
            "SHOPEE_APP_ID": "id", "SHOPEE_APP_SECRET": "sec",
            "SHOPEE_SEARCHES": "cozinha, moda feminina,",
        }
        with mock.patch.dict(os.environ, env, clear=False):
            cfg = config.Config()
        self.assertEqual(cfg.kabum_awin_token, "tok")
        self.assertEqual(cfg.kabum_publisher_id, 4242)
        self.assertEqual(cfg.shopee_searches, ["cozinha", "moda feminina"])


class GmgImpactModuleTest(unittest.TestCase):
    @mock.patch.object(gmg_impact, "_get")
    def test_catalog_pagination_and_currency_filter(self, get):
        get.side_effect = [
            {"Items": [{"Id": "1", "Currency": "BRL"}, {"Id": "2", "Currency": "USD"}], "@nextpageuri": "/next"},
            {"Items": [{"Id": "3", "Currency": "BRL"}]},
        ]
        items = gmg_impact.fetch_catalog_items("sid", "tok", "cat", currency="BRL", page_size=2, max_pages=5)
        self.assertEqual([i["Id"] for i in items], ["1", "3"])
        self.assertEqual(get.call_count, 2)
        self.assertEqual(get.call_args_list[0].kwargs["Page"], 1)
        self.assertEqual(get.call_args_list[1].kwargs["Page"], 2)


if __name__ == "__main__":
    unittest.main()
