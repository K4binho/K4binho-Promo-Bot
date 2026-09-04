import unittest

from k4promo import telegram


class FormatDigestTest(unittest.TestCase):
    def test_digest_with_items(self):
        items = [
            {"title": "SSD Kingston 1TB", "price": 289.90, "source": "ml", "link": "https://example.com/1"},
            {"title": "Ryzen 7 5800X", "price": 1099.00, "source": "ml", "link": "https://example.com/2"},
            {"title": "Cyberpunk 2077", "price": 65.67, "source": "steam", "link": ""},
        ]
        text = telegram.format_digest(items)
        self.assertIn("TOP OFERTAS DO DIA", text)
        self.assertIn("1.", text)
        self.assertIn("2.", text)
        self.assertIn("3.", text)
        self.assertIn("SSD Kingston 1TB", text)
        self.assertIn("R$ 289,90", text)
        self.assertIn("ML", text)
        self.assertIn("STEAM", text)

    def test_digest_with_link(self):
        items = [
            {"title": "Produto X", "price": 100.0, "source": "ml", "link": "https://example.com/x"},
        ]
        text = telegram.format_digest(items)
        self.assertIn("href=", text)

    def test_digest_without_link(self):
        items = [
            {"title": "Produto Y", "price": 50.0, "source": "steam", "link": ""},
        ]
        text = telegram.format_digest(items)
        self.assertNotIn("href=", text)
        self.assertIn("Produto Y", text)

    def test_digest_empty(self):
        text = telegram.format_digest([])
        self.assertIn("TOP OFERTAS DO DIA", text)


class FormatPriceDropTest(unittest.TestCase):
    def test_price_drop_template(self):
        text = telegram.format_price_drop(
            title="SSD Kingston 1TB",
            price=349.00,
            previous_price=399.00,
            link="https://example.com/ssd",
        )
        self.assertIn("CAIU MAIS", text)
        self.assertIn("R$ 349,00", text)
        self.assertIn("R$ 399,00", text)
        self.assertIn("R$ 50,00", text)
        self.assertIn("VER NOVO PREÇO", text)


if __name__ == "__main__":
    unittest.main()
