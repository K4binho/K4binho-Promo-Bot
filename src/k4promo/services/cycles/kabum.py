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

log = logging.getLogger("k4binho")


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    token = getattr(cfg, "kabum_awin_token", "")
    publisher_id = int(getattr(cfg, "kabum_publisher_id", 0) or 0)
    if not (token and publisher_id):
        return 0

    offers = [from_kabum(d) for d in kabum.fetch_deals(min_discount=cfg.kabum_min_discount_percent)]

    dedup.release_stale(
        ctx.seen, "kabum:",
        {o.key for o in offers if o.discount_percent > 0},
        log_tag="Kabum",
    )

    candidates = [o for o in offers if o.key not in ctx.seen and o.title]
    scored = []
    for offer in candidates:
        r = scoring.score_store_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="kabum", rating=offer.rating,
        )
        scored.append((r.total, offer, r, resolve_topic("kabum", offer.title)))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.kabum_max_posts_per_cycle]

    log.info("[Kabum] Encontrados: %d | Candidatos: %d | Selecionados: %d",
             len(offers), len(scored), len(selected))

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
        text = telegram.format_kabum_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount=offer.discount_percent, link=link,
        )
        ok = publisher.publish(
            offer, topic=topic, text=text, result=result, score=score_val,
            link=link, log_tag="Kabum", alert_link=affiliate,
            analytics_kwargs={
                "category": scoring.category_match(offer.title),
                "deal_type": "commercial", "affiliate": True,
            },
        )
        if not ok:
            continue
        posted += 1
        log.info("[Kabum] postado: %d%% off | %s | %s",
                 offer.discount_percent, topic, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
