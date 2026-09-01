"""AliExpress Affiliate API — IOP/HMAC signing + product query (with embedded affiliate links)."""

import hashlib
import hmac
import time
from dataclasses import dataclass

import httpx

API_URL = "https://api-sg.aliexpress.com/sync"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1.5, 3.0, 6.0)


@dataclass
class AliDeal:
    product_id: str
    title: str
    price: float
    original_price: float
    discount_percent: int
    permalink: str
    image_url: str
    commission_rate: float
    sales_count: int


def _sign(app_secret: str, params: dict[str, str]) -> str:
    sorted_params = sorted(params.items())
    base = "".join(k + v for k, v in sorted_params)
    return hmac.new(
        app_secret.encode("utf-8"),
        base.encode("utf-8"),
        hashlib.sha256,
    ).hexdigest().upper()


def _build_params(app_key: str, app_secret: str, method: str, api_params: dict[str, str]) -> dict[str, str]:
    system_params = {
        "method": method,
        "app_key": app_key,
        "sign_method": "sha256",
        "timestamp": str(int(time.time() * 1000)),
    }
    all_params = {**system_params, **api_params}
    all_params["sign"] = _sign(app_secret, all_params)
    return all_params


def _is_frequency_limit(data: dict) -> bool:
    err = data.get("error_response") or {}
    msg = str(err.get("msg", "")).lower()
    return "frequency exceeds" in msg or "frequency" in msg and "limit" in msg


def _call(app_key: str, app_secret: str, method: str,
          api_params: dict[str, str]) -> dict:
    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        try:
            all_params = _build_params(app_key, app_secret, method, api_params)
            resp = httpx.get(API_URL, params=all_params, timeout=30)

            if resp.status_code in RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"transient HTTP {resp.status_code}", request=resp.request, response=resp
                )
            resp.raise_for_status()
            data = resp.json()

            if "error_response" not in data:
                return data

            err = data["error_response"]
            if _is_frequency_limit(data):
                last_error = RuntimeError(f"AliExpress API rate limit: {err.get('msg', err)}")
            else:
                raise RuntimeError(f"AliExpress API error: {err.get('msg', err)}")
        except httpx.HTTPError as exc:
            last_error = exc

        if attempt < len(RETRY_DELAYS):
            time.sleep(RETRY_DELAYS[attempt])

    if last_error is not None:
        raise RuntimeError(f"AliExpress API indisponivel apos retries: {last_error}") from last_error
    raise RuntimeError("AliExpress API indisponivel apos retries")


def _parse_percent(raw: str) -> float:
    return float(raw.replace("%", "").strip()) if raw else 0.0


def fetch_deals(
    app_key: str,
    app_secret: str,
    tracking_id: str,
    *,
    keywords: str = "",
    category_ids: str = "",
    min_sale_price: int = 0,
    max_sale_price: int = 0,
    page_no: int = 1,
    page_size: int = 50,
    sort: str = "LAST_VOLUME_DESC",
    ship_to_country: str = "BR",
) -> list[AliDeal]:
    params: dict[str, str] = {
        "tracking_id": tracking_id,
        "target_currency": "BRL",
        "target_language": "PT",
        "ship_to_country": ship_to_country,
        "sort": sort,
        "page_no": str(page_no),
        "page_size": str(page_size),
    }
    if keywords:
        params["keywords"] = keywords
    if category_ids:
        params["category_ids"] = category_ids
    if min_sale_price:
        params["min_sale_price"] = str(min_sale_price)
    if max_sale_price:
        params["max_sale_price"] = str(max_sale_price)

    data = _call(app_key, app_secret, "aliexpress.affiliate.product.query", params)

    resp_result = data.get("aliexpress_affiliate_product_query_response", {})
    result = resp_result.get("resp_result", {}).get("result", {})
    products = result.get("products", {}).get("product", [])

    deals: list[AliDeal] = []
    for p in products:
        try:
            sale = float(p.get("target_sale_price", "0"))
            original = float(p.get("target_original_price", "0"))
            if original <= 0 or sale <= 0:
                continue
            discount = int(round((1 - sale / original) * 100))
            if discount <= 0:
                continue
            promo_link = p.get("promotion_link", "")
            if not promo_link:
                continue
            deals.append(AliDeal(
                product_id=str(p.get("product_id", "")),
                title=p.get("product_title", ""),
                price=sale,
                original_price=original,
                discount_percent=discount,
                permalink=promo_link,
                image_url=p.get("product_main_image_url", ""),
                commission_rate=_parse_percent(p.get("commission_rate", "0")),
                sales_count=int(p.get("lastest_volume", 0)),
            ))
        except (ValueError, TypeError):
            continue

    return deals
