"""Shopee Affiliate Open API — GraphQL, assinatura SHA256 (não é a API de vendedor)."""

import hashlib
import json
import time

import httpx

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"
RETRYABLE_STATUS = {429, 500, 502, 503, 504}
RETRY_DELAYS = (1.5, 3.0, 6.0)

# GraphQL confirmado publicamente para o Open API de afiliados Shopee (BR).
# Não há endpoint dedicado de cupom/voucher por produto: cupons de
# plataforma/campanha vêm do catálogo manual (promotions.json) ou de
# shopeeOfferV2, quando aplicável à conta.
PRODUCT_OFFER_QUERY = """
query ProductOfferV2($keyword: String, $sortType: Int, $page: Int, $limit: Int) {
  productOfferV2(keyword: $keyword, sortType: $sortType, page: $page, limit: $limit) {
    nodes {
      itemId
      productName
      commissionRate
      commission
      price
      priceMin
      priceMax
      priceDiscountRate
      sales
      ratingStar
      shopId
      shopName
      imageUrl
      productCatIds
      offerLink
      productLink
      periodStartTime
      periodEndTime
    }
    pageInfo {
      page
      limit
      hasNextPage
    }
  }
}
"""

SHOPEE_OFFER_QUERY = """
query ShopeeOfferV2($page: Int, $limit: Int) {
  shopeeOfferV2(page: $page, limit: $limit) {
    nodes {
      offerName
      originalLink
      offerLink
      periodStartTime
      periodEndTime
    }
    pageInfo {
      page
      limit
      hasNextPage
    }
  }
}
"""

GENERATE_SHORT_LINK_MUTATION = """
mutation GenerateShortLink($input: ShortLinkInput!) {
  generateShortLink(input: $input) {
    shortLink
  }
}
"""


def _sign(app_id: str, secret: str, payload: str, timestamp: int) -> str:
    factor = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(factor.encode("utf-8")).hexdigest()


def _auth_header(app_id: str, secret: str, payload: str, timestamp: int) -> str:
    signature = _sign(app_id, secret, payload, timestamp)
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"


def _is_rate_limit(errors: list) -> bool:
    for err in errors or []:
        msg = str(err.get("message", "")).lower()
        code = err.get("extensions", {}).get("code") if isinstance(err, dict) else None
        if "rate" in msg and "limit" in msg:
            return True
        if code in (10030, "10030"):
            return True
    return False


def call(app_id: str, secret: str, query: str, variables: dict | None = None) -> dict:
    body: dict = {"query": query}
    if variables:
        body["variables"] = variables
    payload = json.dumps(body, separators=(",", ":"))

    last_error: Exception | None = None
    for attempt in range(len(RETRY_DELAYS) + 1):
        timestamp = int(time.time())
        headers = {
            "Content-Type": "application/json",
            "Authorization": _auth_header(app_id, secret, payload, timestamp),
        }
        try:
            resp = httpx.post(ENDPOINT, content=payload, headers=headers, timeout=30.0)
            if resp.status_code in RETRYABLE_STATUS:
                raise httpx.HTTPStatusError(
                    f"Shopee API HTTP transitorio {resp.status_code}",
                    request=resp.request, response=resp,
                )
            resp.raise_for_status()
            data = resp.json()
            errors = data.get("errors")
            if errors:
                if _is_rate_limit(errors) and attempt < len(RETRY_DELAYS):
                    last_error = RuntimeError(f"Shopee API rate limit: {errors}")
                    time.sleep(RETRY_DELAYS[attempt])
                    continue
                raise RuntimeError(f"Shopee API erro: {errors}")
            return data["data"]
        except httpx.HTTPError as exc:
            last_error = exc
            if attempt < len(RETRY_DELAYS):
                time.sleep(RETRY_DELAYS[attempt])

    raise RuntimeError(f"Shopee API indisponivel apos retries: {last_error}") from last_error


def fetch_product_offers(
    app_id: str, secret: str, *, keyword: str = "", page: int = 1, limit: int = 20,
) -> dict:
    """Retorna o bloco `productOfferV2` bruto (nodes + pageInfo)."""
    variables = {"page": page, "limit": limit}
    if keyword:
        variables["keyword"] = keyword
    data = call(app_id, secret, PRODUCT_OFFER_QUERY, variables)
    return data.get("productOfferV2") or {}


def fetch_shopee_offers(app_id: str, secret: str, *, page: int = 1, limit: int = 20) -> dict:
    """Campanhas/cupons de plataforma vigentes (`shopeeOfferV2`), quando suportado pela conta."""
    data = call(app_id, secret, SHOPEE_OFFER_QUERY, {"page": page, "limit": limit})
    return data.get("shopeeOfferV2") or {}


def generate_short_link(app_id: str, secret: str, origin_url: str, sub_ids: list[str] | None = None) -> str:
    """Gera deeplink/short link rastreado a partir de um link Shopee (produto/loja)."""
    input_payload: dict = {"originUrl": origin_url}
    if sub_ids:
        input_payload["subIds"] = sub_ids[:5]
    data = call(app_id, secret, GENERATE_SHORT_LINK_MUTATION, {"input": input_payload})
    return (data.get("generateShortLink") or {}).get("shortLink", "")


def _self_test() -> None:
    app_id = "123456"
    secret = "demo"
    timestamp = 1577836800
    payload = (
        '{"query":"{\\nbrandOffer{\\n    nodes{\\n        commissionRate\\n'
        '        offerName\\n    }\\n}\\n}"}'
    )
    expected = "dc88d72feea70c80c52c3399751a7d34966763f51a7f056aa070a5e9df645412"
    got = _sign(app_id, secret, payload, timestamp)
    status = "OK" if got == expected else "FALHOU"
    print(f"[{status}] assinatura")
    print(f"  esperado: {expected}")
    print(f"  obtido:   {got}")


if __name__ == "__main__":
    _self_test()
