from collections import deque
from html import escape
import threading
import time

import httpx

import promotion_engine

MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
PHOTO_URL = "https://api.telegram.org/bot{token}/sendPhoto"


class TelegramRateLimiter:
    """Limitador thread-safe por chat e para o total de mensagens."""

    def __init__(
        self,
        chat_interval_seconds: float = 1.0,
        global_messages_per_second: int = 30,
        *,
        clock=time.monotonic,
        sleeper=time.sleep,
    ) -> None:
        self._lock = threading.Lock()
        self._clock = clock
        self._sleep = sleeper
        self._next_by_chat: dict[str, float] = {}
        self._global_sends: deque[float] = deque()
        self.configure(chat_interval_seconds, global_messages_per_second)

    def configure(
        self,
        chat_interval_seconds: float,
        global_messages_per_second: int,
    ) -> None:
        if chat_interval_seconds < 0:
            raise ValueError("chat_interval_seconds deve ser >= 0")
        if global_messages_per_second < 1:
            raise ValueError("global_messages_per_second deve ser >= 1")
        with self._lock:
            self.chat_interval_seconds = chat_interval_seconds
            self.global_messages_per_second = global_messages_per_second
            self._next_by_chat.clear()
            self._global_sends.clear()

    def wait(self, chat_id: str) -> None:
        chat_key = str(chat_id)
        while True:
            with self._lock:
                now = self._clock()
                while self._global_sends and now - self._global_sends[0] >= 1.0:
                    self._global_sends.popleft()

                chat_wait = max(0.0, self._next_by_chat.get(chat_key, 0.0) - now)
                global_wait = 0.0
                if len(self._global_sends) >= self.global_messages_per_second:
                    global_wait = max(0.0, self._global_sends[0] + 1.0 - now)
                wait_for = max(chat_wait, global_wait)
                if wait_for <= 0:
                    self._next_by_chat[chat_key] = now + self.chat_interval_seconds
                    self._global_sends.append(now)
                    return
            self._sleep(wait_for)


_rate_limiter = TelegramRateLimiter()


def configure_rate_limits(
    chat_interval_seconds: float = 1.0,
    global_messages_per_second: int = 30,
) -> None:
    _rate_limiter.configure(chat_interval_seconds, global_messages_per_second)


