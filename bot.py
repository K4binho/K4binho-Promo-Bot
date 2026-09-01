import logging
import socket
import sys
import time
from datetime import datetime, timezone

import httpx

import alert_store
import analytics
import aliexpress
import bot_commands
import click_server
import click_tracker
import deal_store as ds
import digest_store
import mercadolivre
import ml_playwright
import ml_scraper
import ml_signals
import gmg_cj
import nuuvem
import price_history
import promotion_engine
import scoring
import steam
import telegram
from config import Config
from seen_store import load_seen, save_seen, mark_seen, expire_plus

log = logging.getLogger("k4binho")

_lock_socket: socket.socket | None = None
_ml_session_alert_sent: bool = False


def _acquire_single_instance_lock() -> bool:
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", 47591))
        _lock_socket.listen(1)
        return True
    except OSError:
        return False


def _delay_for(score: int) -> int:
    if score >= 100:
        return 0
    if score >= 85:
        return 300
    return 900


def _diversify_by_category(candidates, limit, max_per_category=2):
    """Evita que um ciclo inteiro saia so de uma categoria (ex: so
    ferramentas) mesmo quando ela domina o score. Pega no maximo
    `max_per_category` por area (informatica/celular/games/audio/
    ferramentas/carregador/automacao/outros), respeitando a ordem por
    score, e só usa os excedentes pra completar o restante das vagas
    se nao houver diversidade suficiente."""
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


_click_links: dict[str, dict] = {}
_plus_candidates: list[tuple[float, str, str, str, object, object]] = []


def _wrap_link(cfg: Config, deal_id: str, destination: str, source: str, title: str) -> str:
    if not cfg.click_tracking_enabled:
        return destination
    click_tracker.register_link(_click_links, deal_id, destination, source=source, title=title)
    click_tracker.save_links(_click_links)
    return click_server.tracking_url(cfg.click_base_url, deal_id)


def _check_alerts(cfg: Config, alerts: dict, title: str, price: float, source: str, link: str, product_id: str = "") -> None:
    matches = alert_store.match_deal(alerts, title, price, source, product_id=product_id)
    for chat_id, alert in matches:
        bot_commands.notify_alert_match(cfg.telegram_bot_token, chat_id, alert, title, price, link)
    if matches:
        alert_store.save_alerts(alerts)


def _promotion_signature(promo: promotion_engine.Promotion) -> tuple:
    return (
        promo.source, promo.kind, promo.code, promo.discount_amount,
        promo.discount_percent, promo.minimum_spend, promo.max_discount,
        promo.selected_users_only, promo.app_only, promo.requires_coins,
        promo.rescue_url,
    )


def _merge_promotions(*groups) -> list[promotion_engine.Promotion]:
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


def _ml_scan_priority(deal, best_sellers: set[str], trends: list[str]) -> float:
    score = float(deal.discount_percent * 2)
    score += min(int(getattr(deal, "sales_count", 0) or 0), 5000) / 100
    if scoring.category_match(deal.title):
        score += 30
    if deal.item_id in best_sellers:
        score += 30
    if ml_signals.title_matches_trend(deal.title, trends):
        score += 20
    if getattr(deal, "official_store", False):
        score += 15
    if getattr(deal, "coupon_amount", None):
        score += 40
    return score


def _ml_signal_points(deal, *, is_best_seller: bool, is_trending: bool, guaranteed_promotion: bool) -> int:
    points=0; sales=int(getattr(deal,"sales_count",0) or 0); rating=float(getattr(deal,"rating",0) or 0)
    if is_best_seller: points += 2
    if is_trending: points += 1
    if bool(getattr(deal,"official_store",False)): points += 1
    if sales >= 5000: points += 2
    elif sales >= 500: points += 1
    if rating >= 4.7 and sales >= 100: points += 1
    if guaranteed_promotion: points += 2
    return points


def _ml_commercial_fallback_eligible(result, *, has_price_evidence: bool, signal_points: int, already_seen: bool, guaranteed_promotion: bool, score_min: int) -> bool:
    if already_seen or not has_price_evidence or signal_points < 2: return False
    if result.quality < 35 or result.conversion < 25 or result.confidence < 25: return False
    return guaranteed_promotion or result.total >= max(45, score_min - 25)


def _ml_promotions_for_deals(cfg: Config, deals: list, best_sellers: set[str], trends: list[str], seen, dry_run: bool) -> tuple[dict[str, list[promotion_engine.Promotion]], dict[str, int]]:
    catalog=promotion_engine.load_catalog(cfg.promotions_file); cache=promotion_engine.load_cache(); promo_map={}; needs=[]
    stats={"eligible":0,"cache_hits":0,"scanned":0,"found":0,"codes":0,"seen_scanned":0}
    for deal in deals:
        manual=promotion_engine.promotions_for_item(catalog,"mercadolivre",deal.title,deal.price); listing=[]
        lp=promotion_engine.promotion_from_coupon_amount("mercadolivre",getattr(deal,"coupon_amount",None))
        if lp: listing.append(lp)
        cached=promotion_engine.get_cached_promotions(cache,f"ml:{deal.item_id}",cfg.ml_coupon_cache_hours,promotion_max_age_hours=cfg.ml_coupon_positive_cache_hours)
        if cached is not None: stats["cache_hits"] += 1
        promo_map[deal.item_id]=_merge_promotions(manual,listing,cached or [])
        if cached is None and deal.permalink: needs.append(deal)
    stats["eligible"]=len(needs)
    if cfg.ml_coupon_discovery_enabled and not dry_run and needs:
        needs.sort(key=lambda d:_ml_scan_priority(d,best_sellers,trends)+(10 if d.item_id in seen else 0),reverse=True)
        targets=needs[:max(0,cfg.ml_coupon_scan_items)]; urls=[d.permalink for d in targets]
        try: discovered=ml_playwright.discover_promotions(urls) if urls else {}
        except ml_playwright.NotLoggedIn as exc: log.warning("[ML][cupom] descoberta via pagina indisponivel: %s",exc); discovered={}
        except Exception as exc: log.warning("[ML][cupom] falha na descoberta: %s",exc); discovered={}
        for deal in targets:
            found=discovered.get(deal.permalink,[]); promotion_engine.set_cached_promotions(cache,f"ml:{deal.item_id}",found)
            promo_map[deal.item_id]=_merge_promotions(promo_map.get(deal.item_id,[]),found); stats["scanned"] += 1
            if deal.item_id in seen: stats["seen_scanned"] += 1
            if found:
                stats["found"] += 1; stats["codes"] += sum(1 for p in found if p.code)
                ev=promotion_engine.evaluate_price(deal.price,found,title=deal.title); d=ev.display_promotion; code=d.code if d and d.code else "sem-codigo"
                log.info("[ML][promo-scan] %s | %s | economia=R$ %.2f",deal.title[:55],code,ev.guaranteed_savings)
            else: log.info("[ML][promo-scan] %s | sem promocao",deal.title[:55])
        promotion_engine.save_cache(cache)
    return promo_map,stats


