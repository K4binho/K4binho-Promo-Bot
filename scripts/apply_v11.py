from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

def r(p): return (ROOT / p).read_text(encoding='utf-8')
def w(p, s): (ROOT / p).write_text(s, encoding='utf-8')
def rep(s, old, new, label):
    c = s.count(old)
    if c != 1: raise RuntimeError(f'{label}: esperado 1, encontrado {c}')
    return s.replace(old, new, 1)
def between(s,start,end,new,label):
    i=s.find(start); j=s.find(end,i+len(start))
    if i<0 or j<0: raise RuntimeError(f'{label}: marcadores ausentes')
    return s[:i]+new+s[j:]

def patch_promotion_engine():
    p='promotion_engine.py'; s=r(p)
    a='def promotion_from_dict(data: dict) -> Promotion:\n    allowed = set(Promotion.__dataclass_fields__)\n    clean = {k: v for k, v in data.items() if k in allowed}\n    return Promotion(**clean)\n'
    s=rep(s,a,a+'\n\ndef promotion_fingerprint(promo: Promotion | None) -> str:\n    if promo is None: return ""\n    parts=(promo.source,promo.kind,promo.code.strip().upper(),round(float(promo.discount_amount or 0),2),round(float(promo.discount_percent or 0),4),round(float(promo.minimum_spend or 0),2),round(float(promo.max_discount or 0),2),bool(promo.selected_users_only),bool(promo.app_only),bool(promo.requires_coins))\n    return "|".join(str(v) for v in parts)\n','fingerprint')
    old='def get_cached_promotions(cache: dict, key: str, max_age_hours: int) -> list[Promotion] | None:\n    entry = cache.get(key)\n    if not isinstance(entry, dict):\n        return None\n    checked_at = _parse_datetime(str(entry.get("checked_at", "")))\n    if checked_at is None:\n        return None\n    if datetime.now(UTC) - checked_at > timedelta(hours=max(1, max_age_hours)):\n        return None\n    raw_promos = entry.get("promotions", [])\n    if not isinstance(raw_promos, list):\n        return []\n    promos = []\n    for raw in raw_promos:\n        if isinstance(raw, dict):\n            try:\n                promos.append(promotion_from_dict(raw))\n            except (TypeError, ValueError):\n                continue\n    return promos\n'
    new='def get_cached_promotions(cache: dict, key: str, max_age_hours: int, promotion_max_age_hours: int | None = None) -> list[Promotion] | None:\n    entry = cache.get(key)\n    if not isinstance(entry, dict): return None\n    checked_at = _parse_datetime(str(entry.get("checked_at", "")))\n    if checked_at is None: return None\n    raw_promos = entry.get("promotions", [])\n    if not isinstance(raw_promos, list): raw_promos=[]\n    ttl = promotion_max_age_hours if raw_promos and promotion_max_age_hours is not None else max_age_hours\n    if datetime.now(UTC) - checked_at > timedelta(hours=max(1, ttl)): return None\n    promos=[]\n    for raw in raw_promos:\n        if isinstance(raw, dict):\n            try: promos.append(promotion_from_dict(raw))\n            except (TypeError, ValueError): continue\n    return promos\n'
    s=rep(s,old,new,'cache ttl'); w(p,s)

