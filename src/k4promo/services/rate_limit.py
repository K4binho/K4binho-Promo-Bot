"""Rate limit por janela deslizante — usado pra comandos e ``/buscar``.

Independente do ``RateLimiter`` de ``telegram/client.py`` (aquele impõe um
intervalo mínimo entre envios; este aqui conta quantos eventos aconteceram
numa janela de tempo, por chave — por chat ou globalmente).
"""

from __future__ import annotations

import threading
import time
from collections import deque


class WindowRateLimiter:
    """No máximo ``max_events`` eventos por chave a cada ``window_seconds``.

    Uma chave ``None`` funciona como limite global (uma fila só, sem chat).
    Thread-safe. Registros antigos são limpos a cada acesso da própria
    chave — sem necessidade de um processo de limpeza separado, e sem
    manter timestamps além da janela configurada.
    """

    def __init__(self, max_events: int, window_seconds: float) -> None:
        self.max_events = max_events
        self.window_seconds = window_seconds
        self._lock = threading.Lock()
        self._events: dict[str | None, deque[float]] = {}

    def allow(self, key: str | None = None) -> bool:
        """Registra uma tentativa e devolve se ela é permitida agora."""
        now = time.monotonic()
        with self._lock:
            bucket = self._events.setdefault(key, deque())
            self._prune(bucket, now)
            if len(bucket) >= self.max_events:
                return False
            bucket.append(now)
            return True

    def _prune(self, bucket: deque[float], now: float) -> None:
        cutoff = now - self.window_seconds
        while bucket and bucket[0] < cutoff:
            bucket.popleft()

    def prune_all(self) -> None:
        """Limpeza periódica: remove chaves sem eventos recentes, evitando
        que o dict cresça pra sempre com chats que só apareceram uma vez."""
        now = time.monotonic()
        with self._lock:
            empty_keys = []
            for key, bucket in self._events.items():
                self._prune(bucket, now)
                if not bucket:
                    empty_keys.append(key)
            for key in empty_keys:
                del self._events[key]
