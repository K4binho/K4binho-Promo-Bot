from unittest.mock import Mock, patch

import httpx

import aliexpress
import mercadolivre


def _response(status: int, payload=None):
    request = httpx.Request("GET", "https://example.test")
    return httpx.Response(status, request=request, json=payload if payload is not None else {})


def test_ml_retry_recovers_after_503():
    ok = _response(200, [])
    with patch.object(mercadolivre.httpx, "get", side_effect=[_response(503), ok]) as get, patch.object(mercadolivre.time, "sleep"):
        result = mercadolivre._get_with_retry("https://example.test")
    assert result.status_code == 200
    assert get.call_count == 2


def test_ml_fetch_items_skips_failed_chunk_and_continues():
    ids = [f"MLB{i}" for i in range(21)]
    failed = httpx.ConnectError("offline", request=httpx.Request("GET", "https://example.test"))
    payload = [{"code": 200, "body": {"id": "MLB20", "title": "ok", "price": 10, "permalink": "x", "thumbnail": ""}}]
    with patch.object(mercadolivre, "_get_with_retry", side_effect=[failed, _response(200, payload)]):
        deals = mercadolivre.fetch_items(ids, "token")
    assert [d.item_id for d in deals] == ["MLB20"]


def test_ali_frequency_limit_retries_then_recovers():
    limited = _response(200, {"error_response": {"msg": "Api access frequency exceeds the limit. this ban will last 1 seconds"}})
    ok_payload = {"aliexpress_affiliate_product_query_response": {"resp_result": {"result": {"products": {"product": []}}}}}
    ok = _response(200, ok_payload)
    with patch.object(aliexpress.httpx, "get", side_effect=[limited, ok]) as get, patch.object(aliexpress.time, "sleep"):
        result = aliexpress._call("key", "secret", "method", {})
    assert "error_response" not in result
    assert get.call_count == 2
