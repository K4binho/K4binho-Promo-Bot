"""Digest diário "TOP OFERTAS DO DIA", publicado no tópico Melhores do Dia.

Consolida o mesmo produto entre vários ciclos do dia e protege contra envio
duplicado por dois caminhos: memória do processo e estado persistido.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone

import httpx

from k4promo import telegram
from k4promo.domain.topics import MELHORES_DO_DIA
from k4promo.services import analytics, scoring
from k4promo.services.context import CycleContext
from k4promo.services.router import topic_thread_id
from k4promo.storage import digest_store

log = logging.getLogger("k4binho")


def _product_key(title: str) -> str:
    # Mesma ideia da consolidação do feed: produtos com o mesmo título
    # normalizado disputam uma única vaga no TOP.
    return scoring._normalize(title)[:80]


def build_items(entries: list[dict], max_items: int) -> list[dict]:
    """Consolida o dia: mesmo produto fica com a menor oferta; empate decide
    pela maior qualidade."""
    best_by_product: dict[str, dict] = {}
    for entry in entries:
        key = _product_key(str(entry.get("title", "")))
        if not key:
            continue
        current = best_by_product.get(key)
        if current is None:
            best_by_product[key] = entry
            continue
        price = float(entry.get("price", 0) or 0)
        quality = float(entry.get("quality_score", 0) or 0)
        current_price = float(current.get("price", 0) or 0)
        current_quality = float(current.get("quality_score", 0) or 0)
        if price < current_price or (price == current_price and quality > current_quality):
            best_by_product[key] = entry

    ranked = sorted(best_by_product.values(),
                    key=lambda e: e.get("quality_score") or 0, reverse=True)
    return [
        {"title": e.get("title", ""), "price": e.get("price", 0),
         "source": e.get("source", ""), "link": ""}
        for e in ranked[:max_items]
    ]


def run(ctx: CycleContext, last_digest_date: str) -> str:
    """Envia o digest se for hora. Devolve a data corrente do controle."""
    cfg = ctx.cfg
    now = datetime.now(timezone.utc).astimezone()
    today = now.strftime("%Y-%m-%d")

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

    today_entries = [
        e for e in analytics.load_entries()
        if e.get("timestamp", "").startswith(today) and e.get("action") == "published"
    ]
    if not today_entries:
        log.info("[Digest] Nenhuma oferta publicada hoje.")
        return today

    items = build_items(today_entries, cfg.digest_max_items)
    if not items:
        log.info("[Digest] Nenhum item elegivel para o TOP de hoje.")
        return today

    content_hash = digest_store.digest_hash(items)
    if state.get("last_digest_hash") == content_hash and state.get("last_sent_date") == today:
        log.info("[Digest] Conteudo identico ao TOP ja enviado hoje; ignorando.")
        return today

    if ctx.dry_run:
        log.info("[Digest][dry-run] %d itens no digest. Nao enviado.", len(items))
        return today

    try:
        telegram.send_message(
            cfg.telegram_bot_token, cfg.telegram_channel_id,
            telegram.format_digest(items),
            thread_id=topic_thread_id(cfg, MELHORES_DO_DIA),
        )
        # Só marca como enviado depois da confirmação do Telegram, para uma
        # falha de rede não bloquear o digest do dia.
        digest_store.mark_sent(state, today, content_hash)
        log.info("[Digest] TOP OFERTAS DO DIA enviado com %d itens e estado persistido.", len(items))
    except httpx.HTTPError as exc:
        log.error("[Digest] falha ao enviar: %s", exc)
        return last_digest_date

    return today
