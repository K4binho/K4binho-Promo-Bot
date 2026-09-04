"""Cada loja tem nomes próprios para os mesmos campos; os adaptadores unificam."""

import unittest

from k4promo.providers import adapters
from k4promo.providers.aliexpress import AliDeal
from k4promo.providers.gmg import GmgDeal
from k4promo.providers.kabum import KabumDeal
from k4promo.providers.mercadolivre.api import Deal
from k4promo.providers.nuuvem import NuuvemCoupon, NuuvemDeal
from k4promo.providers.shopee import ShopeeDeal
from k4promo.providers.steam import GameDeal


class AdapterTest(unittest.TestCase):
    def test_mercadolivre(self):
        offer = adapters.from_mercadolivre(Deal(
            item_id="MLB123", title="SSD 1TB", price=289.9, original_price=599.9,
            permalink="https://ml/p/MLB123", thumbnail="https://img/ml",
            sales_count=1200, rating=4.8, official_store=True,
            offer_label="OFERTA DO DIA", coupon_amount=50.0, free_shipping=True,
        ))
        self.assertEqual(offer.source, "ml")
        self.assertEqual(offer.offer_id, "MLB123")
        self.assertEqual(offer.key, "MLB123")  # ML não usa prefixo
        self.assertEqual(offer.image_url, "https://img/ml")
        self.assertEqual(offer.discount_percent, 52)
        self.assertTrue(offer.official_store)
        self.assertTrue(offer.free_shipping)
        self.assertEqual(offer.coupon_amount, 50.0)
        self.assertEqual(offer.offer_label, "OFERTA DO DIA")

    def test_aliexpress(self):
        offer = adapters.from_aliexpress(AliDeal(
            product_id="9", title="Furadeira", price=150.0, original_price=300.0,
            discount_percent=50, permalink="https://a/9", image_url="https://img/a",
            commission_rate=5.0, sales_count=2000,
        ))
        self.assertEqual(offer.key, "aliexpress:9")
        self.assertEqual(offer.sales_count, 2000)
        self.assertEqual(offer.commission_rate, 5.0)

    def test_shopee(self):
        offer = adapters.from_shopee(ShopeeDeal(
            item_id="s1", title="Panela", price=39.9, original_price=79.9,
            discount_percent=50, permalink="https://s/1", image_url="https://img/s",
            sales_count=1500, rating=4.8, commission_rate=8.0, shop_name="Loja",
        ))
        self.assertEqual(offer.key, "shopee:s1")
        self.assertEqual(offer.rating, 4.8)
        self.assertEqual(offer.sales_count, 1500)

    def test_kabum(self):
        offer = adapters.from_kabum(KabumDeal(
            product_id="10", title="Mouse", price=89.9, original_price=199.9,
            discount_percent=55, permalink="https://k/10", image_url="https://img/k",
            free_shipping=True, rating=4.7, rating_count=12, offer_name="ESQUENTA",
        ))
        self.assertEqual(offer.key, "kabum:10")
        self.assertTrue(offer.free_shipping)
        self.assertEqual(offer.rating, 4.7)
        self.assertEqual(offer.offer_label, "ESQUENTA")

    def test_gmg(self):
        offer = adapters.from_gmg(GmgDeal(
            item_id="g1", title="Elden Ring", price=99.0, original_price=249.0,
            discount_percent=60.0, permalink="https://g/1", image_url="https://img/g",
            promo_code="GMG10", promo_description="10% extra",
        ))
        self.assertEqual(offer.key, "gmg:g1")
        self.assertEqual(offer.discount_percent, 60)
        self.assertIsInstance(offer.discount_percent, int)
        self.assertEqual(offer.promo_code, "GMG10")

    def test_steam(self):
        offer = adapters.from_steam(GameDeal(
            game_id="app_1", title="Hades", price=9.99, original_price=49.99,
            discount_percent=80, permalink="https://s/app/1",
            header_image="https://img/steam", lowest_price=8.99,
            review_score=97, review_count=5000, waitlisted=3000, store_type="app",
        ))
        self.assertEqual(offer.key, "steam:app_1")
        self.assertEqual(offer.image_url, "https://img/steam")
        self.assertEqual(offer.lowest_price, 8.99)
        self.assertEqual(offer.store_type, "app")
        self.assertEqual(offer.waitlisted, 3000)

    def test_nuuvem_coupon_becomes_promo_fields(self):
        offer = adapters.from_nuuvem(NuuvemDeal(
            game_id="n1", title="Cyberpunk", price=59.9, original_price=199.9,
            discount_percent=70, permalink="https://n/1", image_url="https://img/n",
            lowest_price=49.9, coupon=NuuvemCoupon(code="NUU10", discount="10%", game="", region="BR"),
            waitlisted=800, review_score=86, review_count=900,
        ))
        self.assertEqual(offer.key, "nuuvem:n1")
        self.assertEqual(offer.promo_code, "NUU10")
        self.assertEqual(offer.promo_description, "10%")

    def test_nuuvem_without_coupon(self):
        offer = adapters.from_nuuvem(NuuvemDeal(
            game_id="n2", title="Jogo", price=10.0, original_price=100.0,
            discount_percent=90, permalink="https://n/2", image_url="",
        ))
        self.assertEqual(offer.promo_code, "")
        self.assertEqual(offer.promo_description, "")

    def test_raw_is_preserved(self):
        deal = AliDeal("9", "t", 1.0, 2.0, 50, "u", "i", 1.0, 1)
        self.assertIs(adapters.from_aliexpress(deal).raw, deal)


class GateFunctionsAcceptOfferTest(unittest.TestCase):
    """Os portões das lojas de jogos leem só campos que o Offer também tem."""

    def test_steam_quality_gate(self):
        from k4promo.providers import steam
        offer = adapters.from_steam(GameDeal(
            game_id="a", title="t", price=1.0, original_price=2.0, discount_percent=50,
            permalink="u", header_image="", review_score=90, review_count=1000,
        ))
        self.assertTrue(steam.is_quality_game(offer, 80, 500))
        self.assertFalse(steam.is_quality_game(offer, 95, 500))

    def test_nuuvem_most_wanted_gate(self):
        from k4promo.providers import nuuvem
        offer = adapters.from_nuuvem(NuuvemDeal(
            game_id="a", title="t", price=1.0, original_price=2.0, discount_percent=50,
            permalink="u", image_url="", waitlisted=500,
        ))
        self.assertTrue(nuuvem.is_most_wanted(offer, 300))
        self.assertFalse(nuuvem.is_most_wanted(offer, 1000))


if __name__ == "__main__":
    unittest.main()
