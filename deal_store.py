import json
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

STORE_PATH = Path(__file__).parent / "deal_store.json"

log = logging.getLogger("k4binho")


def load_deals() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_deals(deals: dict[str, dict]) -> None:
    STORE_PATH.write_text(
        json.dumps(deals, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def record_published(deals: dict[str, dict], item_id: str, price: float, *, promotion_signature: str = "") -> None:
    deals[item_id] = {"price": round(price, 2), "posted_at": datetime.now(UTC).isoformat(), "promotion_signature": promotion_signature}


def check_promotion_revival(deals: dict[str, dict], item_id: str, current_price: float, promotion_signature: str, *, min_drop_percent: float = 5.0, min_drop_amount: float = 20.0, cooldown_hours: int = 6, now: datetime | None = None) -> tuple[bool, float | None]:
    entry=deals.get(item_id)
    if not entry or not promotion_signature: return False, None
    if str(entry.get("promotion_signature","") or "") == promotion_signature: return False, None
    try: previous=float(entry.get("price"))
    except (TypeError, ValueError): return False, None
    if previous <= 0 or current_price >= previous: return False, previous
    raw=str(entry.get("posted_at","") or "")
    if raw:
        try:
            posted=datetime.fromisoformat(raw)
            if posted.tzinfo is None: posted=posted.replace(tzinfo=UTC)
            current=now or datetime.now(UTC)
            if current-posted.astimezone(UTC) < timedelta(hours=max(0,cooldown_hours)): return False, previous
        except ValueError: pass
    amount=previous-current_price; pct=(amount/previous)*100
    return (pct >= min_drop_percent or amount >= min_drop_amount), previous


def check_price_drop(
    deals: dict[str, dict],
    item_id: str,
    current_price: float,
    min_drop_percent: int = 10,
    min_drop_amount: float = 20.0,
) -> tuple[bool, float | None]:
    entry = deals.get(item_id)
    if not entry:
        return False, None
    previous_price = entry["price"]
    if current_price >= previous_price:
        return False, None
    drop_amount = previous_price - current_price
    drop_percent = (drop_amount / previous_price) * 100
    if drop_percent >= min_drop_percent or drop_amount >= min_drop_amount:
        return True, previous_price
    return False, None