def run_cycle(
    cfg: Config,
    seen: set[str],
    history: dict[str, list[list[str | int]]],
    published_deals: dict[str, dict],
    alerts: dict[str, list[dict]],
    dry_run: bool,
) -> int:
    global _ml_session_alert_sent

    try:
        deals = ml_scraper.scrape_deals(min_discount=0, category_ids=cfg.ml_highlight_category_ids)
    except httpx.HTTPError as exc:
        log.error("[ML] scrape ofertas: %s", exc)
        deals = []

    if cfg.ml_highlight_category_ids:
        try:
            highlight_deals = mercadolivre.collect_highlight_deals(
                cfg.ml_highlight_category_ids,
                cfg.ml_site,
                cfg.ml_client_id,
                cfg.ml_client_secret,
            )
        except RuntimeError as exc:
            log.error("[ML] descoberta por categoria: %s", exc)
            highlight_deals = []
        existing_ids = {d.item_id for d in deals}
        novos = [d for d in highlight_deals if d.item_id not in existing_ids]
        if novos:
            log.info("[ML] +%d produto(s) via highlights por categoria.", len(novos))
        deals.extend(novos)

    if not deals:
        log.info("[ML] Nenhuma oferta encontrada (scraper e API vazios).")
        return 0

    best_sellers = ml_signals.best_seller_ids(
        cfg.ml_highlight_category_ids, cfg.ml_client_id, cfg.ml_client_secret
    )
    trends = ml_signals.trending_keywords(cfg.ml_client_id, cfg.ml_client_secret)
    promotion_map, promotion_scan_stats = _ml_promotions_for_deals(
        cfg, deals, best_sellers, trends, seen, dry_run
    )
    candidates = []

    ml_stats = {
        "found": len(deals),
        "price_ok": 0,
        "history_ready": 0,
        "launch_ok": 0,
        "strong_signal": 0,
        "already_seen": 0,
        "strict_approved": 0,
        "commercial_fallback": 0,
        "with_promotion": 0,
        "coupon_codes": 0,
        "promotion_revival": 0,
    }
    commercial_fallback_ids: set[str] = set()
    promotion_revival_ids: set[str] = set()

    for deal in deals:
        observations = price_history.observation_count(
            history, deal.item_id, cfg.price_history_days
        )
        historical_min = price_history.min_price(
            history, deal.item_id, cfg.price_history_days
        )
        historical_avg = price_history.avg_price(
            history, deal.item_id, cfg.price_history_days
        )

        promotions = promotion_map.get(deal.item_id, [])
        promo_eval = promotion_engine.evaluate_price(
            deal.price, promotions, title=deal.title
        )
        display_promo = promo_eval.display_promotion
        promo_code = display_promo.code if display_promo else ""
        if promo_eval.active_promotions:
            ml_stats["with_promotion"] += 1
        if promo_code:
            ml_stats["coupon_codes"] += 1

        result = scoring.score(
            deal=deal,
            min_price_30d=historical_min,
            obs_count=observations + 1,
            is_best_seller=deal.item_id in best_sellers,
            is_trending=ml_signals.title_matches_trend(deal.title, trends),
            avg_price_30d=historical_avg,
            effective_price=promo_eval.scoring_price,
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_code=promo_code if promo_eval.best_guaranteed else "",
        )
        # Histórico continua usando o preço público listado. Cupom temporário não
        # contamina a série de preço base.
        price_history.record(history, deal.item_id, deal.price)

        has_price_evidence = result.price_subtotal >= cfg.price_min
        history_ready = observations + 1 >= cfg.min_history_observations
        by_history = history_ready and result.total >= cfg.score_min
        by_launch = result.total >= cfg.launch_score

        is_best_seller = deal.item_id in best_sellers
        is_trending = ml_signals.title_matches_trend(deal.title, trends)
        signal_points = _ml_signal_points(deal, is_best_seller=is_best_seller, is_trending=is_trending, guaranteed_promotion=promo_eval.guaranteed_savings > 0)
        strong_commercial_signal = signal_points >= 2

        if has_price_evidence:
            ml_stats["price_ok"] += 1
        if history_ready:
            ml_stats["history_ready"] += 1
        if by_launch:
            ml_stats["launch_ok"] += 1
        if strong_commercial_signal:
            ml_stats["strong_signal"] += 1
        if deal.item_id in seen:
            ml_stats["already_seen"] += 1

        strict_approved = (
            has_price_evidence
            and (by_history or by_launch)
            and deal.item_id not in seen
        )
        if strict_approved:
            ml_stats["strict_approved"] += 1

        commercial_fallback = (not strict_approved and _ml_commercial_fallback_eligible(result, has_price_evidence=has_price_evidence, signal_points=signal_points, already_seen=deal.item_id in seen, guaranteed_promotion=promo_eval.guaranteed_savings > 0, score_min=cfg.score_min))
        if commercial_fallback:
            commercial_fallback_ids.add(deal.item_id)
            ml_stats["commercial_fallback"] += 1

        approved = strict_approved or commercial_fallback
        if dry_run:
            status = "APROVADA" if approved else "cortada"
            reasons = "; ".join(result.reasons) or "sem sinais"
            promo_txt = ""
            if promo_eval.guaranteed_savings > 0:
                promo_txt = f" | promo R${promo_eval.guaranteed_savings:.2f} -> R${promo_eval.scoring_price:.2f}"
            elif promo_eval.best_conditional:
                promo_txt = f" | promo condicional -> R${promo_eval.potential_price:.2f}"
            log.info(
                "[ML][score %s] %d | preco %d | hist %d/%d%s | %s | %s",
                status, result.total, result.price_subtotal,
                observations + 1, cfg.min_history_observations, promo_txt,
                deal.title[:50], reasons,
            )
        if approved:
            candidates.append((
                result.total, deal, result, historical_min, historical_avg,
                None, promo_eval,
            ))

        if not approved and deal.item_id in seen:
            current_effective = promo_eval.scoring_price
            sig = promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed)
            is_revival, prev_price = ds.check_promotion_revival(published_deals, deal.item_id, current_effective, sig, min_drop_percent=cfg.ml_promo_revival_min_drop_percent, min_drop_amount=cfg.ml_promo_revival_min_drop_amount, cooldown_hours=cfg.ml_promo_revival_cooldown_hours)
            if is_revival:
                promotion_revival_ids.add(deal.item_id); ml_stats["promotion_revival"] += 1
                log.info("[ML][promo-revival] %s | %.2f -> %.2f", deal.title[:45], prev_price, current_effective)
                candidates.append((result.total + 25, deal, result, historical_min, historical_avg, prev_price, promo_eval))
            else:
                is_drop, prev_price = ds.check_price_drop(published_deals, deal.item_id, current_effective)
                if is_drop:
                    log.info("[ML][price-drop] %s caiu de %.2f para %.2f", deal.title[:40], prev_price, current_effective)
                    candidates.append((result.total + 20, deal, result, historical_min, historical_avg, prev_price, promo_eval))

    candidates.sort(key=lambda pair: pair[0], reverse=True)
    selected = _diversify_by_category(candidates, cfg.max_posts_per_cycle)

    log.info(
        "[ML] Encontrados: %d | Preco OK: %d | Historico pronto: %d | "
        "Launch score: %d | Sinal comercial forte: %d | Ja vistos: %d | "
        "Promocao: %d | Codigos: %d | Promo scan elegiveis: %d | Promo cache: %d | Scaneados: %d | Promo encontradas: %d | Vistos reescaneados: %d | Aprovados estritos: %d | Fallback comercial: %d | Reativados por promocao: %d | Candidatos: %d | Selecionados: %d",
        ml_stats["found"], ml_stats["price_ok"], ml_stats["history_ready"], ml_stats["launch_ok"], ml_stats["strong_signal"], ml_stats["already_seen"], ml_stats["with_promotion"], ml_stats["coupon_codes"], promotion_scan_stats["eligible"], promotion_scan_stats["cache_hits"], promotion_scan_stats["scanned"], promotion_scan_stats["found"], promotion_scan_stats["seen_scanned"], ml_stats["strict_approved"], ml_stats["commercial_fallback"], ml_stats["promotion_revival"], len(candidates), len(selected),
    )

    if commercial_fallback_ids:
        log.info(
            "[ML] Fallback comercial ativo: preco OK + sinais independentes + guardrails de qualidade/conversao/confianca.",
        )

    if dry_run:
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
        log.critical("[ML] Sem sessao ML = comissao zero. Rode: python login_ml.py")
        if not _ml_session_alert_sent:
            alert_target = cfg.telegram_admin_chat_id or cfg.telegram_channel_id
            try:
                telegram.send_message(
                    cfg.telegram_bot_token,
                    alert_target,
                    "⚠️ <b>Sessão do Mercado Livre expirou.</b>\n\n"
                    "O bot não consegue gerar links de afiliado até relogar.\n"
                    "Rode: <code>python login_ml.py</code>",
                )
                _ml_session_alert_sent = True
            except Exception:
                pass
        return 0

    posted = 0
    for score_val, deal, result, hist_min, hist_avg, drop_prev, promo_eval in selected:
        if posted:
            delay = max(7, _delay_for(score_val))
            if delay > 7:
                log.info("[ML] score %d; aguardando %d min.", score_val, delay // 60)
            time.sleep(delay)
        link, image = links.get(deal.permalink, (None, None))
        if not link:
            log.warning("[ML] sem short_url para %s", deal.item_id)
            continue
        link = _wrap_link(cfg, deal.item_id, link, "ml", deal.title)
        effective_price = promo_eval.scoring_price

        if drop_prev is not None:
            text = telegram.format_price_drop(
                title=deal.title,
                price=effective_price,
                previous_price=drop_prev,
                link=link,
                promotion=promo_eval,
            )
            action = "promotion_revival" if deal.item_id in promotion_revival_ids else "price_drop"
        else:
            text = telegram.format_deal(
                title=deal.title,
                price=deal.price,
                original_price=deal.original_price,
                discount=deal.discount_percent,
                link=link,
                sales_count=deal.sales_count,
                rating=deal.rating,
                official_store=deal.official_store,
                offer_label=deal.offer_label,
                coupon_amount=deal.coupon_amount,
                min_price_30d=hist_min,
                avg_price_30d=hist_avg,
                history_confidence=result.history_confidence,
                promotion=promo_eval,
            )
            action = "published"
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=cfg.telegram_thread_id,
                image_url=image,
            )
        except httpx.HTTPError as exc:
            log.error("[ML] envio '%s': %s", deal.item_id, exc)
            continue

        mark_seen(seen, deal.item_id)
        ds.record_published(published_deals, deal.item_id, effective_price, promotion_signature=promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed))
        posted += 1
        display_promo = promo_eval.display_promotion
        analytics.record_deal(
            source="ml",
            product_id=deal.item_id,
            title=deal.title,
            price=effective_price,
            listed_price=deal.price,
            original_price=deal.original_price,
            discount_percent=(
                round((deal.original_price - effective_price) / deal.original_price * 100)
                if deal.original_price and deal.original_price > effective_price
                else deal.discount_percent
            ),
            quality_score=result.quality,
            conversion_score=result.conversion,
            retention_score=result.retention,
            confidence_score=result.confidence,
            final_score=result.final,
            price_subtotal=result.price_subtotal,
            reasons=result.reasons,
            history_observations=price_history.observation_count(
                history, deal.item_id, cfg.price_history_days
            ),
            min_price_30d=hist_min,
            avg_price_30d=hist_avg,
            history_confidence=result.history_confidence,
            category=scoring.category_match(deal.title),
            deal_type="commercial",
            affiliate=True,
            action=action,
            promotion_code=display_promo.code if display_promo else "",
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_conditional=bool(display_promo and display_promo.conditional),
        )
        if promo_eval.guaranteed_savings > 0:
            code_label = f" {display_promo.code}" if display_promo and display_promo.code else ""
            log.info(
                "[ML][cupom%s] %s: score %d | %.2f -> %.2f | %s",
                code_label, action, score_val, deal.price, effective_price, deal.title[:50],
            )
        elif deal.item_id in commercial_fallback_ids:
            log.info(
                "[ML][fallback-comercial] %s: score %d | %s",
                action, score_val, deal.title[:50],
            )
        else:
            log.info("[ML] %s: score %d | %s", action, score_val, deal.title[:50])
        _check_alerts(cfg, alerts, deal.title, effective_price, "ml", link)

    return posted


