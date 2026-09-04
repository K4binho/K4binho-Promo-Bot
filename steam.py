import re
from dataclasses import dataclass

import httpx

SEARCH_URL = "https://store.steampowered.com/search/results/"
ITAD_LOOKUP_URL = "https://api.isthereanydeal.com/games/lookup/v1"
ITAD_WAITLIST_URL = "https://api.isthereanydeal.com/stats/waitlist/v1"
ITAD_HISTORYLOW_URL = "https://api.isthereanydeal.com/games/historylow/v1"
STEAM_REVIEWS_URL = "https://store.steampowered.com/appreviews/{appid}"
BUNDLE_RESOLVE_URL = "https://store.steampowered.com/actions/ajaxresolvebundles"
PAGE_SIZE = 50
MAX_PAGES = 10
DEFAULT_BUNDLE_SCAN_APPS = 24


@dataclass
class GameDeal:
    game_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str
    header_image: str
    lowest_price: float | None = None
    review_score: int | None = None
    review_count: int | None = None
    waitlisted: int | None = None
    store_type: str = "app"
    store_id: str = ""


def fetch_specials(
    api_key: str = "",
    country: str = "BR",
    limit: int = 500,
    bundle_scan_apps: int = DEFAULT_BUNDLE_SCAN_APPS,
) -> list[GameDeal]:
    deals: list[GameDeal] = []
    seen_ids: set[str] = set()

    for page in range(MAX_PAGES):
        start = page * PAGE_SIZE
        try:
            resp = httpx.get(
                SEARCH_URL,
                params={
                    "query": "",
                    "start": start,
                    "count": PAGE_SIZE,
                    "specials": 1,
                    "sort_by": "Reviews_DESC",
                    "cc": country.lower(),
                    "infinite": 1,
                    "l": "brazilian",
                },
                headers={"Accept": "application/json"},
                timeout=30,
            )
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if page == 0:
                raise RuntimeError(f"Steam search: {exc}") from None
            break

        data = resp.json()
        html = data.get("results_html", "")
        if not html or not html.strip():
            break

        page_deals = _parse_results_html(html)
        for d in page_deals:
            if d.game_id not in seen_ids:
                seen_ids.add(d.game_id)
                deals.append(d)

        total = data.get("total_count", 0)
        if start + PAGE_SIZE >= total:
            break

    # Steam's normal search is primarily app-oriented. A bundle can be present
    # on the store and still never appear in /search/results, which meant the
    # parser support for /bundle/ alone was not enough. Scan a bounded number
    # of the strongest discounted app pages, discover bundle IDs referenced by
    # those pages, then resolve them through Steam's own bundle endpoint.
    if bundle_scan_apps > 0:
        app_seed = sorted(
            (d for d in deals if d.store_type == "app"),
            key=lambda d: d.discount_percent,
            reverse=True,
        )[:bundle_scan_apps]
        try:
            bundle_ids = _discover_bundle_ids_from_apps(app_seed, country=country)
            for d in _resolve_bundles(bundle_ids, country=country):
                if d.game_id not in seen_ids:
                    seen_ids.add(d.game_id)
                    deals.append(d)
        except httpx.HTTPError:
            # Bundle discovery is additive. Never make the normal Steam cycle
            # fail because this secondary source is temporarily unavailable.
            pass

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals[:limit]


def _discover_bundle_ids_from_apps(
    app_deals: list[GameDeal],
    country: str = "BR",
) -> set[str]:
    """Discover Steam bundle IDs advertised on a bounded set of app pages.

    This is intentionally not a brute-force crawler. It only visits app pages
    that were already discovered by the normal specials search.
    """
    bundle_ids: set[str] = set()
    headers = {
        "User-Agent": "Mozilla/5.0 K4binhoPromoBot/1.0",
        # Bypass the common age gate so purchase blocks are present in HTML.
        "Cookie": "birthtime=568022401; lastagecheckage=1-January-1988",
    }
    for deal in app_deals:
        if deal.store_type != "app":
            continue
        url = deal.permalink or f"https://store.steampowered.com/app/{deal.store_id or deal.game_id}/"
        try:
            resp = httpx.get(
                url,
                params={"cc": country.lower(), "l": "brazilian"},
                headers=headers,
                timeout=20,
                follow_redirects=True,
            )
            resp.raise_for_status()
        except httpx.HTTPError:
            continue
        html = resp.text
        bundle_ids.update(re.findall(r'data-ds-bundleid=["\'](\d+)["\']', html, re.IGNORECASE))
        bundle_ids.update(re.findall(r'/bundle/(\d+)', html, re.IGNORECASE))
    return bundle_ids


