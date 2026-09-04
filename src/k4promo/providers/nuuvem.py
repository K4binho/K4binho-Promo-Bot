"""Nuuvem deals via IsThereAnyDeal API (Nuuvem shop ID 50) + coupon scraping."""

import re
from dataclasses import dataclass, field

import httpx

ITAD_DEALS_URL = "https://api.isthereanydeal.com/deals/v2"
ITAD_INFO_URL = "https://api.isthereanydeal.com/games/info/v2"
NUUVEM_SHOP_ID = 50
COUPONS_URL = "https://www.nuuvem.com/br-pt/log-cupom-interno"


@dataclass
class NuuvemCoupon:
    code: str
    discount: str
    game: str
    region: str


@dataclass
class NuuvemDeal:
    game_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str
    image_url: str
    lowest_price: float | None = None
    coupon: NuuvemCoupon | None = None
    waitlisted: int | None = None
    review_score: int | None = None
    review_count: int | None = None


def fetch_coupons() -> list[NuuvemCoupon]:
    try:
        resp = httpx.get(COUPONS_URL, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    coupons: list[NuuvemCoupon] = []
    text = resp.text

    blocks = re.split(r'<(?:div|article|section)[^>]*class="[^"]*coupon[^"]*"', text, flags=re.IGNORECASE)
    if len(blocks) <= 1:
        code_pattern = re.findall(
            r'(?:code|cupom|coupon)[^>]*>([A-Z0-9]{4,20})</[^>]*>.*?'
            r'(\d+%|R\$\s*\d+)',
            text, re.IGNORECASE | re.DOTALL
        )
        for code, discount in code_pattern:
            coupons.append(NuuvemCoupon(
                code=code.strip(),
                discount=discount.strip(),
                game="",
                region="BR",
            ))

    if not coupons:
        lines = text.split('\n')
        for i, line in enumerate(lines):
            code_m = re.search(r'<(?:strong|b|code|span)[^>]*>\s*([A-Z][A-Z0-9]{3,19})\s*</(?:strong|b|code|span)>', line)
            if code_m:
                code = code_m.group(1)
                context = '\n'.join(lines[max(0, i-3):i+5])
                disc_m = re.search(r'(\d+%|R\$\s*[\d,.]+)', context)
                discount = disc_m.group(1) if disc_m else ""
                game_m = re.search(r'(?:para|for|em)\s+(.+?)(?:<|$|\.|,)', context, re.IGNORECASE)
                game = game_m.group(1).strip() if game_m else ""
                if discount:
                    coupons.append(NuuvemCoupon(
                        code=code,
                        discount=discount,
                        game=game[:80],
                        region="BR",
                    ))

    return coupons


def _match_coupon(title: str, coupons: list[NuuvemCoupon]) -> NuuvemCoupon | None:
    title_lower = title.lower()
    for c in coupons:
        if c.game and c.game.lower() in title_lower:
            return c
        game_words = c.game.lower().split()
        if game_words and len(game_words) >= 2 and all(w in title_lower for w in game_words):
            return c
    return None


PAGE_SIZE = 50
MAX_PAGES = 10


def fetch_deals(
    itad_api_key: str, country: str = "BR", limit: int = 500
) -> list[NuuvemDeal]:
    if not itad_api_key:
        return []

    coupons = fetch_coupons()
    deals: list[NuuvemDeal] = []
    seen_ids: set[str] = set()

    for page in range(MAX_PAGES):
        params = {
            "key": itad_api_key,
            "country": country,
            "shops": NUUVEM_SHOP_ID,
            "sort": "-cut",
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
        }
        try:
            resp = httpx.get(ITAD_DEALS_URL, params=params, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if page == 0:
                raise RuntimeError(f"ITAD/Nuuvem: {exc}") from None
            break

        entries = resp.json().get("list", [])
        if not entries:
            break

        for entry in entries:
            if entry.get("type") != "game":
                continue
            deal_info = entry.get("deal") or {}
            price_obj = deal_info.get("price") or {}
            regular_obj = deal_info.get("regular") or {}
            price = price_obj.get("amount")
            if price is None or price <= 0:
                continue
            original = regular_obj.get("amount")
            discount = int(deal_info.get("cut") or 0)
            if discount <= 0:
                continue
            low_obj = deal_info.get("historyLow") or {}
            lowest = low_obj.get("amount")
            assets = entry.get("assets") or {}
            title = entry.get("title", "")
            game_id = entry.get("id", "")
            if game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            coupon = _match_coupon(title, coupons) if coupons else None
            deals.append(NuuvemDeal(
                game_id=game_id,
                title=title,
                price=float(price),
                original_price=float(original) if original else None,
                discount_percent=discount,
                permalink=deal_info.get("url", ""),
                image_url=assets.get("banner600") or assets.get("boxart") or "",
                lowest_price=float(lowest) if lowest else None,
                coupon=coupon,
            ))

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals[:limit]


def _fetch_itad_info(api_key: str, game_id: str) -> dict | None:
    try:
        resp = httpx.get(
            ITAD_INFO_URL,
            params={"key": api_key, "id": game_id},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.HTTPError:
        return None


def enrich_with_popularity(api_key: str, deals: list["NuuvemDeal"]) -> None:
    """Preenche waitlisted (quantas pessoas tem o jogo na lista de
    desejos da ITAD - metrica de 'procura') e nota/qtd de reviews do
    Steam quando disponivel, pro mesmo jogo. Mesmo padrao usado em
    steam.py."""
    if not api_key:
        return
    for deal in deals:
        info = _fetch_itad_info(api_key, deal.game_id)
        if not info:
            continue
        for review in info.get("reviews") or []:
            if review.get("source") == "Steam":
                deal.review_score = review.get("score")
                deal.review_count = review.get("count")
                break
        stats = info.get("stats") or {}
        deal.waitlisted = stats.get("waitlisted")


def is_most_wanted(deal: "NuuvemDeal", min_waitlisted: int) -> bool:
    return deal.waitlisted is not None and deal.waitlisted >= min_waitlisted

