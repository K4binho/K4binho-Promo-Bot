"""Roteamento de publicações: (loja, título) → tópico → thread do Telegram.

Separa duas decisões que costumam ser confundidas:

- **qual tópico** a oferta pertence (regra de produto, depende da loja e do
  título);
- **qual thread** do fórum corresponde a esse tópico (configuração).
"""

from __future__ import annotations

from k4promo.domain.topics import (
    ACHADINHOS, GAME_STORES, JOGOS, MELHORES_DO_DIA, store_allowed, store_key,
)
from k4promo.services.categorizer import classify_title


def resolve_topic(source: str, title: str) -> str:
    """Decide o tópico de publicação para uma oferta.

    - lojas de jogos → Jogos em Promoção;
    - lojas físicas → classificação por título; sem match → Achadinhos;
    - loja não permitida no tópico classificado → Achadinhos.
    """
    store = store_key(source)
    if store in GAME_STORES:
        return JOGOS
    topic = classify_title(title) or ACHADINHOS
    if topic == JOGOS or not store_allowed(topic, store):
        topic = ACHADINHOS
    return topic


def topic_thread_id(cfg, topic: str) -> int | None:
    """Thread do tópico. Aceita ``Config`` real ou objetos simples (testes).

    Um tópico desativado (0 no ``.env``) cai no thread geral.
    """
    resolver = getattr(cfg, "topic_thread_id", None)
    if callable(resolver):
        return resolver(topic)
    ids = getattr(cfg, "telegram_topic_ids", None) or {}
    value = ids.get(topic)
    return value if value is not None else getattr(cfg, "telegram_thread_id", None)


def campaign_thread_id(cfg, source: str) -> int | None:
    """Avisos de campanha: lojas de jogos vão para Jogos; campanhas de lojas
    físicas (ex.: evento AliExpress) são vitrine e vão para Melhores do Dia."""
    if store_key(source) in GAME_STORES:
        return topic_thread_id(cfg, JOGOS)
    return topic_thread_id(cfg, MELHORES_DO_DIA)
