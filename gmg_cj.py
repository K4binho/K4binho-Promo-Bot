"""Integracao com a impact.com (Partner API v16) para trazer deals/cupons
da Green Man Gaming (GMG).

Endpoints e schemas abaixo foram confirmados diretamente no OpenAPI
publicado pela impact.com (https://integrations.impact.com/llms.txt ->
Partner API Reference), nao sao mais estimativa.

Credenciais: CJ_ACCOUNT_SID / CJ_AUTH_TOKEN no .env (nomes mantidos por
legado, mas o valor e o Account SID / Auth Token gerados no painel da
impact.com: User profile -> Settings -> Technical -> API).

Base path (persona Partner): https://api.impact.com/Mediapartners/{AccountSID}/
Auth: HTTP Basic (AccountSID = usuario, AuthToken = senha).

Recursos usados:
  GET  /Campaigns                              -> programas que voce promove
  GET  /Catalogs?CampaignId=..                  -> catalogos de um programa
  GET  /Catalogs/{CatalogId}/Items              -> itens do catalogo (preco,
                                                    imagem, url de tracking
                                                    JA PRONTA, promocoes
                                                    aplicadas embutidas)
  GET  /Promotions                              -> promocoes disponiveis
  GET  /PromoCodes?AdvertiserId=..              -> cupons por anunciante
  POST /Programs/{ProgramId}/TrackingLinks      -> gerar link de tracking
                                                    customizado (deep link)
"""
from dataclasses import dataclass

import httpx

BASE_URL = "https://api.impact.com"
GMG_NAME_HINT = "Green Man Gaming"
DEFAULT_CATALOG_CURRENCY = "BRL"


@dataclass
class GmgDeal:
    item_id: str
    title: str
    price: float
    original_price: float | None
    discount_percent: float
    permalink: str  # ja e a tracking URL retornada pelo catalogo, pronta pra usar
    image_url: str
    promo_code: str | None = None
    promo_description: str | None = None
    promo_is_platform_wide: bool = False


def _auth(account_sid: str, auth_token: str) -> httpx.BasicAuth:
    """impact.com autentica via HTTP Basic: Account SID = usuario,
    Auth Token = senha (nao e Bearer token)."""
    return httpx.BasicAuth(account_sid, auth_token)


def _headers() -> dict:
    return {"Accept": "application/json"}