def run_steam_cycle(cfg: Config, seen: set[str], alerts: dict[str, list[dict]], dry_run: bool) -> int:
    try:
        games = steam.fetch_specials(cfg.itad_api_key, bundle_scan_apps=cfg.steam_bundle_scan_apps)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.error("[Steam] %s", exc)
        return 0

    current_ids = {f"steam:{g.game_id}" for g in games if g.discount_percent > 0}
    stale = [s for s in seen if s.startswith("steam:") and s not in current_ids]
    for s in stale:
        del seen[s]
    if stale:
        log.info("[Steam] %d jogo(s) saiu(ram) de promo, liberado(s) pra re-post.", len(stale))

    candidates = [
        g
        for g in games
        if g.discount_percent >= cfg.steam_min_discount_percent
        and f"steam:{g.game_id}" not in seen
    ]
    candidates.sort(key=lambda g: g.discount_percent, reverse=True)
    to_enrich = candidates[:60]
    steam.enrich(cfg.itad_api_key, to_enrich)

    # Score every discounted/unseen game after enrichment, not only the ones
    # that pass the normal popularity/review gate.  The broader pool is used
    # solely by the editorial fallback; the normal Steam publication rules
    # remain unchanged below.  This also gives bundles/packages with missing
    # review metadata a chance to be considered editorially instead of being
    # discarded before scoring.
    all_scored = []
    for g in to_enrich:
        r = scoring.score_game(
            title=g.title,
            price=g.price,
            original_price=g.original_price,
            discount_percent=g.discount_percent,
            source="steam",
            review_score=g.review_score,
            review_count=g.review_count,
            lowest_price=g.lowest_price,
            waitlisted=g.waitlisted,
        )
        all_scored.append((r.total, g, r))
        _plus_candidates.append({
            "score": r.total, "source": "steam", "seen_key": f"steam:{g.game_id}",
            "title": g.title, "price": g.price, "original_price": g.original_price,
            "discount_percent": g.discount_percent, "link": g.permalink,
            "lowest_price": g.lowest_price, "image_url": g.header_image,
            "game_id": g.game_id, "result": r, "thread_id": cfg.telegram_steam_thread_id,
        })

    # Apps use the normal review/popularity quality gate. Bundles/packages
    # usually have no standalone review object, so a strong non-app offer can
    # pass the normal PLUS path by editorial score instead of waiting for the
    # global fallback window.
    normal_app_ids = {
        g.game_id for g in to_enrich
        if g.store_type == "app"
        and steam.is_quality_game(g, cfg.steam_min_review_score, cfg.steam_min_review_count)
        and (g.waitlisted is None or g.waitlisted >= cfg.steam_min_waitlisted)
    }
    strong_nonapp_ids = {
        g.game_id
        for total, g, _r in all_scored
        if g.store_type != "app"
        and g.discount_percent >= cfg.steam_min_discount_percent
        and total >= getattr(cfg, "plus_editorial_min_score", 25)
    }
    eligible_ids = normal_app_ids | strong_nonapp_ids
    scored = [(total, g, r) for total, g, r in all_scored if g.game_id in eligible_ids]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.steam_max_posts_per_cycle]

    n_fetched = len(games)
    n_apps = sum(1 for g in games if g.store_type == "app")
    n_subs = sum(1 for g in games if g.store_type == "sub")
    n_bundles = sum(1 for g in games if g.store_type == "bundle")
    n_discount = len([g for g in games if g.discount_percent >= cfg.steam_min_discount_percent])
    n_not_seen = len([g for g in games if g.discount_percent >= cfg.steam_min_discount_percent and f"steam:{g.game_id}" not in seen])
    n_reviews_ok = sum(
        1 for g in to_enrich
        if steam.is_quality_game(g, cfg.steam_min_review_score, cfg.steam_min_review_count)
    )
    n_waitlist_ok = sum(
        1 for g in to_enrich
        if steam.is_quality_game(g, cfg.steam_min_review_score, cfg.steam_min_review_count)
        and (g.waitlisted is None or g.waitlisted >= cfg.steam_min_waitlisted)
    )
    n_nonapp_without_reviews = sum(
        1 for g in to_enrich
        if g.store_type != "app" and g.review_count is None
    )
    log.info(
        "[Steam] Encontrados: %d (apps=%d, packages=%d, bundles=%d) | "
        "Desconto>=%d%%: %d | Nao vistos: %d | Reviews OK: %d | "
        "Waitlist OK: %d | Bundle/package sem review: %d | Non-app editorial OK: %d | "
        "Scored: %d | Selecionados: %d",
        n_fetched, n_apps, n_subs, n_bundles,
        cfg.steam_min_discount_percent, n_discount, n_not_seen, n_reviews_ok,
        n_waitlist_ok, n_nonapp_without_reviews, len(strong_nonapp_ids), len(scored), len(selected),
    )

    if dry_run:
        for total, g, r in scored:
            log.info("  score %d | %d%% off | %s%% positivo | %s reviews | wl %s | %s", total, g.discount_percent, g.review_score, g.review_count, g.waitlisted, g.title[:50])
        return 0
    if not selected:
        return 0

    posted = 0
    for _score_val, game, _result in selected:
        game_link = _wrap_link(cfg, f"steam:{game.game_id}", game.permalink, "steam", game.title)
        text = telegram.format_game_deal(
            title=game.title,
            price=game.price,
            original_price=game.original_price,
            discount=game.discount_percent,
            link=game_link,
            lowest_price=game.lowest_price,
        )
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=cfg.telegram_steam_thread_id,
                image_url=game.header_image or None,
            )
        except httpx.HTTPError as exc:
            log.error("[Steam] envio '%s': %s", game.game_id, exc)
            continue

        mark_seen(seen, f"steam:{game.game_id}")
        posted += 1
        analytics.record_deal(
            source="steam",
            product_id=game.game_id,
            title=game.title,
            price=game.price,
            original_price=game.original_price,
            discount_percent=game.discount_percent,
            quality_score=_result.quality,
            conversion_score=_result.conversion,
            retention_score=_result.retention,
            confidence_score=_result.confidence,
            final_score=_result.final,
            history_confidence=_result.history_confidence,
            category="games",
            deal_type="plus",
            affiliate=False,
            action="published",
        )
        log.info("[Steam] postado: %d%% off | %s", game.discount_percent, game.title[:50])
        _check_alerts(cfg, alerts, game.title, game.price, "steam", game.permalink)
        if posted < len(selected):
            time.sleep(7)

    return posted


