"""Histórico de publicações e regras de republicação (Fase 4, seções 16-17).

A chave (``item_id``) já vem pronta de ``Offer.key`` — ``"<source>:<id>"``
pra toda loja, com o Mercado Livre mantendo o id puro por compatibilidade
histórica (ver ``domain.models.Offer.key``). Este módulo não precisa saber
de fonte: quem chama já garante que a chave nunca cruza lojas.

Uma publicação já feita só pode voltar por um destes motivos:
``menor_preco_historico``, ``novo_cupom``, ``queda_de_preco`` ou
``periodo_configurado``. ``should_republish`` decide isso nessa ordem de
prioridade e devolve o motivo, pra virar ``last_reason``/analytics.
"""

from __future__ import annotations

import json
import logging
import re
import unicodedata
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from k4promo.storage.atomic import atomic_write_json
from k4promo.storage.paths import data_path

STORE_PATH = data_path("deal_store.json")

log = logging.getLogger("k4binho")

_PUNCT_RE = re.compile(r"[^\w\s]", re.UNICODE)
_SPACE_RE = re.compile(r"\s+")


def load_deals() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_deals(deals: dict[str, dict]) -> None:
    atomic_write_json(STORE_PATH, deals)


# ---------------------------------------------------------------------------
# Normalização — pra reconhecer o mesmo produto relistado sob outro ID.
# ---------------------------------------------------------------------------

def normalize_title(title: str) -> str:
    if not title:
        return ""
    t = unicodedata.normalize("NFKD", title.strip().lower())
    t = "".join(char for char in t if not unicodedata.combining(char))
    t = _PUNCT_RE.sub("", t)
    return _SPACE_RE.sub(" ", t).strip()


def normalize_url(url: str) -> str:
    if not url:
        return ""
    parts = urlsplit(url)
    return f"{parts.netloc}{parts.path}".rstrip("/").lower()


def find_by_normalized_title(
    deals: dict[str, dict], source: str, normalized_title: str
) -> tuple[str, dict] | None:
    """Procura publicação da mesma loja por título normalizado.

    Aceita aliases históricos de chave (``ali:`` e ``aliexpress:``), para o
    estado antigo continuar bloqueando relistagem do AliExpress.
    """
    if not normalized_title:
        return None
    for key, entry in deals.items():
        if source == "ml":
            same_source = ":" not in key
        elif source in {"ali", "aliexpress"}:
            same_source = key.startswith(("ali:", "aliexpress:"))
        else:
            same_source = key.startswith(f"{source}:")
        if same_source and entry.get("normalized_title") == normalized_title:
            return key, entry
    return None


def find_by_title_in_seen(
    seen: dict[str, str], deals: dict[str, dict], source: str, title: str
) -> tuple[str, dict] | None:
    """Compatibilidade: consulta histórico de publicação por título."""
    return find_by_normalized_title(deals, source, normalize_title(title))


def source_key_aliases(source: str, offer_id: str) -> tuple[str, ...]:
    """Devolve chaves atuais e legadas aceitas para uma oferta."""
    if source in {"ali", "aliexpress"}:
        return (f"aliexpress:{offer_id}", f"ali:{offer_id}")
    if source == "ml":
        return (offer_id,)
    return (f"{source}:{offer_id}",)


# ---------------------------------------------------------------------------
# Gravação — schema completo, aditivo (compatível com o formato antigo).
# ---------------------------------------------------------------------------

def record_published(
    deals: dict[str, dict],
    item_id: str,
    price: float,
    *,
    promotion_signature: str = "",
    title: str = "",
    url: str = "",
    message_id: int | None = None,
    thread_id: int | None = None,
    reason: str = "novo",
) -> None:
    existing = deals.get(item_id) or {}
    now = datetime.now(UTC).isoformat()

    try:
        prev_best = float(existing.get("best_price", existing.get("price", price)))
    except (TypeError, ValueError):
        prev_best = price

    deals[item_id] = {
        "price": round(price, 2),
        "best_price": round(min(price, prev_best), 2),
        "posted_at": now,
        "first_posted_at": existing.get("first_posted_at") or now,
        "promotion_signature": promotion_signature,
        "normalized_title": normalize_title(title) if title else existing.get("normalized_title", ""),
        "normalized_url": normalize_url(url) if url else existing.get("normalized_url", ""),
        "message_id": message_id if message_id is not None else existing.get("message_id"),
        "thread_id": thread_id if thread_id is not None else existing.get("thread_id"),
        "republish_count": existing.get("republish_count", 0) + (1 if existing else 0),
        "last_reason": reason,
    }


