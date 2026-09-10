"""Testes do /buscar (Fase 3, seção 13): separação jogo/produto, botões,
callback autorizado só pro chat original, expiração, rate limit."""

from __future__ import annotations

import json
import time
from types import SimpleNamespace

import httpx
import pytest

from k4promo.commands import hunt
from k4promo.services.rate_limit import WindowRateLimiter
from k4promo.telegram import client


def _cfg():
    return SimpleNamespace(
        aliexpress_app_key="k", aliexpress_app_secret="s", aliexpress_tracking_id="t",
        shopee_app_id="a", shopee_app_secret="b",
    )


@pytest.fixture(autouse=True)
def _isolate():
    hunt.reset_for_testing()
    client.reset_client_for_testing()
    yield
    hunt.reset_for_testing()
    client.reset_client_for_testing()


def _install_capture():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith("/sendMessage"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        if request.url.path.endswith("/answerCallbackQuery"):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": True})
        return httpx.Response(404, json={"ok": False})

    client.reset_client_for_testing(httpx.Client(transport=httpx.MockTransport(handler)))
    client._rate_limiter = client.RateLimiter(chat_interval=0.0, global_interval=0.0)
    return sent


def _steam_result(title="Palworld", price=59.9):
    return hunt.HuntResult(source="steam", title=title, price=price, link="https://x/1")


def _shopee_result(title="Boneco Palworld", price=39.9):
    return hunt.HuntResult(source="shopee", title=title, price=price, link="https://x/2")


# ---------------------------------------------------------------------------
# _run_search: separação jogo/produto e botões
# ---------------------------------------------------------------------------

def test_run_search_separa_jogo_e_produto_e_manda_botoes(monkeypatch):
    sent = _install_capture()
    monkeypatch.setattr(hunt, "_search_aliexpress", lambda cfg, q: [])
    monkeypatch.setattr(hunt, "_search_shopee", lambda cfg, q: [_shopee_result()])
    monkeypatch.setattr(hunt, "_search_steam", lambda q: [_steam_result()])

    hunt._run_search(_cfg(), "TOKEN", "111", "palworld")

    entry = hunt._pending["111"]
    assert len(entry["results"]["jogo"]) == 1
    assert len(entry["results"]["produto"]) == 1
    assert entry["searching"] is False

    assert len(sent) == 1
    assert "reply_markup" in sent[0]
    buttons = sent[0]["reply_markup"]["inline_keyboard"][0]
    assert buttons[0]["callback_data"] == "hunt:jogo:111"
    assert buttons[1]["callback_data"] == "hunt:produto:111"


def test_run_search_so_jogo_envia_lista_direto_sem_botoes(monkeypatch):
    sent = _install_capture()
    monkeypatch.setattr(hunt, "_search_aliexpress", lambda cfg, q: [])
    monkeypatch.setattr(hunt, "_search_shopee", lambda cfg, q: [])
    monkeypatch.setattr(hunt, "_search_steam", lambda q: [_steam_result()])

    hunt._run_search(_cfg(), "TOKEN", "111", "palworld")

    assert len(sent) == 1
    assert "reply_markup" not in sent[0]
    assert "Palworld" in sent[0]["text"]


def test_run_search_nada_encontrado(monkeypatch):
    sent = _install_capture()
    monkeypatch.setattr(hunt, "_search_aliexpress", lambda cfg, q: [])
    monkeypatch.setattr(hunt, "_search_shopee", lambda cfg, q: [])
    monkeypatch.setattr(hunt, "_search_steam", lambda q: [])

    hunt._run_search(_cfg(), "TOKEN", "111", "xyzxyz123")

    assert "Nada encontrado" in sent[0]["text"]


def test_run_search_fonte_falha_nao_derruba_as_outras(monkeypatch):
    sent = _install_capture()

    def falha(cfg, q):
        raise RuntimeError("boom")

    monkeypatch.setattr(hunt, "_search_aliexpress", falha)
    monkeypatch.setattr(hunt, "_search_shopee", lambda cfg, q: [_shopee_result()])
    monkeypatch.setattr(hunt, "_search_steam", lambda q: [])

    hunt._run_search(_cfg(), "TOKEN", "111", "algo")

    assert hunt._pending["111"]["results"]["produto"] == [_shopee_result()]
    assert len(sent) == 1


# ---------------------------------------------------------------------------
# Callback: autorização por chat + expiração + reaproveita resultado
# ---------------------------------------------------------------------------

def test_callback_de_outro_chat_e_recusado():
    sent = _install_capture()
    hunt._pending["111"] = {
        "searching": False, "expires_at": time.monotonic() + 600,
        "query": "x", "results": {"jogo": [_steam_result()], "produto": []},
    }
    callback = {
        "id": "cb1", "data": "hunt:jogo:111",
        "message": {"chat": {"id": 222}},
    }
    handled = hunt.handle_callback("TOKEN", callback)
    assert handled is True
    assert sent[0].get("show_alert") is True
    assert "não é sua" in sent[0]["text"]
    # Não deve ter enviado a lista de resultados (só a resposta do callback).
    assert len(sent) == 1


def test_callback_do_chat_correto_devolve_resultado_sem_rechamar_apis(monkeypatch):
    sent = _install_capture()
    monkeypatch.setattr(
        hunt, "_search_steam",
        lambda q: (_ for _ in ()).throw(AssertionError("não deveria rechamar a API")),
    )
    hunt._pending["111"] = {
        "searching": False, "expires_at": time.monotonic() + 600,
        "query": "palworld", "results": {"jogo": [_steam_result()], "produto": []},
    }
    callback = {"id": "cb1", "data": "hunt:jogo:111", "message": {"chat": {"id": 111}}}

    handled = hunt.handle_callback("TOKEN", callback)

    assert handled is True
    # answerCallbackQuery + sendMessage com o resultado.
    assert len(sent) == 2
    assert "Palworld" in sent[1]["text"]


def test_callback_busca_expirada():
    sent = _install_capture()
    hunt._pending["111"] = {
        "searching": False, "expires_at": time.monotonic() - 1,
        "query": "x", "results": {"jogo": [_steam_result()], "produto": []},
    }
    callback = {"id": "cb1", "data": "hunt:jogo:111", "message": {"chat": {"id": 111}}}

    hunt.handle_callback("TOKEN", callback)

    assert sent[0].get("show_alert") is True
    assert "expirada" in sent[0]["text"]


def test_callback_ignorado_se_nao_for_do_hunt():
    handled = hunt.handle_callback("TOKEN", {"id": "cb1", "data": "outracoisa:1", "message": {}})
    assert handled is False


# ---------------------------------------------------------------------------
# Rate limit de /buscar (chat e global) e "uma busca por vez"
# ---------------------------------------------------------------------------

def test_buscar_bloqueia_segunda_busca_do_mesmo_chat_enquanto_a_primeira_roda():
    sent = _install_capture()
    hunt._pending["111"] = {
        "searching": True, "expires_at": time.monotonic() + 600,
        "query": "x", "results": {"jogo": [], "produto": []},
    }
    hunt.handle_buscar(_cfg(), "TOKEN", "111", "outra busca")
    assert "em andamento" in sent[0]["text"]


def test_buscar_respeita_rate_limit_por_chat(monkeypatch):
    sent = _install_capture()
    hunt._chat_limiter = WindowRateLimiter(max_events=1, window_seconds=3600)
    hunt._global_limiter = WindowRateLimiter(max_events=100, window_seconds=60)
    monkeypatch.setattr(
        "k4promo.commands.hunt.threading.Thread",
        lambda *a, **kw: SimpleNamespace(start=lambda: None),
    )

    hunt.handle_buscar(_cfg(), "TOKEN", "111", "primeira")
    hunt._pending["111"]["searching"] = False  # simula a primeira busca já concluída
    hunt.handle_buscar(_cfg(), "TOKEN", "111", "segunda")

    assert "Limite de buscas por hora" in sent[-1]["text"]


def test_buscar_respeita_rate_limit_global(monkeypatch):
    sent = _install_capture()
    hunt._chat_limiter = WindowRateLimiter(max_events=100, window_seconds=3600)
    hunt._global_limiter = WindowRateLimiter(max_events=1, window_seconds=60)
    monkeypatch.setattr(
        "k4promo.commands.hunt.threading.Thread",
        lambda *a, **kw: SimpleNamespace(start=lambda: None),
    )

    hunt.handle_buscar(_cfg(), "TOKEN", "111", "primeira")
    hunt.handle_buscar(_cfg(), "TOKEN", "222", "segunda")

    assert "Muitas buscas agora" in sent[-1]["text"]


def test_buscar_sem_texto_pede_uso():
    sent = _install_capture()
    hunt.handle_buscar(_cfg(), "TOKEN", "111", "   ")
    assert "/buscar" in sent[0]["text"]
