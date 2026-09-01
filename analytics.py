import json
import logging
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

STORE_PATH = Path(__file__).parent / "analytics.jsonl"

log = logging.getLogger("k4binho")


def _generate_deal_id() -> str:
    return uuid4().hex[:12]


def record_deal(
    *,
    source: str,
    product_id: str,
    title: str,
    price: float,
    listed_price: float | None = None,
    original_price: float | None = None,
    discount_percent: int = 0,
    quality_score: int | None = None,
    conversion_score: int | None = None,
    retention_score: int | None = None,
    confidence_score: int | None = None,
    final_score: float | None = None,
    price_subtotal: int | None = None,
    reasons: list[str] | None = None,
    history_observations: int | None = None,
    min_price_30d: float | None = None,
    avg_price_30d: float | None = None,
    history_confidence: str = "",
    category: str = "",
    deal_type: str = "commercial",
    affiliate: bool = False,
    action: str = "published",
    action_reason: str = "",
    promotion_code: str = "",
    promotion_savings: float = 0.0,
    promotion_conditional: bool = False,
) -> str:
    deal_id = _generate_deal_id()
    now = datetime.now(UTC)
    entry = {
        "deal_id": deal_id,
        "timestamp": now.isoformat(),
        "source": source,
        "product_id": product_id,
        "title": title,
        "price": price,
        "listed_price": listed_price,
        "original_price": original_price,
        "discount_percent": discount_percent,
        "quality_score": quality_score,
        "conversion_score": conversion_score,
        "retention_score": retention_score,
        "confidence_score": confidence_score,
        "final_score": final_score,
        "price_subtotal": price_subtotal,
        "reasons": reasons or [],
        "history_observations": history_observations,
        "min_price_30d": min_price_30d,
        "avg_price_30d": avg_price_30d,
        "history_confidence": history_confidence,
        "category": category,
        "deal_type": deal_type,
        "affiliate": affiliate,
        "action": action,
        "action_reason": action_reason,
        "promotion_code": promotion_code,
        "promotion_savings": promotion_savings,
        "promotion_conditional": promotion_conditional,
    }
    try:
        with open(STORE_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("[Analytics] falha ao gravar: %s", exc)
    return deal_id


def load_entries(limit: int = 0) -> list[dict]:
    if not STORE_PATH.exists():
        return []
    entries = []
    with open(STORE_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit > 0:
        return entries[-limit:]
    return entries
