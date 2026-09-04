"""Validação leve pré-publicação, reaproveitável por qualquer provider.

Não tenta validar tudo (preço/desconto/cupom já são recalculados a cada
ciclo, a partir de dados frescos, então "desatualizado" não se aplica aqui).
O que este módulo cobre é o que só se sabe fazendo uma checagem de rede
*na hora de publicar*: o link ainda responde e não é um 404/410 explícito,
e (opcionalmente) a imagem ainda carrega.

Princípio: falha de rede ambígua (timeout, DNS, 5xx) NÃO bloqueia a
publicação — só um "não encontrado" definitivo (404/410) bloqueia. Isso
evita derrubar anúncios legítimos por instabilidade momentânea do site,
mantendo a regra do projeto de "sem evidência suficiente não afirma, mas
também não pune a oferta por ausência de evidência".
"""

import logging

import httpx

log = logging.getLogger("k4binho")

_DEFINITELY_BROKEN = {404, 410}


def link_is_broken(url: str, *, timeout: float = 6.0) -> bool:
    """True somente quando há evidência forte de que o link não existe mais."""
    if not url:
        return True
    try:
        resp = httpx.head(url, timeout=timeout, follow_redirects=True)
        if resp.status_code in _DEFINITELY_BROKEN:
            return True
        if resp.status_code == 405:
            # Alguns servidores nao aceitam HEAD; tenta GET leve antes de concluir.
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
            return resp.status_code in _DEFINITELY_BROKEN
        return False
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        log.debug("[validation] link '%s' inconclusivo (%s) - nao bloqueando.", url, exc)
        return False


def image_is_reachable(url: str, *, timeout: float = 6.0) -> bool:
    """True quando a imagem responde OK. Falha de rede => True (nao bloqueia por si so;
    quem chama decide se quer publicar sem imagem ou pular o item)."""
    if not url:
        return False
    try:
        resp = httpx.head(url, timeout=timeout, follow_redirects=True)
        if resp.status_code == 405:
            resp = httpx.get(url, timeout=timeout, follow_redirects=True)
        return resp.status_code < 400
    except (httpx.HTTPError, httpx.InvalidURL) as exc:
        log.debug("[validation] imagem '%s' inconclusiva (%s).", url, exc)
        return True