def run_gmg_cycle(cfg: Config, seen: set[str], alerts: dict[str, list[dict]], dry_run: bool) -> int:
    if not (cfg.cj_account_sid and cfg.cj_auth_token and cfg.gmg_program_id and cfg.gmg_catalog_id):
        # Integracao GMG/CJ ainda nao configurada (faltam credenciais ou IDs);
        # nao trata como erro, so pula o ciclo silenciosamente.
        return 0
    try:
        catalog_items = gmg_cj.fetch_catalog_items(
            cfg.cj_account_sid, cfg.cj_auth_token, cfg.gmg_catalog_id
        )
        promo_codes = gmg_cj.fetch_promo_codes(
            cfg.cj_account_sid, cfg.cj_auth_token, program_id=cfg.gmg_program_id
        )
    except httpx.HTTPError as exc:
        log.error("[GMG] %s", exc)
        return 0

    games = gmg_cj.parse_deals(catalog_items, promo_codes)

    current_ids = {f"gmg:{g.item_id}" for g in games if g.discount_percent > 0}
    stale = [s for s in seen if s.startswith("gmg:") and s not in current_ids]
    for s in stale:
        del seen[s]
    if stale:
        log.info("[GMG] %d jogo(s) saiu(ram) de promo, liberado(s) pra re-post.", len(stale))

    unseen_discounted = [
        g for g in games
        if g.discount_percent > 0 and f"gmg:{g.item_id}" not in seen
    ]
    candidates = [g for g in unseen_discounted if g.discount_percent >= cfg.gmg_min_discount_percent]
    candidates.sort(key=lambda g: g.discount_percent, reverse=True)

    all_scored_gmg = []
    for g in unseen_discounted:
        r = scoring.score_game(
            title=g.title,
            price=g.price,
            original_price=g.original_price,
            discount_percent=int(g.discount_percent),
            source="gmg",
        )
        all_scored_gmg.append((r.total, g, r))
        _plus_candidates.append({
            "score": r.total, "source": "gmg", "seen_key": f"gmg:{g.item_id}",
            "title": g.title, "price": g.price, "original_price": g.original_price,
            "discount_percent": int(g.discount_percent), "link": g.permalink,
            "lowest_price": None, "image_url": g.image_url, "game_id": g.item_id,
            "result": r, "thread_id": cfg.telegram_gmg_thread_id,
            "promo_code": g.promo_code, "promo_description": g.promo_description,
        })

    normal_ids = {g.item_id for g in candidates}
    scored_gmg = [(total, g, r) for total, g, r in all_scored_gmg if g.item_id in normal_ids]
    scored_gmg.sort(key=lambda x: x[0], reverse=True)
    selected = scored_gmg[: cfg.gmg_max_posts_per_cycle]

    n_fetched = len(games)
    n_discount = len([g for g in games if g.discount_percent >= cfg.gmg_min_discount_percent])
    log.info(
        "[GMG] Encontrados: %d | Desconto>=%d%%: %d | Nao vistos: %d | Scored: %d | Selecionados: %d",
        n_fetched, cfg.gmg_min_discount_percent, n_discount, len(candidates), len(scored_gmg), len(selected),
    )

    if dry_run:
        for total, g, r in scored_gmg:
            log.info("  score %d | %s%% | %s", total, g.discount_percent, g.title[:50])
        return 0
    if not selected:
        return 0

    posted = 0
    for _score_val, game, _gmg_result in selected:
        link = game.permalink
        if not link:
            log.warning("[GMG] sem link para %s", game.item_id)
            continue
        link = _wrap_link(cfg, f"gmg:{game.item_id}", link, "gmg", game.title)
        text = telegram.format_gmg_deal(
            title=game.title,
            price=game.price,
            original_price=game.original_price,
            discount=game.discount_percent,
            link=link,
            promo_code=game.promo_code,
            promo_description=game.promo_description,
        )
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=cfg.telegram_gmg_thread_id,
                image_url=game.image_url or None,
            )
        except httpx.HTTPError as exc:
            log.error("[GMG] envio '%s': %s", game.item_id, exc)
            continue

        mark_seen(seen, f"gmg:{game.item_id}")
        posted += 1
        analytics.record_deal(
            source="gmg",
            product_id=game.item_id,
            title=game.title,
            price=game.price,
            original_price=game.original_price,
            discount_percent=int(game.discount_percent),
            quality_score=_gmg_result.quality,
            conversion_score=_gmg_result.conversion,
            retention_score=_gmg_result.retention,
            confidence_score=_gmg_result.confidence,
            final_score=_gmg_result.final,
            history_confidence=_gmg_result.history_confidence,
            category="games",
            deal_type="plus",
            affiliate=False,
            action="published",
        )
        log.info("[GMG] postado: %s%% off | %s", game.discount_percent, game.title[:50])
        _check_alerts(cfg, alerts, game.title, game.price, "gmg", link)
        if posted < len(selected):
            time.sleep(7)

    return posted


