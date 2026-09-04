"""Estado persistente da vitrine "Melhores do Dia".

Evita copiar o mesmo produto mais de uma vez em uma janela de dias e limita
a quantidade de cópias por dia.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from k4promo.storage.paths import data_path

STATE_PATH = data_path("showcase_state.json")
MEMORY_DAYS = 7


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"copied": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"copied": {}}
    if not isinstance(data, dict) or not isinstance(data.get("copied"), dict):
        return {"copied": {}}
    return data


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    tmp.write_text(
        json.dumps(state, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    tmp.replace(STATE_PATH)


def prune(state: dict, now: datetime | None = None, days: int = MEMORY_DAYS) -> None:
    current = now or datetime.now(UTC)
    cutoff = current - timedelta(days=days)
    copied = state.setdefault("copied", {})
    for key in list(copied):
        try:
            when = datetime.fromisoformat(copied[key])
        except (TypeError, ValueError):
            del copied[key]
            continue
        if when < cutoff:
            del copied[key]


def already_copied(state: dict, key: str) -> bool:
    return key in state.get("copied", {})


def copies_today(state: dict, now: datetime | None = None) -> int:
    current = (now or datetime.now(UTC)).astimezone()
    today = current.strftime("%Y-%m-%d")
    total = 0
    for ts in state.get("copied", {}).values():
        try:
            when = datetime.fromisoformat(ts).astimezone()
        except (TypeError, ValueError):
            continue
        if when.strftime("%Y-%m-%d") == today:
            total += 1
    return total


def mark_copied(state: dict, key: str, now: datetime | None = None) -> None:
    current = now or datetime.now(UTC)
    state.setdefault("copied", {})[key] = current.isoformat()
