"""Realtime Telegram update listener.

Runs Telegram Bot API long polling independently from the promotion cycle so
commands are handled immediately even while the main worker is sleeping.
"""

import logging
import threading
import time
from collections.abc import Callable

import httpx

GETUPDATES_URL = "https://api.telegram.org/bot{token}/getUpdates"

log = logging.getLogger("k4binho")


class TelegramRealtimeListener:
    def __init__(
        self,
        token: str,
        handler: Callable[[dict], None],
        *,
        timeout_seconds: int = 25,
        retry_seconds: float = 2.0,
    ) -> None:
        self.token = token
        self.handler = handler
        self.timeout_seconds = max(1, timeout_seconds)
        self.retry_seconds = max(0.5, retry_seconds)
        self._offset = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self._thread = threading.Thread(
            target=self._run,
            name="telegram-realtime-listener",
            daemon=True,
        )
        self._thread.start()
        log.info("[Telegram] listener realtime iniciado.")

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        with httpx.Client(timeout=self.timeout_seconds + 10) as client:
            while not self._stop.is_set():
                try:
                    response = client.get(
                        GETUPDATES_URL.format(token=self.token),
                        params={
                            "offset": self._offset,
                            "timeout": self.timeout_seconds,
                            "allowed_updates": ["message"],
                        },
                    )
                    response.raise_for_status()
                    updates = response.json().get("result", [])
                    for update in updates:
                        update_id = int(update.get("update_id", 0))
                        self._offset = max(self._offset, update_id + 1)
                        try:
                            self.handler(update)
                        except Exception:
                            log.exception("[Telegram] erro processando update_id=%s", update_id)
                except httpx.HTTPError as exc:
                    if not self._stop.is_set():
                        log.warning("[Telegram] listener indisponivel: %s", exc)
                        time.sleep(self.retry_seconds)
                except Exception:
                    if not self._stop.is_set():
                        log.exception("[Telegram] falha inesperada no listener")
                        time.sleep(self.retry_seconds)
