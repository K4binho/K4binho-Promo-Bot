"""Caca ativa de oferta por palavra-chave (pedido do usuario = prioridade 0).

Pedido feito no bot nao espera o ciclo editorial: consulta as lojas na hora e
responde com preco real. Fontes com busca por termo funcionando: AliExpress
(affiliate product.query), Shopee (productOfferV2 keyword) e Steam (search com
`term`). Mercado Livre nao entra: `/sites/MLB/search` responde 403 pro nosso
token e o HTML de `lista.mercadolivre.com.br` cai em pagina anti-bot.

Cada resultado carrega `kind` (jogo ou item) porque as lojas misturam: buscar
'skyrim' devolve o jogo na Steam e caneca na Shopee, e quem pediu escolhe qual.
"""

import logging
import unicodedata
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

import httpx

import aliexpress
import shopee
import shopee_api
import steam

log = logging.getLogger("k4binho")


@dataclass
class HuntResult:
    source: str
    product_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    link: str
    image_url: str = ""
    relevance: float = 0.0
    kind: str = "item"

    @property
    def key(self) -> str:
        return f"{self.source}:{self.product_id}"


GAME_KIND = "jogo"
ITEM_KIND = "item"

_GAME_SOURCES = {"steam", "nuuvem", "gmg"}

# Chave/gift card vendida em loja fisica ainda e o jogo, nao bugiganga tematica.
_KEY_WORDS = (
    "steam key", "chave steam", "gift card", "giftcard", "cd key", "cd-key",
    "codigo steam", "key global", "steam gift",
)


def _classify_kind(source: str, title: str) -> str:
    """Separa jogo de produto fisico.

    Busca por 'skyrim' na Shopee/AliExpress devolve caneca, marcador e colar; o
    usuario que pediu o jogo recebia so acessorio. A loja e o sinal forte (Steam
    vende jogo, Shopee vende coisa), e o titulo resgata chave/gift card.
    """
    if source in _GAME_SOURCES:
        return GAME_KIND
    norm = _normalize(title)
    if any(k in norm for k in _KEY_WORDS):
        return GAME_KIND
    return ITEM_KIND


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def _relevant(title: str, terms: list[str]) -> bool:
    """Exige todos os termos no titulo. A busca da loja e generosa demais:
    'lego star wars' devolve suporte de acrilico e bloco solto."""
    norm = _normalize(title)
    return all(t in norm for t in terms)


def _relevance(title: str, terms: list[str]) -> float:
    """Fracao das palavras do titulo que o usuario pediu.

    Ordenar so por preco entrega chaveiro e adesivo antes do produto: acessorio
    e sempre mais barato. Titulo curto que e quase todo o termo pedido
    ('Palworld') pontua alto; titulo longo com o termo enfiado no meio
    ('Chaveiro de Poke Ball do jogo Palworld, pingente') pontua baixo.
    """
    words = [w for w in _normalize(title).split() if w]
    if not words:
        return 0.0
    hits = sum(1 for w in words if any(t in w for t in terms))
    return hits / len(words)


def _hunt_aliexpress(keywords: str, app_key: str, app_secret: str, tracking_id: str, limit: int) -> list[HuntResult]:
    if not (app_key and app_secret and tracking_id):
        return []
    deals = aliexpress.fetch_deals(
        app_key, app_secret, tracking_id, keywords=keywords, page_size=limit
    )
    return [
        HuntResult(
            source="aliexpress",
            product_id=d.product_id,
            title=d.title,
            price=d.price,
            original_price=d.original_price or None,
            discount_percent=d.discount_percent,
            link=d.permalink,
            image_url=d.image_url,
        )
        for d in deals
    ]


def _hunt_shopee(keywords: str, app_id: str, secret: str, limit: int) -> list[HuntResult]:
    if not (app_id and secret):
        return []
    deals = shopee.fetch_deals(app_id, secret, keywords=[keywords], page_size=limit)
    results = []
    for d in deals:
        link = d.affiliate_link or shopee.ensure_affiliate_link(app_id, secret, d)
        results.append(
            HuntResult(
                source="shopee",
                product_id=d.item_id,
                title=d.title,
                price=d.price,
                original_price=d.original_price or None,
                discount_percent=d.discount_percent,
                link=link,
                image_url=d.image_url,
            )
        )
    return results


def _hunt_steam(keywords: str, limit: int) -> list[HuntResult]:
    deals = steam.search_by_keyword(keywords, limit=limit)
    return [
        HuntResult(
            source="steam",
            product_id=d.game_id,
            title=d.title,
            price=d.price,
            original_price=d.original_price,
            discount_percent=d.discount_percent,
            link=d.permalink,
            image_url=d.header_image,
        )
        for d in deals
    ]


def hunt(
    keywords: str,
    *,
    max_price: float | None = None,
    aliexpress_app_key: str = "",
    aliexpress_app_secret: str = "",
    aliexpress_tracking_id: str = "",
    shopee_app_id: str = "",
    shopee_app_secret: str = "",
    per_source_limit: int = 20,
) -> list[HuntResult]:
    """Busca o termo em todas as lojas em paralelo, do mais barato pro mais caro."""
    terms = [t for t in _normalize(keywords).split() if t]
    if not terms:
        return []

    jobs = {
        "aliexpress": lambda: _hunt_aliexpress(
            keywords, aliexpress_app_key, aliexpress_app_secret,
            aliexpress_tracking_id, per_source_limit,
        ),
        "shopee": lambda: _hunt_shopee(
            keywords, shopee_app_id, shopee_app_secret, per_source_limit
        ),
        "steam": lambda: _hunt_steam(keywords, per_source_limit),
    }

    found: list[HuntResult] = []
    with ThreadPoolExecutor(max_workers=len(jobs)) as pool:
        futures = {name: pool.submit(job) for name, job in jobs.items()}
        for name, future in futures.items():
            try:
                found.extend(future.result())
            except (httpx.HTTPError, RuntimeError, ValueError, KeyError) as exc:
                log.warning("[Caca] fonte %s falhou para %r: %s", name, keywords, exc)

    filtered = [r for r in found if r.price > 0 and _relevant(r.title, terms)]
    if max_price is not None:
        filtered = [r for r in filtered if r.price <= max_price]
    for r in filtered:
        r.relevance = _relevance(r.title, terms)
        r.kind = _classify_kind(r.source, r.title)
    # Relevancia em faixa grossa antes do preco: dentro da mesma faixa o mais
    # barato ganha, mas acessorio barato nao passa na frente do produto.
    filtered.sort(key=lambda r: (-round(r.relevance, 1), r.price))
    return filtered


def split_kinds(results: list[HuntResult]) -> tuple[list[HuntResult], list[HuntResult]]:
    """Devolve (jogos, itens) preservando a ordem de relevancia."""
    return (
        [r for r in results if r.kind == GAME_KIND],
        [r for r in results if r.kind != GAME_KIND],
    )
