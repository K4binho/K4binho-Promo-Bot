"""Controle de duplicação e de republicação.

Três regras que antes estavam copiadas em cada ciclo:

- **liberar o que saiu de promoção**: uma chave em ``seen`` cuja oferta não
  aparece mais com desconto volta a ser publicável;
- **ignorar o que já foi publicado**: filtro por ``seen``;
- **consolidar o mesmo produto**: títulos normalizados iguais disputam uma vaga
  só, e vence o menor preço.

Queda de preço e revival por promoção continuam em ``storage.deal_store``,
porque dependem do preço efetivo já publicado.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Iterable, Sequence

from k4promo.services import scoring

log = logging.getLogger("k4binho")


def release_stale(
    seen: dict[str, str],
    prefix: str,
    active_keys: Iterable[str],
    *,
    log_tag: str,
    noun: str = "produto",
) -> int:
    """Remove de ``seen`` as chaves de ``prefix`` que não estão mais ativas.

    Devolve quantas foram liberadas para republicação.
    """
    active = set(active_keys)
    stale = [k for k in seen if k.startswith(prefix) and k not in active]
    for key in stale:
        del seen[key]
    if stale:
        log.info("[%s] %d %s(s) saiu(ram) de promo, liberado(s) pra re-post.", log_tag, len(stale), noun)
    return len(stale)


def dedupe_by_title(
    items: Sequence[Any],
    *,
    title_of: Callable[[Any], str] = lambda d: d.title,
    price_of: Callable[[Any], float] = lambda d: d.price,
    length: int = 60,
) -> list:
    """Consolida itens com o mesmo título normalizado, mantendo o mais barato.

    Usa a mesma normalização do scoring para que a consolidação siga o critério
    já aplicado no digest e no feed.
    """
    best: dict[str, Any] = {}
    for item in items:
        key = scoring._normalize(title_of(item))[:length]
        current = best.get(key)
        if current is None or price_of(item) < price_of(current):
            best[key] = item
    return list(best.values())
