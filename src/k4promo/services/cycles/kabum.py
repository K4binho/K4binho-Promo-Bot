"""Ciclo da KaBuM! (comercial; principal fonte de Tecnologia).

O link afiliado é gerado item a item pelo link builder da Awin. Sem link não há
comissão, então a oferta simplesmente não é publicada.
"""

from __future__ import annotations

import logging

from k4promo import telegram
from k4promo.providers import kabum
from k4promo.providers.adapters import from_kabum
from k4promo.services import dedup, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import resolve_topic
from k4promo.storage import deal_store as ds

log = logging.getLogger("k4binho")

REPUBLISH_SCORE_BONUS = 20


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    token = getattr(cfg, "kabum_awin_token", "")
    publisher_id = int(getattr(cfg, "kabum_publisher_id", 0) or 0)
    if not (token and publisher_id):
        return 0

    offers = [from_kabum(d) for d in kabum.fetch_deals(min_discount=cfg.kabum_min_discount_percent)]
    offers = dedup.dedupe_by_title(offers)
    offers = dedup.drop_relisted(
        offers, ctx.published_deals, source_of=lambda _offer: "kabum",
        seen=ctx.seen,
    )

    dedup.release_stale(
        ctx.seen, "kabum:",
        dedup.active_keys_for_titles(
            offers, ctx.published_deals,
            {o.key for o in offers if o.discount_percent > 0},
            source_of=lambda _offer: "kabum",
        ),
        log_tag="Kabum",
    )

    republish = dedup.reinject_republishable(
        ctx, offers,
        min_drop_percent=getattr(cfg, "repost_min_drop_percent", 10),
        min_drop_amount=getattr(cfg, "repost_min_drop_amount", 20.0),
        repost_min_days=getattr(cfg, "repost_min_days", 0),
    )
    republish_info = {o.key: (reason, prev) for o, reason, prev in republish}

    candidates = [
        o for o in offers
        if ctx.republish_keys.get(o.key, o.key) not in ctx.seen and o.title
    ]
    candidates.extend(o for o, _reason, _prev in republish)
    scored = []
    for offer in candidates:
        r = scoring.score_store_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="kabum", rating=offer.rating,
        )
        total = r.total + (REPUBLISH_SCORE_BONUS if offer.key in republish_info else 0)
        scored.append((total, offer, r, resolve_topic("kabum", offer.title)))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.kabum_max_posts_per_cycle]

    log.info("[Kabum] Encontrados: %d | Candidatos: %d | Republicaveis: %d | Selecionados: %d",
             len(offers), len(scored), len(republish), len(selected))

    if ctx.dry_run:
        for total, o, _r, topic in scored:
            log.info("  score %d | %d%% | %s | %s", total, o.discount_percent, topic, o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result, topic in selected:
        affiliate = kabum.generate_affiliate_link(token, publisher_id, offer.permalink)
        if not affiliate:
            log.warning("[Kabum] sem link afiliado para %s; nao publicado.", offer.offer_id)
            continue
        link = publisher.affiliate_link(offer, affiliate)
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
            text = telegram.format_kabum_deal(
                title=offer.title, price=offer.price, original_price=offer.original_price,
                discount=offer.discount_percent, link=link,
            )
        ok = publisher.publish(
            offer, topic=topic, text=text, result=result, score=score_val,
            link=link, log_tag="Kabum", alert_link=affiliate,
            previous_message=previous_message,
            analytics_kwargs={
                "category": scoring.category_match(offer.title),
                "deal_type": "commercial", "affiliate": True,
                "action": reason,
            },
        )
        if not ok:
            continue
        ds.record_published(
            ctx.published_deals, ctx.republish_keys.get(offer.key, offer.key), offer.price,
            title=offer.title, url=link,
            message_id=publisher.last_message_id, thread_id=publisher.last_thread_id,
            reason=reason,
        )
        posted += 1
        log.info("[Kabum] postado (%s): %d%% off | %s | %s",
                 reason, offer.discount_percent, topic, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
