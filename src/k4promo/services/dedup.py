"""Controle de duplicação e de republicação."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from typing import Any

from k4promo.storage import deal_store as ds

log = logging.getLogger("k4binho")


def release_stale(
    seen: dict[str, str],
    prefix: str | Iterable[str],
    active_keys: Iterable[str],
    *,
    log_tag: str,
    noun: str = "produto",
) -> int:
    """Libera chaves de ofertas que saíram de promoção."""
    prefixes = (prefix,) if isinstance(prefix, str) else tuple(prefix)
    active = set(active_keys)
    stale = [k for k in seen if k.startswith(prefixes) and k not in active]
    for key in stale:
        del seen[key]
    if stale:
        log.info(
            "[%s] %d %s(s) saiu(ram) de promo, liberado(s) pra re-post.",
            log_tag, len(stale), noun,
        )
    return len(stale)


def dedupe_by_title(
    items: Sequence[Any],
    *,
    title_of: Callable[[Any], str] = lambda d: d.title,
    price_of: Callable[[Any], float] = lambda d: d.price,
    source_of: Callable[[Any], str] = lambda d: getattr(d, "source", ""),
    key_of: Callable[[Any], str] = lambda d: getattr(d, "key", ""),
    length: int = 120,
) -> list:
    """Consolida títulos iguais da mesma loja e mantém menor preço."""
    best: dict[tuple[str, str], Any] = {}
    for item in items:
        title = ds.normalize_title(title_of(item))[:length]
        if not title:
            title = f"__key__:{key_of(item)}"
        key = (source_of(item), title)
        current = best.get(key)
        if current is None or price_of(item) < price_of(current):
            best[key] = item
    return list(best.values())


def active_keys_for_titles(
    items: Sequence[Any],
    published_deals: dict[str, dict],
    active_keys: Iterable[str],
    *,
    source_of: Callable[[Any], str] = lambda d: getattr(d, "source", ""),
    title_of: Callable[[Any], str] = lambda d: getattr(d, "title", ""),
) -> set[str]:
    """Mantém chave histórica ativa quando provider relista produto."""
    active = set(active_keys)
    for item in items:
        title = ds.normalize_title(title_of(item))
        if not title:
            continue
        previous = ds.find_by_normalized_title(
            published_deals, source_of(item), title
        )
        if previous is not None:
            active.add(previous[0])
    return active


def drop_relisted(
    items: Sequence[Any],
    published_deals: dict[str, dict],
    *,
    source_of: Callable[[Any], str] = lambda d: getattr(d, "source", ""),
    title_of: Callable[[Any], str] = lambda d: getattr(d, "title", ""),
    key_of: Callable[[Any], str] = lambda d: getattr(d, "key", ""),
    keep_keys: set[str] | None = None,
    seen: dict[str, str] | None = None,
) -> list:
    """Remove relistagem já publicada, exceto chaves liberadas."""
    result = []
    for item in items:
        key = key_of(item)
        title = ds.normalize_title(title_of(item))
        previous = (
            ds.find_by_normalized_title(published_deals, source_of(item), title)
            if title else None
        )
        if (
            previous is not None
            and previous[0] != key
            and (keep_keys is None or key not in keep_keys)
            and (seen is None or previous[0] not in seen)
        ):
            continue
        result.append(item)
    return result


def reinject_republishable(
    ctx,
    offers: Iterable[Any],
    *,
    key_of: Callable[[Any], str] = lambda o: o.key,
    price_of: Callable[[Any], float] = lambda o: o.price,
    promotion_signature_of: Callable[[Any], str] = lambda o: "",
    source_of: Callable[[Any], str] = lambda o: getattr(o, "source", ""),
    min_drop_percent: int = 10,
    min_drop_amount: float = 20.0,
    repost_min_days: int = 0,
) -> list[tuple[Any, str, float | None]]:
    """Retorna ofertas vistas que podem ser republicadas."""
    result = []
    for offer in offers:
        key = key_of(offer)
        title = ds.normalize_title(getattr(offer, "title", ""))
        previous = (
            ds.find_by_normalized_title(ctx.published_deals, source_of(offer), title)
            if title else None
        )
        canonical_key = previous[0] if previous is not None else key
        if canonical_key != key:
            ctx.republish_keys[key] = canonical_key
        if canonical_key not in ctx.seen:
            continue
        should, reason, prev_price = ds.should_republish(
            ctx.published_deals,
            canonical_key,
            price_of(offer),
            promotion_signature=promotion_signature_of(offer),
            min_drop_percent=min_drop_percent,
            min_drop_amount=min_drop_amount,
            repost_min_days=repost_min_days,
        )
        if should:
            result.append((offer, reason, prev_price))
    return result