def run_aliexpress_cycle(cfg: Config, seen: set[str], alerts: dict[str, list[dict]], dry_run: bool) -> int:
    if not (cfg.aliexpress_app_key and cfg.aliexpress_app_secret):
        return 0

    deals: list = []
    searches = cfg.aliexpress_searches or [("", "")]
    seen_ids: set[str] = set()
    for kw, cat in searches:
        try:
            batch = aliexpress.fetch_deals(
                cfg.aliexpress_app_key,
                cfg.aliexpress_app_secret,
                cfg.aliexpress_tracking_id,
                keywords=kw,
                category_ids=cat,
                page_size=20,
            )
            for d in batch:
                if d.product_id not in seen_ids:
                    seen_ids.add(d.product_id)
                    deals.append(d)
        except (RuntimeError, httpx.HTTPError) as exc:
            log.error("[Ali] %s: %s", kw, exc)
            continue

    current_ids = {f"ali:{d.product_id}" for d in deals if d.discount_percent > 0}
    stale = [s for s in seen if s.startswith("ali:") and s not in current_ids]
    for s in stale:
        del seen[s]
    if stale:
        log.info("[Ali] %d produto(s) saiu(ram) de promo, liberado(s) pra re-post.", len(stale))

    candidates = [
        d
        for d in deals
        if d.discount_percent >= cfg.aliexpress_min_discount_percent
        and f"ali:{d.product_id}" not in seen
    ]

    deduped: dict[str, aliexpress.AliDeal] = {}
    for d in candidates:
        key = scoring._normalize(d.title)[:60]
        existing = deduped.get(key)
        if existing is None or d.price < existing.price:
            deduped[key] = d
    candidates = list(deduped.values())

    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    scored_ali = []
    promotion_count = 0
    for d in candidates:
        cat = scoring.category_match(d.title)
        promos = promotion_engine.promotions_for_item(
            catalog, "aliexpress", d.title, d.price
        )
        promo_eval = promotion_engine.evaluate_price(d.price, promos, title=d.title)
        display_promo = promo_eval.display_promotion
        if display_promo:
            promotion_count += 1
        r = scoring.score_aliexpress(
            title=d.title,
            price=d.price,
            original_price=d.original_price,
            discount_percent=d.discount_percent,
            sales_count=d.sales_count,
            commission_rate=d.commission_rate,
            effective_price=promo_eval.scoring_price,
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_code=(
                display_promo.code
                if display_promo and promo_eval.best_guaranteed
                else ""
            ),
        )
        scored_ali.append((r.total, d, r, cat, promo_eval))
    scored_ali.sort(key=lambda x: x[0], reverse=True)
    selected = scored_ali[: cfg.aliexpress_max_posts_per_cycle]

    log.info(
        "[Ali] Encontrados: %d | Candidatos: %d | Com promocao configurada: %d | Selecionados: %d",
        len(deals), len(scored_ali), promotion_count, len(selected),
    )

    if dry_run:
        log.info(
            "[Ali][dry-run] %d oferta(s) aprovada(s) de %d com %d%%+ off.",
            len(selected), len(scored_ali), cfg.aliexpress_min_discount_percent,
        )
        for total, d, r, cat, promo_eval in scored_ali:
            promo = promo_eval.display_promotion
            promo_text = ""
            if promo_eval.guaranteed_savings > 0:
                promo_text = f" | cupom {promo.code or '-'} -> R${promo_eval.scoring_price:.2f}"
            elif promo:
                promo_text = " | promo condicional"
            log.info(
                "  score %d | %d%% | %d vendas%s | %s",
                total, d.discount_percent, d.sales_count, promo_text, d.title[:50],
            )
        return 0
    if not selected:
        return 0

    posted = 0
    for _score_val, deal, _ali_result, _ali_cat, promo_eval in selected:
        ali_link = _wrap_link(
            cfg, f"ali:{deal.product_id}", deal.permalink, "aliexpress", deal.title
        )
        text = telegram.format_aliexpress_deal(
            title=deal.title,
            price=deal.price,
            original_price=deal.original_price,
            discount=deal.discount_percent,
            link=ali_link,
            commission_rate=deal.commission_rate,
            sales_count=deal.sales_count,
            promotion=promo_eval,
        )
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=cfg.telegram_aliexpress_thread_id,
                image_url=deal.image_url or None,
            )
        except httpx.HTTPError as exc:
            log.error("[Ali] envio '%s': %s", deal.product_id, exc)
            continue

        mark_seen(seen, f"ali:{deal.product_id}")
        posted += 1
        display_promo = promo_eval.display_promotion
        effective_price = promo_eval.scoring_price
        analytics.record_deal(
            source="aliexpress",
            product_id=deal.product_id,
            title=deal.title,
            price=effective_price,
            listed_price=deal.price,
            original_price=deal.original_price,
            discount_percent=(
                round((deal.original_price - effective_price) / deal.original_price * 100)
                if deal.original_price and deal.original_price > effective_price
                else deal.discount_percent
            ),
            quality_score=_ali_result.quality,
            conversion_score=_ali_result.conversion,
            retention_score=_ali_result.retention,
            confidence_score=_ali_result.confidence,
            final_score=_ali_result.final,
            history_confidence=_ali_result.history_confidence,
            category=_ali_cat,
            deal_type="commercial",
            affiliate=True,
            action="published",
            promotion_code=display_promo.code if display_promo else "",
            promotion_savings=promo_eval.guaranteed_savings,
            promotion_conditional=bool(display_promo and display_promo.conditional),
        )
        if promo_eval.guaranteed_savings > 0:
            log.info(
                "[Ali][cupom %s] postado: %.2f -> %.2f | %s",
                display_promo.code if display_promo else "",
                deal.price, effective_price, deal.title[:50],
            )
        else:
            log.info("[Ali] postado: %d%% off | %s", deal.discount_percent, deal.title[:50])
        _check_alerts(cfg, alerts, deal.title, effective_price, "aliexpress", deal.permalink)
        if posted < len(selected):
            time.sleep(7)

    return posted


