"""Ciclo do Mercado Livre.

É o único ciclo com forma própria, porque combina quatro coisas que as outras
lojas não têm: histórico de preço, descoberta de cupom por navegador logado,
fallback comercial independente de histórico e republicação por queda real de
preço efetivo (price-drop e revival por promoção).

Ordem das decisões por anúncio:

1. histórico e promoções → preço efetivo garantido;
2. score multidimensional sobre o preço efetivo;
3. aprovação estrita (histórico + score, ou launch score) **ou** fallback
   comercial (evidência de preço + sinais + guardrails);
4. se reprovado e já publicado: revival por promoção nova, senão price-drop.
"""

from __future__ import annotations

import logging
import time

import httpx

from k4promo import telegram
from k4promo.domain.models import Offer
from k4promo.providers.adapters import from_mercadolivre
from k4promo.providers.mercadolivre import api as mercadolivre
from k4promo.providers.mercadolivre import browser as ml_playwright
from k4promo.providers.mercadolivre import promotions as ml_promotions
from k4promo.providers.mercadolivre import scraper as ml_scraper
from k4promo.providers.mercadolivre import signals as ml_signals
from k4promo.services import promotions as promotion_engine
from k4promo.services import scoring
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.router import resolve_topic
from k4promo.storage import deal_store as ds
from k4promo.storage import price_history

log = logging.getLogger("k4binho")

# Avisa uma vez por execução que a sessão do ML caiu.
_session_alert_sent = False


def _delay_for(score: int) -> int:
    if score >= 100:
        return 0
    if score >= 85:
        return 300
    return 900


def _diversify_by_category(candidates, limit, max_per_category=2):
    """Evita que um ciclo inteiro saia só de uma categoria (ex.: só
    ferramentas) mesmo quando ela domina o score. Pega no máximo
    ``max_per_category`` por área, respeitando a ordem por score, e só usa os
    excedentes para completar as vagas restantes se não houver diversidade
    suficiente."""
    picked, leftover, counts = [], [], {}
    for entry in candidates:
        area = scoring.category_match(entry[1].title) or "outros"
        if counts.get(area, 0) < max_per_category and len(picked) < limit:
            picked.append(entry)
            counts[area] = counts.get(area, 0) + 1
        else:
            leftover.append(entry)
    for item in leftover:
        if len(picked) >= limit:
            break
        picked.append(item)
    picked.sort(key=lambda pair: pair[0], reverse=True)
    return picked


def _collect_offers(cfg) -> list[Offer]:
    try:
        deals = ml_scraper.scrape_deals(min_discount=0, category_ids=cfg.ml_highlight_category_ids)
    except httpx.HTTPError as exc:
        log.error("[ML] scrape ofertas: %s", exc)
        deals = []

    if cfg.ml_highlight_category_ids:
        try:
            highlight_deals = mercadolivre.collect_highlight_deals(
                cfg.ml_highlight_category_ids, cfg.ml_site,
                cfg.ml_client_id, cfg.ml_client_secret,
            )
        except RuntimeError as exc:
            log.error("[ML] descoberta por categoria: %s", exc)
            highlight_deals = []
        existing_ids = {d.item_id for d in deals}
        novos = [d for d in highlight_deals if d.item_id not in existing_ids]
        if novos:
            log.info("[ML] +%d produto(s) via highlights por categoria.", len(novos))
        deals.extend(novos)
    return [from_mercadolivre(d) for d in deals]


def _warn_session_expired(cfg) -> None:
    global _session_alert_sent
    if _session_alert_sent:
        return
    target = cfg.telegram_admin_chat_id or cfg.telegram_channel_id
    try:
        telegram.send_message(
            cfg.telegram_bot_token, target,
            "⚠️ <b>Sessão do Mercado Livre expirou.</b>\n\n"
            "O bot não consegue gerar links de afiliado até relogar.\n"
            "Rode: <code>python scripts/login_ml.py</code>",
        )
        _session_alert_sent = True
    except Exception:
        pass