def patch_deal_store():
    p='deal_store.py'; s=r(p)
    s=rep(s,'from datetime import UTC, datetime\n','from datetime import UTC, datetime, timedelta\n','timedelta')
    old='def record_published(deals: dict[str, dict], item_id: str, price: float) -> None:\n    deals[item_id] = {\n        "price": round(price, 2),\n        "posted_at": datetime.now(UTC).isoformat(),\n    }\n'
    new='''def record_published(deals: dict[str, dict], item_id: str, price: float, *, promotion_signature: str = "") -> None:\n    deals[item_id] = {"price": round(price, 2), "posted_at": datetime.now(UTC).isoformat(), "promotion_signature": promotion_signature}\n\n\ndef check_promotion_revival(deals: dict[str, dict], item_id: str, current_price: float, promotion_signature: str, *, min_drop_percent: float = 5.0, min_drop_amount: float = 20.0, cooldown_hours: int = 6, now: datetime | None = None) -> tuple[bool, float | None]:\n    entry=deals.get(item_id)\n    if not entry or not promotion_signature: return False, None\n    if str(entry.get("promotion_signature","") or "") == promotion_signature: return False, None\n    try: previous=float(entry.get("price"))\n    except (TypeError, ValueError): return False, None\n    if previous <= 0 or current_price >= previous: return False, previous\n    raw=str(entry.get("posted_at","") or "")\n    if raw:\n        try:\n            posted=datetime.fromisoformat(raw)\n            if posted.tzinfo is None: posted=posted.replace(tzinfo=UTC)\n            current=now or datetime.now(UTC)\n            if current-posted.astimezone(UTC) < timedelta(hours=max(0,cooldown_hours)): return False, previous\n        except ValueError: pass\n    amount=previous-current_price; pct=(amount/previous)*100\n    return (pct >= min_drop_percent or amount >= min_drop_amount), previous\n'''
    s=rep(s,old,new,'revival'); w(p,s)

def patch_playwright():
    p='ml_playwright.py'; s=r(p)
    start='def _promotion_text_from_page(page) -> str:\n'; end='def generate_links(\n'
    new=r'''def _promotion_text_from_page(page) -> str:
    return page.evaluate("""() => { const root=document.querySelector('main')||document.body; return root ? (root.innerText||'') : ''; }""") or ""

_PROMO_TRIGGER_WORDS=("cupom","cupons","ver cupom","ver cupons","aplicar cupom","usar cupom","beneficio","benefícios","beneficios","desconto","resgatar")
_BLOCKED_TRIGGER_WORDS=("comprar","finalizar","checkout","carrinho","pagar","adicionar ao carrinho")
def _is_safe_promo_trigger(text: str) -> bool:
    norm=" ".join((text or "").lower().split())
    return bool(norm and len(norm)<=180 and not any(w in norm for w in _BLOCKED_TRIGGER_WORDS) and any(w in norm for w in _PROMO_TRIGGER_WORDS))
def _expand_promotion_elements(page, max_clicks: int = 4) -> int:
    candidates=page.locator("button, a, [role='button'], summary")
    try: count=min(candidates.count(),100)
    except Exception: return 0
    clicked=0; seen=set()
    for idx in range(count):
        if clicked>=max_clicks: break
        item=candidates.nth(idx)
        try: text=(item.inner_text(timeout=350) or "").strip()
        except Exception: continue
        norm=" ".join(text.lower().split())
        if norm in seen or not _is_safe_promo_trigger(text): continue
        seen.add(norm)
        try:
            if not item.is_visible(timeout=250): continue
            item.click(timeout=900); page.wait_for_timeout(450); clicked += 1
        except Exception: continue
    return clicked
def discover_promotions(product_urls: list[str]) -> dict[str, list[promotion_engine.Promotion]]:
    if not product_urls: return {}
    if not USER_DATA_DIR.exists(): raise NotLoggedIn("Sem sessao. Rode: python login_ml.py")
    results={}
    with sync_playwright() as p:
        ctx=_launch(p,headless=False); page=ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            for i,url in enumerate(product_urls):
                try:
                    page.goto(url,wait_until="domcontentloaded"); page.wait_for_timeout(2300 if i==0 else 1000)
                    if i==0 and not _cookie(ctx,"ssid"): raise NotLoggedIn("Sessao expirou. Rode: python login_ml.py")
                    before=_promotion_text_from_page(page); _expand_promotion_elements(page); after=_promotion_text_from_page(page)
                    results[url]=promotion_engine.parse_mercadolivre_text(before if after==before else f"{before}\n{after}")
                except NotLoggedIn: raise
                except Exception: results[url]=[]
        finally: ctx.close()
    return results

'''
    s=between(s,start,end,new,'playwright'); w(p,s)

