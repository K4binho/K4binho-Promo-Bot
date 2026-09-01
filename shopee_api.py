import hashlib
import json
import time

import httpx

ENDPOINT = "https://open-api.affiliate.shopee.com.br/graphql"


def _sign(app_id: str, secret: str, payload: str, timestamp: int) -> str:
    factor = f"{app_id}{timestamp}{payload}{secret}"
    return hashlib.sha256(factor.encode("utf-8")).hexdigest()


def _auth_header(app_id: str, secret: str, payload: str, timestamp: int) -> str:
    signature = _sign(app_id, secret, payload, timestamp)
    return f"SHA256 Credential={app_id}, Timestamp={timestamp}, Signature={signature}"


def call(app_id: str, secret: str, query: str, variables: dict | None = None) -> dict:
    body: dict = {"query": query}
    if variables:
        body["variables"] = variables
    payload = json.dumps(body, separators=(",", ":"))
    timestamp = int(time.time())
    headers = {
        "Content-Type": "application/json",
        "Authorization": _auth_header(app_id, secret, payload, timestamp),
    }
    resp = httpx.post(ENDPOINT, content=payload, headers=headers, timeout=30.0)
    resp.raise_for_status()
    data = resp.json()
    if data.get("errors"):
        raise RuntimeError(f"Shopee API erro: {data['errors']}")
    return data["data"]


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
