"""Cobre o parser do catalogo Kabum (scrape_deals) e a geracao de link Awin.

A pagina de promocao e um app Next.js: os produtos nao existem no HTML
renderizado, so no payload JSON de `__NEXT_DATA__`. Estes testes fixam o
contrato desse payload (campos `code`, `priceWithDiscount`, `offer`) em vez
de classes CSS, que mudavam a cada deploy e zeravam a coleta.
"""
from unittest.mock import patch

import httpx

import kabum


class _Resp:
    def __init__(self, text="", status_code=200, payload=None):
        self.text = text
        self.status_code = status_code
        self._payload = payload

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("erro", request=None, response=None)


def _page(items):
    import json

    payload = {"props": {"pageProps": {"data": {"catalogServer": {"data": items}}}}}
    return _Resp(
        '<html><body><script id="__NEXT_DATA__" type="application/json">'
        + json.dumps(payload)
        + "</script></body></html>"
    )


_ITEM_WITH_OFFER = {
    "code": 905107,
    "name": "Suporte de Mesa Articulado para Monitor",
    "friendlyName": "suporte-de-mesa-articulado-para-monitor",
    "price": 188.88,
    "priceWithDiscount": 169.99,
    "oldPrice": 188.88,
    "discountPercentage": 10,
    "image": "https://images.kabum.com.br/produtos/fotos/905107/a.jpg",
    "offer": {"price": 88.88, "priceWithDiscount": 79.99, "discountPercentage": 52},
}

_ITEM_WITHOUT_OFFER = {
    "code": 172366,
    "name": "Memoria RAM Kingston Fury Beast 16GB",
    "friendlyName": "memoria-ram-kingston-fury-beast-16gb",
    "price": 1094.11,
    "priceWithDiscount": 929.99,
    "oldPrice": 0,
    "discountPercentage": 15,
    "image": "",
    "images": ["https://images.kabum.com.br/produtos/fotos/172366/b.jpg"],
    "offer": None,
}

_ITEM_FULL_PRICE = {
    "code": 870979,
    "name": "Starlink Mini",
    "friendlyName": "starlink-mini",
    "price": 799.9,
    "priceWithDiscount": 799.9,
    "oldPrice": 799.9,
    "discountPercentage": 0,
    "offer": None,
}


def test_scrape_deals_reads_products_from_next_data_payload():
    with patch.object(kabum.httpx, "get", return_value=_page([_ITEM_WITHOUT_OFFER])):
        deals = kabum.scrape_deals(min_discount=10)

    assert len(deals) == 1
    deal = deals[0]
    assert deal.product_id == "172366"
    assert deal.title == "Memoria RAM Kingston Fury Beast 16GB"
    assert deal.price == 929.99
    assert deal.original_price == 1094.11
    assert deal.discount_percent == 15
    assert deal.permalink == (
        "https://www.kabum.com.br/produto/172366/memoria-ram-kingston-fury-beast-16gb"
    )
    assert deal.image_url.endswith("172366/b.jpg")


def test_scrape_deals_prefers_timed_offer_price_over_generic_discount():
    # A oferta por tempo limitado (offer.priceWithDiscount = 79.99) e sempre
    # mais barata que o desconto geral do produto (169.99); anunciar o geral
    # seria prometer um preco pior que o real.
    with patch.object(kabum.httpx, "get", return_value=_page([_ITEM_WITH_OFFER])):
        deals = kabum.scrape_deals(min_discount=10)

    assert deals[0].price == 79.99
    assert deals[0].discount_percent == 58


def test_scrape_deals_filters_below_min_discount():
    with patch.object(kabum.httpx, "get", return_value=_page([_ITEM_FULL_PRICE])):
        assert kabum.scrape_deals(min_discount=10) == []


def test_scrape_deals_sorts_by_discount_desc_and_dedupes_by_code():
    items = [_ITEM_WITHOUT_OFFER, _ITEM_WITH_OFFER, dict(_ITEM_WITH_OFFER)]
    with patch.object(kabum.httpx, "get", return_value=_page(items)):
        deals = kabum.scrape_deals(min_discount=10)

    assert [d.product_id for d in deals] == ["905107", "172366"]


def test_scrape_deals_without_next_data_returns_empty():
    with patch.object(kabum.httpx, "get", return_value=_Resp("<html>bloqueado</html>")):
        assert kabum.scrape_deals() == []


def test_scrape_deals_http_error_returns_empty():
    with patch.object(kabum.httpx, "get", side_effect=httpx.ConnectTimeout("timeout")):
        assert kabum.scrape_deals() == []


def test_generate_affiliate_link_posts_to_awin_api_and_prefers_short_url():
    resp = _Resp(payload={"url": "https://www.awin1.com/cread.php?x=1",
                          "shortUrl": "https://tidd.ly/abc"})
    with patch.object(kabum.httpx, "post", return_value=resp) as post:
        link = kabum.generate_affiliate_link(
            "token", 3063407, "https://www.kabum.com.br/produto/1/x"
        )

    assert link == "https://tidd.ly/abc"
    url = post.call_args.args[0]
    assert url == "https://api.awin.com/publishers/3063407/linkbuilder/generate"
    body = post.call_args.kwargs["json"]
    assert body["advertiserId"] == kabum.KABUM_ADVERTISER_ID
    assert body["destinationUrl"] == "https://www.kabum.com.br/produto/1/x"


def test_ensure_affiliate_link_falls_back_to_direct_permalink():
    deal = kabum.KabumDeal(
        product_id="1", title="X", price=10.0, original_price=20.0,
        discount_percent=50, permalink="https://www.kabum.com.br/produto/1/x",
        image_url="",
    )
    with patch.object(kabum, "generate_affiliate_link", return_value=None):
        assert kabum.ensure_affiliate_link("t", 1, deal) == deal.permalink
