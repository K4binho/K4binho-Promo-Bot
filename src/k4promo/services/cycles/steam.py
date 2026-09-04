"""Ciclo da Steam (editorial, tópico Jogos)."""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.domain.topics import JOGOS
from k4promo.providers import steam
from k4promo.providers.adapters import from_steam
from k4promo.services import dedup, scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import topic_thread_id

log = logging.getLogger("k4binho")

ENRICH_LIMIT = 60


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    try:
        games = steam.fetch_specials(cfg.itad_api_key, bundle_scan_apps=cfg.steam_bundle_scan_apps)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.error("[Steam] %s", exc)
        return 0

    dedup.release_stale(
        ctx.seen, "steam:",
        {f"steam:{g.game_id}" for g in games if g.discount_percent > 0},
        log_tag="Steam", noun="jogo",
    )

    candidates = [
        g for g in games
        if g.discount_percent >= cfg.steam_min_discount_percent
        and f"steam:{g.game_id}" not in ctx.seen
    ]
    candidates.sort(key=lambda g: g.discount_percent, reverse=True)
    to_enrich = candidates[:ENRICH_LIMIT]
    # O enriquecimento (ITAD) altera o objeto do provider no lugar, então só
    # depois dele a oferta é normalizada.
    steam.enrich(cfg.itad_api_key, to_enrich)
    offers = [from_steam(g) for g in to_enrich]

    # Pontua todo jogo com desconto e não visto após o enriquecimento, e não só
    # os que passam no portão normal de reviews/popularidade. Esse conjunto mais
    # amplo serve apenas ao fallback editorial; as regras normais de publicação
    # continuam abaixo. Também dá a bundles/packages sem review a chance de
    # serem considerados editorialmente em vez de descartados antes do score.
    all_scored = []
    for offer in offers:
        r = scoring.score_game(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount_percent=offer.discount_percent, source="steam",
            review_score=offer.review_score, review_count=offer.review_count,
            lowest_price=offer.lowest_price, waitlisted=offer.waitlisted,
        )
        all_scored.append((r.total, offer, r))
        ctx.plus_candidates.append({
            "score": r.total, "source": "steam", "seen_key": offer.key,
            "title": offer.title, "price": offer.price, "original_price": offer.original_price,
            "discount_percent": offer.discount_percent, "link": offer.permalink,
            "lowest_price": offer.lowest_price, "image_url": offer.image_url,
            "game_id": offer.offer_id, "result": r, "thread_id": topic_thread_id(cfg, JOGOS),
            "review_score": offer.review_score,
        })

    # Apps usam o portão normal de review/popularidade. Bundles/packages
    # geralmente não têm review próprio, então uma oferta non-app forte passa
    # pelo caminho PLUS normal por score editorial em vez de esperar a janela
    # global do fallback.
    normal_app_ids = {
        o.offer_id for o in offers
        if o.store_type == "app"
        and steam.is_quality_game(o, cfg.steam_min_review_score, cfg.steam_min_review_count)
        and (o.waitlisted is None or o.waitlisted >= cfg.steam_min_waitlisted)
    }
    strong_nonapp_ids = {
        o.offer_id for total, o, _r in all_scored
        if o.store_type != "app"
        and o.discount_percent >= cfg.steam_min_discount_percent
        and total >= getattr(cfg, "plus_editorial_min_score", 25)
    }
    eligible_ids = normal_app_ids | strong_nonapp_ids
    scored = [(total, o, r) for total, o, r in all_scored if o.offer_id in eligible_ids]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.steam_max_posts_per_cycle]

    log.info(
        "[Steam] Encontrados: %d (apps=%d, packages=%d, bundles=%d) | "
        "Desconto>=%d%%: %d | Nao vistos: %d | Reviews OK: %d | "
        "Waitlist OK: %d | Bundle/package sem review: %d | Non-app editorial OK: %d | "
        "Scored: %d | Selecionados: %d",
        len(games),
        sum(1 for g in games if g.store_type == "app"),
        sum(1 for g in games if g.store_type == "sub"),
        sum(1 for g in games if g.store_type == "bundle"),
        cfg.steam_min_discount_percent,
        len([g for g in games if g.discount_percent >= cfg.steam_min_discount_percent]),
        len([g for g in games if g.discount_percent >= cfg.steam_min_discount_percent
             and f"steam:{g.game_id}" not in ctx.seen]),
        sum(1 for o in offers
            if steam.is_quality_game(o, cfg.steam_min_review_score, cfg.steam_min_review_count)),
        sum(1 for o in offers
            if steam.is_quality_game(o, cfg.steam_min_review_score, cfg.steam_min_review_count)
            and (o.waitlisted is None or o.waitlisted >= cfg.steam_min_waitlisted)),
        sum(1 for o in offers if o.store_type != "app" and o.review_count is None),
        len(strong_nonapp_ids), len(scored), len(selected),
    )

    if ctx.dry_run:
        for total, o, _r in scored:
            log.info("  score %d | %d%% off | %s%% positivo | %s reviews | wl %s | %s",
                     total, o.discount_percent, o.review_score, o.review_count,
                     o.waitlisted, o.title[:50])
        return 0
    if not selected:
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result in selected:
        link = publisher.affiliate_link(offer)
        text = telegram.format_game_deal(
            title=offer.title, price=offer.price, original_price=offer.original_price,
            discount=offer.discount_percent, link=link, lowest_price=offer.lowest_price,
        )
        ok = publisher.publish(
            offer, topic=JOGOS, text=text, result=result, score=score_val,
            link=link, log_tag="Steam", alert_link=offer.permalink,
            analytics_kwargs={"category": "games", "deal_type": "plus", "affiliate": False},
        )
        if not ok:
            continue
        posted += 1
        log.info("[Steam] postado: %d%% off | %s", offer.discount_percent, offer.title[:50])
        publisher.pace(posted, len(selected))

    return posted
