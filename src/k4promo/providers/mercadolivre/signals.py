import unicodedata

import httpx

from k4promo.providers.mercadolivre.oauth import get_valid_token

HIGHLIGHTS_URL = "https://api.mercadolibre.com/highlights/MLB/category/{cat}"
TRENDS_URL = "https://api.mercadolibre.com/trends/MLB"


def _headers(client_id: str, client_secret: str) -> dict | None:
    token = get_valid_token(client_id, client_secret)
    return {"Authorization": f"Bearer {token}"} if token else None


def best_seller_ids(categories: list[str], client_id: str, client_secret: str) -> set[str]:
    headers = _headers(client_id, client_secret)
    if not headers:
        return set()
    ids: set[str] = set()
    for cat in categories:
        try:
            resp = httpx.get(HIGHLIGHTS_URL.format(cat=cat), headers=headers, timeout=30)
            if resp.status_code == 200:
                ids.update(x["id"] for x in resp.json().get("content", []) if x.get("id"))
        except httpx.HTTPError:
            continue
    return ids


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    text = "".join(c for c in text if not unicodedata.combining(c))
    return text


def trending_keywords(client_id: str, client_secret: str) -> list[str]:
    headers = _headers(client_id, client_secret)
    if not headers:
        return []
    try:
        resp = httpx.get(TRENDS_URL, headers=headers, timeout=30)
    except httpx.HTTPError:
        return []
    if resp.status_code != 200:
        return []
    return [_normalize(x["keyword"]) for x in resp.json() if x.get("keyword")]


def title_matches_trend(title: str, keywords: list[str]) -> bool:
    norm_title = _normalize(title)
    for kw in keywords:
        tokens = kw.split()
        if len(tokens) >= 2 and kw in norm_title:
            return True
    return False
