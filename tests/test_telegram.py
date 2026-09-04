import unittest

from k4promo import telegram


class FormatDealTest(unittest.TestCase):
    def test_normal_deal_no_history(self):
        text = telegram.format_deal(
            title="SSD Kingston 1TB",
            price=289.90,
            original_price=399.90,
            discount=27,
            link="https://example.com/ssd",
        )
        self.assertIn("SSD Kingston 1TB", text)
        self.assertIn("27% OFF", text)
        self.assertIn("VER OFERTA", text)
        self.assertNotIn("MENOR PREÇO", text)
        self.assertNotIn("abaixo da média", text)

    def test_lowest_price_header(self):
        text = telegram.format_deal(
            title="Monitor LG 27",
            price=799.0,
            original_price=1199.0,
            discount=33,
            link="https://example.com/monitor",
            min_price_30d=799.0,
            avg_price_30d=999.0,
            history_confidence="high",
        )
        self.assertIn("MENOR PREÇO MONITORADO", text)

    def test_below_average_shown(self):
        text = telegram.format_deal(
            title="Mouse Logitech",
            price=150.0,
            original_price=200.0,
            discount=25,
            link="https://example.com/mouse",
            min_price_30d=140.0,
            avg_price_30d=180.0,
            history_confidence="medium",
        )
        self.assertIn("abaixo da média", text)

    def test_low_confidence_hides_history(self):
        text = telegram.format_deal(
            title="Teclado",
            price=100.0,
            original_price=150.0,
            discount=33,
            link="https://example.com/kb",
            min_price_30d=100.0,
            avg_price_30d=130.0,
            history_confidence="low",
        )
        self.assertNotIn("MENOR PREÇO", text)
        self.assertNotIn("abaixo da média", text)

    def test_coupon_shown(self):
        text = telegram.format_deal(
            title="Produto X",
            price=50.0,
            original_price=80.0,
            discount=37,
            link="https://example.com/x",
            coupon_amount=10.0,
        )
        self.assertIn("Cupom", text)

    def test_selos(self):
        text = telegram.format_deal(
            title="Produto Y",
            price=100.0,
            original_price=200.0,
            discount=50,
            link="https://example.com/y",
            sales_count=5000,
            rating=4.8,
            official_store=True,
            offer_label="OFERTA DO DIA",
        )
        self.assertIn("Loja oficial", text)
        self.assertIn("4.8", text)
        self.assertIn("5mil+", text)
        self.assertIn("OFERTA DO DIA", text)


class FormatGameDealTest(unittest.TestCase):
    def test_steam_plus_header(self):
        text = telegram.format_game_deal(
            title="Cyberpunk 2077",
            price=65.67,
            original_price=199.0,
            discount=67,
            link="https://store.steampowered.com/app/1091500",
        )
        self.assertIn("PLUS", text)
        self.assertIn("STEAM", text)
        self.assertIn("VER NA STEAM", text)

    def test_lowest_historical(self):
        text = telegram.format_game_deal(
            title="RDR2",
            price=74.97,
            original_price=299.0,
            discount=75,
            link="https://store.steampowered.com/app/1174180",
            lowest_price=74.97,
        )
        self.assertIn("Menor preço histórico", text)

    def test_custom_source(self):
        text = telegram.format_game_deal(
            title="Game X",
            price=30.0,
            original_price=60.0,
            discount=50,
            link="https://example.com",
            source="GOG",
        )
        self.assertIn("PLUS", text)
        self.assertIn("GOG", text)


class FormatNuuvemDealTest(unittest.TestCase):
    def test_nuuvem_plus_header(self):
        text = telegram.format_nuuvem_deal(
            title="Hollow Knight",
            price=14.99,
            original_price=29.99,
            discount=50,
            link="https://www.nuuvem.com/item/hollow-knight",
        )
        self.assertIn("PLUS", text)
        self.assertIn("NUUVEM", text)
        self.assertIn("VER NA NUUVEM", text)

    def test_coupon(self):
        text = telegram.format_nuuvem_deal(
            title="Game Y",
            price=20.0,
            original_price=40.0,
            discount=50,
            link="https://example.com",
            coupon_code="SAVE10",
            coupon_discount="10%",
        )
        self.assertIn("SAVE10", text)
        self.assertIn("10%", text)


class FormatAliexpressDealTest(unittest.TestCase):
    def test_aliexpress_header(self):
        text = telegram.format_aliexpress_deal(
            title="Cabo USB-C",
            price=15.0,
            original_price=30.0,
            discount=50,
            link="https://s.click.aliexpress.com/xxx",
        )
        self.assertIn("ALIEXPRESS", text)
        self.assertIn("VER OFERTA", text)

    def test_sales_shown(self):
        text = telegram.format_aliexpress_deal(
            title="Item Z",
            price=10.0,
            original_price=20.0,
            discount=50,
            link="https://example.com",
            sales_count=3000,
        )
        self.assertIn("3mil+", text)


class FormatGmgDealTest(unittest.TestCase):
    def test_gmg_plus_header(self):
        text = telegram.format_gmg_deal(
            title="Elden Ring",
            price=99.0,
            original_price=199.0,
            discount=50,
            link="https://www.greenmangaming.com/xxx",
        )
        self.assertIn("PLUS", text)
        self.assertIn("GREEN MAN GAMING", text)
        self.assertIn("VER OFERTA", text)

    def test_promo_code(self):
        text = telegram.format_gmg_deal(
            title="Game W",
            price=40.0,
            original_price=80.0,
            discount=50,
            link="https://example.com",
            promo_code="GMG20",
            promo_description="20% extra",
        )
        self.assertIn("GMG20", text)
        self.assertIn("20% extra", text)


if __name__ == "__main__":
    unittest.main()
