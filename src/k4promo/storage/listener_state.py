"""Persiste o ``update_id`` do último update processado pelo listener em
tempo real, pra não reenviar/reprocessar comandos depois de um restart."""

from __future__ import annotations

import json
import logging

from k4promo.storage.atomic import atomic_write_json
from k4promo.storage.paths import data_path

OFFSET_PATH = data_path("listener_offset.json")

log = logging.getLogger("k4binho")


def load_last_update_id() -> int:
    if not OFFSET_PATH.exists():
        return 0
    try:
        data = json.loads(OFFSET_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return 0
    value = data.get("last_update_id", 0) if isinstance(data, dict) else 0
    return int(value) if isinstance(value, (int, float)) else 0


def save_last_update_id(update_id: int) -> None:
    try:
        atomic_write_json(OFFSET_PATH, {"last_update_id": update_id})
    except OSError as exc:
        log.warning("[Listener] falha ao persistir offset: %s", exc)
