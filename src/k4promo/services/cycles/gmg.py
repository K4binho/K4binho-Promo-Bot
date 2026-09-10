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
from k4promo.storage import deal_store as ds

log = logging.getLogger("k4binho")

REPUBLISH_SCORE_BONUS = 20


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
    offers = dedup.dedupe_by_title(offers)
    offers = dedup.drop_relisted(
        offers, ctx.published_deals, source_of=lambda _offer: "gmg",
        seen=ctx.seen,
    )

    dedup.release_stale(
        ctx.seen, "gmg:",
        dedup.active_keys_for_titles(
            offers, ctx.published_deals,
            {o.key for o in offers if o.discount_percent > 0},
            source_of=lambda _offer: "gmg",
        ),
        log_tag="GMG", noun="jogo",
    )

    republish = dedup.reinject_republishable(
        ctx, offers,
        min_drop_percent=getattr(cfg, "repost_min_drop_percent", 10),
        min_drop_amount=getattr(cfg, "repost_min_drop_amount", 20.0),
        repost_min_days=getattr(cfg, "repost_min_days", 0),
    )
    republish_info = {o.key: (reason, prev) for o, reason, prev in republish}

    unseen_discounted = [
        o for o in offers
        if o.discount_percent > 0
        and ctx.republish_keys.get(o.key, o.key) not in ctx.seen
    ]
    normal_ids = {
        o.offer_id for o in unseen_discounted
        if o.discount_percent >= cfg.gmg_min_discount_percent
    }
    normal_ids.update(o.offer_id for o, _reason, _prev in republish)

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
    for offer, _reason, _prev in republish:
        r = scoring.score_game(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="gmg",
        )
        all_scored.append((r.total, offer, r))

    scored = [
        (total + (REPUBLISH_SCORE_BONUS if o.key in republish_info else 0), o, r)
        for total, o, r in all_scored if o.offer_id in normal_ids
    ]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.gmg_max_posts_per_cycle]

    log.info(
        "[GMG] Encontrados: %d | Desconto>=%d%%: %d | Nao vistos: %d | Republicaveis: %d | "
        "Scored: %d | Selecionados: %d",
        len(offers), cfg.gmg_min_discount_percent,
        len([o for o in offers if o.discount_percent >= cfg.gmg_min_discount_percent]),
        len(normal_ids), len(republish), len(scored), len(selected),
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
        reason, prev_price = republish_info.get(offer.key, ("novo", None))
        prev_entry = ctx.published_deals.get(offer.key) if reason != "novo" else None
        previous_message = None
        if prev_entry and prev_entry.get("message_id") is not None:
            previous_message = (prev_entry.get("message_id"), prev_entry.get("thread_id"))

        if prev_price is not None:
            text = telegram.format_price_drop(
                title=offer.title, price=offer.price, previous_price=prev_price, link=link,
            )
        else:
            text = telegram.format_gmg_deal(
                title=offer.title, price=offer.price, original_price=offer.original_price,
                discount=offer.discount_percent, link=link,
                promo_code=offer.promo_code or None,
                promo_description=offer.promo_description or None,
            )
        ok = publisher.publish(
            offer, topic=JOGOS, text=text, result=result, score=score_val,
            link=link, log_tag="GMG",
            previous_message=previous_message,
            analytics_kwargs={
                "category": "games", "deal_type": "plus", "affiliate": False,
                "action": reason,
            },
        )
        if not ok:
            continue
        ds.record_published(
            ctx.published_deals, ctx.republish_keys.get(offer.key, offer.key), offer.price,
            promotion_signature=offer.promo_code or "",
            title=offer.title, url=link,
            message_id=publisher.last_message_id, thread_id=publisher.last_thread_id,
            reason=reason,
        )
        posted += 1
        log.info("[GMG] postado (%s): %s%% off | %s", reason, offer.discount_percent, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