def patch_bot():
    p='bot.py'; s=r(p); marker='def _ml_promotions_for_deals(\n'
    helpers='''def _ml_signal_points(deal, *, is_best_seller: bool, is_trending: bool, guaranteed_promotion: bool) -> int:\n    points=0; sales=int(getattr(deal,"sales_count",0) or 0); rating=float(getattr(deal,"rating",0) or 0)\n    if is_best_seller: points += 2\n    if is_trending: points += 1\n    if bool(getattr(deal,"official_store",False)): points += 1\n    if sales >= 5000: points += 2\n    elif sales >= 500: points += 1\n    if rating >= 4.7 and sales >= 100: points += 1\n    if guaranteed_promotion: points += 2\n    return points\n\n\ndef _ml_commercial_fallback_eligible(result, *, has_price_evidence: bool, signal_points: int, already_seen: bool, guaranteed_promotion: bool, score_min: int) -> bool:\n    if already_seen or not has_price_evidence or signal_points < 2: return False\n    if result.quality < 35 or result.conversion < 25 or result.confidence < 25: return False\n    return guaranteed_promotion or result.total >= max(45, score_min - 25)\n\n\n'''
    s=s.replace(marker,helpers+marker,1)
    new=r'''def _ml_promotions_for_deals(cfg: Config, deals: list, best_sellers: set[str], trends: list[str], seen, dry_run: bool) -> tuple[dict[str, list[promotion_engine.Promotion]], dict[str, int]]:
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


'''
    s=between(s,marker,'def run_cycle(\n',new,'bot scan')
    s=rep(s,'    promotion_map, promotion_scanned = _ml_promotions_for_deals(\n        cfg, deals, best_sellers, trends, seen, dry_run\n    )\n','    promotion_map, promotion_scan_stats = _ml_promotions_for_deals(\n        cfg, deals, best_sellers, trends, seen, dry_run\n    )\n','assignment')
    old='''        sales_count = int(getattr(deal, "sales_count", 0) or 0)\n        rating = float(getattr(deal, "rating", 0) or 0)\n        official_store = bool(getattr(deal, "official_store", False))\n        strong_commercial_signal = (\n            is_best_seller\n            or is_trending\n            or official_store\n            or sales_count >= 500\n            or rating >= 4.7\n            or promo_eval.guaranteed_savings > 0\n        )\n'''
    s=rep(s,old,'        signal_points = _ml_signal_points(deal, is_best_seller=is_best_seller, is_trending=is_trending, guaranteed_promotion=promo_eval.guaranteed_savings > 0)\n        strong_commercial_signal = signal_points >= 2\n','signal')
    old='''        commercial_fallback = (\n            not strict_approved\n            and has_price_evidence\n            and deal.item_id not in seen\n            and not history_ready\n            and result.total >= commercial_floor\n            and strong_commercial_signal\n        )\n'''
    s=rep(s,old,'        commercial_fallback = (not strict_approved and _ml_commercial_fallback_eligible(result, has_price_evidence=has_price_evidence, signal_points=signal_points, already_seen=deal.item_id in seen, guaranteed_promotion=promo_eval.guaranteed_savings > 0, score_min=cfg.score_min))\n','fallback')
    s=rep(s,'        "coupon_codes": 0,\n    }\n    commercial_fallback_ids: set[str] = set()\n','        "coupon_codes": 0,\n        "promotion_revival": 0,\n    }\n    commercial_fallback_ids: set[str] = set()\n    promotion_revival_ids: set[str] = set()\n','stats')
    old='''        if not approved and deal.item_id in seen:\n            current_effective = promo_eval.scoring_price\n            is_drop, prev_price = ds.check_price_drop(\n                published_deals, deal.item_id, current_effective\n            )\n            if is_drop:\n                log.info(\n                    "[ML][price-drop] %s caiu de %.2f para %.2f",\n                    deal.title[:40], prev_price, current_effective,\n                )\n                candidates.append((\n                    result.total + 20, deal, result, historical_min,\n                    historical_avg, prev_price, promo_eval,\n                ))\n'''
    new='''        if not approved and deal.item_id in seen:\n            current_effective = promo_eval.scoring_price\n            sig = promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed)\n            is_revival, prev_price = ds.check_promotion_revival(published_deals, deal.item_id, current_effective, sig, min_drop_percent=cfg.ml_promo_revival_min_drop_percent, min_drop_amount=cfg.ml_promo_revival_min_drop_amount, cooldown_hours=cfg.ml_promo_revival_cooldown_hours)\n            if is_revival:\n                promotion_revival_ids.add(deal.item_id); ml_stats["promotion_revival"] += 1\n                log.info("[ML][promo-revival] %s | %.2f -> %.2f", deal.title[:45], prev_price, current_effective)\n                candidates.append((result.total + 25, deal, result, historical_min, historical_avg, prev_price, promo_eval))\n            else:\n                is_drop, prev_price = ds.check_price_drop(published_deals, deal.item_id, current_effective)\n                if is_drop:\n                    log.info("[ML][price-drop] %s caiu de %.2f para %.2f", deal.title[:40], prev_price, current_effective)\n                    candidates.append((result.total + 20, deal, result, historical_min, historical_avg, prev_price, promo_eval))\n'''
    s=rep(s,old,new,'revival')
    old='''        "Promocao: %d | Codigos: %d | Scaneados: %d | "\n        "Aprovados estritos: %d | Fallback comercial: %d | "\n        "Candidatos: %d | Selecionados: %d",\n        ml_stats["found"], ml_stats["price_ok"], ml_stats["history_ready"],\n        ml_stats["launch_ok"], ml_stats["strong_signal"], ml_stats["already_seen"],\n        ml_stats["with_promotion"], ml_stats["coupon_codes"], promotion_scanned,\n        ml_stats["strict_approved"], ml_stats["commercial_fallback"],\n        len(candidates), len(selected),\n'''
    new='''        "Promocao: %d | Codigos: %d | Promo scan elegiveis: %d | Promo cache: %d | Scaneados: %d | Promo encontradas: %d | Vistos reescaneados: %d | Aprovados estritos: %d | Fallback comercial: %d | Reativados por promocao: %d | Candidatos: %d | Selecionados: %d",\n        ml_stats["found"], ml_stats["price_ok"], ml_stats["history_ready"], ml_stats["launch_ok"], ml_stats["strong_signal"], ml_stats["already_seen"], ml_stats["with_promotion"], ml_stats["coupon_codes"], promotion_scan_stats["eligible"], promotion_scan_stats["cache_hits"], promotion_scan_stats["scanned"], promotion_scan_stats["found"], promotion_scan_stats["seen_scanned"], ml_stats["strict_approved"], ml_stats["commercial_fallback"], ml_stats["promotion_revival"], len(candidates), len(selected),\n'''
    s=rep(s,old,new,'log')
    s=rep(s,'            "[ML] Fallback comercial ativo: score minimo %d + sinal forte + preco OK + sem historico completo.\",\n            commercial_floor,\n','            "[ML] Fallback comercial ativo: preco OK + sinais independentes + guardrails de qualidade/conversao/confianca.\",\n','fallback log')
    s=rep(s,'            action = "price_drop"\n','            action = "promotion_revival" if deal.item_id in promotion_revival_ids else "price_drop"\n','action')
    s=rep(s,'        ds.record_published(published_deals, deal.item_id, effective_price)\n','        ds.record_published(published_deals, deal.item_id, effective_price, promotion_signature=promotion_engine.promotion_fingerprint(promo_eval.best_guaranteed))\n','record')
    s=s.replace('    commercial_floor = max(60, cfg.score_min - 10)\n',''); w(p,s)

def main():
    patch_promotion_engine(); patch_deal_store(); patch_playwright(); patch_bot(); print('Promotion Engine V1.1 aplicado')
if __name__=='__main__': main()
