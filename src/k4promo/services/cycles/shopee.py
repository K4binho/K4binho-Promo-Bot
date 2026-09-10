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
from k4promo.storage import deal_store as ds

log = logging.getLogger("k4binho")

PAGE_LIMIT = 20
REPUBLISH_SCORE_BONUS = 20


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

    offers = dedup.dedupe_by_title(offers)
    offers = dedup.drop_relisted(
        offers, ctx.published_deals, source_of=lambda _offer: "shopee",
        seen=ctx.seen,
    )
    dedup.release_stale(
        ctx.seen, "shopee:",
        dedup.active_keys_for_titles(
            offers, ctx.published_deals,
            {o.key for o in offers if o.discount_percent > 0},
            source_of=lambda _offer: "shopee",
        ),
        log_tag="Shopee",
    )

    # Fase 4: quem já foi visto mas caiu de preço, bateu piso histórico ou
    # passou do período configurado volta a disputar uma vaga.
    republish = dedup.reinject_republishable(
        ctx, offers,
        min_drop_percent=getattr(cfg, "repost_min_drop_percent", 10),
        min_drop_amount=getattr(cfg, "repost_min_drop_amount", 20.0),
        repost_min_days=getattr(cfg, "repost_min_days", 0),
    )
    republish_info = {o.key: (reason, prev) for o, reason, prev in republish}

    candidates = [
        o for o in offers
        if o.discount_percent >= cfg.shopee_min_discount_percent
        and o.sales_count >= getattr(cfg, "shopee_min_sales", 0)
        and ctx.republish_keys.get(o.key, o.key) not in ctx.seen
    ]
    candidates.extend(o for o, _reason, _prev in republish)
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
        total = r.total + (REPUBLISH_SCORE_BONUS if offer.key in republish_info else 0)
        scored.append((total, offer, r, resolve_topic("shopee", offer.title), promo_eval))
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.shopee_max_posts_per_cycle]

    log.info("[Shopee] Encontrados: %d | Candidatos: %d | Republicaveis: %d | Selecionados: %d",
             len(offers), len(scored), len(republish), len(selected))

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
        reason, prev_price = republish_info.get(offer.key, ("novo", None))
        prev_entry = ctx.published_deals.get(offer.key) if reason != "novo" else None
        previous_message = None
        if prev_entry and prev_entry.get("message_id") is not None:
            previous_message = (prev_entry.get("message_id"), prev_entry.get("thread_id"))

        if prev_price is not None:
            text = telegram.format_price_drop(
                title=offer.title, price=promo_eval.scoring_price, previous_price=prev_price,
                link=link, promotion=promo_eval,
            )
        else:
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
            previous_message=previous_message,
            analytics_kwargs={
                "listed_price": offer.price,
                "category": scoring.category_match(offer.title),
                "deal_type": "commercial", "affiliate": True,
                "promotion_code": display_promo.code if display_promo else "",
                "promotion_savings": promo_eval.guaranteed_savings,
                "promotion_conditional": bool(display_promo and display_promo.conditional),
                "action": reason,
            },
            showcase_kwargs={"coupon_savings": promo_eval.guaranteed_savings},
        )
        if not ok:
            continue
        ds.record_published(
            ctx.published_deals, ctx.republish_keys.get(offer.key, offer.key), promo_eval.scoring_price,
            promotion_signature=display_promo.code if display_promo else "",
            title=offer.title, url=link,
            message_id=publisher.last_message_id, thread_id=publisher.last_thread_id,
            reason=reason,
        )
        posted += 1
        log.info("[Shopee] postado (%s): %d%% off | %s | %s",
                 reason, offer.discount_percent, topic, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
