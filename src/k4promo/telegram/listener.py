"""Listener de comandos em tempo real (Fase 3, seção 12).

Roda em thread própria com long polling contínuo — não fica preso à
cadência dos ciclos das lojas (ao contrário do antigo ``poll_commands``
síncrono, chamado uma vez por ciclo). Continua funcionando durante os
ciclos e durante o intervalo entre eles; encerra junto com o processo.
"""

from __future__ import annotations

import logging
import os
import threading
import time

import httpx

from k4promo import telegram
from k4promo.commands import admin, hunt
from k4promo.services.context import CycleContext
from k4promo.services.rate_limit import WindowRateLimiter
from k4promo.storage import alert_store, listener_state

log = logging.getLogger("k4binho")

GETUPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


class Listener:
    """Um listener por processo. ``start()``/``stop()`` controlam a thread."""

    def __init__(self, cfg, ctx: CycleContext, client: httpx.Client | None = None) -> None:
        self.cfg = cfg
        self.ctx = ctx
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._client = client
        self._owns_client = client is None
        self._command_limiter = WindowRateLimiter(
            _env_int("COMMAND_RATE_LIMIT_PER_MINUTE", 12), 60
        )

    def start(self) -> None:
        if self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._run, daemon=True, name="tg-listener"
        )
        self._thread.start()
        log.info("[Listener] iniciado (long polling).")

    def stop(self, timeout: float = 5.0) -> None:
        self._stop_event.set()
        if self._thread is not None:
            self._thread.join(timeout=timeout)
            self._thread = None
        if self._client is not None and self._owns_client:
            self._client.close()
            self._client = None
        log.info("[Listener] encerrado.")

    # -- loop principal -----------------------------------------------

    def _run(self) -> None:
        poll_timeout = _env_int("TELEGRAM_LISTENER_POLL_SECONDS", 25)
        if self._client is None:
            self._client = httpx.Client(timeout=poll_timeout + 10)
        last_update_id = listener_state.load_last_update_id()

        while not self._stop_event.is_set():
            try:
                updates = self._get_updates(last_update_id, poll_timeout)
            except Exception as exc:
                # Falha de rede/timeout no polling não pode matar a thread —
                # ela é a única forma de o bot responder comandos.
                log.warning("[Listener] polling falhou; tentando de novo: %s", exc)
                time.sleep(2)
                continue

            for update in updates:
                last_update_id = max(last_update_id, update.get("update_id", 0))
                try:
                    self._dispatch(update)
                except Exception as exc:
                    log.error("[Listener] falha ao processar update: %s", exc)

            if updates:
                listener_state.save_last_update_id(last_update_id)
            else:
                # No mundo real o long poll do Telegram já bloqueia até
                # poll_timeout esperando update novo; isso só evita um loop
                # apertado quando a resposta volta instantânea (testes/mock).
                time.sleep(0.05)

    def _get_updates(self, last_update_id: int, poll_timeout: int) -> list[dict]:
        resp = self._client.get(
            GETUPDATES_URL.format(token=self.cfg.telegram_bot_token),
            params={
                "offset": last_update_id + 1,
                "timeout": poll_timeout,
                "allowed_updates": ["message", "callback_query"],
            },
        )
        resp.raise_for_status()
        return resp.json().get("result", [])

    # -- roteamento ------------------------------------------------------

    def _dispatch(self, update: dict) -> None:
        token = self.cfg.telegram_bot_token

        msg = update.get("message")
        if msg and msg.get("text"):
            self._dispatch_message(token, msg)
            return

        callback = update.get("callback_query")
        if callback:
            self._dispatch_callback(token, callback)

    def _dispatch_message(self, token: str, msg: dict) -> None:
        chat_id = str(msg["chat"]["id"])
        if not self._command_limiter.allow(chat_id):
            log.info("[Listener] chat=%s ignorado (rate limit de comandos).", chat_id)
            return

        text = msg["text"].strip()
        if text.startswith("/buscar"):
            query = text[len("/buscar"):].strip()
            hunt.handle_buscar(self.cfg, token, chat_id, query)
            return

        # Comandos de alerta mexem em ctx.alerts, compartilhado com as fontes
        # concorrentes (Fase 1) — protegidos pelo mesmo lock que Publisher usa.
        with self.ctx.lock:
            admin.dispatch_message(
                token, chat_id, text, self.ctx.alerts,
                admin_chat_id=self.cfg.telegram_admin_chat_id,
            )
            alert_store.save_alerts(self.ctx.alerts)

    def _dispatch_callback(self, token: str, callback: dict) -> None:
        handled = hunt.handle_callback(token, callback)
        if not handled:
            # Callback que não reconhecemos: só tira o "carregando" do botão.
            telegram.answer_callback_query(token, callback.get("id", ""))