def run_nuuvem_cycle(cfg: Config, seen: set[str], alerts: dict[str, list[dict]], dry_run: bool) -> int:
    if not cfg.itad_api_key:
        return 0
    try:
        deals = nuuvem.fetch_deals(cfg.itad_api_key)
    except (RuntimeError, httpx.HTTPError) as exc:
        log.error("[Nuuvem] %s", exc)
        return 0

    current_ids = {f"nuuvem:{d.game_id}" for d in deals if d.discount_percent > 0}
    stale = [s for s in seen if s.startswith("nuuvem:") and s not in current_ids]
    for s in stale:
        del seen[s]
    if stale:
        log.info("[Nuuvem] %d jogo(s) saiu(ram) de promo, liberado(s) pra re-post.", len(stale))

    candidates = [
        d
        for d in deals
        if d.discount_percent >= cfg.nuuvem_min_discount_percent
        and f"nuuvem:{d.game_id}" not in seen
    ]

    candidates.sort(key=lambda d: d.discount_percent, reverse=True)
    to_enrich = candidates[:60]
    nuuvem.enrich_with_popularity(cfg.itad_api_key, to_enrich)

    all_scored = []
    for d in to_enrich:
        r = scoring.score_game(
            title=d.title,
            price=d.price,
            original_price=d.original_price,
            discount_percent=d.discount_percent,
            source="nuuvem",
            review_score=d.review_score,
            review_count=d.review_count,
            lowest_price=d.lowest_price,
            waitlisted=d.waitlisted,
        )
        all_scored.append((r.total, d, r))
        _plus_candidates.append({
            "score": r.total, "source": "nuuvem", "seen_key": f"nuuvem:{d.game_id}",
            "title": d.title, "price": d.price, "original_price": d.original_price,
            "discount_percent": d.discount_percent, "link": d.permalink,
            "lowest_price": d.lowest_price, "image_url": d.image_url,
            "game_id": d.game_id, "result": r, "thread_id": cfg.telegram_nuuvem_thread_id,
            "coupon_code": d.coupon.code if d.coupon else None,
            "coupon_discount": d.coupon.discount if d.coupon else None,
        })

    eligible_ids = {d.game_id for d in to_enrich if nuuvem.is_most_wanted(d, cfg.nuuvem_min_waitlisted)}
    candidates = [d for d in to_enrich if d.game_id in eligible_ids]
    scored = [(total, d, r) for total, d, r in all_scored if d.game_id in eligible_ids]
    scored.sort(key=lambda x: x[0], reverse=True)
    selected = scored[: cfg.nuuvem_max_posts_per_cycle]

    n_fetched = len(deals)
    n_discount = len([d for d in deals if d.discount_percent >= cfg.nuuvem_min_discount_percent])
    n_not_seen = len([d for d in deals if d.discount_percent >= cfg.nuuvem_min_discount_percent and f"nuuvem:{d.game_id}" not in seen])
    n_waitlisted = len(candidates)
    log.info(
        "[Nuuvem] Encontrados: %d | Desconto>=%d%%: %d | Nao vistos: %d | Waitlisted>=%d: %d | Scored: %d | Selecionados: %d",
        n_fetched, cfg.nuuvem_min_discount_percent, n_discount, n_not_seen, cfg.nuuvem_min_waitlisted, n_waitlisted, len(scored), len(selected),
    )

    if dry_run:
        for total, d, r in scored:
            log.info("  score %d | %d%% | %s na waitlist | %s", total, d.discount_percent, d.waitlisted, d.title[:50])
        return 0
    if not selected:
        return 0

    posted = 0
    for _score_val, deal, _result in selected:
        nuuvem_link = _wrap_link(cfg, f"nuuvem:{deal.game_id}", deal.permalink, "nuuvem", deal.title)
        text = telegram.format_nuuvem_deal(
            title=deal.title,
            price=deal.price,
            original_price=deal.original_price,
            discount=deal.discount_percent,
            link=nuuvem_link,
            lowest_price=deal.lowest_price,
            coupon_code=deal.coupon.code if deal.coupon else None,
            coupon_discount=deal.coupon.discount if deal.coupon else None,
        )
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=cfg.telegram_nuuvem_thread_id,
                image_url=deal.image_url or None,
            )
        except httpx.HTTPError as exc:
            log.error("[Nuuvem] envio '%s': %s", deal.game_id, exc)
            continue

        mark_seen(seen, f"nuuvem:{deal.game_id}")
        posted += 1
        analytics.record_deal(
            source="nuuvem",
            product_id=deal.game_id,
            title=deal.title,
            price=deal.price,
            original_price=deal.original_price,
            discount_percent=deal.discount_percent,
            quality_score=_result.quality,
            conversion_score=_result.conversion,
            retention_score=_result.retention,
            confidence_score=_result.confidence,
            final_score=_result.final,
            history_confidence=_result.history_confidence,
            category="games",
            deal_type="plus",
            affiliate=False,
            action="published",
        )
        log.info("[Nuuvem] postado: %d%% off | %s", deal.discount_percent, deal.title[:50])
        _check_alerts(cfg, alerts, deal.title, deal.price, "nuuvem", deal.permalink)
        if posted < len(selected):
            time.sleep(7)

    return posted


