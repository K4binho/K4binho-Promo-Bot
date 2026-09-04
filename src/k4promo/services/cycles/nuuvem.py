"""Ciclo da Nuuvem (editorial, tópico Jogos)."""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.domain.topics import JOGOS
from k4promo.providers import nuuvem
from k4promo.providers.adapters import from_nuuvem
from k4promo.services import dedup, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import topic_thread_id

log = logging.getLogger("k4binho")

ENRICH_LIMIT = 60


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    if not cfg.itad_api_key:
        return 0
    try:
        deals = nuuvem.fetch_deals(cfg.itad_api_key)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.error("[Nuuvem] %s", exc)
        return 0

    dedup.release_stale(
        ctx.seen, "nuuvem:",
        {f"nuuvem:{d.game_id}" for d in deals if d.discount_percent > 0},
        log_tag="Nuuvem", noun="jogo",
    )

    candidates = [
        d for d in deals
        if d.discount_percent >= cfg.nuuvem_min_discount_percent
        and f"nuuvem:{d.game_id}" not in ctx.seen
    ]
    candidates.sort(key=lambda d: d.discount_percent, reverse=True)
    to_enrich = candidates[:ENRICH_LIMIT]
    # O enriquecimento altera o objeto do provider no lugar; normalizar depois.
    nuuvem.enrich_with_popularity(cfg.itad_api_key, to_enrich)
    offers = [from_nuuvem(d) for d in to_enrich]

    all_scored = []
    for offer in offers:
        r = scoring.score_game(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="nuuvem",
            review_score=offer.review_score, review_count=offer.review_count,
            lowest_price=offer.lowest_price, waitlisted=offer.waitlisted,
        )
        all_scored.append((r.total, offer, r))
        ctx.plus_candidates.append({
            "score": r.total, "source": "nuuvem", "seen_key": offer.key,
            "title": offer.title, "price": offer.price, "original_price": offer.original_price,
            "discount_percent": offer.discount_percent, "link": offer.permalink,
            "lowest_price": offer.lowest_price, "image_url": offer.image_url,
            "game_id": offer.offer_id, "result": r, "thread_id": topic_thread_id(cfg, JOGOS),
            "coupon_code": offer.promo_code or None,
            "coupon_discount": offer.promo_description or None,
            "review_score": offer.review_score,
        })

    eligible_ids = {o.offer_id for o in offers if nuuvem.is_most_wanted(o, cfg.nuuvem_min_waitlisted)}
    scored = [(total, o, r) for total, o, r in all_scored if o.offer_id in eligible_ids]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.nuuvem_max_posts_per_cycle]

    log.info(
        "[Nuuvem] Encontrados: %d | Desconto>=%d%%: %d | Nao vistos: %d | "
        "Waitlisted>=%d: %d | Scored: %d | Selecionados: %d",
        len(deals), cfg.nuuvem_min_discount_percent,
        len([d for d in deals if d.discount_percent >= cfg.nuuvem_min_discount_percent]),
        len([d for d in deals if d.discount_percent >= cfg.nuuvem_min_discount_percent
             and f"nuuvem:{d.game_id}" not in ctx.seen]),
        cfg.nuuvem_min_waitlisted, len(eligible_ids), len(scored), len(selected),
    )

    if ctx.dry_run:
        for total, o, _r in scored:
            log.info("  score %d | %d%% | %s na waitlist | %s",
                     total, o.discount_percent, o.waitlisted, o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result in selected:
        link = publisher.affiliate_link(offer)
        text = telegram.format_nuuvem_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount=offer.discount_percent, link=link, lowest_price=offer.lowest_price,
            coupon_code=offer.promo_code or None,
            coupon_discount=offer.promo_description or None,
        )
        ok = publisher.publish(
            offer, topic=JOGOS, text=text, result=result, score=score_val,
            link=link, log_tag="Nuuvem", alert_link=offer.permalink,
            analytics_kwargs={"category": "games", "deal_type": "plus", "affiliate": False},
        )
        if not ok:
            continue
        posted += 1
        log.info("[Nuuvem] postado: %d%% off | %s", offer.discount_percent, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
