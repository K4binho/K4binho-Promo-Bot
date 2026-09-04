import unittest
from unittest import mock

import httpx
from k4promo.providers import steam


class SteamPackageParsingTest(unittest.TestCase):
    def test_parses_package_sale_with_real_sub_url(self):
        html = '''
        <a href="https://store.steampowered.com/sub/123456/?snr=1" data-ds-packageid="123456" data-ds-appid="632470,870780">
          <span class="title">Pacote Disco Elysium + Control</span>
          <div class="discount_pct">-90%</div>
          <div class="discount_original_price">R$ 89,99</div>
          <div class="discount_final_price">R$ 8,99</div>
          <img src="https://example.com/package.jpg">
        </a>
        '''
        deals = steam._parse_results_html(html)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.store_type, "sub")
        self.assertEqual(d.store_id, "123456")
        self.assertEqual(d.game_id, "sub_123456")
        self.assertEqual(d.price, 8.99)
        self.assertEqual(d.original_price, 89.99)
        self.assertEqual(d.discount_percent, 90)
        self.assertEqual(d.permalink, "https://store.steampowered.com/sub/123456/")

    def test_parses_bundle_sale(self):
        html = '''
        <a href="https://store.steampowered.com/bundle/98765/Bundle_Name/" data-ds-bundleid="98765">
          <span class="title">Bundle Teste</span>
          <div class="discount_pct">-80%</div>
          <div class="discount_original_price">R$ 100,00</div>
          <div class="discount_final_price">R$ 20,00</div>
        </a>
        '''
        d = steam._parse_results_html(html)[0]
        self.assertEqual(d.store_type, "bundle")
        self.assertEqual(d.game_id, "bundle_98765")
        self.assertEqual(d.permalink, "https://store.steampowered.com/bundle/98765/Bundle_Name/")

    def test_app_behavior_is_preserved(self):
        html = '''
        <a href="https://store.steampowered.com/app/111/Test/" data-ds-appid="111">
          <span class="title">App Teste</span>
          <div class="discount_pct">-50%</div>
          <div class="discount_original_price">R$ 40,00</div>
          <div class="discount_final_price">R$ 20,00</div>
        </a>
        '''
        d = steam._parse_results_html(html)[0]
        self.assertEqual(d.store_type, "app")
        self.assertEqual(d.game_id, "111")
        self.assertEqual(d.header_image, "https://cdn.akamai.steamstatic.com/steam/apps/111/header.jpg")

    @mock.patch.object(steam.httpx, "get")
    def test_enrich_skips_package_without_fake_reviews(self, get):
        d = steam.GameDeal(
            game_id="sub_123", title="Pacote", price=8.99,
            original_price=89.99, discount_percent=90,
            permalink="https://store.steampowered.com/sub/123/", header_image="",
            store_type="sub", store_id="123",
        )
        steam.enrich("key", [d])
        get.assert_not_called()
        self.assertIsNone(d.review_score)
        self.assertIsNone(d.review_count)


if __name__ == "__main__":
    unittest.main()


class _FakeResponse:
    def __init__(self, *, json_data=None, text="", status_code=200):
        self._json_data = json_data
        self.text = text
        self.status_code = status_code

    def json(self):
        return self._json_data

    def raise_for_status(self):
        if self.status_code >= 400:
            request = httpx.Request("GET", "https://store.steampowered.com/")
            response = httpx.Response(self.status_code, request=request)
            raise httpx.HTTPStatusError("error", request=request, response=response)


class SteamBundleDiscoveryTest(unittest.TestCase):
    @mock.patch.object(steam.httpx, "get")
    def test_discovers_bundle_id_from_discounted_app_page(self, get):
        get.return_value = _FakeResponse(text='''
            <div class="game_area_purchase_game_wrapper" data-ds-bundleid="23667">
              <a href="https://store.steampowered.com/bundle/23667/Disco_Control/">Comprar bundle</a>
            </div>
        ''')
        seed = steam.GameDeal(
            game_id="632470", title="Disco Elysium", price=8.99,
            original_price=89.99, discount_percent=90,
            permalink="https://store.steampowered.com/app/632470/Disco_Elysium/",
            header_image="", store_type="app", store_id="632470",
        )
        ids = steam._discover_bundle_ids_from_apps([seed])
        self.assertEqual(ids, {"23667"})

    def test_parses_resolved_real_world_bundle_shape(self):
        payload = [{
            "bundleid": 23667,
            "name": "Pacote Disco Elysium - The Final Cut + Control Ultimate Edition",
            "header_image_url": "https://example.com/header.jpg",
            "initial_price": 8999,
            "final_price": 899,
            "discount_percent": 90,
            "packageids": [1, 2],
            "appids": [632470, 870780],
        }]
        deals = steam._parse_resolved_bundles(payload)
        self.assertEqual(len(deals), 1)
        d = deals[0]
        self.assertEqual(d.game_id, "bundle_23667")
        self.assertEqual(d.store_type, "bundle")
        self.assertEqual(d.price, 8.99)
        self.assertEqual(d.original_price, 89.99)
        self.assertEqual(d.discount_percent, 90)
        self.assertEqual(d.permalink, "https://store.steampowered.com/bundle/23667/")

    @mock.patch.object(steam.httpx, "get")
    def test_fetch_specials_discovers_bundle_not_present_in_search_results(self, get):
        search_html = '''
        <a href="https://store.steampowered.com/app/632470/Disco_Elysium/" data-ds-appid="632470">
          <span class="title">Disco Elysium - The Final Cut</span>
          <div class="discount_pct">-75%</div>
          <div class="discount_original_price">R$ 75,99</div>
          <div class="discount_final_price">R$ 18,99</div>
        </a>
        '''
        app_html = '''
        <div data-ds-bundleid="23667">
          <a href="https://store.steampowered.com/bundle/23667/Disco_Control/">Bundle</a>
        </div>
        '''
        resolved = [{
            "bundleid": 23667,
            "name": "Pacote Disco Elysium - The Final Cut + Control Ultimate Edition",
            "header_image_url": "https://example.com/header.jpg",
            "initial_price": 8999,
            "final_price": 899,
            "discount_percent": 90,
        }]

        def fake_get(url, **kwargs):
            if url == steam.SEARCH_URL:
                return _FakeResponse(json_data={"results_html": search_html, "total_count": 1})
            if url == steam.BUNDLE_RESOLVE_URL:
                return _FakeResponse(json_data=resolved)
            if "/app/632470/" in url:
                return _FakeResponse(text=app_html)
            raise AssertionError(f"URL inesperada: {url}")

        get.side_effect = fake_get
        deals = steam.fetch_specials(country="BR", limit=500, bundle_scan_apps=8)
        by_id = {d.game_id: d for d in deals}
        self.assertIn("632470", by_id)
        self.assertIn("bundle_23667", by_id)
        self.assertEqual(by_id["bundle_23667"].price, 8.99)
        self.assertEqual(by_id["bundle_23667"].discount_percent, 90)

