"""Camada Telegram: envio (``client``) e layout das mensagens (``formatters``).

O pacote reexporta a superfície pública dos dois módulos para que o restante
do código escreva ``telegram.send_message(...)`` e ``telegram.format_deal(...)``
sem precisar saber em qual arquivo cada função mora.
"""

from k4promo.telegram.client import MESSAGE_URL, PHOTO_URL, send_message
from k4promo.telegram.formatters import (
    format_aliexpress_deal,
    format_campaign_notice,
    format_deal,
    format_digest,
    format_game_deal,
    format_gmg_deal,
    format_kabum_deal,
    format_nuuvem_deal,
    format_price_drop,
    format_shopee_deal,
    format_showcase_copy,
)

__all__ = [
    "MESSAGE_URL",
    "PHOTO_URL",
    "send_message",
    "format_aliexpress_deal",
    "format_campaign_notice",
    "format_deal",
    "format_digest",
    "format_game_deal",
    "format_gmg_deal",
    "format_kabum_deal",
    "format_nuuvem_deal",
    "format_price_drop",
    "format_shopee_deal",
    "format_showcase_copy",
]
