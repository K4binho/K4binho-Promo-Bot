"""Ciclo da Green Man Gaming via impact.com (tópico Jogos, com comissão)."""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.domain.topics import JOGOS
from k4promo.providers import gmg
from k4promo.providers.adapters import from_gmg
from k4promo.services import dedup, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import topic_thread_id

log = logging.getLogger("k4binho")


def _credentials(cfg) -> tuple[str, str]:
    """IMPACT_* é o nome oficial; CJ_* segue aceito como alias legado."""
    sid = getattr(cfg, "impact_account_sid", "") or getattr(cfg, "cj_account_sid", "")
    token = getattr(cfg, "impact_auth_token", "") or getattr(cfg, "cj_auth_token", "")
    return sid, token


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    account_sid, auth_token = _credentials(cfg)
    if not (account_sid and auth_token and cfg.gmg_program_id and cfg.gmg_catalog_id):
        # Integração ainda não configurada: não é erro, só pula o ciclo.
        return 0
    try:
        catalog_items = gmg.fetch_catalog_items(
            account_sid, auth_token, cfg.gmg_catalog_id,
            currency=getattr(cfg, "gmg_catalog_currency", "") or None,
            page_size=getattr(cfg, "gmg_catalog_page_size", 1000),
            max_pages=getattr(cfg, "gmg_catalog_max_pages", 10),
        )
        promo_codes = gmg.fetch_promo_codes(account_sid, auth_token, program_id=cfg.gmg_program_id)
    except httpx.HTTPError as exc:
        log.error("[GMG] %s", exc)
        return 0

    offers = [from_gmg(g) for g in gmg.parse_deals(catalog_items, promo_codes)]

    dedup.release_stale(
        ctx.seen, "gmg:",
        {o.key for o in offers if o.discount_percent > 0},
        log_tag="GMG", noun="jogo",
    )

    unseen_discounted = [
        o for o in offers if o.discount_percent > 0 and o.key not in ctx.seen
    ]
    normal_ids = {
        o.offer_id for o in unseen_discounted
        if o.discount_percent >= cfg.gmg_min_discount_percent
    }

    all_scored = []
    for offer in unseen_discounted:
        r = scoring.score_game(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="gmg",
        )
        all_scored.append((r.total, offer, r))
        ctx.plus_candidates.append({
            "score": r.total, "source": "gmg", "seen_key": offer.key,
            "title": offer.title, "price": offer.price, "original_price": offer.original_price,
            "discount_percent": offer.discount_percent, "link": offer.permalink,
            "lowest_price": None, "image_url": offer.image_url, "game_id": offer.offer_id,
            "result": r, "thread_id": topic_thread_id(cfg, JOGOS),
            "promo_code": offer.promo_code or None,
            "promo_description": offer.promo_description or None,
        })

    scored = [(total, o, r) for total, o, r in all_scored if o.offer_id in normal_ids]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.gmg_max_posts_per_cycle]

    log.info(
        "[GMG] Encontrados: %d | Desconto>=%d%%: %d | Nao vistos: %d | Scored: %d | Selecionados: %d",
        len(offers), cfg.gmg_min_discount_percent,
        len([o for o in offers if o.discount_percent >= cfg.gmg_min_discount_percent]),
        len(normal_ids), len(scored), len(selected),
    )

    if ctx.dry_run:
        for total, o, _r in scored:
            log.info("  score %d | %s%% | %s", total, o.discount_percent, o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result in selected:
        if not offer.permalink:
            log.warning("[GMG] sem link para %s", offer.offer_id)
            continue
        link = publisher.affiliate_link(offer)
        text = telegram.format_gmg_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount=offer.discount_percent, link=link,
            promo_code=offer.promo_code or None,
            promo_description=offer.promo_description or None,
        )
        ok = publisher.publish(
            offer, topic=JOGOS, text=text, result=result, score=score_val,
            link=link, log_tag="GMG",
            analytics_kwargs={"category": "games", "deal_type": "plus", "affiliate": False},
        )
        if not ok:
            continue
        posted += 1
        log.info("[GMG] postado: %s%% off | %s", offer.discount_percent, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
