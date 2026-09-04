"""Ciclo da Shopee (comercial; principal fonte de Casa, Moda e Achadinhos).

``offerLink`` da API de afiliados já é o link com comissão, então não há passo
extra de geração de link.
"""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.providers import shopee
from k4promo.providers.adapters import from_shopee
from k4promo.services import dedup, promotions as promotion_engine, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import resolve_topic

log = logging.getLogger("k4binho")

PAGE_LIMIT = 20


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    app_id = getattr(cfg, "shopee_app_id", "")
    app_secret = getattr(cfg, "shopee_app_secret", "")
    if not (app_id and app_secret):
        return 0

    offers: list = []
    seen_ids: set[str] = set()
    for kw in (list(getattr(cfg, "shopee_searches", []) or []) or [""]):
        try:
            batch = shopee.fetch_deals(app_id, app_secret, keyword=kw, limit=PAGE_LIMIT)
        except (RuntimeError, httpx.HTTPError, KeyError, TypeError, ValueError) as exc:
            log.error("[Shopee] %s: %s", kw or "geral", exc)
            continue
        for offer in map(from_shopee, batch):
            if offer.offer_id not in seen_ids:
                seen_ids.add(offer.offer_id)
                offers.append(offer)

    dedup.release_stale(
        ctx.seen, "shopee:",
        {o.key for o in offers if o.discount_percent > 0},
        log_tag="Shopee",
    )

    candidates = [
        o for o in offers
        if o.discount_percent >= cfg.shopee_min_discount_percent
        and o.sales_count >= getattr(cfg, "shopee_min_sales", 0)
        and o.key not in ctx.seen
    ]
    candidates = dedup.dedupe_by_title(candidates)

    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    scored = []
    for offer in candidates:
        promos = promotion_engine.promotions_for_item(catalog, "shopee", offer.title, offer.price)
        promo_eval = promotion_engine.evaluate_price(offer.price, promos, title=offer.title)
        display_promo = promo_eval.display_promotion
        r = scoring.score_store_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="shopee",
            sales_count=offer.sales_count, rating=offer.rating,
            effective_price=promo_eval.scoring_price,
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_code=display_promo.code if display_promo and promo_eval.best_guaranteed else "",
        )
        scored.append((r.total, offer, r, resolve_topic("shopee", offer.title), promo_eval))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.shopee_max_posts_per_cycle]

    log.info("[Shopee] Encontrados: %d | Candidatos: %d | Selecionados: %d",
             len(offers), len(scored), len(selected))

    if ctx.dry_run:
        for total, o, _r, topic, _pe in scored:
            log.info("  score %d | %d%% | %d vendas | %s | %s",
                     total, o.discount_percent, o.sales_count, topic, o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result, topic, promo_eval in selected:
        link = publisher.affiliate_link(offer)
        text = telegram.format_shopee_deal(
            title=offer.title, price=offer.price, link=link,
            original_price=offer.original_price, discount=offer.discount_percent,
            sales_count=offer.sales_count, rating=offer.rating, promotion=promo_eval,
        )
        display_promo = promo_eval.display_promotion
        ok = publisher.publish(
            offer, topic=topic, text=text, result=result, score=score_val,
            link=link, log_tag="Shopee", price=promo_eval.scoring_price,
            alert_link=offer.permalink,
            analytics_kwargs={
                "listed_price": offer.price,
                "category": scoring.category_match(offer.title),
                "deal_type": "commercial", "affiliate": True,
                "promotion_code": display_promo.code if display_promo else "",
                "promotion_savings": promo_eval.guaranteed_savings,
                "promotion_conditional": bool(display_promo and display_promo.conditional),
            },
            showcase_kwargs={"coupon_savings": promo_eval.guaranteed_savings},
        )
        if not ok:
            continue
        posted += 1
        log.info("[Shopee] postado: %d%% off | %s | %s",
                 offer.discount_percent, topic, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
