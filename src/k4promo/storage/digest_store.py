import hashlib
import json
import logging
from pathlib import Path

from k4promo.storage.paths import data_path

STATE_PATH = data_path("digest_state.json")
log = logging.getLogger("k4binho")


def load_state() -> dict[str, str]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_state(state: dict[str, str]) -> None:
    """Persist digest state atomically so restarts don't resend today's digest."""
    tmp = STATE_PATH.with_suffix(".tmp")
    payload = json.dumps(state, ensure_ascii=False, separators=(",", ":"))
    tmp.write_text(payload, encoding="utf-8")
    tmp.replace(STATE_PATH)


def digest_hash(items: list[dict]) -> str:
    """Stable hash of the visible digest content, independent of dict ordering."""
    normalized = [
        {
            "title": str(item.get("title", "")),
            "price": round(float(item.get("price", 0) or 0), 2),
            "source": str(item.get("source", "")),
        }
        for item in items
    ]
    raw = json.dumps(normalized, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def already_sent_today(state: dict[str, str], today: str) -> bool:
    return state.get("last_sent_date") == today


def mark_sent(state: dict[str, str], today: str, content_hash: str) -> None:
    state["last_sent_date"] = today
    state["last_digest_hash"] = content_hash
    save_state(state)
