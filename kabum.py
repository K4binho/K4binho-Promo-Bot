"""Kabum deals via Next.js catalog payload + Awin affiliate link generation."""

import json
import logging
import re
from dataclasses import dataclass

import httpx

log = logging.getLogger("k4binho")

OFERTAS_URL = "https://www.kabum.com.br/promocao/maisvendidos"
AWIN_LINK_URL = "https://api.awin.com/publishers/{publisher_id}/linkbuilder/generate"
KABUM_ADVERTISER_ID = 17729

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_NEXT_DATA_RE = re.compile(
    r'<script id="__NEXT_DATA__" type="application/json">(.*?)</script>',
    re.DOTALL,
)


@dataclass
class KabumDeal:
    product_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str
    image_url: str


def _effective_price(item: dict) -> float:
    """A pagina aplica um desconto "geral" (priceWithDiscount) e, por cima,
    um desconto de oferta por tempo limitado (offer.priceWithDiscount), que
    quando presente e sempre o preco final mais baixo."""
    offer = item.get("offer") or {}
    offer_price = offer.get("priceWithDiscount")
    if offer_price:
        return float(offer_price)
    price_with_discount = item.get("priceWithDiscount")
    if price_with_discount:
        return float(price_with_discount)
    return float(item.get("price") or 0.0)


def _original_price(item: dict) -> float | None:
    original = item.get("price") or item.get("oldPrice")
    return float(original) if original else None


def _parse_item(item: dict) -> KabumDeal | None:
    product_id = str(item.get("code") or "")
    if not product_id:
        return None

    price = _effective_price(item)
    if price <= 0:
        return None

    original = _original_price(item)
    if original and original > price:
        discount = round((original - price) / original * 100)
    else:
        discount = 0

    friendly_name = item.get("friendlyName") or ""
    permalink = f"https://www.kabum.com.br/produto/{product_id}/{friendly_name}"

    images = item.get("images") or []
    image_url = item.get("image") or (images[0] if images else "")

    return KabumDeal(
        product_id=product_id,
        title=item.get("name") or "",
        price=price,
        original_price=original,
        discount_percent=discount,
        permalink=permalink,
        image_url=image_url,
    )


def scrape_deals(min_discount: int = 10) -> list[KabumDeal]:
    try:
        resp = httpx.get(OFERTAS_URL, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[Kabum] scrape: %s", exc)
        return []

    match = _NEXT_DATA_RE.search(resp.text)
    if not match:
        log.error("[Kabum] scrape: __NEXT_DATA__ nao encontrado no HTML")
        return []

    try:
        next_data = json.loads(match.group(1))
        items = next_data["props"]["pageProps"]["data"]["catalogServer"]["data"]
    except (json.JSONDecodeError, KeyError, TypeError) as exc:
        log.error("[Kabum] scrape: payload inesperado: %s", exc)
        return []

    deals: list[KabumDeal] = []
    seen_ids: set[str] = set()
    for item in items:
        deal = _parse_item(item)
        if deal is None or deal.product_id in seen_ids:
            continue
        if deal.discount_percent < min_discount:
            continue
        seen_ids.add(deal.product_id)
        deals.append(deal)

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals


def ensure_affiliate_link(awin_token: str, publisher_id: int, deal: "KabumDeal") -> str:
    """Garante link rastreado via Awin. Se a geracao falhar, mantem o link
    direto do produto em vez de descartar a oferta."""
    if not deal.permalink:
        return ""
    link = generate_affiliate_link(awin_token, publisher_id, deal.permalink)
    return link or deal.permalink


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
            params={"accessToken": awin_token},
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
