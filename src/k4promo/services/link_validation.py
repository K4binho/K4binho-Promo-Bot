"""Validação de link antes de publicar (Fase 6, seção 20).

Um link CONFIRMADO morto (404/410) não deve ser publicado. Qualquer outro
resultado — timeout, falha de DNS, erro 5xx, ou qualquer coisa que não seja
um "não" definitivo — é inconclusivo e NÃO bloqueia a publicação: a rede é
instável, e é pior perder uma oferta boa por um problema passageiro do que
publicar um link que só *pode* estar com problema.

Imagem quebrada nunca é checada aqui: o cliente Telegram (Fase 2) já tenta
enviar a foto e cai pra texto puro sozinho se a Bot API rejeitar a URL —
checar a imagem de novo aqui seria uma segunda rede só pra confirmar o que
o próprio envio já vai confirmar.

Um cache curto evita bater o mesmo link várias vezes no mesmo ciclo (ou em
ciclos consecutivos, dentro da janela).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from enum import Enum

import httpx

log = logging.getLogger("k4binho")


def _env_float(name: str, default: float) -> float:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return float(raw.strip())
    except ValueError:
        return default


CACHE_TTL_SECONDS = _env_float("LINK_VALIDATION_CACHE_TTL_SECONDS", 300.0)
TIMEOUT_SECONDS = _env_float("LINK_VALIDATION_TIMEOUT_SECONDS", 8.0)

DEFINITELY_DEAD = frozenset({404, 410})


class LinkStatus(Enum):
    VALID = "valid"      # confirmado OK (2xx/3xx) ou nunca checado com sucesso
    INVALID = "invalid"  # confirmado morto (404/410)
    UNKNOWN = "unknown"  # inconclusivo (timeout, DNS, 5xx, etc.)


_cache: dict[str, tuple[float, LinkStatus]] = {}
_cache_lock = threading.Lock()


def clear_cache() -> None:
    """Só pra testes — o cache de produção se renova sozinho pelo TTL."""
    with _cache_lock:
        _cache.clear()


def _cached(url: str) -> LinkStatus | None:
    with _cache_lock:
        entry = _cache.get(url)
    if entry is None:
        return None
    ts, status = entry
    if time.monotonic() - ts > CACHE_TTL_SECONDS:
        return None
    return status


def _store(url: str, status: LinkStatus) -> None:
    with _cache_lock:
        _cache[url] = (time.monotonic(), status)


def check_link(url: str) -> LinkStatus:
    """Verifica se um link ainda existe. Nunca levanta exceção — qualquer
    falha de rede vira ``UNKNOWN``, não uma exceção pro chamador tratar."""
    if not url or not url.strip():
        return LinkStatus.INVALID

    cached = _cached(url)
    if cached is not None:
        return cached

    status = _check_uncached(url)
    _store(url, status)
    return status


def _check_uncached(url: str) -> LinkStatus:
    try:
        resp = httpx.head(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
    except httpx.HTTPError as exc:
        log.debug("[LinkValidation] HEAD inconclusivo para %s: %s", url, exc)
        return LinkStatus.UNKNOWN

    if resp.status_code == 405:
        # Alguns servidores recusam HEAD (405) mas respondem GET normalmente.
        try:
            resp = httpx.get(url, timeout=TIMEOUT_SECONDS, follow_redirects=True)
        except httpx.HTTPError as exc:
            log.debug("[LinkValidation] GET inconclusivo para %s: %s", url, exc)
            return LinkStatus.UNKNOWN

    if resp.status_code in DEFINITELY_DEAD:
        return LinkStatus.INVALID
    if resp.status_code >= 500:
        # Pode ser instabilidade momentânea da loja — inconclusivo.
        return LinkStatus.UNKNOWN
    return LinkStatus.VALID


def is_blocked(url: str) -> bool:
    """``True`` só quando o link foi CONFIRMADO morto. Qualquer resultado
    inconclusivo devolve ``False`` — a publicação segue normalmente."""
    return check_link(url) is LinkStatus.INVALID
