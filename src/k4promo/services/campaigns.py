"""Avisos únicos de campanhas promocionais descritas em ``promotions.json``.

Campanha de loja de jogos vai para o tópico Jogos; as demais são vitrine e vão
para Melhores do Dia. Cada campanha é anunciada uma vez só, controlada por
``promotion_state.json``.
"""

from __future__ import annotations

import logging

import httpx

from k4promo import telegram
from k4promo.services import promotions as promotion_engine
from k4promo.services.context import CycleContext
from k4promo.services.router import campaign_thread_id

log = logging.getLogger("k4binho")


def run(ctx: CycleContext) -> int:
    cfg = ctx.cfg
    if not cfg.promotion_campaign_notices_enabled:
        return 0
    catalog = promotion_engine.load_catalog(cfg.promotions_file)
    if not catalog:
        return 0
    state = promotion_engine.load_state()
    due = promotion_engine.due_campaigns(catalog, state)
    if not due:
        return 0

    if ctx.dry_run:
        for campaign in due:
            log.info("[Promo][dry-run] campanha pronta para aviso: %s | %s",
                     campaign.get("source", ""), campaign.get("title", ""))
        return 0

    posted = 0
    for campaign in due:
        campaign_id = str(campaign.get("id", "")).strip()
        source = str(campaign.get("source", "")).lower()
        try:
            telegram.send_message(
                cfg.telegram_bot_token, cfg.telegram_channel_id,
                telegram.format_campaign_notice(campaign),
                thread_id=campaign_thread_id(cfg, source),
            )
        except httpx.HTTPError as exc:
            log.error("[Promo] falha ao avisar campanha '%s': %s", campaign_id, exc)
            continue
        promotion_engine.mark_campaign_announced(state, campaign_id)
        posted += 1
        log.info("[Promo] campanha avisada: %s | %s", source, campaign.get("title", ""))
    return posted
