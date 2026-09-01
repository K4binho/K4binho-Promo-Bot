from dataclasses import dataclass
import time

import httpx

from ml_oauth import get_valid_token


RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (2, 5, 10)


@dataclass
class Deal:
    item_id: str
    title: str
    price: float
    original_price: float | None
    permalink: str
    thumbnail: str
    sales_count: int = 0
    rating: float | None = None
    official_store: bool = False
    offer_label: str = ""
    coupon_amount: float | None = None

    @property
    def discount_percent(self) -> int:
        if not self.original_price or self.original_price <= self.price:
            return 0
        return round((self.original_price - self.price) / self.original_price * 100)


def _build_headers(access_token: str) -> dict:
    if access_token:
        return {"Authorization": f"Bearer {access_token}"}
    return {}


HIGHLIGHTS_URL = "https://api.mercadolibre.com/highlights/{site}/category/{cat}"
ITEMS_URL = "https://api.mercadolibre.com/items"


def _get_with_retry(url: str, *, params: dict | None = None, headers: dict | None = None, timeout: int = 30) -> httpx.Response:
    last_exc: Exception | None = None
    attempts = len(RETRY_DELAYS) + 1
    for attempt in range(attempts):
        try:
            resp = httpx.get(url, params=params, headers=headers, timeout=timeout)
            if resp.status_code not in RETRYABLE_STATUS:
                resp.raise_for_status()
                return resp
            last_exc = httpx.HTTPStatusError(
                f"transient HTTP {resp.status_code}", request=resp.request, response=resp
            )
        except httpx.HTTPError as exc:
            last_exc = exc

        if attempt < len(RETRY_DELAYS):
            retry_after = 0.0
            if 'resp' in locals() and getattr(resp, 'headers', None):
                try:
                    retry_after = float(resp.headers.get("Retry-After", "0") or 0)
                except ValueError:
                    retry_after = 0.0
            time.sleep(max(RETRY_DELAYS[attempt], retry_after))

    assert last_exc is not None
    raise last_exc


def _deals_from_items_payload(payload: list[dict]) -> list[Deal]:
    deals = []
    for entry in payload:
        if entry.get("code") != 200:
            continue
        item = entry.get("body", {})
        deals.append(
            Deal(
                item_id=item.get("id", ""),
                title=item.get("title", ""),
                price=float(item.get("price") or 0),
                original_price=(float(item["original_price"]) if item.get("original_price") else None),
                permalink=item.get("permalink", ""),
                thumbnail=item.get("thumbnail", ""),
                sales_count=int(item.get("sold_quantity") or 0),
                official_store=bool(item.get("official_store_id")),
            )
        )
    return deals


def fetch_items(item_ids: list[str], access_token: str) -> list[Deal]:
    """Busca itens em lotes de 20 sem deixar falha transitória derrubar o bot.

    Cada lote usa retry/backoff para 429/5xx. Se um lote continuar falhando,
    ele é ignorado e os lotes restantes continuam sendo processados.
    """
    deals: list[Deal] = []
    for i in range(0, len(item_ids), 20):
        chunk = item_ids[i : i + 20]
        if not chunk:
            continue
        try:
            resp = _get_with_retry(
                ITEMS_URL,
                params={"ids": ",".join(chunk)},
                headers=_build_headers(access_token),
                timeout=30,
            )
        except httpx.HTTPError as exc:
            print(f"[erro] ML /items lote ignorado apos retries: {exc}")
            continue
        deals.extend(_deals_from_items_payload(resp.json()))
    return deals


def collect_highlight_deals(
    categories: list[str],
    site: str,
    client_id: str,
    client_secret: str,
) -> list[Deal]:
    """Descobre produtos em alta por categoria e completa via /items."""
    token = get_valid_token(client_id, client_secret)
    if not token:
        raise RuntimeError("Sem token valido do Mercado Livre. Rode: python ml_setup.py")

    ids: set[str] = set()
    for cat in categories:
        try:
            resp = _get_with_retry(
                HIGHLIGHTS_URL.format(site=site, cat=cat),
                headers=_build_headers(token),
                timeout=30,
            )
            ids.update(x["id"] for x in resp.json().get("content", []) if x.get("id"))
        except httpx.HTTPError as exc:
            print(f"[erro] highlights categoria {cat} ignorada apos retries: {exc}")
            continue

    if not ids:
        return []
    return fetch_items(list(ids), token)