def _last_plus_publish_hours_ago() -> float:
    entries = analytics.load_entries(limit=200)
    now = datetime.now(timezone.utc)
    for e in reversed(entries):
        if e.get("deal_type") == "plus" and e.get("action") == "published":
            try:
                ts = datetime.fromisoformat(e["timestamp"])
                return (now - ts).total_seconds() / 3600
            except (KeyError, ValueError):
                continue
    return 999.0


def run_plus_fallback(cfg: Config, seen: dict[str, str], alerts: dict[str, list[dict]], dry_run: bool) -> int:
    """Publishes at most one strong PLUS candidate when the normal PLUS
    pipelines have been silent for a configured period.

    The candidate pool is collected by the Steam/Nuuvem/GMG cycles before
    their stricter normal gates.  The fallback never bypasses seen/cooldown
    and still requires PLUS_EDITORIAL_MIN_SCORE.
    """
    hours_ago = _last_plus_publish_hours_ago()
    if hours_ago < cfg.plus_editorial_hours_without:
        log.info(
            "[PLUS] Fallback nao necessario: ultima publicacao ha %.1fh (janela %dh).",
            hours_ago, cfg.plus_editorial_hours_without,
        )
        return 0

    eligible = [
        c for c in _plus_candidates
        if c.get("seen_key") not in seen
        and c.get("link")
        and c.get("score", 0) >= cfg.plus_editorial_min_score
    ]
    if not eligible:
        best = max((c.get("score", 0) for c in _plus_candidates if c.get("seen_key") not in seen), default=None)
        if best is None:
            log.info("[PLUS] Nenhuma publicacao: nenhum candidato editorial elegivel neste ciclo.")
        else:
            log.info(
                "[PLUS] Nenhuma publicacao: melhor score %.1f abaixo do minimo editorial %d.",
                best, cfg.plus_editorial_min_score,
            )
        return 0

    candidate = max(eligible, key=lambda c: c.get("score", 0))
    log.info(
        "[PLUS] Fallback editorial candidato: %s | %s | score %.1f | minimo %d",
        candidate["source"], candidate["title"][:60], candidate["score"],
        cfg.plus_editorial_min_score,
    )
    if dry_run:
        log.info("[PLUS][dry-run] Fallback editorial nao enviado.")
        return 0

    source = candidate["source"]
    link = _wrap_link(
        cfg, candidate["seen_key"], candidate["link"], source, candidate["title"]
    )
    if source == "steam":
        text = telegram.format_game_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            lowest_price=candidate.get("lowest_price"),
        )
    elif source == "nuuvem":
        text = telegram.format_nuuvem_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            lowest_price=candidate.get("lowest_price"),
            coupon_code=candidate.get("coupon_code"),
            coupon_discount=candidate.get("coupon_discount"),
        )
    elif source == "gmg":
        text = telegram.format_gmg_deal(
            title=candidate["title"], price=candidate["price"],
            original_price=candidate["original_price"],
            discount=candidate["discount_percent"], link=link,
            promo_code=candidate.get("promo_code"),
            promo_description=candidate.get("promo_description"),
        )
    else:
        log.warning("[PLUS] Fonte de fallback desconhecida: %s", source)
        return 0

    try:
        telegram.send_message(
            cfg.telegram_bot_token, cfg.telegram_channel_id, text,
            thread_id=candidate.get("thread_id"),
            image_url=candidate.get("image_url") or None,
        )
    except httpx.HTTPError as exc:
        log.error("[PLUS] falha no fallback '%s': %s", candidate["title"][:50], exc)
        return 0

    mark_seen(seen, candidate["seen_key"])
    result = candidate["result"]
    analytics.record_deal(
        source=source,
        product_id=str(candidate["game_id"]),
        title=candidate["title"],
        price=candidate["price"],
        original_price=candidate["original_price"],
        discount_percent=int(candidate["discount_percent"]),
        quality_score=result.quality,
        conversion_score=result.conversion,
        retention_score=result.retention,
        confidence_score=result.confidence,
        final_score=result.final,
        history_confidence=result.history_confidence,
        category="games", deal_type="plus", affiliate=False,
        action="published", action_reason="plus_editorial_fallback",
    )
    log.info(
        "[PLUS] Fallback editorial publicado: %s | %s | score %.1f",
        source, candidate["title"][:60], candidate["score"],
    )
    _check_alerts(cfg, alerts, candidate["title"], candidate["price"], source, candidate["link"])
    return 1



def _campaign_thread_id(cfg: Config, source: str) -> int | None:
    source = source.lower()
    if source == "aliexpress":
        return cfg.telegram_aliexpress_thread_id
    if source == "steam":
        return cfg.telegram_steam_thread_id
    if source == "nuuvem":
        return cfg.telegram_nuuvem_thread_id
    if source == "gmg":
        return cfg.telegram_gmg_thread_id
    return cfg.telegram_thread_id


def run_promotion_campaigns(cfg: Config, dry_run: bool) -> int:
    if not cfg.promotion_campaign_notices_enabled:
        return 0
    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    if not catalog:
        return 0
    state = promotion_engine.load_state()
    due = promotion_engine.due_campaigns(catalog, state)
    if not due:
        return 0

    if dry_run:
        for campaign in due:
            log.info(
                "[Promo][dry-run] campanha pronta para aviso: %s | %s",
                campaign.get("source", ""), campaign.get("title", ""),
            )
        return 0

    posted = 0
    for campaign in due:
        campaign_id = str(campaign.get("id", "")).strip()
        source = str(campaign.get("source", "")).lower()
        text = telegram.format_campaign_notice(campaign)
        try:
            telegram.send_message(
                cfg.telegram_bot_token,
                cfg.telegram_channel_id,
                text,
                thread_id=_campaign_thread_id(cfg, source),
            )
        except httpx.HTTPError as exc:
            log.error("[Promo] falha ao avisar campanha '%s': %s", campaign_id, exc)
            continue
        promotion_engine.mark_campaign_announced(state, campaign_id)
        posted += 1
        log.info("[Promo] campanha avisada: %s | %s", source, campaign.get("title", ""))
    return posted

