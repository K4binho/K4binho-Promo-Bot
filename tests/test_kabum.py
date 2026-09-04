import unittest

from k4promo.providers import kabum


def _item(pid="948677", title="Mouse Gamer OP1", price=1111.10, cash=999.99, offer=None, old_price=0.0, **extra):
    attrs = {
        "title": title, "price": price, "price_with_discount": cash, "old_price": old_price,
        "discount_percentage": 10, "available": True, "has_free_shipping": True,
        "average_of_ratings": 4.7, "number_of_ratings": 12,
        "photos": {"p": ["https://images.kabum.com.br/p.jpg"], "g": ["https://images.kabum.com.br/g.jpg"]},
        "product_link": f"https://www.kabum.com.br/produto/{pid}/mouse-gamer-op1",
    }
    if offer is not None:
        attrs["offer"] = offer
    attrs.update(extra)
    return {"id": pid, "type": "product", "attributes": attrs}


class KabumParserTest(unittest.TestCase):
    def test_offer_price_and_real_discount(self):
        offer = {"name": "ESQUENTA 9DO9", "price": 566.66, "price_with_discount": 509.99,
                 "discount_percentage": 49, "ends_at": 1789131600}
        deals = kabum.parse_products({"data": [_item(offer=offer)]})
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.product_id, "948677")
        self.assertAlmostEqual(d.price, 509.99)
        self.assertAlmostEqual(d.original_price, 1111.10)
        self.assertEqual(d.discount_percent, 54)
        self.assertTrue(d.free_shipping)
        self.assertEqual(d.rating, 4.7)
        self.assertEqual(d.image_url, "https://images.kabum.com.br/g.jpg")
        self.assertEqual(d.offer_name, "ESQUENTA 9DO9")
        self.assertEqual(d.permalink, "https://www.kabum.com.br/produto/948677/mouse-gamer-op1")

    def test_only_pix_discount_is_small(self):
        deals = kabum.parse_products({"data": [_item()]})
        self.assertEqual(deals[0].discount_percent, 10)

    def test_old_price_when_no_offer(self):
        deals = kabum.parse_products({"data": [_item(price=100.0, cash=90.0, old_price=200.0)]})
        self.assertEqual(deals[0].discount_percent, 55)
        self.assertEqual(deals[0].original_price, 200.0)

    def test_skips_unavailable_and_garbage(self):
        deals = kabum.parse_products({"data": [_item(available=False), "x", {"id": "1", "attributes": {}}]})
        self.assertEqual(deals, [])

    def test_builds_link_when_missing(self):
        deals = kabum.parse_products({"data": [_item(product_link="", title="Placa-Mãe MSI A520M")]})
        self.assertEqual(deals[0].permalink, "https://www.kabum.com.br/produto/948677/placa-mae-msi-a520m")


if __name__ == "__main__":
    unittest.main()