def _get(path: str, account_sid: str, auth_token: str, **params) -> dict:
    url = f"{BASE_URL}{path}"
    resp = httpx.get(
        url,
        auth=_auth(account_sid, auth_token),
        headers=_headers(),
        params={k: v for k, v in params.items() if v is not None},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json()


def list_programs(account_sid: str, auth_token: str) -> list[dict]:
    """GET /Mediapartners/{AccountSID}/Campaigns
    Retorna todos os programas (marcas) que voce ja promove. Cada item
    traz AdvertiserId, AdvertiserName, CampaignId (= o "ProgramId" usado
    em outros endpoints, como TrackingLinks), CampaignName etc."""
    data = _get(f"/Mediapartners/{account_sid}/Campaigns", account_sid, auth_token)
    return data.get("Campaigns", [])


def find_gmg_program(account_sid: str, auth_token: str) -> dict | None:
    """Procura o programa da Green Man Gaming entre os programas que voce
    ja promove, casando pelo nome do anunciante. Retorna o objeto Program
    inteiro (contem CampaignId, AdvertiserId etc.) ou None se nao achar."""
    for program in list_programs(account_sid, auth_token):
        name = program.get("AdvertiserName") or program.get("CampaignName") or ""
        if GMG_NAME_HINT.lower() in name.lower():
            return program
    return None


def list_catalogs(account_sid: str, auth_token: str, campaign_id: str | None = None) -> list[dict]:
    """GET /Mediapartners/{AccountSID}/Catalogs?CampaignId=..
    Sem campaign_id, lista todos os catalogos disponiveis pra voce."""
    data = _get(
        f"/Mediapartners/{account_sid}/Catalogs",
        account_sid,
        auth_token,
        CampaignId=campaign_id,
    )
    return data.get("Catalogs", [])


def select_product_catalog(
    catalogs: list[dict], preferred_currency: str = DEFAULT_CATALOG_CURRENCY
) -> dict | None:
    """Escolhe o catalogo de produtos da moeda desejada, evitando bundles."""
    currency = preferred_currency.strip().upper()
    product_catalogs = [
        catalog for catalog in catalogs
        if "product catalog" in str(catalog.get("Name", "")).lower()
    ]
    return next(
        (
            catalog for catalog in product_catalogs
            if currency in str(catalog.get("Name", "")).upper()
        ),
        product_catalogs[0] if product_catalogs else None,
    )


def resolve_program_and_catalog(
    account_sid: str,
    auth_token: str,
    program_id: str = "",
    catalog_id: str = "",
    preferred_currency: str = DEFAULT_CATALOG_CURRENCY,
) -> tuple[str, str]:
    """Descobre IDs da GMG quando eles nao foram preenchidos no ambiente."""
    if program_id and catalog_id:
        return program_id, catalog_id

    program = find_gmg_program(account_sid, auth_token)
    if not program:
        raise RuntimeError("Programa Green Man Gaming nao encontrado na conta impact.com")
    resolved_program_id = program_id or str(program.get("CampaignId") or "")
    if not resolved_program_id:
        raise RuntimeError("Programa GMG sem CampaignId")
    if catalog_id:
        return resolved_program_id, catalog_id

    catalogs = list_catalogs(
        account_sid, auth_token, campaign_id=resolved_program_id
    )
    catalog = select_product_catalog(catalogs, preferred_currency)
    resolved_catalog_id = str(catalog.get("Id") or "") if catalog else ""
    if not resolved_catalog_id:
        raise RuntimeError(
            f"Catalogo de produtos GMG ({preferred_currency}) nao encontrado"
        )
    return resolved_program_id, resolved_catalog_id


def fetch_catalog_items(
    account_sid: str,
    auth_token: str,
    catalog_id: str,
    query: str | None = None,
    *,
    page_size: int = 1000,
    max_pages: int = 10,
) -> list[dict]:
    """GET /Mediapartners/{AccountSID}/Catalogs/{CatalogId}/Items
    `query` (opcional) filtra itens, ex.: "CurrentPrice > 50".
    A API pagina o catalogo; le ate `max_pages` sem repetir a primeira pagina.
    """
    items: list[dict] = []
    page_size = max(1, min(int(page_size), 1000))
    max_pages = max(1, int(max_pages))

    for page in range(1, max_pages + 1):
        data = _get(
            f"/Mediapartners/{account_sid}/Catalogs/{catalog_id}/Items",
            account_sid,
            auth_token,
            Query=query,
            Page=page,
            PageSize=page_size,
        )
        batch = data.get("Items", [])
        if not isinstance(batch, list) or not batch:
            break
        items.extend(batch)
        try:
            total_pages = int(data.get("@numpages") or page)
        except (TypeError, ValueError):
            total_pages = page
        if page >= total_pages:
            break
    return items


def fetch_promotions(account_sid: str, auth_token: str) -> list[dict]:
    """GET /Mediapartners/{AccountSID}/Promotions
    Nao ha filtro por anunciante documentado neste endpoint; filtre pelo
    campo AdvertiserName/AdvertiserId no resultado."""
    data = _get(f"/Mediapartners/{account_sid}/Promotions", account_sid, auth_token)
    return data.get("Promotions", [])


def fetch_promo_codes(
    account_sid: str, auth_token: str, advertiser_id: str | None = None, program_id: str | None = None
) -> list[dict]:
    """GET /Mediapartners/{AccountSID}/PromoCodes
    Suporta filtro por AdvertiserId e/ou ProgramId (arrays na query)."""
    data = _get(
        f"/Mediapartners/{account_sid}/PromoCodes",
        account_sid,
        auth_token,
        AdvertiserId=advertiser_id,
        ProgramId=program_id,
    )
    return data.get("PromoCodes", [])


def create_tracking_link(
    account_sid: str,
    auth_token: str,
    program_id: str,
    deep_link: str | None = None,
    link_type: str = "Regular",
    custom_path: str | None = None,
    subid1: str | None = None,
) -> str | None:
    """POST /Mediapartners/{AccountSID}/Programs/{ProgramId}/TrackingLinks
    Use so se precisar de um link de tracking customizado alem do `Url`
    que ja vem pronto em cada item do catalogo (fetch_catalog_items).
    `program_id` = o mesmo valor de CampaignId retornado por list_programs."""
    url = f"{BASE_URL}/Mediapartners/{account_sid}/Programs/{program_id}/TrackingLinks"
    params = {
        "Type": link_type,
        "CustomPath": custom_path,
        "DeepLink": deep_link,
        "subId1": subid1,
    }
    resp = httpx.post(
        url,
        auth=_auth(account_sid, auth_token),
        headers=_headers(),
        params={k: v for k, v in params.items() if v is not None},
        timeout=30,
    )
    resp.raise_for_status()
    return resp.json().get("TrackingURL")


def _fallback_promo_code(promo_codes: list[dict]) -> tuple[str | None, str | None]:
    """Pega o primeiro cupom ACTIVE da lista de PromoCodes da conta, pra usar
    como fallback em itens cujo catalogo nao trouxe promocao embutida.

    Os nomes de campo abaixo (Code/State/Description) sao a melhor hipotese
    com base na documentacao conceitual da impact.com (nao ha, nos docs
    consultados, o schema JSON literal do endpoint /PromoCodes) - confira
    contra uma resposta real antes de confiar cegamente nisso. Se o campo
    nao bater, o fallback so nao encontra nada e o cupom fica None (nao
    quebra o resto do ciclo).
    """
    for code in promo_codes:
        state = (code.get("State") or code.get("Status") or "").upper()
        if state and state != "ACTIVE":
            continue
        text = code.get("Code") or code.get("PromoCode") or code.get("PromoCodeText")
        if text:
            desc = code.get("Description") or code.get("PromotionTitle")
            return text, desc
    return None, None


def parse_deals(
    catalog_items: list[dict], promo_codes: list[dict] | None = None
) -> list[GmgDeal]:
    """Converte os Items do catalogo (que ja trazem preco, imagem, url de
    tracking e promocoes aplicadas embutidas) em GmgDeal.

    `promo_codes` (opcional, resultado de fetch_promo_codes) so e usado
    como fallback: aplica o mesmo cupom generico da conta em qualquer item
    cujo catalogo nao tenha trazido promocao embutida. Sem isso, itens sem
    promo embutido simplesmente ficam sem cupom (promo_code=None), o que e
    normal - a maioria do desconto ja vem no preco, cupom e bonus."""
    fallback_code, fallback_desc = (
        _fallback_promo_code(promo_codes) if promo_codes else (None, None)
    )

    results = []
    for item in catalog_items:
        promos = item.get("Promotions") or []
        first_promo = promos[0] if promos else {}

        current_price = item.get("CurrentPrice")
        if current_price is None:
            continue

        promo_code = first_promo.get("GenericRedemptionCode") or fallback_code
        promo_description = first_promo.get("PromotionTitle") or (
            fallback_desc if promo_code == fallback_code else None
        )
        is_platform_wide = bool(promo_code) and not first_promo.get("GenericRedemptionCode")

        results.append(
            GmgDeal(
                item_id=item.get("CatalogItemId") or item.get("Id") or "",
                title=item.get("Name") or "",
                price=float(current_price),
                original_price=float(item["OriginalPrice"]) if item.get("OriginalPrice") else None,
                discount_percent=float(item.get("DiscountPercentage") or 0),
                permalink=item.get("Url") or "",
                image_url=item.get("ImageUrl") or "",
                promo_code=promo_code or None,
                promo_description=promo_description,
                promo_is_platform_wide=is_platform_wide,
            )
        )
    return results


def promotion_from_deal(deal: "GmgDeal") -> "Promotion | None":
    """Converte o cupom solto (promo_code/promo_description) da GmgDeal para
    o modelo unificado do promotion_engine, pra passar pelos mesmos filtros
    de confianca (is_trustworthy) e pela mesma exibicao dos outros providers.

    A API da GMG/impact.com nao expoe valor de desconto do cupom nesse
    endpoint (so o codigo e o titulo da promocao) - o desconto real ja vem
    embutido no preco do catalogo. Por isso a Promotion criada aqui nao tem
    discount_amount/discount_percent: ela existe so pra exibir o codigo de
    forma confiavel, sem inventar um valor de economia que a API nao informa.
    """
    from promotion_engine import Promotion, SCOPE_PLATFORM, SCOPE_PRODUCT

    if not deal.promo_code:
        return None
    return Promotion(
        source="gmg",
        kind="coupon",
        code=deal.promo_code,
        description=deal.promo_description or "",
        scope=SCOPE_PLATFORM if deal.promo_is_platform_wide else SCOPE_PRODUCT,
        product_ids=[deal.item_id] if not deal.promo_is_platform_wide else [],
        confidence="api",
    )


if __name__ == "__main__":
    import os

    from dotenv import load_dotenv

    load_dotenv()

    sid = os.environ.get("CJ_ACCOUNT_SID", "")
    token = os.environ.get("CJ_AUTH_TOKEN", "")

    if not (sid and token):
        raise SystemExit("Defina CJ_ACCOUNT_SID e CJ_AUTH_TOKEN no .env (credenciais da impact.com).")

    print("[gmg] Buscando o programa da Green Man Gaming entre seus programas aprovados...")
    program = find_gmg_program(sid, token)
    if not program:
        raise SystemExit(
            "Nao achei a GMG entre os programas dessa conta impact.com. "
            "Confirme que a aprovacao ja saiu (GET /Campaigns deve listar 'Green Man Gaming')."
        )

    campaign_id = program["CampaignId"]
    advertiser_id = program["AdvertiserId"]
    print(f"[gmg] Programa encontrado: {program.get('CampaignName')} (CampaignId={campaign_id})")

    print("[gmg] Listando catalogos desse programa...")
    catalogs = list_catalogs(sid, token, campaign_id=campaign_id)
    if not catalogs:
        raise SystemExit("Nenhum catalogo encontrado para esse programa.")

    print("[gmg] Buscando cupons de promo code para a GMG (fallback, caso o catalogo nao traga cupom embutido)...")
    promo_codes = fetch_promo_codes(sid, token, advertiser_id=advertiser_id)
    print(f"[gmg] {len(promo_codes)} promo code(s) encontrados para o anunciante.")

    all_deals: list[GmgDeal] = []
    for catalog in catalogs:
        print(f"[gmg] Catalogo '{catalog.get('Name')}' ({catalog.get('NumberOfItems')} itens) — buscando itens...")
        items = fetch_catalog_items(sid, token, catalog["Id"])
        all_deals.extend(parse_deals(items, promo_codes))

    print(f"[gmg] {len(all_deals)} deal(s) montado(s) a partir do(s) catalogo(s).")
