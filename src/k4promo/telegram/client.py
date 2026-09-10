"""Cliente da Telegram Bot API.

Fase 2 do hardening operacional: cliente HTTP reutilizável (pool de conexões),
rate limit por chat e global, retry exponencial em 429/5xx/erros de rede
temporários, respeito ao ``retry_after`` do Telegram, fallback de foto para
texto, suporte a ``reply_markup``/callback query, retorno do ``message_id`` e
exclusão de mensagem. Nunca loga o token do bot nem a URL completa da API.

O layout das mensagens (o que vira texto/HTML) continua em ``formatters.py``;
este módulo só transporta.
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time

import httpx

log = logging.getLogger("k4binho")

API_BASE = "https://api.telegram.org/bot{token}"
MESSAGE_URL = API_BASE + "/sendMessage"
PHOTO_URL = API_BASE + "/sendPhoto"
DELETE_URL = API_BASE + "/deleteMessage"
ANSWER_CALLBACK_URL = API_BASE + "/answerCallbackQuery"

# Limites reais da Bot API.
TEXT_MAX_LEN = 4096
CAPTION_MAX_LEN = 1024

RETRYABLE_STATUS = frozenset({500, 502, 503, 504})

_INCOMPLETE_TAG_RE = re.compile(r"<[^>]*$")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


# ---------------------------------------------------------------------------
# Sanitização — nunca deixar o token do bot chegar a um log.
# ---------------------------------------------------------------------------

def sanitize(text: str, token: str | None = None) -> str:
    """Remove o token do bot de uma string antes dela ir pro log."""
    if not text:
        return text
    if token:
        text = text.replace(token, "<token>")
    # Cinto de segurança: qualquer coisa que pareça um token de bot Telegram
    # (dígitos ':' resto) dentro de uma URL /bot.../ também é redigida, para
    # o caso de o token não ter sido passado explicitamente.
    return re.sub(r"/bot\d+:[A-Za-z0-9_-]+", "/bot<token>", text)


def _truncate(text: str, max_len: int) -> str:
    """Corta o texto no limite do Telegram. Best-effort quanto a HTML: remove
    uma tag cortada ao meio na borda do corte, mas não garante tags
    balanceadas para conteúdo que já ultrapassava o limite de tags abertas.
    """
    if not text or len(text) <= max_len:
        return text
    cut = text[: max_len - 1]
    cut = _INCOMPLETE_TAG_RE.sub("", cut)
    return cut.rstrip() + "…"


# ---------------------------------------------------------------------------
# Rate limiting — por chat e global.
# ---------------------------------------------------------------------------

class RateLimiter:
    """Impõe um intervalo mínimo entre chamadas: uma por chat, outra global.

    Thread-safe: várias fontes (ciclos concorrentes, Fase 1) e o listener em
    tempo real (Fase 3) podem chamar ``acquire`` ao mesmo tempo.
    """

    def __init__(self, chat_interval: float, global_interval: float) -> None:
        self.chat_interval = max(0.0, chat_interval)
        self.global_interval = max(0.0, global_interval)
        self._lock = threading.Lock()
        self._last_global = 0.0
        self._last_chat: dict[str, float] = {}

    def acquire(self, chat_id: str | None) -> None:
        """Bloqueia até que seja seguro enviar pro ``chat_id`` (e globalmente)."""
        while True:
            with self._lock:
                now = time.monotonic()
                wait_global = self._last_global + self.global_interval - now
                wait_chat = 0.0
                if chat_id is not None:
                    last_chat = self._last_chat.get(chat_id, 0.0)
                    wait_chat = last_chat + self.chat_interval - now
                wait = max(wait_global, wait_chat, 0.0)
                if wait <= 0:
                    self._last_global = now
                    if chat_id is not None:
                        self._last_chat[chat_id] = now
                    return
            time.sleep(wait)


_rate_limiter: RateLimiter | None = None
_rate_limiter_lock = threading.Lock()


def _get_rate_limiter() -> RateLimiter:
    global _rate_limiter
    if _rate_limiter is None:
        with _rate_limiter_lock:
            if _rate_limiter is None:
                _rate_limiter = RateLimiter(
                    chat_interval=_env_float("TELEGRAM_CHAT_INTERVAL_SECONDS", 1.0),
                    global_interval=1.0 / max(1, _env_int("TELEGRAM_GLOBAL_MESSAGES_PER_SECOND", 25)),
                )
    return _rate_limiter


# ---------------------------------------------------------------------------
# Cliente HTTP reutilizável.
# ---------------------------------------------------------------------------

_client: httpx.Client | None = None
_client_lock = threading.Lock()


def _get_client() -> httpx.Client:
    global _client
    if _client is None:
        with _client_lock:
            if _client is None:
                timeout = _env_float("TELEGRAM_HTTP_TIMEOUT_SECONDS", 30.0)
                _client = httpx.Client(
                    timeout=timeout,
                    limits=httpx.Limits(max_connections=20, max_keepalive_connections=10),
                )
    return _client


def reset_client_for_testing(client: httpx.Client | None = None) -> None:
    """Só pra testes: injeta um client (normalmente com MockTransport) ou
    força a recriação do client real na próxima chamada."""
    global _client, _rate_limiter
    _client = client
    _rate_limiter = None


def _sleep_backoff(attempt: int) -> None:
    time.sleep(_backoff_seconds(attempt))


def _backoff_seconds(attempt: int) -> float:
    """Backoff exponencial: 0.5s, 1s, 2s, 4s... com teto em 15s."""
    return min(0.5 * (2 ** (attempt - 1)), 15.0)


def _retry_after_seconds(resp: httpx.Response, attempt: int) -> float:
    try:
        body = resp.json()
        retry_after = body.get("parameters", {}).get("retry_after")
        if retry_after is not None:
            return float(retry_after)
    except ValueError:
        pass
    header = resp.headers.get("Retry-After")
    if header:
        try:
            return float(header)
        except ValueError:
            pass
    return _backoff_seconds(attempt)


class TelegramAPIError(httpx.HTTPStatusError):
    """Erro reportado pela Bot API com ``ok: false`` mesmo em HTTP 200."""


def _sanitized_status_error(resp: httpx.Response, token: str) -> httpx.HTTPStatusError:
    """Constrói o HTTPStatusError que ``resp.raise_for_status()`` geraria,
    mas com o token redigido da mensagem — a exceção original do httpx
    embute a URL completa (com token) na mensagem, e quem a captura rio
    acima costuma logar ``str(exc)`` direto."""
    try:
        resp.raise_for_status()
    except httpx.HTTPStatusError as exc:
        return httpx.HTTPStatusError(
            sanitize(str(exc), token), request=exc.request, response=exc.response
        )
    raise AssertionError("status esperado como erro")  # pragma: no cover


def _sanitized_transport_error(exc: httpx.TransportError, token: str) -> httpx.TransportError:
    return type(exc)(sanitize(str(exc), token), request=getattr(exc, "request", None))


def _call(
    url: str,
    payload: dict,
    *,
    token: str,
    chat_id: str | None,
    max_retries: int | None = None,
) -> dict:
    """POST com rate limit + retry. Devolve o campo ``result`` da resposta.

    Sempre levanta uma subclasse de ``httpx.HTTPError`` em caso de falha
    definitiva, para que o código existente (``except httpx.HTTPError``)
    continue funcionando sem alteração.
    """
    if max_retries is None:
        max_retries = _env_int("TELEGRAM_HTTP_MAX_RETRIES", 3)
    client = _get_client()
    limiter = _get_rate_limiter()
    attempt = 0

    while True:
        limiter.acquire(chat_id)
        try:
            resp = client.post(url, json=payload)
        except httpx.TransportError as exc:
            attempt += 1
            if attempt > max_retries:
                log.error(
                    "[Telegram] falha de rede após %d tentativa(s): %s",
                    max_retries, sanitize(str(exc), token),
                )
                raise _sanitized_transport_error(exc, token) from None
            log.warning(
                "[Telegram] falha de rede (tentativa %d/%d); retry em breve: %s",
                attempt, max_retries, sanitize(str(exc), token),
            )
            _sleep_backoff(attempt)
            continue

        if resp.status_code == 429:
            attempt += 1
            wait = _retry_after_seconds(resp, attempt)
            if attempt > max_retries:
                log.error("[Telegram] rate limited (429) após %d tentativa(s).", max_retries)
                raise _sanitized_status_error(resp, token) from None
            log.warning("[Telegram] rate limited (429); aguardando %.1fs.", wait)
            time.sleep(wait)
            continue

        if resp.status_code in RETRYABLE_STATUS:
            attempt += 1
            if attempt > max_retries:
                log.error(
                    "[Telegram] erro %d após %d tentativa(s).", resp.status_code, max_retries
                )
                raise _sanitized_status_error(resp, token) from None
            log.warning(
                "[Telegram] erro %d (tentativa %d/%d); retry em breve.",
                resp.status_code, attempt, max_retries,
            )
            _sleep_backoff(attempt)
            continue

        try:
            resp.raise_for_status()
        except httpx.HTTPStatusError as exc:
            log.error(
                "[Telegram] erro %d: %s", resp.status_code, sanitize(str(exc), token)
            )
            raise _sanitized_status_error(resp, token) from None

        data = resp.json()
        if not data.get("ok", False):
            desc = sanitize(str(data.get("description", "erro desconhecido")), token)
            log.error("[Telegram] API retornou ok=false: %s", desc)
            raise TelegramAPIError(desc, request=resp.request, response=resp)
        return data.get("result") or {}


def _message_payload(
    chat_id: str, text: str, thread_id: int | None, reply_markup: dict | None
) -> dict:
    payload = {
        "chat_id": chat_id,
        "text": _truncate(text, TEXT_MAX_LEN),
        "parse_mode": "HTML",
        "disable_web_page_preview": False,
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return payload


def _photo_payload(
    chat_id: str, image_url: str, caption: str, thread_id: int | None, reply_markup: dict | None
) -> dict:
    payload = {
        "chat_id": chat_id,
        "photo": image_url,
        "caption": _truncate(caption, CAPTION_MAX_LEN),
        "parse_mode": "HTML",
    }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    if reply_markup is not None:
        payload["reply_markup"] = reply_markup
    return payload


def send_message(
    token: str,
    channel_id: str,
    text: str,
    thread_id: int | None = None,
    image_url: str | None = None,
    reply_markup: dict | None = None,
) -> int | None:
    """Envia uma mensagem (com foto, se ``image_url`` for informado).

    Devolve o ``message_id`` da mensagem publicada, ou ``None`` se a API não
    devolveu um (não deveria acontecer em uso normal). Se o envio com foto
    falhar, tenta reenviar como texto puro antes de desistir.
    """
    if image_url:
        payload = _photo_payload(channel_id, image_url, text, thread_id, reply_markup)
        try:
            result = _call(
                PHOTO_URL.format(token=token), payload, token=token, chat_id=channel_id
            )
            return result.get("message_id")
        except httpx.HTTPError as exc:
            log.warning(
                "[Telegram] foto rejeitada (%s); reenviando sem imagem.",
                sanitize(str(exc), token),
            )

    payload = _message_payload(channel_id, text, thread_id, reply_markup)
    result = _call(MESSAGE_URL.format(token=token), payload, token=token, chat_id=channel_id)
    return result.get("message_id")


def delete_message(token: str, chat_id: str, message_id: int) -> bool:
    """Apaga uma mensagem. Falha ao apagar nunca propaga — best effort."""
    payload = {"chat_id": chat_id, "message_id": message_id}
    try:
        _call(DELETE_URL.format(token=token), payload, token=token, chat_id=chat_id)
        return True
    except httpx.HTTPError as exc:
        log.warning(
            "[Telegram] falha ao apagar mensagem %s: %s", message_id, sanitize(str(exc), token)
        )
        return False


def answer_callback_query(
    token: str,
    callback_query_id: str,
    text: str | None = None,
    show_alert: bool = False,
) -> None:
    """Responde a um callback de botão inline. Falha nunca propaga."""
    payload: dict = {"callback_query_id": callback_query_id}
    if text:
        payload["text"] = text
    if show_alert:
        payload["show_alert"] = True
    try:
        _call(ANSWER_CALLBACK_URL.format(token=token), payload, token=token, chat_id=None)
    except httpx.HTTPError as exc:
        log.warning("[Telegram] falha ao responder callback: %s", sanitize(str(exc), token))
