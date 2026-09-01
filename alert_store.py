import json
import logging
import unicodedata
from datetime import UTC, datetime
from pathlib import Path

STORE_PATH = Path(__file__).parent / "alerts.json"
COOLDOWN_HOURS = 24

log = logging.getLogger("k4binho")


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def load_alerts() -> dict[str, list[dict]]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_alerts(alerts: dict[str, list[dict]]) -> None:
    STORE_PATH.write_text(
        json.dumps(alerts, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def add_alert(
    alerts: dict[str, list[dict]],
    chat_id: str,
    keywords: str,
    max_price: float | None = None,
    source: str | None = None,
) -> dict:
    entry = {
        "keywords": keywords.strip(),
        "keywords_normalized": _normalize(keywords),
        "max_price": max_price,
        "source": source,
        "notified": {},
    }
    alerts.setdefault(chat_id, []).append(entry)
    return entry


def remove_alert(alerts: dict[str, list[dict]], chat_id: str, index: int) -> bool:
    user_alerts = alerts.get(chat_id, [])
    if 0 <= index < len(user_alerts):
        user_alerts.pop(index)
        if not user_alerts:
            alerts.pop(chat_id, None)
        return True
    return False


def get_alerts(alerts: dict[str, list[dict]], chat_id: str) -> list[dict]:
    return alerts.get(chat_id, [])


def _is_in_cooldown(alert: dict, product_id: str, current_price: float) -> bool:
    notified = alert.get("notified", {})
    entry = notified.get(product_id)
    if not entry:
        return False
    last_price = entry.get("price", 0)
    last_at = entry.get("at", "")
    if not last_at:
        return False
    try:
        last_time = datetime.fromisoformat(last_at)
    except (TypeError, ValueError):
        return False
    hours_since = (datetime.now(UTC) - last_time).total_seconds() / 3600
    if hours_since >= COOLDOWN_HOURS:
        return False
    if current_price < last_price * 0.9:
        return False
    return True


def _record_notification(alert: dict, product_id: str, price: float) -> None:
    alert.setdefault("notified", {})[product_id] = {
        "price": round(price, 2),
        "at": datetime.now(UTC).isoformat(),
    }


def match_deal(
    alerts: dict[str, list[dict]],
    title: str,
    price: float,
    source: str,
    product_id: str = "",
) -> list[tuple[str, dict]]:
    title_norm = _normalize(title)
    dedup_key = product_id or _normalize(title)[:60]
    matches = []
    for chat_id, user_alerts in alerts.items():
        for alert in user_alerts:
            kw = alert["keywords_normalized"]
            if kw not in title_norm:
                continue
            if alert.get("max_price") and price > alert["max_price"]:
                continue
            if alert.get("source") and alert["source"] != source:
                continue
            if _is_in_cooldown(alert, dedup_key, price):
                continue
            _record_notification(alert, dedup_key, price)
            matches.append((chat_id, alert))
    return matches
