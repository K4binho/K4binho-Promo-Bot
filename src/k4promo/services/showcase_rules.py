"""Critérios de elegibilidade da vitrine "Melhores do Dia".

A vitrine não coleta: ela copia publicações que já saíram em outros tópicos.
Este módulo decide *se* uma publicação merece a cópia e com que prioridade.
"""

from __future__ import annotations

from dataclasses import dataclass

from k4promo.domain.topics import (
    GAME_STORES, MELHORES_DO_DIA, PHYSICAL_STORES, SHOWCASE_EDITORIAL_STORES,
    STORE_TOPIC_PRIORITY, store_key, store_rank,
)

@dataclass
class ShowcaseVerdict:
    eligible: bool
    reasons: list[str]
    priority: int  # menor = melhor (rank da loja)


def showcase_eligible(
    source: str,
    *,
    price: float,
    discount_percent: int = 0,
    sales_count: int = 0,
    coupon_savings: float = 0.0,
    free_shipping: bool = False,
    lowest_price: bool = False,
    rating: float | None = None,
    review_score: int | None = None,
    has_image: bool = False,
    min_physical_discount: int = 40,
    min_game_discount: int = 70,
) -> ShowcaseVerdict:
    """Aplica os critérios da vitrine.

    Produto físico: desconto real >= ``min_physical_discount``, cupom
    relevante ou menor preço registrado contam como critério forte; alto
    volume de vendas e frete grátis são critérios de apoio (precisam de dois).

    Jogo: gratuito ou desconto >= ``min_game_discount``. Steam/Nuuvem só com
    forte valor editorial (gratuito, ou desconto alto + review >= 85 ou
    menor preço histórico).

    Em todos os casos exige imagem adequada e reputação não negativa.
    """
    store = store_key(source)
    reasons: list[str] = []
    rank = store_rank(MELHORES_DO_DIA, store)
    if store in SHOWCASE_EDITORIAL_STORES:
        rank = len(STORE_TOPIC_PRIORITY[MELHORES_DO_DIA]) + 1

    if not has_image:
        return ShowcaseVerdict(False, ["sem imagem adequada"], rank)
    if rating is not None and rating < 4.0:
        return ShowcaseVerdict(False, [f"reputacao baixa ({rating:.1f})"], rank)

    if store in GAME_STORES:
        is_free = price <= 0
        big_discount = discount_percent >= min_game_discount
        if is_free:
            reasons.append("jogo gratuito")
        if big_discount:
            reasons.append(f"jogo com {discount_percent}% off")
        if not (is_free or big_discount):
            return ShowcaseVerdict(False, ["jogo sem desconto excepcional"], rank)
        if store in SHOWCASE_EDITORIAL_STORES and not is_free:
            editorial = (review_score is not None and review_score >= 85) or lowest_price
            if not editorial:
                return ShowcaseVerdict(False, ["steam/nuuvem sem forte valor editorial"], rank)
            reasons.append("forte valor editorial")
        return ShowcaseVerdict(True, reasons, rank)

    if store not in PHYSICAL_STORES:
        return ShowcaseVerdict(False, [f"loja fora da vitrine ({store})"], rank)

    strong = 0
    soft = 0
    if discount_percent >= min_physical_discount:
        strong += 1
        reasons.append(f"desconto real {discount_percent}%")
    if coupon_savings > 0 and price > 0 and coupon_savings / price >= 0.05:
        strong += 1
        reasons.append(f"cupom relevante (R$ {coupon_savings:.0f})")
    if lowest_price:
        strong += 1
        reasons.append("menor preco registrado")
    if sales_count >= 1000:
        soft += 1
        reasons.append(f"alto volume ({sales_count} vendas)")
    if free_shipping:
        soft += 1
        reasons.append("frete gratis")

    if strong >= 1 or soft >= 2:
        return ShowcaseVerdict(True, reasons, rank)
    return ShowcaseVerdict(False, reasons or ["sem criterio de vitrine"], rank)
