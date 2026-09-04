import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from k4promo.storage.paths import data_path

STORE_PATH = data_path("seen.json")
PLUS_PREFIXES = ("steam:", "nuuvem:", "gmg:")
PLUS_EXPIRE_DAYS = 7


def load_seen() -> dict[str, str]:
    if not STORE_PATH.exists():
        return {}
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, list):
        now = datetime.now(UTC).isoformat()
        return {item: now for item in raw}
    if isinstance(raw, dict):
        return raw
    return {}


def save_seen(seen: dict[str, str]) -> None:
    STORE_PATH.write_text(
        json.dumps(seen, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def mark_seen(seen: dict[str, str], item_id: str) -> None:
    seen[item_id] = datetime.now(UTC).isoformat()


def expire_plus(seen: dict[str, str], days: int = PLUS_EXPIRE_DAYS) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    expired = []
    for item_id, ts in seen.items():
        if not any(item_id.startswith(p) for p in PLUS_PREFIXES):
            continue
        try:
            when = datetime.fromisoformat(ts)
            if when < cutoff:
                expired.append(item_id)
        except (TypeError, ValueError):
            continue
    for item_id in expired:
        del seen[item_id]
    return len(expired)
