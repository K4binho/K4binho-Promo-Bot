import unittest

from k4promo.providers.mercadolivre.api import Deal
from k4promo.services import scoring


def make_deal(price=100.0, original=200.0, sales=0, rating=None,
              official=False, label=""):
    return Deal(
        item_id="MLB1",
        title="Produto Teste",
        price=price,
        original_price=original,
        permalink="https://x/p/MLB1",
        thumbnail="",
        sales_count=sales,
        rating=rating,
        official_store=official,
        offer_label=label,
    )


class ScoringTest(unittest.TestCase):
    def test_oferta_forte_pontua_alto(self):
        deal = make_deal(price=100, original=250, sales=10000, rating=4.8,
                         official=True, label="OFERTA DO DIA")
        r = scoring.score(deal, min_price_30d=100, obs_count=5,
                          is_best_seller=True, is_trending=True)
        self.assertGreaterEqual(r.total, 70)
        self.assertGreaterEqual(r.price_subtotal, 30)

    def test_sem_historico_nao_ganha_bonus_menor_preco(self):
        deal = make_deal(price=100, original=250)
        r = scoring.score(deal, min_price_30d=100, obs_count=1,
                          is_best_seller=False, is_trending=False)
        self.assertNotIn("menor preco 30d", " ".join(r.reasons))

    def test_com_historico_ganha_bonus_menor_preco(self):
        deal = make_deal(price=100, original=250)
        r = scoring.score(deal, min_price_30d=100, obs_count=scoring.MIN_HISTORY_OBS,
                          is_best_seller=False, is_trending=False)
        self.assertIn("menor preco 30d", " ".join(r.reasons))

    def test_sem_avaliacoes_penaliza(self):
        deal = make_deal(rating=None)
        r = scoring.score(deal, min_price_30d=None, obs_count=1,
                          is_best_seller=False, is_trending=False)
        self.assertIn("sem avaliacoes", " ".join(r.reasons))

    def test_trend_sozinho_nao_passa_gate_de_preco(self):
        deal = make_deal(price=100, original=105, sales=0, rating=None)
        r = scoring.score(deal, min_price_30d=None, obs_count=1,
                          is_best_seller=False, is_trending=True)
        self.assertLess(r.price_subtotal, 30)


if __name__ == "__main__":
    unittest.main()
