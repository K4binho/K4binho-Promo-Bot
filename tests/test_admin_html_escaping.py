"""Fase 2 (seção 11 do prompt mestre): escapar títulos, termos de alerta,
nomes e links usados em HTML — nunca deixar entrada do usuário quebrar (ou
injetar) o parse_mode=HTML das mensagens do bot.
"""

from __future__ import annotations

import json

import httpx

from k4promo.commands import admin
from k4promo.telegram import client


def _install_capture():
    captured: dict[str, str] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        captured["text"] = body.get("text", "")
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    client.reset_client_for_testing(httpx.Client(transport=httpx.MockTransport(handler)))
    client._rate_limiter = client.RateLimiter(chat_interval=0.0, global_interval=0.0)
    return captured


def test_add_alert_escapa_palavra_chave_maliciosa():
    captured = _install_capture()
    alerts: dict[str, list[dict]] = {}
    admin._handle_add_alert(
        "TOKEN", "111", "<script>alert(1)</script>", alerts
    )
    assert "<script>" not in captured["text"]
    assert "&lt;script&gt;" in captured["text"]
    client.reset_client_for_testing()


def test_list_alerts_escapa_palavra_chave_salva():
    captured = _install_capture()
    alerts: dict[str, list[dict]] = {
        "111": [{"keywords": "rtx <b>5070</b>", "max_price": None}]
    }
    admin._handle_list_alerts("TOKEN", "111", alerts)
    assert "<b>5070</b>" not in captured["text"]
    assert "&lt;b&gt;5070&lt;/b&gt;" in captured["text"]
    client.reset_client_for_testing()


def test_notify_alert_match_escapa_titulo_palavra_chave_e_link():
    captured = _install_capture()
    admin.notify_alert_match(
        "TOKEN",
        "111",
        alert={"keywords": "ssd <i>500gb</i>"},
        title='Produto " onclick="alert(1)',
        price=100.0,
        link='https://example.com/x?a=1&b="2',
    )
    text = captured["text"]
    assert "<i>500gb</i>" not in text
    assert "&lt;i&gt;500gb&lt;/i&gt;" in text
    assert 'onclick="alert(1)"' not in text
    assert "&quot;" in text
    client.reset_client_for_testing()