def _resolve_bundles(bundle_ids: set[str] | list[str], country: str = "BR") -> list[GameDeal]:
    ids = sorted({str(x) for x in bundle_ids if str(x).isdigit()}, key=int)
    if not ids:
        return []

    deals: list[GameDeal] = []
    # Keep requests small even though the endpoint accepts a list of IDs.
    for start in range(0, len(ids), 40):
        chunk = ids[start:start + 40]
        resp = httpx.get(
            BUNDLE_RESOLVE_URL,
            params={
                "bundleids": ",".join(chunk),
                "cc": country.upper(),
                "l": "brazilian",
            },
            timeout=20,
        )
        resp.raise_for_status()
        payload = resp.json()
        if not isinstance(payload, list):
            continue
        deals.extend(_parse_resolved_bundles(payload))
    return deals


def _parse_resolved_bundles(payload: list[dict]) -> list[GameDeal]:
    deals: list[GameDeal] = []
    for item in payload:
        if not isinstance(item, dict):
            continue
        bundle_id = str(item.get("bundleid") or "")
        title = str(item.get("name") or "").strip()
        try:
            initial = int(item.get("initial_price") or 0)
            final = int(item.get("final_price") or 0)
            discount = int(item.get("discount_percent") or 0)
        except (TypeError, ValueError):
            continue
        if not bundle_id.isdigit() or not title or final <= 0 or discount <= 0:
            continue
        deals.append(GameDeal(
            game_id=f"bundle_{bundle_id}",
            title=title,
            price=final / 100.0,
            original_price=(initial / 100.0) if initial > 0 else None,
            discount_percent=discount,
            permalink=f"https://store.steampowered.com/bundle/{bundle_id}/",
            header_image=str(item.get("header_image_url") or item.get("main_capsule") or ""),
            store_type="bundle",
            store_id=bundle_id,
        ))
    return deals


