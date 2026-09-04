"""Preparação e publicação de uma oferta.

Concentra a sequência que antes estava repetida em todos os ciclos: embrulhar o
link no tracking, enviar ao tópico certo, marcar como visto, oferecer a
publicação à vitrine, gravar analytics e disparar alertas dos usuários.

Trabalha sobre ``Offer``, então não precisa saber de qual loja a oferta veio.
Os campos que dependem da loja (categoria, tipo de deal, cupom aplicado) chegam
por ``analytics_kwargs`` e ``showcase_kwargs``, que sobrescrevem os defaults
derivados da própria oferta.

A publicação nunca levanta exceção de rede: falha de envio é registrada e
devolve ``False``, para o ciclo seguir com as demais ofertas.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from typing import Any

import httpx

from k4promo import telegram
from k4promo.commands import admin as bot_commands
from k4promo.domain.models import Offer
from k4promo.services import analytics, click_server, showcase
from k4promo.services.context import CycleContext
from k4promo.services.router import topic_thread_id
from k4promo.storage import alert_store, click_store
from k4promo.storage.seen_store import mark_seen

log = logging.getLogger("k4binho")

# Espaçamento mínimo entre duas publicações da mesma fonte.
PACE_SECONDS = 7


@dataclass
class Publisher:
    """Publica ofertas de um ciclo, no contexto desse ciclo."""

    ctx: CycleContext

    @property
    def cfg(self):
        return self.ctx.cfg

    # -- links -------------------------------------------------------------

    def wrap_link(self, deal_id: str, destination: str, source: str, title: str) -> str:
        """Aplica o redirect de tracking quando ele está habilitado."""
        if not self.cfg.click_tracking_enabled:
            return destination
        click_store.register_link(
            self.ctx.click_links, deal_id, destination, source=source, title=title
        )
        click_store.save_links(self.ctx.click_links)
        return click_server.tracking_url(self.cfg.click_base_url, deal_id)

    def affiliate_link(self, offer: Offer, destination: str | None = None) -> str:
        """Link final da oferta, já com tracking quando habilitado."""
        return self.wrap_link(
            offer.key, destination or offer.permalink, offer.source, offer.title
        )

    # -- alertas -----------------------------------------------------------

    def check_alerts(
        self, title: str, price: float, source: str, link: str, product_id: str = ""
    ) -> None:
        matches = alert_store.match_deal(
            self.ctx.alerts, title, price, source, product_id=product_id
        )
        for chat_id, alert in matches:
            bot_commands.notify_alert_match(
                self.cfg.telegram_bot_token, chat_id, alert, title, price, link
            )
        if matches:
            alert_store.save_alerts(self.ctx.alerts)

    # -- publicação --------------------------------------------------------

    def publish(
        self,
        offer: Offer,
        *,
        topic: str,
        text: str,
        result: Any,
        score: float,
        link: str,
        log_tag: str,
        price: float | None = None,
        seen_key: str | None = None,
        showcase_key: str | None = None,
        analytics_kwargs: dict | None = None,
        showcase_kwargs: dict | None = None,
        alert_link: str | None = None,
    ) -> bool:
        """Publica uma oferta já formatada e registra todos os efeitos.

        ``price`` é o preço efetivo (pós-cupom) quando ele difere do preço
        listado da oferta.
        """
        effective = offer.price if price is None else price
        key = seen_key or offer.key

        try:
            telegram.send_message(
                self.cfg.telegram_bot_token,
                self.cfg.telegram_channel_id,
                text,
                thread_id=topic_thread_id(self.cfg, topic),
                image_url=offer.image_url or None,
            )
        except httpx.HTTPError as exc:
            log.error("[%s] envio '%s': %s", log_tag, offer.offer_id, exc)
            return False

        mark_seen(self.ctx.seen, key)

        showcase_fields = {
            "discount_percent": offer.discount_percent,
            "sales_count": offer.sales_count,
            "rating": offer.rating,
            "free_shipping": offer.free_shipping,
            "review_score": offer.review_score,
            "lowest_price": bool(
                offer.lowest_price is not None and effective <= offer.lowest_price
            ),
        }
        showcase_fields.update(showcase_kwargs or {})
        showcase.register(
            self.ctx,
            key=showcase_key or key,
            source=offer.source,
            topic=topic,
            score=score,
            text=text,
            image_url=offer.image_url,
            price=effective,
            **showcase_fields,
        )

        analytics_fields = {
            "source": offer.source,
            "topic": topic,
            "product_id": offer.offer_id,
            "title": offer.title,
            "price": effective,
            "original_price": offer.original_price,
            "discount_percent": offer.discount_percent,
            "quality_score": result.quality,
            "conversion_score": result.conversion,
            "retention_score": result.retention,
            "confidence_score": result.confidence,
            "final_score": result.final,
            "history_confidence": result.history_confidence,
            "action": "published",
        }
        analytics_fields.update(analytics_kwargs or {})
        analytics.record_deal(**analytics_fields)

        self.check_alerts(
            offer.title, effective, offer.source,
            alert_link or link, product_id=offer.offer_id,
        )
        return True

    @staticmethod
    def pace(posted: int, total: int) -> None:
        """Espaça publicações consecutivas da mesma fonte."""
        if posted < total:
            time.sleep(PACE_SECONDS)
