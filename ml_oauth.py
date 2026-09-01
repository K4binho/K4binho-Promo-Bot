import time
from pathlib import Path
import json

import httpx

TOKEN_URL = "https://api.mercadolibre.com/oauth/token"
TOKEN_PATH = Path(__file__).parent / "ml_token.json"


def _load_token() -> dict:
    if not TOKEN_PATH.exists():
        return {}
    try:
        return json.loads(TOKEN_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def _save_token(data: dict) -> None:
    data["obtained_at"] = int(time.time())
    TOKEN_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def exchange_code(client_id: str, client_secret: str, code: str, redirect_uri: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "redirect_uri": redirect_uri,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_token(data)
    return data


def _refresh(client_id: str, client_secret: str, refresh_token: str) -> dict:
    resp = httpx.post(
        TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "client_id": client_id,
            "client_secret": client_secret,
            "refresh_token": refresh_token,
        },
        headers={"Accept": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    data = resp.json()
    _save_token(data)
    return data


def get_valid_token(client_id: str, client_secret: str) -> str | None:
    data = _load_token()
    if not data:
        return None

    obtained = data.get("obtained_at", 0)
    expires_in = data.get("expires_in", 0)
    # renova 5 min antes de expirar
    if time.time() < obtained + expires_in - 300:
        return data.get("access_token")

    refresh_token = data.get("refresh_token")
    if not refresh_token:
        return None
    try:
        data = _refresh(client_id, client_secret, refresh_token)
    except httpx.HTTPError:
        return None
    return data.get("access_token")