def send_message(token: str, channel_id: str, text: str,
                 thread_id: int | None = None,
                 image_url: str | None = None) -> None:
    if image_url:
        url = PHOTO_URL.format(token=token)
        payload = {
            "chat_id": channel_id,
            "photo": image_url,
            "caption": text,
            "parse_mode": "HTML",
        }
    else:
        url = MESSAGE_URL.format(token=token)
        payload = {
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    _rate_limiter.wait(str(channel_id))
    resp = httpx.post(url, json=payload, timeout=30)
    resp.raise_for_status()


def _format_price_brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _price_block(price: float, original_price: float | None, discount: int) -> list[str]:
    lines = []
    if original_price and discount > 0:
        economia = original_price - price
        lines.append(f"De: <s>{_format_price_brl(original_price)}</s>")
        lines.append(f"Por: <b>{_format_price_brl(price)}</b>")
        lines.append(f"<b>{discount}% OFF</b> · Economize {_format_price_brl(economia)}")
    else:
        lines.append(f"<b>{_format_price_brl(price)}</b>")
    return lines


def _history_block(
    price: float,
    min_price_30d: float | None,
    avg_price_30d: float | None,
    history_confidence: str,
) -> list[str]:
    if history_confidence == "low":
        return []
    lines = []
    if min_price_30d is not None and price <= min_price_30d and history_confidence == "high":
        lines.append("🏆 <b>Menor preço que monitoramos</b>")
    elif avg_price_30d is not None and price < avg_price_30d:
        diff = avg_price_30d - price
        lines.append(f"📉 {_format_price_brl(diff)} abaixo da média recente")
    return lines


def _deal_header(
    discount: int,
    is_lowest_price: bool,
    history_confidence: str,
) -> str:
    if is_lowest_price and history_confidence == "high":
        return "🏆 <b>MENOR PREÇO MONITORADO</b>"
    if discount >= 50:
        return "🔥 <b>OFERTA DESTAQUE</b>"
    return "🔥 <b>OFERTA</b>"



def _promotion_lines(evaluation: promotion_engine.PriceEvaluation | None) -> list[str]:
    if evaluation is None:
        return []
    promo = evaluation.display_promotion
    if promo is None:
        return []

    lines: list[str] = []
    if evaluation.best_guaranteed and evaluation.guaranteed_savings > 0:
        lines.append(
            f"🎟️ Com promoção: <b>{_format_price_brl(evaluation.guaranteed_price)}</b> "
            f"(economize {_format_price_brl(evaluation.guaranteed_savings)})"
        )
    elif evaluation.best_conditional and evaluation.potential_savings > 0:
        lines.append(
            f"🎟️ Pode chegar a <b>{_format_price_brl(evaluation.potential_price)}</b> "
            f"com condição promocional"
        )

    if promo.code:
        lines.append(f"🎟️ Cupom: <code>{escape(promo.code)}</code>")
    elif promo.discount_amount and not evaluation.best_guaranteed:
        lines.append(f"🎟️ Desconto de até {_format_price_brl(promo.discount_amount)}")

    conditions: list[str] = []
    if promo.minimum_spend > 0:
        conditions.append(f"compra mínima {_format_price_brl(promo.minimum_spend)}")
    if promo.selected_users_only:
        conditions.append("apenas usuários selecionados")
    if promo.app_only:
        conditions.append("somente no app")
    if promo.requires_coins:
        conditions.append("requer moedas")
    if conditions:
        lines.append("⚠️ " + " · ".join(conditions))
    if promo.rescue_url:
        lines.append(f'<a href="{escape(promo.rescue_url)}">RESGATAR CUPONS</a>')
    return lines

def format_deal(
    title: str, price: float, original_price: float | None,
    discount: int, link: str,
    sales_count: int = 0, rating: float | None = None,
    official_store: bool = False, offer_label: str = "",
    coupon_amount: float | None = None,
    min_price_30d: float | None = None,
    avg_price_30d: float | None = None,
    history_confidence: str = "low",
    promotion: promotion_engine.PriceEvaluation | None = None,
) -> str:
    comparison_price = promotion.scoring_price if promotion is not None else price
    effective_discount = discount
    if original_price and original_price > comparison_price:
        effective_discount = round((original_price - comparison_price) / original_price * 100)
    is_lowest = (
        min_price_30d is not None
        and comparison_price <= min_price_30d
        and history_confidence == "high"
    )

    header = _deal_header(effective_discount, is_lowest, history_confidence)
    lines = [header, ""]
    lines.append(f"📦 <b>{escape(title)}</b>")
    lines.append("")

    lines.extend(_price_block(price, original_price, discount))

    promo_lines = _promotion_lines(promotion)
    if promo_lines:
        lines.extend(promo_lines)
    elif coupon_amount:
        lines.append(f"🎟️ Cupom de {_format_price_brl(coupon_amount)} disponível")

    hist = _history_block(comparison_price, min_price_30d, avg_price_30d, history_confidence)
    if hist:
        lines.append("")
        lines.extend(hist)

    selos = []
    if offer_label:
        selos.append(f"⚡ {escape(offer_label)}")
    if official_store:
        selos.append("✅ Loja oficial")
    if rating:
        selos.append(f"⭐ {rating:.1f}")
    if sales_count >= 1000:
        selos.append(f"🛒 {sales_count // 1000}mil+ vendidos")
    elif sales_count > 0:
        selos.append(f"🛒 {sales_count}+ vendidos")
    if selos:
        lines.append("")
        lines.append(" · ".join(selos))

    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER OFERTA</a>")
    return "\n".join(lines)


def format_game_deal(
    title: str, price: float, original_price: float | None,
    discount: int, link: str,
    lowest_price: float | None = None,
    source: str = "STEAM",
) -> str:
    lines = [f"🎮 <b>PLUS • {escape(source.upper())}</b>", ""]
    lines.append(f"🕹️ <b>{escape(title)}</b>")
    lines.append("")

    lines.extend(_price_block(price, original_price, discount))

    if lowest_price is not None:
        lines.append("")
        if price <= lowest_price:
            lines.append("🏆 <b>Menor preço histórico!</b>")
        else:
            lines.append(f"📉 Menor preço já registrado: {_format_price_brl(lowest_price)}")

    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER NA {escape(source.upper())}</a>")
    return "\n".join(lines)


def format_nuuvem_deal(
    title: str, price: float, original_price: float | None,
    discount: int, link: str,
    lowest_price: float | None = None,
    coupon_code: str | None = None,
    coupon_discount: str | None = None,
) -> str:
    lines = ["🎮 <b>PLUS • NUUVEM</b>", ""]
    lines.append(f"🕹️ <b>{escape(title)}</b>")
    lines.append("")

    lines.extend(_price_block(price, original_price, discount))

    if coupon_code:
        desc = f" ({coupon_discount})" if coupon_discount else ""
        lines.append(f"🎟️ Cupom: <code>{escape(coupon_code)}</code>{desc}")

    if lowest_price is not None:
        lines.append("")
        if price <= lowest_price:
            lines.append("🏆 <b>Menor preço histórico!</b>")
        else:
            lines.append(f"📉 Menor preço já registrado: {_format_price_brl(lowest_price)}")

    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER NA NUUVEM</a>")
    return "\n".join(lines)


def format_aliexpress_deal(
    title: str, price: float, original_price: float | None,
    discount: int, link: str,
    commission_rate: float = 0,
    sales_count: int = 0,
    promotion: promotion_engine.PriceEvaluation | None = None,
) -> str:
    lines = ["🛍️ <b>ALIEXPRESS</b>", ""]
    lines.append(f"📦 <b>{escape(title)}</b>")
    lines.append("")

    lines.extend(_price_block(price, original_price, discount))
    promo_lines = _promotion_lines(promotion)
    if promo_lines:
        lines.extend(promo_lines)

    selos = []
    if sales_count >= 1000:
        selos.append(f"🛒 {sales_count // 1000}mil+ vendidos")
    elif sales_count > 0:
        selos.append(f"🛒 {sales_count}+ vendidos")
    if selos:
        lines.append("")
        lines.append(" · ".join(selos))

    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER OFERTA</a>")
    return "\n".join(lines)



def format_shopee_deal(
    title: str,
    price: float,
    link: str,
    promotion: promotion_engine.PriceEvaluation | None = None,
) -> str:
    lines = ["🛍️ <b>SHOPEE</b>", "", f"📦 <b>{escape(title)}</b>", ""]
    lines.append(f"💰 <b>{_format_price_brl(price)}</b>")
    promo_lines = _promotion_lines(promotion)
    if promo_lines:
        lines.extend(promo_lines)
    lines.append("")
    lines.append(f'<a href="{escape(link)}">VER OFERTA</a>')
    return "\n".join(lines)


def format_campaign_notice(campaign: dict) -> str:
    source = str(campaign.get("source", "PROMO")).upper()
    title = str(campaign.get("title", "Campanha promocional"))
    starts_label = str(campaign.get("starts_label", "")).strip()
    lines = [f"⏰ <b>EVENTO • {escape(source)}</b>", "", f"🔥 <b>{escape(title)}</b>"]
    if starts_label:
        lines.append(f"🕒 {escape(starts_label)}")

    description = str(campaign.get("description", "")).strip()
    if description:
        lines.extend(["", escape(description)])

    coupons = campaign.get("coupons", [])
    if isinstance(coupons, list) and coupons:
        lines.extend(["", "🎟️ <b>Cupons:</b>"])
        for raw in coupons:
            if not isinstance(raw, dict):
                continue
            code = escape(str(raw.get("code", "")).strip())
            amount = raw.get("discount_amount")
            percent = raw.get("discount_percent")
            minimum = raw.get("minimum_spend")
            desc_parts = []
            if amount:
                desc_parts.append(f"{_format_price_brl(float(amount))} OFF")
            elif percent:
                desc_parts.append(f"{float(percent):g}% OFF")
            if minimum:
                desc_parts.append(f"em {_format_price_brl(float(minimum))}")
            desc = " ".join(desc_parts)
            if code:
                lines.append(f"• <code>{code}</code> — {escape(desc)}")

    landing = str(campaign.get("landing_url", "")).strip()
    coins = str(campaign.get("coins_url", "")).strip()
    if landing:
        lines.extend(["", f'<a href="{escape(landing)}">VER CAMPANHA</a>'])
    if coins:
        lines.append(f'<a href="{escape(coins)}">COLETAR MOEDAS</a>')
    return "\n".join(lines)

def format_price_drop(
    title: str, price: float, previous_price: float,
    link: str,
    promotion: promotion_engine.PriceEvaluation | None = None,
) -> str:
    drop = previous_price - price
    lines = ["⬇️ <b>CAIU MAIS!</b>", ""]
    lines.append(f"📦 <b>{escape(title)}</b>")
    lines.append("")
    lines.append(f"Antes: <s>{_format_price_brl(previous_price)}</s>")
    lines.append(f"Agora: <b>{_format_price_brl(price)}</b>")
    lines.append(f"{_format_price_brl(drop)} mais barato desde nosso último alerta")
    promo_lines = _promotion_lines(promotion)
    if promo_lines:
        lines.extend(promo_lines)
    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER NOVO PREÇO</a>")
    return "\n".join(lines)


def format_gmg_deal(
    title: str, price: float, original_price: float | None,
    discount: int, link: str,
    promo_code: str | None = None,
    promo_description: str | None = None,
) -> str:
    lines = ["🎮 <b>PLUS • GREEN MAN GAMING</b>", ""]
    lines.append(f"🕹️ <b>{escape(title)}</b>")
    lines.append("")

    lines.extend(_price_block(price, original_price, discount))

    if promo_code:
        desc = f" — {escape(promo_description)}" if promo_description else ""
        lines.append(f"🎟️ Cupom: <code>{escape(promo_code)}</code>{desc}")

    lines.append("")
    lines.append(f"<a href=\"{escape(link)}\">VER OFERTA</a>")
    return "\n".join(lines)


def _truncate(text: str, max_len: int = 50) -> str:
    if len(text) <= max_len:
        return text
    return text[: max_len - 1].rsplit(" ", 1)[0] + "…"


def format_digest(items: list[dict]) -> str:
    lines = ["🏆 <b>TOP OFERTAS DO DIA</b>", ""]
    for i, item in enumerate(items, 1):
        title = escape(_truncate(item["title"]))
        price = _format_price_brl(item["price"])
        discount = item.get("discount_percent", 0)
        source = item.get("source", "").upper()
        tag = f" · {source}" if source else ""
        disc = f" ({discount}% OFF)" if discount else ""
        link = escape(item.get("link", ""))
        if link:
            lines.append(f"{i}. <a href=\"{link}\">{title}</a>")
        else:
            lines.append(f"{i}. {title}")
        lines.append(f"   <b>{price}</b>{disc}{tag}")
        lines.append("")
    return "\n".join(lines)
