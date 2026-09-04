"""KaBuM! — ofertas via API pública de catálogo + link afiliado Awin.

A página https://www.kabum.com.br/ofertas é renderizada no cliente; o HTML
servido não traz os produtos. A listagem é alimentada por
``servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products`` (mesma
chamada que o site faz), que devolve preço, oferta ativa, fotos, avaliação e
frete grátis por item. Este módulo consome essa API diretamente.

Semântica de preço observada na resposta (2026-09-03):

- ``price``: preço de tabela (parcelado);
- ``price_with_discount``: preço à vista/pix do preço de tabela (~10 % off);
- ``offer``: quando existe, é a oferta ativa, com ``offer.price`` (preço em
  oferta) e ``offer.price_with_discount`` (à vista da oferta) e ``ends_at``;
- ``old_price``: preço riscado, quando o site exibe "de/por".

O desconto real usado pelo bot compara o preço à vista final com o preço de
tabela. Itens sem ``offer`` e sem ``old_price`` só têm o desconto pix e caem
no filtro de desconto mínimo.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import httpx

log = logging.getLogger("k4binho")

OFERTAS_URL = "https://www.kabum.com.br/ofertas"
CATALOG_URL = "https://servicespub.prod.api.aws.grupokabum.com.br/catalog/v2/products"
# Awin Publisher API (Link Builder). Autenticação por header Bearer.
AWIN_LINK_URL = "https://api.awin.com/publishers/{publisher_id}/linkbuilder/generate"
KABUM_ADVERTISER_ID = 17729

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Accept-Language": "pt-BR,pt;q=0.9",
    "Origin": "https://www.kabum.com.br",
    "Referer": OFERTAS_URL,
}


@dataclass
class KabumDeal:
    product_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str
    image_url: str
    free_shipping: bool = False
    rating: float | None = None
    rating_count: int = 0
    offer_name: str = ""
    offer_ends_at: int | None = None


def _to_float(raw) -> float | None:
    if raw is None or raw == "":
        return None
    try:
        return float(raw)
    except (TypeError, ValueError):
        return None


def _first_photo(attrs: dict) -> str:
    photos = attrs.get("photos") or {}
    if isinstance(photos, dict):
        for size in ("g", "m", "p"):
            urls = photos.get(size) or []
            if urls:
                return str(urls[0])
    images = attrs.get("images") or []
    if isinstance(images, list) and images:
        first = images[0]
        if isinstance(first, str):
            return first
        if isinstance(first, dict):
            return str(first.get("url") or first.get("src") or "")
    return ""


def _slugify(title: str) -> str:
    import re
    import unicodedata

    norm = unicodedata.normalize("NFKD", title.lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    norm = re.sub(r"[^a-z0-9]+", "-", norm).strip("-")
    return norm[:120] or "produto"


def parse_products(payload: dict) -> list[KabumDeal]:
    """Converte a resposta da API de catálogo em ``KabumDeal``. Não aplica
    filtro de desconto; o chamador decide o mínimo."""
    deals: list[KabumDeal] = []
    for item in (payload or {}).get("data") or []:
        if not isinstance(item, dict):
            continue
        attrs = item.get("attributes") or {}
        product_id = str(item.get("id") or attrs.get("code") or "").strip()
        title = str(attrs.get("title") or "").strip()
        if not product_id or not title:
            continue
        if attrs.get("available") is False:
            continue

        list_price = _to_float(attrs.get("price")) or 0.0
        cash_price = _to_float(attrs.get("price_with_discount")) or list_price
        old_price = _to_float(attrs.get("old_price")) or 0.0
        offer = attrs.get("offer") or {}
        offer_name = ""
        offer_ends_at = None
        if isinstance(offer, dict) and offer:
            offer_cash = _to_float(offer.get("price_with_discount"))
            offer_price = _to_float(offer.get("price"))
            cash_price = offer_cash or offer_price or cash_price
            offer_name = str(offer.get("name") or "")
            ends = offer.get("ends_at")
            offer_ends_at = int(ends) if isinstance(ends, (int, float)) else None

        if cash_price <= 0:
            continue

        original: float | None = None
        reference = max(old_price, list_price)
        if reference > cash_price:
            original = reference
            discount = round((reference - cash_price) / reference * 100)
        else:
            discount = int(_to_float(attrs.get("discount_percentage")) or 0)

        link = str(attrs.get("product_link") or "").strip()
        if not link.startswith("http"):
            link = f"https://www.kabum.com.br/produto/{product_id}/{_slugify(title)}"

        rating = _to_float(attrs.get("average_of_ratings") or attrs.get("score_of_ratings"))
        if rating is not None and rating <= 0:
            rating = None

        deals.append(KabumDeal(
            product_id=product_id,
            title=title,
            price=cash_price,
            original_price=original,
            discount_percent=max(0, discount),
            permalink=link,
            image_url=_first_photo(attrs),
            free_shipping=bool(attrs.get("has_free_shipping")),
            rating=rating,
            rating_count=int(_to_float(attrs.get("number_of_ratings")) or 0),
            offer_name=offer_name,
            offer_ends_at=offer_ends_at,
        ))
    return deals


def fetch_deals(
    min_discount: int = 10,
    *,
    pages: int = 3,
    page_size: int = 100,
    sort: str = "most_searched",
) -> list[KabumDeal]:
    """Busca `pages` páginas do catálogo e devolve só itens com desconto real
    >= ``min_discount``, ordenados do maior desconto para o menor."""
    deals: list[KabumDeal] = []
    seen: set[str] = set()
    for page in range(1, max(1, pages) + 1):
        params = {
            "page_number": page,
            "page_size": page_size,
            "facet_filters": "",
            "sort": sort,
            "is_prime": "false",
            "payload_data": "products_all_filters",
        }
        try:
            resp = httpx.get(CATALOG_URL, params=params, headers=HEADERS, timeout=30)
            resp.raise_for_status()
            payload = resp.json()
        except (httpx.HTTPError, ValueError) as exc:
            log.error("[Kabum] catalogo pagina %d: %s", page, exc)
            break
        batch = parse_products(payload)
        if not batch:
            break
        for d in batch:
            if d.product_id in seen:
                continue
            seen.add(d.product_id)
            if d.discount_percent >= min_discount:
                deals.append(d)
        meta = (payload.get("meta") or {}).get("total_pages_count")
        if isinstance(meta, int) and page >= meta:
            break

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals


# Nome antigo mantido por compatibilidade com o ciclo do bot.
scrape_deals = fetch_deals


def generate_affiliate_link(
    awin_token: str,
    publisher_id: int,
    destination_url: str,
) -> str | None:
    if not awin_token or not publisher_id:
        return None
    try:
        resp = httpx.post(
            AWIN_LINK_URL.format(publisher_id=publisher_id),
            json={
                "advertiserId": KABUM_ADVERTISER_ID,
                "destinationUrl": destination_url,
                "shorten": True,
            },
            headers={
                "Authorization": f"Bearer {awin_token}",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
        if resp.status_code != 200:
            log.warning("[Kabum] Awin link builder %d: %s", resp.status_code, resp.text[:200])
            return None
        data = resp.json()
        return data.get("shortUrl") or data.get("url")
    except httpx.HTTPError as exc:
        log.error("[Kabum] Awin link builder: %s", exc)
        return None
