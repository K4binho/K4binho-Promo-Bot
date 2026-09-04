"""Nuuvem deals via IsThereAnyDeal API (Nuuvem shop ID 50) + coupon scraping."""

import re
from dataclasses import dataclass, field
from html import unescape

import httpx

ITAD_DEALS_URL = "https://api.isthereanydeal.com/deals/v2"
ITAD_INFO_URL = "https://api.isthereanydeal.com/games/info/v2"
NUUVEM_SHOP_ID = 50
COUPONS_URL = "https://www.nuuvem.com/br-pt/log-cupom-interno"


@dataclass
class NuuvemCoupon:
    code: str
    discount: str
    game: str
    region: str


@dataclass
class NuuvemDeal:
    game_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: int
    permalink: str
    image_url: str
    lowest_price: float | None = None
    coupon: NuuvemCoupon | None = None
    waitlisted: int | None = None
    review_score: int | None = None
    review_count: int | None = None


_STOP_WORDS = re.compile(r'\bPa[ií]ses:|Acesse Agora|Usos extremamente', re.IGNORECASE)
# Nomes de jogo aparecem em Title Case/CAPS na descricao; conectores em
# portugues ("de", "para", "o", "as versoes", "lancamento") ficam em
# minusculas, entao o maior trecho contiguo capitalizado tende a ser o
# nome do jogo (ou parte substancial dele, o suficiente pro match por
# substring em _match_coupon).
_CAPITALIZED_RUN = re.compile(r'[A-Z\u00c0-\u00dd0-9][\w\u00c0-\u00ff]*(?:[\s:\-]+[A-Z\u00c0-\u00dd0-9][\w\u00c0-\u00ff]*)*')


def _extract_game_name(window: str) -> str:
    cut = _STOP_WORDS.split(window)[0]
    candidates = [c.strip() for c in _CAPITALIZED_RUN.findall(cut) if len(c.strip()) > 2]
    if not candidates:
        return ""
    return max(candidates, key=len)[:80]


