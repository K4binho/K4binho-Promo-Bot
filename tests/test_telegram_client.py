"""Testes da Fase 2: cliente Telegram resiliente.

Usa httpx.MockTransport pra simular a Bot API sem tocar a rede de verdade
(o ambiente de execução nem libera api.telegram.org). Cobre os critérios de
aceite: rate limit por chat/global, retry em 429 respeitando retry_after,
retry em 5xx, fallback de foto pra texto, message_id, delete_message,
callback query e sanitização de token nos logs.
"""

from __future__ import annotations

import json
import time

import httpx
import pytest

from k4promo.telegram import client


@pytest.fixture(autouse=True)
def _reset_client():
    """Cada teste começa com client/rate-limiter limpos."""
    client.reset_client_for_testing()
    yield
    client.reset_client_for_testing()


def _install(handler) -> None:
    """Injeta um httpx.Client com MockTransport e sem rate limit (por
    padrão) pra não atrasar os testes que não são sobre rate limit."""
    transport = httpx.MockTransport(handler)
    client.reset_client_for_testing(httpx.Client(transport=transport))
    client._rate_limiter = client.RateLimiter(chat_interval=0.0, global_interval=0.0)


def _body(request: httpx.Request) -> dict:
    return json.loads(request.content)


# ---------------------------------------------------------------------------
# message_id
# ---------------------------------------------------------------------------

def test_send_message_returns_message_id():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/sendMessage")
        body = _body(request)
        assert body["chat_id"] == "-100123"
        assert body["parse_mode"] == "HTML"
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 555}})

    _install(handler)
    msg_id = client.send_message("TOKEN", "-100123", "olá")
    assert msg_id == 555


def test_thread_id_is_sent_as_message_thread_id():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        assert body["message_thread_id"] == 2197
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    _install(handler)
    client.send_message("TOKEN", "-100123", "olá", thread_id=2197)


# ---------------------------------------------------------------------------
# Retry em 5xx
# ---------------------------------------------------------------------------

def test_retry_on_5xx_then_succeeds(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] < 3:
            return httpx.Response(503, json={"ok": False, "description": "instável"})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 9}})

    _install(handler)
    msg_id = client.send_message("TOKEN", "-100123", "olá")
    assert msg_id == 9
    assert calls["n"] == 3


def test_retry_exhausted_raises(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        return httpx.Response(502, json={"ok": False, "description": "fora do ar"})

    _install(handler)
    with pytest.raises(httpx.HTTPStatusError):
        client.send_message("TOKEN", "-100123", "olá", reply_markup=None)
    # max_retries default é 3 -> 1 tentativa inicial + 3 retries = 4 chamadas
    assert calls["n"] == 4


# ---------------------------------------------------------------------------
# Retry em 429 respeitando retry_after
# ---------------------------------------------------------------------------

def test_respects_retry_after_on_429(monkeypatch):
    sleeps: list[float] = []
    monkeypatch.setattr(client.time, "sleep", lambda s: sleeps.append(s))
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            return httpx.Response(
                429,
                json={"ok": False, "error_code": 429, "parameters": {"retry_after": 2.5}},
            )
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    _install(handler)
    msg_id = client.send_message("TOKEN", "-100123", "olá")
    assert msg_id == 7
    assert 2.5 in sleeps


# ---------------------------------------------------------------------------
# Erro de rede temporário
# ---------------------------------------------------------------------------

def test_network_error_retries_then_raises(monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda *_: None)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("conexão recusada", request=request)

    _install(handler)
    with pytest.raises(httpx.TransportError):
        client.send_message("TOKEN", "-100123", "olá")


# ---------------------------------------------------------------------------
# Fallback de foto pra texto
# ---------------------------------------------------------------------------

def test_photo_failure_falls_back_to_text():
    calls = {"photo": 0, "text": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendPhoto"):
            calls["photo"] += 1
            return httpx.Response(
                400,
                json={"ok": False, "error_code": 400, "description": "wrong file identifier"},
            )
        calls["text"] += 1
        body = _body(request)
        assert "photo" not in body
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    _install(handler)
    msg_id = client.send_message(
        "TOKEN", "-100123", "olá", image_url="https://example.com/quebrada.jpg"
    )
    assert msg_id == 42
    assert calls["photo"] == 1
    assert calls["text"] == 1


# ---------------------------------------------------------------------------
# delete_message / answer_callback_query
# ---------------------------------------------------------------------------

def test_delete_message_returns_true_on_success():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/deleteMessage")
        body = _body(request)
        assert body == {"chat_id": "-100123", "message_id": 42}
        return httpx.Response(200, json={"ok": True, "result": True})

    _install(handler)
    assert client.delete_message("TOKEN", "-100123", 42) is True


def test_delete_message_returns_false_on_failure_without_raising():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400, json={"ok": False, "description": "message to delete not found"}
        )

    _install(handler)
    assert client.delete_message("TOKEN", "-100123", 999) is False


def test_answer_callback_query_sends_expected_payload():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path.endswith("/answerCallbackQuery")
        body = _body(request)
        assert body == {
            "callback_query_id": "cb1",
            "text": "Feito!",
            "show_alert": True,
        }
        return httpx.Response(200, json={"ok": True, "result": True})

    _install(handler)
    client.answer_callback_query("TOKEN", "cb1", text="Feito!", show_alert=True)


def test_answer_callback_query_never_raises_on_failure():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "query is too old"})

    _install(handler)
    client.answer_callback_query("TOKEN", "cb-velho")  # não deve levantar