def run(ctx: CycleContext) -> int:
    cfg, seen = ctx.cfg, ctx.seen
    offers = _collect_offers(cfg)
    if not offers:
        log.info("[ML] Nenhuma oferta encontrada (scraper e API vazios).")
        return 0

    best_sellers = ml_signals.best_seller_ids(
        cfg.ml_highlight_category_ids, cfg.ml_client_id, cfg.ml_client_secret
    )
    trends = ml_signals.trending_keywords(cfg.ml_client_id, cfg.ml_client_secret)
    promotion_map, scan_stats = ml_promotions.promotions_for_offers(
        cfg, offers, best_sellers, trends, seen, ctx.dry_run
    )

    candidates: list = []
    stats = {
        "found": len(offers), "price_ok": 0, "history_ready": 0, "launch_ok": 0,
        "strong_signal": 0, "already_seen": 0, "strict_approved": 0,
        "commercial_fallback": 0, "with_promotion": 0, "coupon_codes": 0,
        "promotion_revival": 0,
    }
    fallback_ids: set[str] = set()
    revival_ids: set[str] = set()

    for offer in offers:
        item_id = offer.offer_id
        observations = price_history.observation_count(ctx.history, item_id, cfg.price_history_days)
        historical_min = price_history.min_price(ctx.history, item_id, cfg.price_history_days)
        historical_avg = price_history.avg_price(ctx.history, item_id, cfg.price_history_days)

        promo_eval = promotion_engine.evaluate_price(
            offer.price, promotion_map.get(item_id, []), title=offer.title
        )
        display_promo = promo_eval.display_promotion
        promo_code = display_promo.code if display_promo else ""
        if promo_eval.active_promotions:
            stats["with_promotion"] += 1
        if promo_code:
            stats["coupon_codes"] += 1

        is_best_seller = item_id in best_sellers
        is_trending = ml_signals.title_matches_trend(offer.title, trends)

        result = scoring.score(
            deal=offer, min_price_30d=historical_min, obs_count=observations + 1,
            is_best_seller=is_best_seller, is_trending=is_trending,
            avg_price_30d=historical_avg, effective_price=promo_eval.scoring_price,
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_code=promo_code if promo_eval.best_guaranteed else "",
        )
        # O histórico continua usando o preço público listado: cupom temporário
        # não contamina a série base.
        price_history.record(ctx.history, item_id, offer.price)

        has_price_evidence = result.price_subtotal >= cfg.price_min
        history_ready = observations + 1 >= cfg.min_history_observations
        by_history = history_ready and result.total >= cfg.score_min
        by_launch = result.total >= cfg.launch_score
        points = ml_promotions.signal_points(
            offer, is_best_seller=is_best_seller, is_trending=is_trending,
            guaranteed_promotion=promo_eval.guaranteed_savings > 0,
        )

        if has_price_evidence:
            stats["price_ok"] += 1
        if history_ready:
            stats["history_ready"] += 1
        if by_launch:
            stats["launch_ok"] += 1
        if points >= 2:
            stats["strong_signal"] += 1
        already_seen = offer.key in seen
        if already_seen:
            stats["already_seen"] += 1

        strict_approved = has_price_evidence and (by_history or by_launch) and not already_seen
        if strict_approved:
            stats["strict_approved"] += 1

        commercial_fallback = not strict_approved and ml_promotions.commercial_fallback_eligible(
            result, has_price_evidence=has_price_evidence, signal_points=points,
            already_seen=already_seen,
            guaranteed_promotion=promo_eval.guaranteed_savings > 0, score_min=cfg.score_min,
        )
        if commercial_fallback:
            fallback_ids.add(item_id)
            stats["commercial_fallback"] += 1

        approved = strict_approved or commercial_fallback
        if ctx.dry_run:
            promo_txt = ""
            if promo_eval.guaranteed_savings > 0:
                promo_txt = f" | promo R${promo_eval.guaranteed_savings:.2f} -> R${promo_eval.scoring_price:.2f}"
            elif promo_eval.best_conditional:
                promo_txt = f" | promo condicional -> R${promo_eval.potential_price:.2f}"
            log.info(
                "[ML][score %s] %d | preco %d | hist %d/%d%s | %s | %s",
                "APROVADA" if approved else "cortada", result.total, result.price_subtotal,
                observations + 1, cfg.min_history_observations, promo_txt,
                offer.title[:50], "; ".join(result.reasons) or "sem sinais",
            )
        if approved:
            candidates.append((result.total, offer, result, historical_min, historical_avg, None, promo_eval))

        if not approved and already_seen:
            current_effective = promo_eval.scoring_price
            signature = promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed)
            is_revival, prev_price = ds.check_promotion_revival(
                ctx.published_deals, item_id, current_effective, signature,
                min_drop_percent=cfg.ml_promo_revival_min_drop_percent,
                min_drop_amount=cfg.ml_promo_revival_min_drop_amount,
                cooldown_hours=cfg.ml_promo_revival_cooldown_hours,
            )
            if is_revival:
                revival_ids.add(item_id)
                stats["promotion_revival"] += 1
                log.info("[ML][promo-revival] %s | %.2f -> %.2f",
                         offer.title[:45], prev_price, current_effective)
                candidates.append((result.total + 25, offer, result, historical_min,
                                   historical_avg, prev_price, promo_eval))
            else:
                is_drop, prev_price = ds.check_price_drop(
                    ctx.published_deals, item_id, current_effective
                )
                if is_drop:
                    log.info("[ML][price-drop] %s caiu de %.2f para %.2f",
                             offer.title[:40], prev_price, current_effective)
                    candidates.append((result.total + 20, offer, result, historical_min,
                                       historical_avg, prev_price, promo_eval))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    selected = _diversify_by_category(candidates, cfg.max_posts_per_cycle)

    log.info(
        "[ML] Encontrados: %d | Preco OK: %d | Historico pronto: %d | "
        "Launch score: %d | Sinal comercial forte: %d | Ja vistos: %d | "
        "Promocao: %d | Codigos: %d | Promo scan elegiveis: %d | Promo cache: %d | "
        "Scaneados: %d | Promo encontradas: %d | Vistos reescaneados: %d | "
        "Aprovados estritos: %d | Fallback comercial: %d | Reativados por promocao: %d | "
        "Candidatos: %d | Selecionados: %d",
        stats["found"], stats["price_ok"], stats["history_ready"], stats["launch_ok"],
        stats["strong_signal"], stats["already_seen"], stats["with_promotion"],
        stats["coupon_codes"], scan_stats["eligible"], scan_stats["cache_hits"],
        scan_stats["scanned"], scan_stats["found"], scan_stats["seen_scanned"],
        stats["strict_approved"], stats["commercial_fallback"], stats["promotion_revival"],
        len(candidates), len(selected),
    )
    if fallback_ids:
        log.info("[ML] Fallback comercial ativo: preco OK + sinais independentes + "
                 "guardrails de qualidade/conversao/confianca.")

    if ctx.dry_run:
        log.info("[ML][dry-run] %d oferta(s) aprovada(s). Nenhuma postagem enviada.", len(selected))
        return 0
    if not selected:
        log.info("[ML] Nenhuma oferta com historico e score suficientes.")
        return 0

    try:
        links = ml_playwright.generate_links(
            [entry[1].permalink for entry in selected], cfg.ml_affiliate_tag
        )
    except ml_playwright.NotLoggedIn as exc:
        log.critical("[ML] %s", exc)
        log.critical("[ML] Sem sessao ML = comissao zero. Rode: python scripts/login_ml.py")
        _warn_session_expired(cfg)
        return 0

    publisher = Publisher(ctx)
    posted = 0
    for score_val, offer, result, hist_min, hist_avg, drop_prev, promo_eval in selected:
        if posted:
            delay = max(7, _delay_for(score_val))
            if delay > 7:
                log.info("[ML] score %d; aguardando %d min.", score_val, delay // 60)
            time.sleep(delay)

        short_url, image = links.get(offer.permalink, (None, None))
        if not short_url:
            log.warning("[ML] sem short_url para %s", offer.offer_id)
            continue
        link = publisher.affiliate_link(offer, short_url)
        effective_price = promo_eval.scoring_price
        # O link de afiliado traz a imagem do anúncio; o thumbnail do scraper é
        # o fallback.
        offer.image_url = image or offer.image_url

        if drop_prev is not None:
            text = telegram.format_price_drop(
                title=offer.title, price=effective_price, previous_price=drop_prev,
                link=link, promotion=promo_eval,
            )
            action = "promotion_revival" if offer.offer_id in revival_ids else "price_drop"
        else:
            text = telegram.format_deal(
                title=offer.title, price=offer.price, original_price=offer.original_price,
                discount=offer.discount_percent, link=link, sales_count=offer.sales_count,
                rating=offer.rating, official_store=offer.official_store,
                offer_label=offer.offer_label, coupon_amount=offer.coupon_amount,
                min_price_30d=hist_min, avg_price_30d=hist_avg,
                history_confidence=result.history_confidence, promotion=promo_eval,
            )
            action = "published"

        topic = resolve_topic("ml", offer.title)
        display_promo = promo_eval.display_promotion
        effective_discount = offer.discount_from(effective_price)

        ok = publisher.publish(
            offer, topic=topic, text=text, result=result, score=score_val,
            link=link, log_tag="ML", price=effective_price,
            showcase_key=f"ml:{offer.offer_id}",
            analytics_kwargs={
                "listed_price": offer.price,
                "discount_percent": effective_discount,
                "price_subtotal": result.price_subtotal,
                "reasons": result.reasons,
                "history_observations": price_history.observation_count(
                    ctx.history, offer.offer_id, cfg.price_history_days
                ),
                "min_price_30d": hist_min,
                "avg_price_30d": hist_avg,
                "category": scoring.category_match(offer.title),
                "deal_type": "commercial", "affiliate": True, "action": action,
                "promotion_code": display_promo.code if display_promo else "",
                "promotion_savings": promo_eval.guaranteed_savings,
                "promotion_conditional": bool(display_promo and display_promo.conditional),
            },
            showcase_kwargs={
                "discount_percent": effective_discount,
                "coupon_savings": promo_eval.guaranteed_savings,
                "lowest_price": bool(
                    hist_min is not None and effective_price <= hist_min
                    and result.history_confidence == "high"
                ),
            },
        )
        if not ok:
            continue

        ds.record_published(
            ctx.published_deals, offer.offer_id, effective_price,
            promotion_signature=promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed),
        )
        posted += 1
        if promo_eval.guaranteed_savings > 0:
            code_label = f" {display_promo.code}" if display_promo and display_promo.code else ""
            log.info("[ML][cupom%s] %s: score %d | %.2f -> %.2f | %s",
                     code_label, action, score_val, offer.price, effective_price, offer.title[:50])
        elif offer.offer_id in fallback_ids:
            log.info("[ML][fallback-comercial] %s: score %d | %s", action, score_val, offer.title[:50])
        else:
            log.info("[ML] %s: score %d | %s", action, score_val, offer.title[:50])

    return posted
