"""Modelo padronizado de oferta.

Cada provider continua com o seu próprio dataclass de parsing: é ele que espelha
o formato bruto de cada API e é ele que os testes de parser cobrem. O que este
módulo define é a forma **única** que o restante do sistema consome, para que
filtrar, pontuar, rotear, publicar e deduplicar não precisem saber de qual loja
a oferta veio nem como aquela loja chama cada campo.

A conversão fica em ``k4promo.providers.adapters``, um adaptador por loja.

``Offer`` é deliberadamente um superconjunto: carrega tanto os sinais de produto
físico (vendas, avaliação, frete) quanto os de jogo (menor preço histórico,
review, waitlist). Uma loja preenche o que tem e deixa o resto no default, o que
mantém as funções de portão (``steam.is_quality_game``, ``nuuvem.is_most_wanted``)
e o scoring funcionando sobre a oferta normalizada.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class Offer:
    """Oferta normalizada.

    ``source`` usa o nome curto interno ("ml", "shopee", "ali", "kabum", "gmg",
    "steam", "nuuvem"), o mesmo que já vai para o analytics e que
    ``domain.topics.store_key`` entende.
    """

    source: str
    offer_id: str
    title: str
    price: float
    permalink: str
    original_price: float | None = None
    image_url: str = ""

    # O desconto informado pela própria loja. Fica explícito em vez de sempre
    # recalculado porque cada API arredonda do seu jeito, e mudar o número
    # exibido não é objetivo desta camada.
    discount_percent: int = 0

    # Sinais comerciais (lojas de produto físico).
    sales_count: int = 0
    rating: float | None = None
    official_store: bool = False
    free_shipping: bool = False
    offer_label: str = ""
    coupon_amount: float | None = None
    commission_rate: float = 0.0

    # Sinais editoriais (lojas de jogos).
    lowest_price: float | None = None
    review_score: int | None = None
    review_count: int | None = None
    waitlisted: int | None = None
    store_type: str = ""

    # Cupom que a própria loja entrega junto do item.
    promo_code: str = ""
    promo_description: str = ""

    # Dataclass original do provider, para o que for específico da loja sem
    # poluir este modelo.
    raw: Any = field(default=None, repr=False, compare=False)

    @property
    def key(self) -> str:
        """Chave de deduplicação e persistência, ex.: ``"shopee:123"``.

        O Mercado Livre é a exceção histórica: o ``seen`` e o ``deal_store``
        dele usam o id puro do anúncio, e mudar isso invalidaria o estado já
        gravado em produção.
        """
        if self.source == "ml":
            return self.offer_id
        return f"{self.source}:{self.offer_id}"

    @property
    def is_free(self) -> bool:
        return self.price <= 0

    def discount_from(self, effective_price: float) -> int:
        """Desconto real considerando um preço efetivo (pós-cupom).

        Sem preço original de referência, devolve o desconto informado pela
        loja.
        """
        if not self.original_price or self.original_price <= effective_price:
            return self.discount_percent
        return round((self.original_price - effective_price) / self.original_price * 100)
