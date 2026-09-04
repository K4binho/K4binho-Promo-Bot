"""Limitador de requisicao por usuario (janela deslizante, thread-safe).

Superficie exposta ao publico: qualquer pessoa pode mandar comando no privado do
bot. Sem limite, um unico chat consegue disparar busca em loja (chamada de rede
paga) em rajada, ou encher o log. O limite e por chat e tambem global, porque
varios chats coordenados somam.
"""

import threading
import time


class SlidingWindowLimiter:
    def __init__(
        self,
        max_events: int,
        window_seconds: float,
        *,
        max_keys: int = 5000,
        clock=time.monotonic,
    ) -> None:
        if max_events < 1:
            raise ValueError("max_events deve ser >= 1")
        if window_seconds <= 0:
            raise ValueError("window_seconds deve ser > 0")
        self.max_events = max_events
        self.window_seconds = window_seconds
        self.max_keys = max_keys
        self._clock = clock
        self._lock = threading.Lock()
        self._hits: dict[str, list[float]] = {}

    def _prune(self, now: float) -> None:
        cutoff = now - self.window_seconds
        for key in list(self._hits):
            fresh = [t for t in self._hits[key] if t > cutoff]
            if fresh:
                self._hits[key] = fresh
            else:
                del self._hits[key]

    def check(self, key: str) -> tuple[bool, float]:
        """Consome uma vaga. Retorna (permitido, segundos_para_liberar)."""
        key = str(key)
        with self._lock:
            now = self._clock()
            cutoff = now - self.window_seconds
            hits = [t for t in self._hits.get(key, []) if t > cutoff]
            if len(hits) >= self.max_events:
                self._hits[key] = hits
                return False, max(0.0, hits[0] + self.window_seconds - now)
            hits.append(now)
            self._hits[key] = hits
            # Sem poda o dict cresce por chat visto, e chat_id vem de fora.
            if len(self._hits) > self.max_keys:
                self._prune(now)
            return True, 0.0

    def reset(self, key: str | None = None) -> None:
        with self._lock:
            if key is None:
                self._hits.clear()
            else:
                self._hits.pop(str(key), None)