def fetch_coupons() -> list[NuuvemCoupon]:
    try:
        resp = httpx.get(COUPONS_URL, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    # A pagina de cupons muda de layout HTML a cada campanha (classes e
    # tags diferentes por evento). Em vez de depender de marcacao
    # especifica, removemos toda tag e trabalhamos sobre o texto visivel,
    # que e estavel: cada cupom aparece como "Cupom: CODIGO" seguido de
    # "Descricao: X% de desconto ... <jogo>".
    text = unescape(re.sub(r'<[^>]+>', ' ', resp.text))
    text = re.sub(r'\s+', ' ', text)

    coupons: list[NuuvemCoupon] = []
    matches = list(re.finditer(r'Cupom:\s*([A-Z0-9][A-Z0-9]{2,19})\b', text))
    for i, m in enumerate(matches):
        code = m.group(1)
        next_code_pos = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        segment_limit = min(next_code_pos, m.end() + 400)
        # "Acesse Agora" fecha cada card de cupom na pagina; usa como fim
        # do bloco quando presente pra nao vazar texto do proximo item
        # (inclusive itens sem "Cupom:" com dois-pontos, como recompensas
        # automaticas do tipo "Cupom de R$30 em compras").
        acesse_pos = text.find("Acesse Agora", m.end(), segment_limit)
        window_end = acesse_pos + len("Acesse Agora") if acesse_pos != -1 else segment_limit
        window = text[m.end():window_end]

        pct_m = re.search(r'(\d+%)\s*de desconto', window, re.IGNORECASE)
        val_m = re.search(r'(R\$\s*[\d.,]+)', window)
        discount_m = pct_m or val_m
        if not discount_m:
            # Sem percentual/valor identificavel: nao ha evidencia
            # suficiente do beneficio, nao anuncia (mesma regra usada no
            # motor de cupons para outras fontes).
            continue
        discount = discount_m.group(1)

        game = _extract_game_name(window[discount_m.end():])
        coupons.append(NuuvemCoupon(code=code, discount=discount, game=game, region="BR"))

    return coupons



def _match_coupon(title: str, coupons: list[NuuvemCoupon]) -> NuuvemCoupon | None:
    title_lower = title.lower()
    for c in coupons:
        if c.game and c.game.lower() in title_lower:
            return c
        game_words = c.game.lower().split()
        if game_words and len(game_words) >= 2 and all(w in title_lower for w in game_words):
            return c
    return None


CAMPAIGN_URL = "https://www.nuuvem.com/lp/pt/campanha/"


def fetch_campaign_coupons() -> list[NuuvemCoupon]:
    """Cupons de plataforma (sem jogo especifico) anunciados na landing page
    da campanha ativa (ex.: "garanta 15% OFF em suas compras"). So existem
    durante eventos; fora de campanha a pagina nao tem esse padrao e a
    funcao retorna lista vazia normalmente."""
    try:
        resp = httpx.get(CAMPAIGN_URL, timeout=30, follow_redirects=True)
        if resp.status_code != 200:
            return []
    except httpx.HTTPError:
        return []

    text = unescape(re.sub(r'<[^>]+>', ' ', resp.text))
    text = re.sub(r'\s+', ' ', text)

    coupons: list[NuuvemCoupon] = []
    for m in re.finditer(r'garanta\s+(\d+)%\s*OFF\s*em\s*suas\s*compras', text, re.IGNORECASE):
        code_m = re.search(r'([A-Z0-9]{4,20})\s*Copiado!', text[m.end():m.end() + 300])
        if not code_m:
            continue
        coupons.append(NuuvemCoupon(code=code_m.group(1), discount=f"{m.group(1)}%", game="", region="BR"))
    return coupons


def _best_platform_coupon(coupons: list[NuuvemCoupon]) -> NuuvemCoupon | None:
    """Entre os cupons de plataforma (sem jogo especifico associado),
    escolhe o de maior desconto percentual pra anexar como fallback nas
    ofertas que nao tem cupom de produto/loja proprio."""
    platform = [c for c in coupons if not c.game]
    if not platform:
        return None

    def _pct(c: NuuvemCoupon) -> int:
        pm = re.match(r'(\d+)%', c.discount)
        return int(pm.group(1)) if pm else 0

    return max(platform, key=_pct)


PAGE_SIZE = 50
MAX_PAGES = 10


def fetch_deals(
    itad_api_key: str, country: str = "BR", limit: int = 500
) -> list[NuuvemDeal]:
    if not itad_api_key:
        return []

    coupons = fetch_coupons()
    platform_coupon = _best_platform_coupon(fetch_campaign_coupons())
    deals: list[NuuvemDeal] = []
    seen_ids: set[str] = set()

    for page in range(MAX_PAGES):
        params = {
            "key": itad_api_key,
            "country": country,
            "shops": NUUVEM_SHOP_ID,
            "sort": "-cut",
            "limit": PAGE_SIZE,
            "offset": page * PAGE_SIZE,
        }
        try:
            resp = httpx.get(ITAD_DEALS_URL, params=params, timeout=30)
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            if page == 0:
                raise RuntimeError(f"ITAD/Nuuvem: {exc}") from None
            break

        entries = resp.json().get("list", [])
        if not entries:
            break

        for entry in entries:
            if entry.get("type") != "game":
                continue
            deal_info = entry.get("deal") or {}
            price_obj = deal_info.get("price") or {}
            regular_obj = deal_info.get("regular") or {}
            price = price_obj.get("amount")
            if price is None or price <= 0:
                continue
            original = regular_obj.get("amount")
            discount = int(deal_info.get("cut") or 0)
            if discount <= 0:
                continue
            low_obj = deal_info.get("historyLow") or {}
            lowest = low_obj.get("amount")
            assets = entry.get("assets") or {}
            title = entry.get("title", "")
            game_id = entry.get("id", "")
            if game_id in seen_ids:
                continue
            seen_ids.add(game_id)
            coupon = _match_coupon(title, coupons) if coupons else None
            if coupon is None:
                # Sem cupom de produto/loja proprio: anexa o cupom de
                # plataforma da campanha ativa (se houver) como fallback.
                coupon = platform_coupon
            deals.append(NuuvemDeal(
                game_id=game_id,
                title=title,
                price=float(price),
                original_price=float(original) if original else None,
                discount_percent=discount,
                permalink=deal_info.get("url", ""),
                image_url=assets.get("banner600") or assets.get("boxart") or "",
                lowest_price=float(lowest) if lowest else None,
                coupon=coupon,
            ))

    deals.sort(key=lambda d: d.discount_percent, reverse=True)
    return deals[:limit]


def _fetch_itad_info(api_key: str, game_id: str) -> dict | None:
    try:
        resp = httpx.get(
            ITAD_INFO_URL,
            params={"key": api_key, "id": game_id},
            timeout=15,
        )
        if resp.status_code != 200:
            return None
        return resp.json()
    except httpx.HTTPError:
        return None


def enrich_with_popularity(api_key: str, deals: list["NuuvemDeal"]) -> None:
    """Preenche waitlisted (quantas pessoas tem o jogo na lista de
    desejos da ITAD - metrica de 'procura') e nota/qtd de reviews do
    Steam quando disponivel, pro mesmo jogo. Mesmo padrao usado em
    steam.py."""
    if not api_key:
        return
    for deal in deals:
        info = _fetch_itad_info(api_key, deal.game_id)
        if not info:
            continue
        for review in info.get("reviews") or []:
            if review.get("source") == "Steam":
                deal.review_score = review.get("score")
                deal.review_count = review.get("count")
                break
        stats = info.get("stats") or {}
        deal.waitlisted = stats.get("waitlisted")


def is_most_wanted(deal: "NuuvemDeal", min_waitlisted: int) -> bool:
    return deal.waitlisted is not None and deal.waitlisted >= min_waitlisted

