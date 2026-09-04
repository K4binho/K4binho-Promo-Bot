"""Ciclo do AliExpress (comercial, roteado por tópico)."""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.providers import aliexpress
from k4promo.providers.adapters import from_aliexpress
from k4promo.services import dedup, promotions as promotion_engine, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import resolve_topic

log = logging.getLogger("k4binho")

PAGE_SIZE = 20


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    if not (cfg.aliexpress_app_key and cfg.aliexpress_app_secret):
        return 0

    offers: list = []
    seen_ids: set[str] = set()
    for kw, cat in (cfg.aliexpress_searches or [("", "")]):
        try:
            batch = aliexpress.fetch_deals(
                cfg.aliexpress_app_key, cfg.aliexpress_app_secret, cfg.aliexpress_tracking_id,
                keywords=kw, category_ids=cat, page_size=PAGE_SIZE,
            )
        except (RuntimeError, httpx.HTTPError) as exc:
            log.error("[Ali] %s: %s", kw, exc)
            continue
        for offer in map(from_aliexpress, batch):
            if offer.offer_id not in seen_ids:
                seen_ids.add(offer.offer_id)
                offers.append(offer)

    dedup.release_stale(
        ctx.seen, "ali:",
        {o.key for o in offers if o.discount_percent > 0},
        log_tag="Ali",
    )

    candidates = [
        o for o in offers
        if o.discount_percent >= cfg.aliexpress_min_discount_percent
        and o.key not in ctx.seen
    ]
    candidates = dedup.dedupe_by_title(candidates)

    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    scored = []
    promotion_count = 0
    for offer in candidates:
        promos = promotion_engine.promotions_for_item(catalog, "aliexpress", offer.title, offer.price)
        promo_eval = promotion_engine.evaluate_price(offer.price, promos, title=offer.title)
        display_promo = promo_eval.display_promotion
        if display_promo:
            promotion_count += 1
        r = scoring.score_aliexpress(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, sales_count=offer.sales_count,
            commission_rate=offer.commission_rate,
            effective_price=promo_eval.scoring_price,
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_code=display_promo.code if display_promo and promo_eval.best_guaranteed else "",
        )
        scored.append((r.total, offer, r, scoring.category_match(offer.title), promo_eval))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.aliexpress_max_posts_per_cycle]

    log.info(
        "[Ali] Encontrados: %d | Candidatos: %d | Com promocao configurada: %d | Selecionados: %d",
        len(offers), len(scored), promotion_count, len(selected),
    )

    if ctx.dry_run:
        log.info("[Ali][dry-run] %d oferta(s) aprovada(s) de %d com %d%%+ off.",
                 len(selected), len(scored), cfg.aliexpress_min_discount_percent)
        for total, o, _r, _cat, promo_eval in scored:
            promo = promo_eval.display_promotion
            promo_text = ""
            if promo_eval.guaranteed_savings > 0:
                promo_text = f" | cupom {promo.code or '-'} -> R${promo_eval.scoring_price:.2f}"
            elif promo:
                promo_text = " | promo condicional"
            log.info("  score %d | %d%% | %d vendas%s | %s | %s",
                     total, o.discount_percent, o.sales_count, promo_text,
                     resolve_topic("aliexpress", o.title), o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result, category, promo_eval in selected:
        link = publisher.affiliate_link(offer)
        text = telegram.format_aliexpress_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount=offer.discount_percent, link=link,
            commission_rate=offer.commission_rate, sales_count=offer.sales_count,
            promotion=promo_eval,
        )
        topic = resolve_topic("aliexpress", offer.title)
        display_promo = promo_eval.display_promotion
        effective_price = promo_eval.scoring_price
        effective_discount = offer.discount_from(effective_price)
        ok = publisher.publish(
            offer, topic=topic, text=text, result=result, score=score_val,
            link=link, log_tag="Ali", price=effective_price, alert_link=offer.permalink,
            analytics_kwargs={
                "listed_price": offer.price,
                "discount_percent": effective_discount,
                "category": category, "deal_type": "commercial", "affiliate": True,
                "promotion_code": display_promo.code if display_promo else "",
                "promotion_savings": promo_eval.guaranteed_savings,
                "promotion_conditional": bool(display_promo and display_promo.conditional),
            },
            showcase_kwargs={
                "discount_percent": effective_discount,
                "coupon_savings": promo_eval.guaranteed_savings,
            },
        )
        if not ok:
            continue
        posted += 1
        if promo_eval.guaranteed_savings > 0:
            log.info("[Ali][cupom %s] postado: %.2f -> %.2f | %s | %s",
                     display_promo.code if display_promo else "",
                     offer.price, effective_price, topic, offer.title[:50])
        else:
            log.info("[Ali] postado: %d%% off | %s | %s",
                     offer.discount_percent, topic, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