# ---------------------------------------------------------------------------
# Regras individuais de republicação.
# ---------------------------------------------------------------------------

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


def check_promotion_revival(
    deals: dict[str, dict],
    item_id: str,
    current_price: float,
    promotion_signature: str,
    *,
    min_drop_percent: float = 5.0,
    min_drop_amount: float = 20.0,
    cooldown_hours: int = 6,
    now: datetime | None = None,
) -> tuple[bool, float | None]:
    entry = deals.get(item_id)
    if not entry or not promotion_signature:
        return False, None
    if str(entry.get("promotion_signature", "") or "") == promotion_signature:
        return False, None
    try:
        previous = float(entry.get("price"))
    except (TypeError, ValueError):
        return False, None
    if previous <= 0 or current_price >= previous:
        return False, previous
    raw = str(entry.get("posted_at", "") or "")
    if raw:
        try:
            posted = datetime.fromisoformat(raw)
            if posted.tzinfo is None:
                posted = posted.replace(tzinfo=UTC)
            current = now or datetime.now(UTC)
            if current - posted.astimezone(UTC) < timedelta(hours=max(0, cooldown_hours)):
                return False, previous
        except ValueError:
            pass
    amount = previous - current_price
    pct = (amount / previous) * 100
    return (pct >= min_drop_percent or amount >= min_drop_amount), previous


def check_lowest_price_ever(
    deals: dict[str, dict], item_id: str, current_price: float
) -> tuple[bool, float | None]:
    """Fase 4: preço atual é o menor já publicado pra esse item (mesmo sem
    caracterizar 'queda' em relação ao último post — ex.: o último post já
    tinha subido de preço de novo, e agora voltou a bater o piso)."""
    entry = deals.get(item_id)
    if not entry:
        return False, None
    try:
        best = float(entry.get("best_price", entry.get("price")))
    except (TypeError, ValueError):
        return False, None
    if current_price < best:
        return True, best
    return False, None


def check_period_elapsed(
    deals: dict[str, dict], item_id: str, *, min_days: int, now: datetime | None = None
) -> bool:
    """Fase 4: republica por tempo decorrido, independente de preço —
    ``REPOST_MIN_DAYS``. ``min_days <= 0`` desativa a regra."""
    if min_days <= 0:
        return False
    entry = deals.get(item_id)
    if not entry:
        return False
    raw = str(entry.get("posted_at", "") or "")
    if not raw:
        return False
    try:
        posted = datetime.fromisoformat(raw)
        if posted.tzinfo is None:
            posted = posted.replace(tzinfo=UTC)
    except ValueError:
        return False
    current = now or datetime.now(UTC)
    return (current - posted.astimezone(UTC)) >= timedelta(days=min_days)


# ---------------------------------------------------------------------------
# Regra unificada — usada pelas fontes que não têm lógica própria (ML mantém
# a sua, mais fina, em providers/mercadolivre/service.py).
# ---------------------------------------------------------------------------

def should_republish(
    deals: dict[str, dict],
    item_id: str,
    current_price: float,
    *,
    promotion_signature: str = "",
    min_drop_percent: int = 10,
    min_drop_amount: float = 20.0,
    repost_min_days: int = 0,
    promo_cooldown_hours: int = 6,
    now: datetime | None = None,
) -> tuple[bool, str, float | None]:
    """Decide se uma oferta já publicada pode ser publicada de novo.

    Prioridade: menor preço histórico > novo cupom > queda de preço >
    período configurado. Devolve ``(deveria, motivo, preço_de_referência)``;
    ``motivo`` é ``""`` quando ``deveria`` é ``False``.
    """
    if item_id not in deals:
        return False, "", None

    is_lowest, ref = check_lowest_price_ever(deals, item_id, current_price)
    if is_lowest:
        return True, "menor_preco_historico", ref

    is_revival, ref = check_promotion_revival(
        deals, item_id, current_price, promotion_signature,
        cooldown_hours=promo_cooldown_hours, now=now,
    )
    if is_revival:
        return True, "novo_cupom", ref

    is_drop, ref = check_price_drop(
        deals, item_id, current_price,
        min_drop_percent=min_drop_percent, min_drop_amount=min_drop_amount,
    )
    if is_drop:
        return True, "queda_de_preco", ref

    if check_period_elapsed(deals, item_id, min_days=repost_min_days, now=now):
        return True, "periodo_configurado", deals[item_id].get("price")

    return False, "", None
