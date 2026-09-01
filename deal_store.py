import json
import logging
from datetime import UTC, datetime
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


def record_published(deals: dict[str, dict], item_id: str, price: float) -> None:
    deals[item_id] = {
        "price": round(price, 2),
        "posted_at": datetime.now(UTC).isoformat(),
    }


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
