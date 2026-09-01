"""Kabum deals via scraping + Awin affiliate link generation."""

import logging
import re
from dataclasses import dataclass
from html import unescape

import httpx

log = logging.getLogger("k4binho")

OFERTAS_URL = "https://www.kabum.com.br/ofertas"
AWIN_LINK_URL = "https://www.awin1.com/publishers/{publisher_id}/linkbuilder/generate"
KABUM_ADVERTISER_ID = 17729

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
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


_PRODUCT_RE = re.compile(
    r'<a[^>]+href="(/produto/(\d+)/[^"]*)"[^>]*>.*?</a>',
    re.DOTALL,
)
_TITLE_RE = re.compile(r'class="[^"]*nameCard[^"]*"[^>]*>([^<]+)<')
_PRICE_RE = re.compile(r'class="[^"]*priceCard[^"]*"[^>]*>\s*R\$\s*([\d.,]+)')
_OLD_PRICE_RE = re.compile(r'class="[^"]*oldPriceCard[^"]*"[^>]*>\s*R\$\s*([\d.,]+)')
_DISCOUNT_RE = re.compile(r'class="[^"]*labelDiscount[^"]*"[^>]*>\s*(\d+)%')
_IMG_RE = re.compile(r'<img[^>]+src="(https://images\d*\.kabum\.com\.br/[^"]+)"')


def _parse_brl(value: str) -> float:
    cleaned = value.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def scrape_deals(min_discount: int = 10) -> list[KabumDeal]:
    try:
        resp = httpx.get(OFERTAS_URL, headers=HEADERS, timeout=30, follow_redirects=True)
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[Kabum] scrape: %s", exc)
        return []

    html = resp.text
    deals: list[KabumDeal] = []
    seen_ids: set[str] = set()

    cards = re.split(r'class="[^"]*productCard[^"]*"', html)
    for card in cards[1:]:
        link_m = re.search(r'href="/produto/(\d+)/([^"]*)"', card)
        if not link_m:
            continue
        product_id = link_m.group(1)
        if product_id in seen_ids:
            continue
        seen_ids.add(product_id)

        slug = link_m.group(2)
        permalink = f"https://www.kabum.com.br/produto/{product_id}/{slug}"

        title_m = _TITLE_RE.search(card)
        title = unescape(title_m.group(1).strip()) if title_m else ""

        price_m = _PRICE_RE.search(card)
        price = _parse_brl(price_m.group(1)) if price_m else 0.0
        if price <= 0:
            continue

        old_m = _OLD_PRICE_RE.search(card)
        original = _parse_brl(old_m.group(1)) if old_m else None

        disc_m = _DISCOUNT_RE.search(card)
        if disc_m:
            discount = int(disc_m.group(1))
        elif original and original > price:
            discount = round((original - price) / original * 100)
        else:
            discount = 0

        if discount < min_discount:
            continue

        img_m = _IMG_RE.search(card)
        image_url = img_m.group(1) if img_m else ""

        deals.append(KabumDeal(
            product_id=product_id,
            title=title,
            price=price,
            original_price=original,
            discount_percent=discount,
            permalink=permalink,
            image_url=image_url,
        ))

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals


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
