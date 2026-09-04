"""Provider Shopee Afiliados — normaliza productOfferV2/shopeeOfferV2 para o formato do bot.

Só cobre o programa de afiliados (não gestão de loja/vendedor). A API oficial
não expõe cupom de produto individual: o "melhor cupom" de um item vem do
catálogo manual (promotions.json, escopo `shopee`) somado às campanhas gerais
de `shopeeOfferV2`, quando a conta tiver acesso a esse recurso.
"""

from dataclasses import dataclass, field

import logging

import httpx

import shopee_api

log = logging.getLogger("k4binho")


@dataclass
class ShopeeDeal:
    item_id: str
    title: str
    price: float
    original_price: float
    discount_percent: int
    permalink: str
    affiliate_link: str
    image_url: str
    store: str
    store_id: str
    commission_rate: float
    sales_count: int
    rating: float
    category_ids: list[str] = field(default_factory=list)


def _to_float(raw, default: float = 0.0) -> float:
    try:
        return float(raw)
    except (TypeError, ValueError):
        return default


def _to_int(raw, default: int = 0) -> int:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return default


def _derive_original_price(price: float, discount_rate: float) -> float:
    """priceDiscountRate vem como fração (ex.: 0.15) — sem 'preço anterior' direto na API."""
    if price <= 0 or discount_rate <= 0 or discount_rate >= 1:
        return 0.0
    return round(price / (1 - discount_rate), 2)


def _parse_node(node: dict) -> ShopeeDeal | None:
    if not isinstance(node, dict):
        return None
    item_id = str(node.get("itemId") or "").strip()
    price = _to_float(node.get("price"))
    if not item_id or price <= 0:
        return None

    discount_rate = _to_float(node.get("priceDiscountRate"))
    # A API às vezes retorna a taxa em percentual (0-100) em vez de fração.
    if discount_rate > 1:
        discount_rate = discount_rate / 100
    original_price = _derive_original_price(price, discount_rate)
    discount_percent = round(discount_rate * 100) if discount_rate else 0

    link = node.get("offerLink") or node.get("productLink") or ""
    cat_ids = node.get("productCatIds") or []
    if not isinstance(cat_ids, list):
        cat_ids = [str(cat_ids)]

    return ShopeeDeal(
        item_id=item_id,
        title=str(node.get("productName") or ""),
        price=price,
        original_price=original_price,
        discount_percent=discount_percent,
        permalink=str(node.get("productLink") or link),
        affiliate_link=str(link),
        image_url=str(node.get("imageUrl") or ""),
        store=str(node.get("shopName") or ""),
        store_id=str(node.get("shopId") or ""),
        commission_rate=_to_float(node.get("commissionRate")) * 100
        if _to_float(node.get("commissionRate")) <= 1
        else _to_float(node.get("commissionRate")),
        sales_count=_to_int(node.get("sales")),
        rating=_to_float(node.get("ratingStar")),
        category_ids=[str(c) for c in cat_ids],
    )


def fetch_deals(
    app_id: str,
    secret: str,
    *,
    keywords: list[str] | None = None,
    page_size: int = 20,
    max_pages: int = 1,
) -> list[ShopeeDeal]:
    """Busca ofertas via productOfferV2 para uma lista de palavras-chave (ou geral, se vazia)."""
    if not (app_id and secret):
        return []

    deals: dict[str, ShopeeDeal] = {}
    terms = keywords or [""]
    for term in terms:
        for page in range(1, max_pages + 1):
            try:
                block = shopee_api.fetch_product_offers(
                    app_id, secret, keyword=term, page=page, limit=page_size
                )
            except (RuntimeError, httpx.HTTPError) as exc:
                log.error(
                    "[Shopee] falha ao buscar ofertas (termo=%r, pagina=%d): %s",
                    term, page, exc,
                )
                break
            nodes = block.get("nodes") or []
            for raw in nodes:
                deal = _parse_node(raw)
                if deal and deal.item_id not in deals:
                    deals[deal.item_id] = deal
            page_info = block.get("pageInfo") or {}
            if not page_info.get("hasNextPage") or not nodes:
                break

    return list(deals.values())


def fetch_platform_campaigns(app_id: str, secret: str) -> list[dict]:
    """Campanhas/cupons gerais da plataforma (shopeeOfferV2), quando suportado pela conta."""
    if not (app_id and secret):
        return []
    try:
        block = shopee_api.fetch_shopee_offers(app_id, secret)
    except (RuntimeError, httpx.HTTPError):
        return []
    return [n for n in (block.get("nodes") or []) if isinstance(n, dict)]


def ensure_affiliate_link(app_id: str, secret: str, deal: ShopeeDeal) -> str:
    """Garante link rastreado. Nunca troca silenciosamente por link sem tracking:
    se o `generateShortLink` falhar, mantém o link original da oferta."""
    if deal.affiliate_link:
        return deal.affiliate_link
    if not deal.permalink:
        return ""
    try:
        short_link = shopee_api.generate_short_link(app_id, secret, deal.permalink)
        return short_link or deal.permalink
    except (RuntimeError, httpx.HTTPError):
        return deal.permalink