def _digest_product_key(title: str) -> str:
    # Mesma ideia da consolidacao do feed: produtos com o mesmo titulo
    # normalizado disputam uma unica vaga no TOP.
    return scoring._normalize(title)[:80]


def _build_digest_items(entries: list[dict], max_items: int) -> list[dict]:
    # Consolida o mesmo produto entre varios ciclos do dia. Se ele apareceu
    # mais de uma vez, fica a menor oferta; em empate, a de maior qualidade.
    best_by_product: dict[str, dict] = {}
    for entry in entries:
        title = str(entry.get("title", ""))
        key = _digest_product_key(title)
        if not key:
            continue
        current = best_by_product.get(key)
        price = float(entry.get("price", 0) or 0)
        quality = float(entry.get("quality_score", 0) or 0)
        if current is None:
            best_by_product[key] = entry
            continue
        current_price = float(current.get("price", 0) or 0)
        current_quality = float(current.get("quality_score", 0) or 0)
        if price < current_price or (price == current_price and quality > current_quality):
            best_by_product[key] = entry

    ranked = sorted(
        best_by_product.values(),
        key=lambda e: e.get("quality_score") or 0,
        reverse=True,
    )
    return [
        {
            "title": e.get("title", ""),
            "price": e.get("price", 0),
            "source": e.get("source", ""),
            "link": "",
        }
        for e in ranked[:max_items]
    ]


def run_digest(cfg: Config, dry_run: bool, last_digest_date: str) -> str:
    now = datetime.now(timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")

    # Protecao em memoria (mesmo processo) + persistente (reinicios).
    if today == last_digest_date:
        return last_digest_date
    state = digest_store.load_state()
    if digest_store.already_sent_today(state, today):
        log.info("[Digest] TOP de hoje ja foi enviado; ignorando novo disparo.")
        return today
    if now.hour < cfg.digest_hour:
        return last_digest_date
    if not cfg.digest_enabled:
        return today

    entries = analytics.load_entries()
    today_entries = [
        e for e in entries
        if e.get("timestamp", "").startswith(today)
        and e.get("action") == "published"
    ]
    if not today_entries:
        log.info("[Digest] Nenhuma oferta publicada hoje.")
        return today

    items = _build_digest_items(today_entries, cfg.digest_max_items)
    if not items:
        log.info("[Digest] Nenhum item elegivel para o TOP de hoje.")
        return today

    content_hash = digest_store.digest_hash(items)
    if state.get("last_digest_hash") == content_hash and state.get("last_sent_date") == today:
        log.info("[Digest] Conteudo identico ao TOP ja enviado hoje; ignorando.")
        return today

    if dry_run:
        log.info("[Digest][dry-run] %d itens no digest. Nao enviado.", len(items))
        return today

    text = telegram.format_digest(items)
    try:
        telegram.send_message(
            cfg.telegram_bot_token,
            cfg.telegram_channel_id,
            text,
            thread_id=cfg.telegram_thread_id,
        )
        # Salva somente depois do Telegram confirmar o envio. Assim falha de
        # rede nao marca falsamente o digest como publicado.
        digest_store.mark_sent(state, today, content_hash)
        log.info("[Digest] TOP OFERTAS DO DIA enviado com %d itens e estado persistido.", len(items))
    except httpx.HTTPError as exc:
        log.error("[Digest] falha ao enviar: %s", exc)
        return last_digest_date

    return today


def main() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Evita que URLs com token/chave apareçam no bot.log via logging interno
    # do httpx/httpcore. Erros do projeto continuam sendo registrados.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)

    if not _acquire_single_instance_lock():
        log.critical("Outra instancia do bot ja esta rodando. Saindo.")
        sys.exit(0)

    cfg = Config()
    errors = cfg.validate()
    if errors:
        log.critical("Configuracao invalida:")
        for e in errors:
            log.critical("  - %s", e)
        log.critical("Copie .env.example para .env e preencha.")
        sys.exit(1)

    once = "--once" in sys.argv
    dry_run = "--dry-run" in sys.argv
    seen = load_seen()
    history = price_history.load_history()
    published_deals = ds.load_deals()
    alerts = alert_store.load_alerts()
    global _click_links
    _click_links = click_tracker.load_links()
    last_digest_date = ""
    last_update_id = 0

    if cfg.click_tracking_enabled and not dry_run:
        click_server.start(cfg.click_server_port, _click_links)

    expired = expire_plus(seen)
    if expired:
        log.info("[Seen] %d jogo(s) PLUS expirados (>7 dias), liberados pra re-post.", expired)
        save_seen(seen)

    log.info(
        "Bot iniciado. Score minimo: %d. Historico minimo: %d. Click tracking: %s.",
        cfg.score_min, cfg.min_history_observations,
        "ON" if cfg.click_tracking_enabled else "OFF",
    )

    while True:
        last_update_id = bot_commands.poll_commands(
            cfg.telegram_bot_token, alerts, last_update_id,
            admin_chat_id=cfg.telegram_admin_chat_id,
        )
        _plus_candidates.clear()
        posted = run_promotion_campaigns(cfg, dry_run)
        posted += run_cycle(cfg, seen, history, published_deals, alerts, dry_run)
        save_seen(seen)
        ds.save_deals(published_deals)
        steam_posted = run_steam_cycle(cfg, seen, alerts, dry_run)
        posted += steam_posted
        save_seen(seen)
        gmg_posted = run_gmg_cycle(cfg, seen, alerts, dry_run)
        posted += gmg_posted
        save_seen(seen)
        posted += run_aliexpress_cycle(cfg, seen, alerts, dry_run)
        save_seen(seen)
        nuuvem_posted = run_nuuvem_cycle(cfg, seen, alerts, dry_run)
        posted += nuuvem_posted
        save_seen(seen)

        plus_posted = steam_posted + gmg_posted + nuuvem_posted
        if plus_posted == 0:
            posted += run_plus_fallback(cfg, seen, alerts, dry_run)
            save_seen(seen)
        price_history.save_history(history)
        last_digest_date = run_digest(cfg, dry_run, last_digest_date)
        log.info("Ciclo concluido. %d ofertas postadas.", posted)
        if once or dry_run:
            break
        time.sleep(cfg.poll_interval_seconds)


if __name__ == "__main__":
    main()
