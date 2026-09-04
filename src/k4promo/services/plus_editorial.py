"""Fallback editorial PLUS.

Publica no máximo um candidato editorial forte quando os ciclos PLUS normais
(Steam, Nuuvem, GMG) ficaram calados por um período configurado. O pool é
montado por esses ciclos antes dos seus portões estritos.

O fallback nunca ignora ``seen`` nem o score mínimo editorial: ele só relaxa a
exigência de popularidade, não a de qualidade.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from k4promo import telegram
from k4promo.domain.topics import JOGOS
from k4promo.services import analytics, showcase
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import topic_thread_id
from k4promo.storage.seen_store import mark_seen

log = logging.getLogger("k4binho")

NEVER_PUBLISHED_HOURS = 999.0


def last_publish_hours_ago() -> float:
    """Horas desde a última publicação PLUS registrada em analytics."""
    entries = analytics.load_entries(limit=200)
    now = datetime.now(timezone.utc)
    for entry in reversed(entries):
        if entry.get("deal_type") == "plus" and entry.get("action") == "published":
            try:
                ts = datetime.fromisoformat(entry["timestamp"])
                return (now - ts).total_seconds() / 3600
            except (KeyError, ValueError):
                continue
    return NEVER_PUBLISHED_HOURS


def _format(source: str, candidate: dict, link: str) -> str | None:
    if source == "steam":
        return telegram.format_game_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            lowest_price=candidate.get("lowest_price"),
        )
    if source == "nuuvem":
        return telegram.format_nuuvem_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            lowest_price=candidate.get("lowest_price"),
            coupon_code=candidate.get("coupon_code"),
            coupon_discount=candidate.get("coupon_discount"),
        )
    if source == "gmg":
        return telegram.format_gmg_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            promo_code=candidate.get("promo_code"),
            promo_description=candidate.get("promo_description"),
        )
    return None


def run(ctx: CycleContext) -> int:
    cfg, seen = ctx.cfg, ctx.seen
    hours_ago = last_publish_hours_ago()
    if hours_ago < cfg.plus_editorial_hours_without:
        log.info("[PLUS] Fallback nao necessario: ultima publicacao ha %.1fh (janela %dh).",
                 hours_ago, cfg.plus_editorial_hours_without)
        return 0

    eligible = [
        c for c in ctx.plus_candidates
        if c.get("seen_key") not in seen
        and c.get("link")
        and c.get("score", 0) >= cfg.plus_editorial_min_score
    ]
    if not eligible:
        best = max((c.get("score", 0) for c in ctx.plus_candidates
                    if c.get("seen_key") not in seen), default=None)
        if best is None:
            log.info("[PLUS] Nenhuma publicacao: nenhum candidato editorial elegivel neste ciclo.")
        else:
            log.info("[PLUS] Nenhuma publicacao: melhor score %.1f abaixo do minimo editorial %d.",
                     best, cfg.plus_editorial_min_score)
        return 0

    candidate = max(eligible, key=lambda c: c.get("score", 0))
    log.info("[PLUS] Fallback editorial candidato: %s | %s | score %.1f | minimo %d",
             candidate["source"], candidate["title"][:60], candidate["score"],
             cfg.plus_editorial_min_score)
    if ctx.dry_run:
        log.info("[PLUS][dry-run] Fallback editorial nao enviado.")
        return 0

    publisher = Publisher(ctx)
    source = candidate["source"]
    link = publisher.wrap_link(candidate["seen_key"], candidate["link"], source, candidate["title"])
    text = _format(source, candidate, link)
    if text is None:
        log.warning("[PLUS] Fonte de fallback desconhecida: %s", source)
        return 0

    try:
        telegram.send_message(
            cfg.telegram_bot_token, cfg.telegram_channel_id, text,
            thread_id=candidate.get("thread_id", topic_thread_id(cfg, JOGOS)),
            image_url=candidate.get("image_url") or None,
        )
    except httpx.HTTPError as exc:
        log.error("[PLUS] falha no fallback '%s': %s", candidate["title"][:50], exc)
        return 0

    mark_seen(seen, candidate["seen_key"])
    result = candidate["result"]
    showcase.register(
        ctx, key=candidate["seen_key"], source=source, topic=JOGOS,
        score=candidate["score"], text=text, image_url=candidate.get("image_url") or None,
        price=candidate["price"], discount_percent=int(candidate["discount_percent"]),
        lowest_price=bool(
            candidate.get("lowest_price") is not None
            and candidate["price"] <= candidate["lowest_price"]
        ),
        review_score=candidate.get("review_score"),
    )
    analytics.record_deal(
        source=source, topic=JOGOS, product_id=str(candidate["game_id"]),
        title=candidate["title"], price=candidate["price"],
        original_price=candidate["original_price"],
        discount_percent=int(candidate["discount_percent"]),
        quality_score=result.quality, conversion_score=result.conversion,
        retention_score=result.retention, confidence_score=result.confidence,
        final_score=result.final, history_confidence=result.history_confidence,
        category="games", deal_type="plus", affiliate=False,
        action="published", action_reason="plus_editorial_fallback",
    )
    log.info("[PLUS] Fallback editorial publicado: %s | %s | score %.1f",
             source, candidate["title"][:60], candidate["score"])
    publisher.check_alerts(candidate["title"], candidate["price"], source, candidate["link"])
    return 1
