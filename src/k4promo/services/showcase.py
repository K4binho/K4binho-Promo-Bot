"""Vitrine "🔥 Melhores do Dia".

O tópico não coleta nada. Durante o ciclo, cada publicação enviada aos demais
tópicos é oferecida à vitrine por ``register``; no fim do ciclo, ``run_cycle``
copia as melhores respeitando prioridade de loja, orçamento por ciclo/dia e a
memória de produtos já copiados.
"""

from __future__ import annotations

import logging
import time

import httpx

from k4promo import telegram
from k4promo.domain.topics import MELHORES_DO_DIA, store_label, topic_label
from k4promo.services.context import CycleContext
from k4promo.services.router import topic_thread_id
from k4promo.services.showcase_rules import showcase_eligible
from k4promo.storage import showcase_store

log = logging.getLogger("k4binho")

COPY_PACE_SECONDS = 5


def register(
    ctx: CycleContext,
    *,
    key: str,
    source: str,
    topic: str,
    score: float,
    text: str,
    image_url: str | None,
    price: float,
    discount_percent: int = 0,
    sales_count: int = 0,
    coupon_savings: float = 0.0,
    free_shipping: bool = False,
    lowest_price: bool = False,
    rating: float | None = None,
    review_score: int | None = None,
) -> bool:
    """Avalia uma publicação recém-enviada. True se entrou na fila de cópias."""
    if topic == MELHORES_DO_DIA:
        return False
    cfg = ctx.cfg
    verdict = showcase_eligible(
        source,
        price=price,
        discount_percent=int(discount_percent or 0),
        sales_count=int(sales_count or 0),
        coupon_savings=float(coupon_savings or 0.0),
        free_shipping=free_shipping,
        lowest_price=lowest_price,
        rating=rating,
        review_score=review_score,
        has_image=bool(image_url),
        min_physical_discount=getattr(cfg, "showcase_min_physical_discount", 40),
        min_game_discount=getattr(cfg, "showcase_min_game_discount", 70),
    )
    if not verdict.eligible:
        return False
    ctx.showcase_candidates.append({
        "key": key, "source": source, "topic": topic, "score": float(score),
        "text": text, "image_url": image_url or None,
        "priority": verdict.priority, "reasons": verdict.reasons,
    })
    return True


def run_cycle(ctx: CycleContext) -> int:
    """Copia para a vitrine as melhores publicações do ciclo."""
    cfg = ctx.cfg
    if not getattr(cfg, "showcase_enabled", True):
        return 0
    if not ctx.showcase_candidates:
        return 0

    state = showcase_store.load_state()
    showcase_store.prune(state)
    max_cycle = int(getattr(cfg, "showcase_max_per_cycle", 2))
    max_day = int(getattr(cfg, "showcase_max_per_day", 8))
    remaining_today = max(0, max_day - showcase_store.copies_today(state))
    budget = min(max_cycle, remaining_today)

    ordered = sorted(ctx.showcase_candidates, key=lambda c: (c["priority"], -c["score"]))
    fresh = [c for c in ordered if not showcase_store.already_copied(state, c["key"])]
    log.info(
        "[Vitrine] Candidatos: %d | Ineditos: %d | Orcamento: %d (ciclo %d, dia restante %d)",
        len(ordered), len(fresh), budget, max_cycle, remaining_today,
    )
    if budget <= 0 or not fresh:
        return 0

    posted = 0
    for cand in fresh[:budget]:
        label = f"{topic_label(cand['topic'])} · {store_label(cand['source'])}"
        if ctx.dry_run:
            log.info("[Vitrine][dry-run] copiaria: %s | %s", label, ", ".join(cand["reasons"]))
            continue
        text = telegram.format_showcase_copy(
            cand["text"], topic_label(cand["topic"]), store_label(cand["source"]),
        )
        try:
            telegram.send_message(
                cfg.telegram_bot_token, cfg.telegram_channel_id, text,
                thread_id=topic_thread_id(cfg, MELHORES_DO_DIA),
                image_url=cand.get("image_url"),
            )
        except httpx.HTTPError as exc:
            log.error("[Vitrine] falha ao copiar '%s': %s", cand["key"], exc)
            continue
        showcase_store.mark_copied(state, cand["key"])
        posted += 1
        log.info("[Vitrine] copiado: %s | %s", label, ", ".join(cand["reasons"]))
        if posted < budget:
            time.sleep(COPY_PACE_SECONDS)
    if posted:
        showcase_store.save_state(state)
    return posted
