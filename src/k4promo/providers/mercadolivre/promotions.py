"""Descoberta de promoções do Mercado Livre e sinais de aprovação.

Duas responsabilidades que só existem no ML:

- montar o mapa de promoções por anúncio, juntando catálogo manual, cupom que
  já aparece na listagem e o que o scanner de página descobriu (com cache);
- traduzir sinais comerciais em pontos, base do fallback comercial.
"""

from __future__ import annotations

import logging

from k4promo.providers.mercadolivre import browser as ml_playwright
from k4promo.providers.mercadolivre import signals as ml_signals
from k4promo.services import promotions as promotion_engine
from k4promo.services import scoring

log = logging.getLogger("k4binho")


def _promotion_signature(promo: promotion_engine.Promotion) -> tuple:
    return (
        promo.source, promo.kind, promo.code, promo.discount_amount,
        promo.discount_percent, promo.minimum_spend, promo.max_discount,
        promo.selected_users_only, promo.app_only, promo.requires_coins,
        promo.rescue_url,
    )


def merge_promotions(*groups) -> list[promotion_engine.Promotion]:
    """Junta grupos de promoções sem repetir a mesma condição."""
    merged: list[promotion_engine.Promotion] = []
    seen_keys: set[tuple] = set()
    for group in groups:
        for promo in group or []:
            key = _promotion_signature(promo)
            if key in seen_keys:
                continue
            seen_keys.add(key)
            merged.append(promo)
    return merged


def scan_priority(offer, best_sellers: set[str], trends: list[str]) -> float:
    """Ordem de prioridade para gastar o orçamento de scans do navegador."""
    score = float(offer.discount_percent * 2)
    score += min(int(offer.sales_count or 0), 5000) / 100
    if scoring.category_match(offer.title):
        score += 30
    if offer.offer_id in best_sellers:
        score += 30
    if ml_signals.title_matches_trend(offer.title, trends):
        score += 20
    if offer.official_store:
        score += 15
    if offer.coupon_amount:
        score += 40
    return score


def signal_points(offer, *, is_best_seller: bool, is_trending: bool, guaranteed_promotion: bool) -> int:
    """Evidência comercial acumulada. Rating alto sozinho não basta."""
    points = 0
    sales = int(offer.sales_count or 0)
    rating = float(offer.rating or 0)
    if is_best_seller:
        points += 2
    if is_trending:
        points += 1
    if offer.official_store:
        points += 1
    if sales >= 5000:
        points += 2
    elif sales >= 500:
        points += 1
    if rating >= 4.7 and sales >= 100:
        points += 1
    if guaranteed_promotion:
        points += 2
    return points


def commercial_fallback_eligible(
    result, *, has_price_evidence: bool, signal_points: int, already_seen: bool,
    guaranteed_promotion: bool, score_min: int,
) -> bool:
    """Fallback comercial: não depende de histórico, mas exige guardrails."""
    if already_seen or not has_price_evidence or signal_points < 2:
        return False
    if result.quality < 35 or result.conversion < 25 or result.confidence < 25:
        return False
    return guaranteed_promotion or result.total >= max(45, score_min - 25)


def promotions_for_offers(
    cfg, offers: list, best_sellers: set[str], trends: list[str], seen, dry_run: bool,
) -> tuple[dict[str, list[promotion_engine.Promotion]], dict[str, int]]:
    """Mapa ``offer_id -> promoções`` e as estatísticas do scanner.

    Um item já visto pode ser reescaneado quando o cache expira; isso não o
    republica sozinho, só alimenta a checagem de revival.
    """
    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    cache = promotion_engine.load_cache()
    promo_map: dict[str, list[promotion_engine.Promotion]] = {}
    needs: list = []
    stats = {"eligible": 0, "cache_hits": 0, "scanned": 0, "found": 0, "codes": 0, "seen_scanned": 0}

    for offer in offers:
        manual = promotion_engine.promotions_for_item(
            catalog, "mercadolivre", offer.title, offer.price
        )
        listing = []
        from_listing = promotion_engine.promotion_from_coupon_amount(
            "mercadolivre", offer.coupon_amount
        )
        if from_listing:
            listing.append(from_listing)
        cached = promotion_engine.get_cached_promotions(
            cache, f"ml:{offer.offer_id}", cfg.ml_coupon_cache_hours,
            promotion_max_age_hours=cfg.ml_coupon_positive_cache_hours,
        )
        if cached is not None:
            stats["cache_hits"] += 1
        promo_map[offer.offer_id] = merge_promotions(manual, listing, cached or [])
        if cached is None and offer.permalink:
            needs.append(offer)
    stats["eligible"] = len(needs)

    if cfg.ml_coupon_discovery_enabled and not dry_run and needs:
        needs.sort(
            key=lambda o: scan_priority(o, best_sellers, trends) + (10 if o.key in seen else 0),
            reverse=True,
        )
        targets = needs[: max(0, cfg.ml_coupon_scan_items)]
        urls = [o.permalink for o in targets]
        try:
            discovered = ml_playwright.discover_promotions(urls) if urls else {}
        except ml_playwright.NotLoggedIn as exc:
            log.warning("[ML][cupom] descoberta via pagina indisponivel: %s", exc)
            discovered = {}
        except Exception as exc:
            log.warning("[ML][cupom] falha na descoberta: %s", exc)
            discovered = {}

        for offer in targets:
            found = discovered.get(offer.permalink, [])
            promotion_engine.set_cached_promotions(cache, f"ml:{offer.offer_id}", found)
            promo_map[offer.offer_id] = merge_promotions(promo_map.get(offer.offer_id, []), found)
            stats["scanned"] += 1
            if offer.key in seen:
                stats["seen_scanned"] += 1
            if found:
                stats["found"] += 1
                stats["codes"] += sum(1 for p in found if p.code)
                ev = promotion_engine.evaluate_price(offer.price, found, title=offer.title)
                display = ev.display_promotion
                code = display.code if display and display.code else "sem-codigo"
                log.info("[ML][promo-scan] %s | %s | economia=R$ %.2f",
                         offer.title[:55], code, ev.guaranteed_savings)
            else:
                log.info("[ML][promo-scan] %s | sem promocao", offer.title[:55])
        promotion_engine.save_cache(cache)

    return promo_map, stats
