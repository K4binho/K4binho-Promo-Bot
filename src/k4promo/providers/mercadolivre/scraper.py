import re
from html import unescape

import httpx

from k4promo.providers.mercadolivre.api import Deal

OFERTAS_URL = "https://www.mercadolivre.com.br/ofertas"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "pt-BR,pt;q=0.9",
}

_CARD_RE = re.compile(r'class="[^"]*poly-card[^"]*"')
_LINK_RE = re.compile(r'class="poly-component__title"[^>]*href="([^"]+)"')
_LINK_RE2 = re.compile(r'href="([^"]+)"[^>]*class="poly-component__title"')
_TITLE_RE = re.compile(r'class="poly-component__title"[^>]*>([^<]+)</a>')
_CUR_RE = re.compile(
    r'andes-money-amount(?![^"]*previous)[^>]*aria-label="([\d.]+)\s*reais'
)
_PREV_RE = re.compile(
    r'andes-money-amount--previous[^>]*aria-label="Antes:\s*([\d.]+)\s*reais'
)
_ITEM_ID_RE = re.compile(r'/p/(MLB\d+)')
_SALES_RE = re.compile(r'\+?\s*([\d.]+)\s*mil\s*vendidos|\+?\s*(\d+)\s*vendidos')
_RATING_RE = re.compile(r'poly_star_fill[^>]*></use></svg>\s*<span[^>]*>([\d,\.]+)</span>')
_OFFICIAL_RE = re.compile(r'aria-label="Loja oficial"')
_LABEL_RE = re.compile(r'class="polylabel-fs-xs polylabel-fw-semibold">([^<]+)</span>')
_COUPON_RE = re.compile(r'poly-component__coupons.*?aria-label="([\d.]+)\s*reais"', re.DOTALL)
_FREE_SHIPPING_RE = re.compile(r'frete\s+gr[aá]tis', re.IGNORECASE)


def _to_float(raw: str) -> float | None:
    raw = raw.replace(".", "").strip()
    if not raw:
        return None
    try:
        return float(raw)
    except ValueError:
        return None


def _split_cards(html: str) -> list[str]:
    idxs = [m.start() for m in _CARD_RE.finditer(html)]
    cards = []
    for i, start in enumerate(idxs):
        end = idxs[i + 1] if i + 1 < len(idxs) else len(html)
        cards.append(html[start:end])
    return cards


def _clean_url(url: str) -> str:
    return url.split("#")[0].split("?")[0]


def _parse_card(card: str) -> Deal | None:
    link_m = _LINK_RE.search(card) or _LINK_RE2.search(card)
    if not link_m:
        return None
    permalink = link_m.group(1).replace("&amp;", "&")

    id_m = _ITEM_ID_RE.search(permalink)
    if not id_m:
        return None
    item_id = id_m.group(1)

    title_m = _TITLE_RE.search(card)
    title = unescape(title_m.group(1).strip()) if title_m else ""

    cur_m = _CUR_RE.search(card)
    prev_m = _PREV_RE.search(card)
    price = _to_float(cur_m.group(1)) if cur_m else None
    original = _to_float(prev_m.group(1)) if prev_m else None
    if price is None:
        return None

    return Deal(
        item_id=item_id,
        title=title,
        price=price,
        original_price=original,
        permalink=_clean_url(permalink),
        thumbnail="",
        sales_count=_parse_sales(card),
        rating=_parse_rating(card),
        official_store=bool(_OFFICIAL_RE.search(card)),
        offer_label=_parse_label(card),
        coupon_amount=_parse_coupon(card),
        free_shipping=bool(_FREE_SHIPPING_RE.search(card)),
    )


def _parse_sales(card: str) -> int:
    m = _SALES_RE.search(card)
    if not m:
        return 0
    if m.group(1):
        return int(float(m.group(1).replace(".", "")) * 1000)
    return int(m.group(2))


def _parse_rating(card: str) -> float | None:
    m = _RATING_RE.search(card)
    if not m:
        return None
    try:
        return float(m.group(1).replace(",", "."))
    except ValueError:
        return None


def _parse_label(card: str) -> str:
    m = _LABEL_RE.search(card)
    return unescape(m.group(1).strip()) if m else ""


def _parse_coupon(card: str) -> float | None:
    m = _COUPON_RE.search(card)
    if not m:
        return None
    try:
        return float(m.group(1).replace(".", ""))
    except ValueError:
        return None


def scrape_deals(min_discount: int, category_ids: list[str] | None = None) -> list[Deal]:
    urls = [OFERTAS_URL]
    for cat in (category_ids or []):
        urls.append(f"{OFERTAS_URL}?category={cat}")

    seen_ids: set[str] = set()
    deals: list[Deal] = []

    for url in urls:
        try:
            resp = httpx.get(url, headers=HEADERS, timeout=30, follow_redirects=True)
            resp.raise_for_status()
            resp.encoding = "utf-8"
        except httpx.HTTPError:
            continue
        for card in _split_cards(resp.text):
            deal = _parse_card(card)
            if not deal or deal.item_id in seen_ids:
                continue
            seen_ids.add(deal.item_id)
            if deal.discount_percent >= min_discount:
                deals.append(deal)

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals
