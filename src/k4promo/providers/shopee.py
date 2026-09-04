"""Shopee Afiliados (Open API GraphQL) — busca de ofertas com link afiliado.

Usa ``shopee_api.call`` (assinatura SHA256 já validada pelo self-test) e a
query ``productOfferV2`` da Shopee Affiliate Open API. Os nomes de campo
seguem a documentação pública da API; o parser é defensivo porque a resposta
real ainda precisa ser validada ao vivo com as credenciais da conta.

Sort types documentados: 1 = relevância, 2 = mais vendidos, 3 = preço desc,
4 = preço asc, 5 = maior comissão.
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

from k4promo.providers import shopee_api

log = logging.getLogger("k4binho")

SORT_RELEVANCE = 1
SORT_BEST_SELLING = 2
SORT_COMMISSION = 5


@dataclass
class ShopeeDeal:
    item_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str  # offerLink já é o link afiliado
    image_url: str
    sales_count: int = 0
    rating: float | None = None
    commission_rate: float = 0.0
    shop_name: str = ""


def _to_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(str(raw).replace(",", "."))
    except (TypeError, ValueError):
        return None


def _to_int(raw) -> int:
    value = _to_float(raw)
    return int(value) if value is not None else 0


def build_query(keyword: str, *, sort_type: int, page: int, limit: int) -> str:
    kw = json.dumps(keyword or "", ensure_ascii=False)
    return (
        "{productOfferV2(keyword:%s,sortType:%d,page:%d,limit:%d){"
        "nodes{itemId productName priceMin priceMax priceDiscountRate "
        "commissionRate sales imageUrl shopName ratingStar offerLink productLink}"
        "pageInfo{page limit hasNextPage}}}"
        % (kw, sort_type, page, limit)
    )


def parse_offers(nodes: list[dict]) -> list[ShopeeDeal]:
    deals: list[ShopeeDeal] = []
    for node in nodes or []:
        if not isinstance(node, dict):
            continue
        item_id = str(node.get("itemId") or "").strip()
        title = str(node.get("productName") or "").strip()
        link = str(node.get("offerLink") or "").strip()
        price = _to_float(node.get("priceMin"))
        if price is None:
            price = _to_float(node.get("priceMax"))
        if not item_id or not title or not link or price is None or price <= 0:
            continue

        discount = max(0, min(99, _to_int(node.get("priceDiscountRate"))))
        original: float | None = None
        if discount > 0:
            original = round(price / (1 - discount / 100), 2)

        rate = _to_float(node.get("commissionRate")) or 0.0
        # A API costuma devolver fração ("0.05"); normaliza para percentual.
        if 0 < rate <= 1:
            rate *= 100

        deals.append(ShopeeDeal(
            item_id=item_id,
            title=title,
            price=price,
            original_price=original,
            discount_percent=discount,
            permalink=link,
            image_url=str(node.get("imageUrl") or ""),
            sales_count=_to_int(node.get("sales")),
            rating=_to_float(node.get("ratingStar")),
            commission_rate=rate,
            shop_name=str(node.get("shopName") or ""),
        ))
    return deals


def fetch_deals(
    app_id: str,
    app_secret: str,
    *,
    keyword: str = "",
    sort_type: int = SORT_BEST_SELLING,
    page: int = 1,
    limit: int = 20,
) -> list[ShopeeDeal]:
    query = build_query(keyword, sort_type=sort_type, page=page, limit=limit)
    data = shopee_api.call(app_id, app_secret, query)
    payload = (data or {}).get("productOfferV2") or {}
    return parse_offers(payload.get("nodes") or [])