# ---------------------------------------------------------------------------
# Rate limit (por chat e global) — RateLimiter isolado, sem HTTP.
# ---------------------------------------------------------------------------

def test_rate_limit_per_chat_espaca_mesmo_chat():
    limiter = client.RateLimiter(chat_interval=0.06, global_interval=0.0)
    limiter.acquire("chat1")
    start = time.monotonic()
    limiter.acquire("chat1")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05


def test_rate_limit_per_chat_nao_afeta_chat_diferente():
    limiter = client.RateLimiter(chat_interval=0.5, global_interval=0.0)
    limiter.acquire("chat1")
    start = time.monotonic()
    limiter.acquire("chat2")
    elapsed = time.monotonic() - start
    assert elapsed < 0.1


def test_rate_limit_global_afeta_chats_diferentes():
    limiter = client.RateLimiter(chat_interval=0.0, global_interval=0.06)
    limiter.acquire("chatA")
    start = time.monotonic()
    limiter.acquire("chatB")
    elapsed = time.monotonic() - start
    assert elapsed >= 0.05


# ---------------------------------------------------------------------------
# Sanitização e truncamento
# ---------------------------------------------------------------------------

def test_sanitize_remove_token_explicito():
    token = "123456:ABC-DEF_secreto"
    msg = f"erro ao chamar https://api.telegram.org/bot{token}/sendMessage: timeout"
    out = client.sanitize(msg, token=token)
    assert token not in out
    assert "<token>" in out


def test_sanitize_remove_token_por_padrao_mesmo_sem_passar_explicito():
    msg = "falha em https://api.telegram.org/bot123456:ABC-DEF_secreto/sendMessage"
    out = client.sanitize(msg)
    assert "ABC-DEF_secreto" not in out


def test_truncate_respeita_limite_e_nao_estoura():
    texto = "a" * 5000
    out = client._truncate(texto, client.TEXT_MAX_LEN)
    assert len(out) <= client.TEXT_MAX_LEN
    assert out.endswith("…")


def test_token_nao_vaza_na_excecao_propagada_ao_chamador():
    """A exceção que o restante do código captura (``except httpx.HTTPError
    as exc: log.error(..., exc)``) não pode conter o token — mesmo essa
    exceção sendo a mesma que o httpx levantaria nativamente."""
    token = "999888:SEGREDO_supersecreto"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, json={"ok": False, "description": "chat not found"})

    _install(handler)
    try:
        client.send_message(token, "-100123", "olá")
    except httpx.HTTPError as exc:
        assert token not in str(exc)
    else:
        raise AssertionError("deveria ter levantado")


def test_send_message_trunca_texto_muito_longo():
    def handler(request: httpx.Request) -> httpx.Response:
        body = _body(request)
        assert len(body["text"]) <= client.TEXT_MAX_LEN
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})

    _install(handler)
    client.send_message("TOKEN", "-100123", "x" * 6000)
