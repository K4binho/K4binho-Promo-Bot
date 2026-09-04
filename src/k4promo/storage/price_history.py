import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from k4promo.storage.paths import data_path

STORE_PATH = data_path("price_history.json")


def load_history() -> dict[str, list[list[str | int]]]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_history(history: dict[str, list[list[str | int]]]) -> None:
    STORE_PATH.write_text(
        json.dumps(history, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def record(history: dict[str, list[list[str | int]]], item_id: str, price: float) -> None:
    now = datetime.now(UTC)
    history.setdefault(item_id, []).append([now.isoformat(), round(price * 100)])


def _recent(
    history: dict[str, list[list[str | int]]], item_id: str, days: int
) -> list[int]:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    prices = []
    for observed_at, price_cents in history.get(item_id, []):
        try:
            timestamp = datetime.fromisoformat(str(observed_at))
            if timestamp >= cutoff:
                prices.append(int(price_cents))
        except (TypeError, ValueError):
            continue
    return prices


def observation_count(
    history: dict[str, list[list[str | int]]], item_id: str, days: int
) -> int:
    return len(_recent(history, item_id, days))


def min_price(
    history: dict[str, list[list[str | int]]], item_id: str, days: int
) -> float | None:
    prices = _recent(history, item_id, days)
    return min(prices) / 100 if prices else None


def avg_price(
    history: dict[str, list[list[str | int]]], item_id: str, days: int
) -> float | None:
    prices = _recent(history, item_id, days)
    if not prices:
        return None
    return sum(prices) / len(prices) / 100


def history_confidence(obs_count: int) -> str:
    if obs_count >= 8:
        return "high"
    if obs_count >= 4:
        return "medium"
    return "low"
