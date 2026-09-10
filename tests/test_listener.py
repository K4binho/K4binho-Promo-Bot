"""Testes do listener em tempo real (Fase 3, seção 12)."""

from __future__ import annotations

import json
import threading
import time
from types import SimpleNamespace

import httpx
import pytest

from k4promo.commands import hunt
from k4promo.services.context import CycleContext
from k4promo.storage import listener_state
from k4promo.telegram import client
from k4promo.telegram.listener import Listener


def _cfg():
    return SimpleNamespace(telegram_bot_token="TOKEN", telegram_admin_chat_id="")


def _ctx():
    return CycleContext(cfg=_cfg())


@pytest.fixture(autouse=True)
def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(listener_state, "OFFSET_PATH", tmp_path / "listener_offset.json")
    hunt.reset_for_testing()
    client.reset_client_for_testing()
    yield
    hunt.reset_for_testing()
    client.reset_client_for_testing()


def _install_capture():
    sent: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path.endswith(("/sendMessage", "/answerCallbackQuery")):
            sent.append(json.loads(request.content))
            return httpx.Response(200, json={"ok": True, "result": {"message_id": 1}})
        return httpx.Response(404, json={"ok": False})

    client.reset_client_for_testing(httpx.Client(transport=httpx.MockTransport(handler)))
    client._rate_limiter = client.RateLimiter(chat_interval=0.0, global_interval=0.0)
    return sent


# ---------------------------------------------------------------------------
# Roteamento de mensagem/callback (sem long polling — chamando _dispatch direto)
# ---------------------------------------------------------------------------

def test_dispatch_mensagem_de_alerta_usa_ctx_lock_e_persiste(monkeypatch, tmp_path):
    sent = _install_capture()
    ctx = _ctx()
    saved = {"called": False}
    monkeypatch.setattr(
        "k4promo.telegram.listener.alert_store.save_alerts",
        lambda alerts: saved.__setitem__("called", True),
    )
    listener = Listener(_cfg(), ctx)

    listener._dispatch_message(
        "TOKEN", {"chat": {"id": 111}, "text": "/alerta rtx 5070"}
    )

    assert "111" in ctx.alerts
    assert saved["called"] is True
    assert "Alerta criado" in sent[0]["text"]


def test_dispatch_mensagem_buscar_chama_hunt(monkeypatch):
    ctx = _ctx()
    called = {}
    monkeypatch.setattr(
        "k4promo.telegram.listener.hunt.handle_buscar",
        lambda cfg, token, chat_id, query: called.update(
            token=token, chat_id=chat_id, query=query
        ),
    )
    listener = Listener(_cfg(), ctx)

    listener._dispatch_message("TOKEN", {"chat": {"id": 111}, "text": "/buscar palworld"})

    assert called == {"token": "TOKEN", "chat_id": "111", "query": "palworld"}


def test_dispatch_mensagem_respeita_rate_limit_de_comando(monkeypatch):
    ctx = _ctx()
    calls = {"n": 0}
    monkeypatch.setattr(
        "k4promo.telegram.listener.admin.dispatch_message",
        lambda *a, **kw: calls.__setitem__("n", calls["n"] + 1),
    )
    monkeypatch.setattr("k4promo.telegram.listener.alert_store.save_alerts", lambda alerts: None)
    listener = Listener(_cfg(), ctx)
    listener._command_limiter.max_events = 1

    listener._dispatch_message("TOKEN", {"chat": {"id": 111}, "text": "/status"})
    listener._dispatch_message("TOKEN", {"chat": {"id": 111}, "text": "/status"})

    assert calls["n"] == 1


def test_dispatch_callback_hunt_reconhecido(monkeypatch):
    ctx = _ctx()
    called = {}
    monkeypatch.setattr(
        "k4promo.telegram.listener.hunt.handle_callback",
        lambda token, callback: called.update(token=token, callback=callback) or True,
    )
    listener = Listener(_cfg(), ctx)
    cb = {"id": "cb1", "data": "hunt:jogo:111", "message": {"chat": {"id": 111}}}

    listener._dispatch_callback("TOKEN", cb)

    assert called["callback"] == cb


def test_dispatch_callback_desconhecido_confirma_pra_nao_travar_botao():
    sent = _install_capture()
    ctx = _ctx()
    listener = Listener(_cfg(), ctx)

    listener._dispatch_callback("TOKEN", {"id": "cb1", "data": "outracoisa", "message": {}})

    assert sent == [{"callback_query_id": "cb1"}]


# ---------------------------------------------------------------------------
# Loop de long polling: persiste offset e continua rodando durante o "ciclo"
# ---------------------------------------------------------------------------

def test_run_persiste_offset_apos_processar_update(monkeypatch):
    ctx = _ctx()
    monkeypatch.setattr("k4promo.telegram.listener.admin.dispatch_message", lambda *a, **kw: None)
    monkeypatch.setattr("k4promo.telegram.listener.alert_store.save_alerts", lambda alerts: None)

    processed = threading.Event()
    calls = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        calls["n"] += 1
        if calls["n"] == 1:
            update = {
                "update_id": 555,
                "message": {"chat": {"id": 111}, "text": "/status"},
            }
            return httpx.Response(200, json={"ok": True, "result": [update]})
        processed.set()
        return httpx.Response(200, json={"ok": True, "result": []})

    fake_client = httpx.Client(transport=httpx.MockTransport(handler))
    listener = Listener(_cfg(), ctx, client=fake_client)

    listener.start()
    assert processed.wait(timeout=2)
    listener.stop()

    assert listener_state.load_last_update_id() == 555


def test_listener_continua_ativo_enquanto_uma_tarefa_longa_roda(monkeypatch):
    """Simula 'ciclo demorado': o listener processa updates mesmo com outra
    thread ocupada por um tempo — prova que ele não depende da cadência dos
    ciclos (critério de aceite da seção 27/12)."""
    ctx = _ctx()
    handled = threading.Event()
    monkeypatch.setattr(
        "k4promo.telegram.listener.admin.dispatch_message",
        lambda *a, **kw: handled.set(),
    )
    monkeypatch.setattr("k4promo.telegram.listener.alert_store.save_alerts", lambda alerts: None)

    def handler(request: httpx.Request) -> httpx.Response:
        update = {"update_id": 1, "message": {"chat": {"id": 111}, "text": "/status"}}
        return httpx.Response(200, json={"ok": True, "result": [update]})

    fake_client = httpx.Client(transport=httpx.MockTransport(handler))
    listener = Listener(_cfg(), ctx, client=fake_client)

    long_task_done = threading.Event()
    long_thread = threading.Thread(target=lambda: (time.sleep(0.2), long_task_done.set()))
    long_thread.start()

    listener.start()
    assert handled.wait(timeout=1)  # respondeu ao comando antes do "ciclo" acabar
    assert not long_task_done.is_set()

    long_thread.join()
    listener.stop()
