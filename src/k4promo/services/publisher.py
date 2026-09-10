"""Preparação e publicação de uma oferta."""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from typing import Any

import httpx

from k4promo import telegram
from k4promo.commands import admin as bot_commands
from k4promo.domain.models import Offer
from k4promo.services import analytics, click_server, link_validation, showcase
from k4promo.services.context import CycleContext
from k4promo.services.router import topic_thread_id
from k4promo.storage import alert_store, click_store, deal_store as ds
from k4promo.storage.seen_store import mark_seen

log = logging.getLogger("k4binho")

PACE_SECONDS = 7


@dataclass
class Publisher:
    """Publica ofertas de um ciclo, no contexto desse ciclo."""

    ctx: CycleContext
    last_message_id: int | None = field(default=None, init=False, repr=False)
    last_thread_id: int | None = field(default=None, init=False, repr=False)

    @property
    def cfg(self):
        return self.ctx.cfg

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
        previous_message: tuple[int | None, int | None] | None = None,
    ) -> bool:
        """Publica oferta e registra efeitos compartilhados."""
        effective = offer.price if price is None else price
        key = seen_key or offer.key
        thread_id = topic_thread_id(self.cfg, topic)

        if link_validation.is_blocked(link):
            log.info(
                "[%s] link invalido (404/410), nao publicado: %s",
                log_tag, offer.offer_id,
            )
            return False

        with self.ctx.lock:
            if not self.ctx.worker_is_current():
                log.info("[%s] worker atrasado ignorado: %s", log_tag, offer.title[:60])
                return False

            title_key = ds.normalize_title(offer.title)
            is_republish = previous_message is not None or key in self.ctx.republish_keys
            key = self.ctx.republish_keys.get(key, key)
            if is_republish and previous_message is None:
                previous_entry = self.ctx.published_deals.get(key, {})
                if previous_entry.get("message_id") is not None:
                    previous_message = (
                        previous_entry["message_id"],
                        previous_entry.get("thread_id"),
                    )
            identity = (offer.source, title_key or f"__key__:{key}")
            existing_title = ds.find_by_normalized_title(
                self.ctx.published_deals, offer.source, title_key
            ) if title_key else None

            if not is_republish and (
                key in self.ctx.seen
                or (existing_title is not None and existing_title[0] != key)
            ):
                log.info("[%s] duplicado ignorado: %s", log_tag, offer.title[:60])
                return False
            if not self.ctx.reserve_publication(identity, key):
                log.info("[%s] reserva duplicada ignorada: %s", log_tag, offer.title[:60])
                return False

            if previous_message and previous_message[0] is not None:
                try:
                    telegram.delete_message(
                        self.cfg.telegram_bot_token,
                        self.cfg.telegram_channel_id,
                        previous_message[0],
                    )
                except Exception as exc:
                    log.warning("[%s] falha ao apagar post anterior: %s", log_tag, exc)

            try:
                message_id = telegram.send_message(
                    self.cfg.telegram_bot_token,
                    self.cfg.telegram_channel_id,
                    text,
                    thread_id=thread_id,
                    image_url=offer.image_url or None,
                )
            except httpx.HTTPError as exc:
                self.ctx.release_publication(identity)
                log.error("[%s] envio '%s': %s", log_tag, offer.offer_id, exc)
                return False
            except Exception:
                self.ctx.release_publication(identity)
                raise

            self.last_message_id = message_id
            self.last_thread_id = thread_id
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
                offer.title,
                effective,
                offer.source,
                alert_link or link,
                product_id=offer.offer_id,
            )
            return True

    @staticmethod
    def pace(posted: int, total: int) -> None:
        """Espaça publicações consecutivas da mesma fonte."""
        if posted < total:
            time.sleep(PACE_SECONDS)