def search_by_keyword(
    keywords: str,
    *,
    country: str = "BR",
    limit: int = 20,
) -> list[GameDeal]:
    """Busca por termo, pra atender pedido do usuario na hora.

    Usa `term`, nao `query`: com `query` a Steam ignora o texto e devolve o topo
    de vendas (mesmo `total_count` pra qualquer busca). Sem `specials=1` e sem
    exigir desconto: quem pede um jogo quer saber o preco dele mesmo a preco
    cheio. Exigir desconto fazia a busca por 'skyrim' devolver zero jogo e sobrar
    so caneca e chaveiro das lojas fisicas.
    """
    if not keywords.strip():
        return []
    resp = httpx.get(
        SEARCH_URL,
        params={
            "term": keywords,
            "start": 0,
            "count": min(max(limit, 1), PAGE_SIZE),
            "cc": country.lower(),
            "infinite": 1,
            "l": "brazilian",
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    html = resp.json().get("results_html", "")
    if not html.strip():
        return []
    return _parse_results_html(html, require_discount=False)[:limit]


def _parse_results_html(html: str, *, require_discount: bool = True) -> list[GameDeal]:
    deals: list[GameDeal] = []

    # Steam search rows may represent an app, a package/sub, or a bundle.
    # Keep the real storefront URL/type instead of assuming every row is /app/.
    rows = re.findall(r'<a([^>]*)>(.+?)</a>', html, re.DOTALL | re.IGNORECASE)

    for attrs, row_html in rows:
        app_m = re.search(r'data-ds-appid="([^"]+)"', attrs, re.IGNORECASE)
        package_m = re.search(r'data-ds-packageid="(\d+)"', attrs, re.IGNORECASE)
        bundle_m = re.search(r'data-ds-bundleid="(\d+)"', attrs, re.IGNORECASE)
        href_m = re.search(r'href="([^"]+)"', attrs, re.IGNORECASE)

        href = href_m.group(1).replace('&amp;', '&') if href_m else ""
        href_lower = href.lower()

        store_type = ""
        store_id = ""
        if bundle_m or "/bundle/" in href_lower:
            store_type = "bundle"
            if bundle_m:
                store_id = bundle_m.group(1)
            else:
                m = re.search(r'/bundle/(\d+)', href_lower)
                store_id = m.group(1) if m else ""
        elif package_m or "/sub/" in href_lower:
            store_type = "sub"
            if package_m:
                store_id = package_m.group(1)
            else:
                m = re.search(r'/sub/(\d+)', href_lower)
                store_id = m.group(1) if m else ""
        elif app_m:
            store_type = "app"
            # Packages sometimes expose several appids; for a true app row use
            # the first numeric app id.
            store_id = app_m.group(1).split(',')[0].strip()

        if not store_type or not store_id or not store_id.isdigit():
            continue

        title_m = re.search(r'<span class="title">([^<]+)</span>', row_html)
        if not title_m:
            continue
        title = title_m.group(1).strip()

        discount_m = re.search(r'class="discount_pct[^"]*"[^>]*>-(\d+)%', row_html)
        if not discount_m and require_discount:
            continue
        discount = int(discount_m.group(1)) if discount_m else 0

        original_m = re.search(
            r'class="discount_original_price"[^>]*>\s*R\$\s*([\d.,]+)',
            row_html,
        )
        final_m = re.search(
            r'class="discount_final_price"[^>]*>\s*R\$\s*([\d.,]+)',
            row_html,
        )
        if not final_m:
            continue

        price = _parse_brl(final_m.group(1))
        original = _parse_brl(original_m.group(1)) if original_m else None
        if price <= 0:
            continue

        if not href:
            href = f"https://store.steampowered.com/{store_type}/{store_id}"
        else:
            href = href.split('?')[0]

        image = ""
        if store_type == "app":
            image = f"https://cdn.akamai.steamstatic.com/steam/apps/{store_id}/header.jpg"
        else:
            img_m = re.search(r'<img[^>]+src="([^"]+)"', row_html, re.IGNORECASE)
            if img_m:
                image = img_m.group(1).replace('&amp;', '&')

        public_id = store_id if store_type == "app" else f"{store_type}_{store_id}"
        deals.append(GameDeal(
            game_id=public_id,
            title=title,
            price=price,
            original_price=original,
            discount_percent=discount,
            permalink=href,
            header_image=image,
            store_type=store_type,
            store_id=store_id,
        ))

    return deals


def _parse_brl(value: str) -> float:
    cleaned = value.replace(".", "").replace(",", ".")
    try:
        return float(cleaned)
    except ValueError:
        return 0.0


def _enrich_steam_reviews(deal: GameDeal) -> None:
    """Load review quality directly from Steam."""
    if deal.store_type != "app":
        return
    app_id = deal.store_id or deal.game_id
    try:
        resp = httpx.get(
            STEAM_REVIEWS_URL.format(appid=app_id),
            params={
                "json": 1,
                "language": "all",
                "purchase_type": "all",
                "num_per_page": 0,
            },
            timeout=15,
        )
        if resp.status_code != 200:
            return
        data = resp.json()
        summary = data.get("query_summary") or {}
        total_reviews = int(summary.get("total_reviews") or 0)
        total_positive = int(summary.get("total_positive") or 0)
        if total_reviews > 0:
            deal.review_count = total_reviews
            deal.review_score = round((total_positive / total_reviews) * 100)
    except (httpx.HTTPError, TypeError, ValueError):
        return


def _itad_lookup_uuid(api_key: str, app_id: str) -> str | None:
    """Resolve a Steam appid to the UUID required by ITAD API v2."""
    if not api_key:
        return None
    try:
        resp = httpx.get(
            ITAD_LOOKUP_URL,
            params={"key": api_key, "appid": int(app_id)},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        if not payload.get("found"):
            return None
        game = payload.get("game") or {}
        game_id = str(game.get("id") or "")
        return game_id or None
    except (httpx.HTTPError, TypeError, ValueError):
        return None


def _enrich_itad(api_key: str, deal: GameDeal) -> None:
    """Load ITAD popularity/history using the UUID-based API."""
    if deal.store_type != "app" or not api_key:
        return

    app_id = deal.store_id or deal.game_id
    game_uuid = _itad_lookup_uuid(api_key, app_id)
    if not game_uuid:
        return

    try:
        resp = httpx.get(
            ITAD_WAITLIST_URL,
            params={"key": api_key, "id": game_uuid, "country": "BR"},
            timeout=15,
        )
        if resp.status_code == 200:
            payload = resp.json()
            count = payload.get("count")
            if count is not None:
                deal.waitlisted = int(count)
    except (httpx.HTTPError, TypeError, ValueError):
        pass

    try:
        resp = httpx.post(
            ITAD_HISTORYLOW_URL,
            params={"key": api_key, "country": "BR"},
            json=[game_uuid],
            timeout=15,
        )
        if resp.status_code == 200:
            payload = resp.json()
            if isinstance(payload, list) and payload:
                low = (payload[0] or {}).get("low") or {}
                price = low.get("price") or {}
                amount = price.get("amount")
                if amount is not None:
                    deal.lowest_price = float(amount)
    except (httpx.HTTPError, TypeError, ValueError):
        pass


def enrich(api_key: str, deals: list[GameDeal]) -> None:
    """Enrich Steam apps without making ITAD a single point of failure."""
    for deal in deals:
        if deal.store_type != "app":
            continue
        _enrich_steam_reviews(deal)
        _enrich_itad(api_key, deal)


def is_quality_game(deal: GameDeal, min_review_score: int, min_review_count: int) -> bool:
    if deal.review_count is None or deal.review_count < min_review_count:
        return False
    if deal.review_score is None or deal.review_score < min_review_score:
        return False
    return True
