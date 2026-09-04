"""Motor central de promoções condicionais/cupom para fontes comerciais.

A responsabilidade deste módulo é normalizar promoções de fontes diferentes,
calcular preço efetivo sem prometer descontos condicionais e manter um cache
curto das promoções descobertas em páginas do Mercado Livre.
"""

from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Iterable

CACHE_PATH = Path(__file__).parent / "promotion_cache.json"
STATE_PATH = Path(__file__).parent / "promotion_state.json"
CACHE_SCHEMA_VERSION = 2

_COMMON_FALSE_CODES = {
    "APLICAR", "APROVEITE", "ATIVADO", "CARBON", "COMERCIAL", "COMO",
    "CUPOM", "CUPONS", "DESCONTO", "DISPONIVEL", "DISPONÍVEL", "GANHE",
    "ISSO", "OFF", "POPULAR", "RESGATE", "USAR", "USE", "VER",
}


SCOPE_PRODUCT = "product"
SCOPE_STORE = "store"
SCOPE_PLATFORM = "platform"


@dataclass
class Promotion:
    source: str
    kind: str = "coupon"
    code: str = ""
    description: str = ""
    discount_amount: float | None = None
    discount_percent: float | None = None
    minimum_spend: float = 0.0
    max_discount: float | None = None
    selected_users_only: bool = False
    app_only: bool = False
    requires_coins: bool = False
    rescue_url: str = ""
    starts_at: str = ""
    expires_at: str = ""
    match_keywords: list[str] = field(default_factory=list)
    enabled: bool = True
    confidence: str = "manual"
    scope: str = SCOPE_PRODUCT
    store_ids: list[str] = field(default_factory=list)
    category_ids: list[str] = field(default_factory=list)
    product_ids: list[str] = field(default_factory=list)
    usage_remaining: int | None = None

    @property
    def conditional(self) -> bool:
        return self.selected_users_only or self.app_only or self.requires_coins

    @property
    def has_benefit(self) -> bool:
        return bool(
            (self.discount_amount or 0) > 0
            or (self.discount_percent or 0) > 0
            or self.rescue_url
        )

    def active(self, now: datetime | None = None) -> bool:
        if not self.enabled:
            return False
        if self.usage_remaining is not None and self.usage_remaining <= 0:
            return False
        current = now or datetime.now(UTC)
        start = _parse_datetime(self.starts_at)
        end = _parse_datetime(self.expires_at)
        if start and current < start:
            return False
        if end and current > end:
            return False
        return True

    def matches(
        self,
        title: str,
        price: float,
        *,
        store_id: str = "",
        category_ids: Iterable[str] = (),
        product_id: str = "",
    ) -> bool:
        if price < max(0.0, self.minimum_spend):
            return False
        if not _id_allowed(self.product_ids, [product_id]):
            return False
        if not _id_allowed(self.store_ids, [store_id]):
            return False
        if not _id_allowed(self.category_ids, category_ids):
            return False
        if not self.match_keywords:
            return True
        norm = _normalize(title)
        return any(_normalize(keyword) in norm for keyword in self.match_keywords if keyword)

    def savings_for(self, price: float) -> float:
        if price < max(0.0, self.minimum_spend):
            return 0.0
        candidates: list[float] = []
        if self.discount_amount is not None:
            candidates.append(float(self.discount_amount))
        if self.discount_percent is not None:
            pct_value = price * max(0.0, float(self.discount_percent)) / 100.0
            if self.max_discount is not None:
                pct_value = min(pct_value, float(self.max_discount))
            candidates.append(pct_value)
        if not candidates:
            return 0.0
        # Regras concorrentes descrevem o MESMO cupom: nunca promete a maior.
        savings = min(candidates) if len(candidates) > 1 else candidates[0]
        return min(max(0.0, savings), max(0.0, price))


@dataclass
class PriceEvaluation:
    base_price: float
    guaranteed_price: float
    potential_price: float
    guaranteed_savings: float
    potential_savings: float
    best_guaranteed: Promotion | None = None
    best_conditional: Promotion | None = None
    active_promotions: list[Promotion] = field(default_factory=list)

    @property
    def display_promotion(self) -> Promotion | None:
        if self.best_guaranteed or self.best_conditional:
            return self.best_guaranteed or self.best_conditional
        # Algumas promoções não alteram preço diretamente (ex.: página para
        # resgatar cupons da Shopee). Ainda precisam aparecer na mensagem.
        return next(
            (p for p in self.active_promotions if p.code or p.rescue_url or p.description),
            None,
        )

    @property
    def scoring_price(self) -> float:
        # Nunca usa no score uma condição que pode não existir para todo usuário.
        return self.guaranteed_price


def _normalize(text: str) -> str:
    import unicodedata

    raw = unicodedata.normalize("NFKD", (text or "").lower())
    return "".join(c for c in raw if not unicodedata.combining(c))


def _id_allowed(allowed: Iterable[str], candidates: Iterable[str]) -> bool:
    """Restrição por ID só reprova quando há lista E ela não casa.

    Sem lista, o cupom não é restrito por esse eixo. Com lista mas sem ID
    conhecido do produto, o cupom é reprovado: não há evidência de que ele
    se aplique.
    """
    wanted = {str(a).strip().lower() for a in allowed if str(a).strip()}
    if not wanted:
        return True
    got = {str(c).strip().lower() for c in candidates if str(c).strip()}
    return bool(got & wanted)


def _parse_datetime(raw: str) -> datetime | None:
    if not raw:
        return None
    try:
        value = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def evaluate_price(
    base_price: float,
    promotions: Iterable[Promotion],
    *,
    title: str = "",
    store_id: str = "",
    category_ids: Iterable[str] = (),
    product_id: str = "",
    now: datetime | None = None,
) -> PriceEvaluation:
    active = [
        p
        for p in promotions
        if p.active(now)
        and p.matches(
            title,
            base_price,
            store_id=store_id,
            category_ids=category_ids,
            product_id=product_id,
        )
    ]
    guaranteed: list[tuple[float, Promotion]] = []
    conditional: list[tuple[float, Promotion]] = []

    for promo in active:
        saving = promo.savings_for(base_price)
        if saving <= 0:
            continue
        bucket = conditional if promo.conditional else guaranteed
        bucket.append((saving, promo))

    best_g = max(guaranteed, default=(0.0, None), key=lambda x: x[0])
    best_c = max(conditional, default=(0.0, None), key=lambda x: x[0])

    guaranteed_savings = best_g[0]
    conditional_savings = best_c[0]
    guaranteed_price = max(0.0, base_price - guaranteed_savings)
    potential_price = min(guaranteed_price, max(0.0, base_price - conditional_savings))

    return PriceEvaluation(
        base_price=base_price,
        guaranteed_price=round(guaranteed_price, 2),
        potential_price=round(potential_price, 2),
        guaranteed_savings=round(guaranteed_savings, 2),
        potential_savings=round(max(guaranteed_savings, conditional_savings), 2),
        best_guaranteed=best_g[1],
        best_conditional=best_c[1],
        active_promotions=active,
    )


def promotion_from_coupon_amount(source: str, amount: float | None) -> Promotion | None:
    if not amount or amount <= 0:
        return None
    return Promotion(
        source=source,
        kind="coupon",
        discount_amount=float(amount),
        description=f"Cupom de R$ {amount:.2f}",
        confidence="listing",
    )


def _money(raw: str) -> float | None:
    raw = (raw or "").strip().replace("R$", "").replace(" ", "")
    if not raw:
        return None
    # pt-BR: 1.200,50 / 1200,50 / 1200
    if "," in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        # Um único ponto em valor grande normalmente é separador de milhar.
        parts = raw.split(".")
        if len(parts) > 1 and len(parts[-1]) == 3:
            raw = "".join(parts)
    try:
        return float(raw)
    except ValueError:
        return None


def parse_mercadolivre_text(text: str) -> list[Promotion]:
    """Extrai promoções visíveis do texto renderizado de um anúncio do ML.

    O parser é deliberadamente conservador: se encontrar apenas a palavra
    "cupom" sem código/valor, não inventa desconto.
    """
    cleaned = "\n".join(line.strip() for line in (text or "").splitlines() if line.strip())
    norm = _normalize(cleaned)
    if "cupom" not in norm and "desconto" not in norm:
        return []

    codes: list[str] = []
    code_patterns = [
        r"(?i:(?:use|aplique|usar)\s+(?:o\s+)?cupom)\s*[:\-]?\s*`?([A-Z0-9][A-Z0-9_-]{3,24})`?",
        r"(?i:(?:cupom|c[oó]digo))\s*(?::|\-|é)\s*`?([A-Z0-9][A-Z0-9_-]{3,24})`?",
        r"(?i:cupom)\s+`?([A-Z0-9]*\d[A-Z0-9_-]{3,24})`?",
    ]
    for pattern in code_patterns:
        for match in re.finditer(pattern, cleaned):
            code = match.group(1).strip().upper()
            if code not in _COMMON_FALSE_CODES and code not in codes:
                codes.append(code)

    amount = None
    amount_patterns = [
        r"(?i)(?:cupom|desconto)[^\n]{0,45}?R\$\s*([\d\.]+(?:,\d{1,2})?)",
        r"(?i)R\$\s*([\d\.]+(?:,\d{1,2})?)\s*(?:OFF|de desconto)",
    ]
    for pattern in amount_patterns:
        m = re.search(pattern, cleaned)
        if m:
            amount = _money(m.group(1))
            if amount:
                break

    percent = None
    percent_patterns = [
        r"(?i)cupom[^\n]{0,60}?(\d{1,2}(?:[\.,]\d+)?)\s*%",
        r"(?i)(\d{1,2}(?:[\.,]\d+)?)\s*%[^\n]{0,40}?cupom",
    ]
    for pattern in percent_patterns:
        m = re.search(pattern, cleaned)
        if not m:
            continue
        try:
            percent = float(m.group(1).replace(",", "."))
        except ValueError:
            percent = None
        break

    max_discount = None
    cap_patterns = [
        r"(?i)(?:m[aá]ximo|limite|at[eé])(?:\s+de)?\s*R\$\s*([\d\.]+(?:,\d{1,2})?)",
        r"(?i)R\$\s*([\d\.]+(?:,\d{1,2})?)\s*(?:de\s+)?(?:limite|m[aá]ximo)",
    ]
    for pattern in cap_patterns:
        m = re.search(pattern, cleaned)
        if m:
            max_discount = _money(m.group(1))
            break
    if percent is not None and max_discount is not None and amount == max_discount:
        amount = None

    minimum = 0.0
    min_patterns = [
        r"(?i)(?:acima de|a partir de|em compras de|mínimo|minimo)\s*R\$\s*([\d\.]+(?:,\d{1,2})?)",
        r"(?i)R\$\s*([\d\.]+(?:,\d{1,2})?)\s*(?:ou mais|em compras)",
    ]
    for pattern in min_patterns:
        m = re.search(pattern, cleaned)
        if m:
            minimum = _money(m.group(1)) or 0.0
            break

    # Sem código visível, o cupom da PDP costuma ser coletável pela conta
    # logada no scanner — não vale para todo comprador. Fica condicional para
    # não prometer desconto que outra pessoa não recebe.
    selected = not codes or any(
        phrase in norm
        for phrase in ("usuarios selecionados", "usuários selecionados", "selecionados", "algumas contas")
    )
    app_only = any(phrase in norm for phrase in ("somente no app", "apenas no app", "exclusivo no app"))

    if not codes and amount is None and percent is None:
        return []

    # Um anúncio pode exibir mais de um código. Replica a mesma regra detectada
    # para cada código; se não houver código, ainda preserva o desconto explícito.
    target_codes = codes or [""]
    promos = []
    for code in target_codes:
        promos.append(
            Promotion(
                source="mercadolivre",
                kind="coupon",
                code=code,
                discount_amount=amount,
                discount_percent=percent,
                max_discount=max_discount,
                minimum_spend=minimum,
                selected_users_only=selected,
                app_only=app_only,
                description="Cupom detectado no anúncio",
                confidence="page",
            )
        )
    return promos


def promotion_to_dict(promo: Promotion) -> dict:
    return asdict(promo)


def promotion_from_dict(data: dict) -> Promotion:
    allowed = set(Promotion.__dataclass_fields__)
    clean = {k: v for k, v in data.items() if k in allowed}
    return Promotion(**clean)


def promotion_fingerprint(promo: Promotion | None) -> str:
    if promo is None: return ""
    parts=(promo.source,promo.kind,promo.code.strip().upper(),round(float(promo.discount_amount or 0),2),round(float(promo.discount_percent or 0),4),round(float(promo.minimum_spend or 0),2),round(float(promo.max_discount or 0),2),bool(promo.selected_users_only),bool(promo.app_only),bool(promo.requires_coins))
    return "|".join(str(v) for v in parts)


def is_trustworthy(promo: Promotion) -> bool:
    """Rejeita promoção sem evidência suficiente para ser anunciada.

    Um código só é aceito se não estiver na lista de palavras de layout e
    tiver algum benefício associado (valor, percentual ou página de resgate).
    """
    code = (promo.code or "").strip().upper()
    if code and code in _COMMON_FALSE_CODES:
        return False
    if code and not any(ch.isdigit() for ch in code) and len(code) < 5:
        return False
    return promo.has_benefit or bool(code)


def merge_promotions(*groups: Iterable[Promotion] | None) -> list[Promotion]:
    """Une promoções de várias origens sem duplicar a mesma regra."""
    merged: list[Promotion] = []
    seen: set[str] = set()
    for group in groups:
        for promo in group or []:
            if not is_trustworthy(promo):
                continue
            key = promotion_fingerprint(promo)
            if key in seen:
                continue
            seen.add(key)
            merged.append(promo)
    return merged


def load_catalog(path: str | Path) -> dict:
    """Carrega o catálogo manual de cupons.

    Se o arquivo configurado não existir, cai no `.example` versionado para
    que a estrutura continue válida (todas as entradas de exemplo têm
    `enabled: false`, então nada é anunciado sem confirmação).
    """
    p = Path(path)
    if not p.is_absolute():
        p = Path(__file__).parent / p
    if not p.exists():
        fallback = p.with_name(f"{p.stem}.example{p.suffix}")
        if not fallback.exists():
            return {}
        p = fallback
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def promotions_for_item(
    catalog: dict,
    source: str,
    title: str,
    price: float,
    *,
    store_id: str = "",
    category_ids: Iterable[str] = (),
    product_id: str = "",
) -> list[Promotion]:
    """Cupons do catálogo aplicáveis ao item, em qualquer escopo.

    Entradas de escopo `platform` valem para o provider inteiro; `store` e
    `product` só entram quando o ID do item casa com a restrição.
    """
    entries = catalog.get(source, []) if isinstance(catalog, dict) else []
    if not isinstance(entries, list):
        return []
    promos: list[Promotion] = []
    for raw in entries:
        if not isinstance(raw, dict):
            continue
        try:
            promo = promotion_from_dict({"source": source, **raw})
        except (TypeError, ValueError):
            continue
        if not promo.active():
            continue
        if promo.matches(
            title,
            price,
            store_id=store_id,
            category_ids=category_ids,
            product_id=product_id,
        ):
            promos.append(promo)
    return promos


def load_cache() -> dict:
    if not CACHE_PATH.exists():
        return {}
    try:
        data = json.loads(CACHE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def save_cache(cache: dict) -> None:
    tmp = CACHE_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(CACHE_PATH)
    except OSError:
        tmp.unlink(missing_ok=True)


def get_cached_promotions(cache: dict, key: str, max_age_hours: int, promotion_max_age_hours: int | None = None) -> list[Promotion] | None:
    """Promoções em cache para a chave, ou None quando precisa reescanear.

    Entrada de schema antigo é reaproveitada apenas quando ela registrou
    "nenhuma promoção": esse resultado não depende do parser. Se ela guardou
    promoções vindas de um parser anterior, devolve None para reescanear em
    vez de anunciar cupom que talvez nunca tenha existido.
    """
    entry = cache.get(key)
    if not isinstance(entry, dict): return None
    checked_at = _parse_datetime(str(entry.get("checked_at", "")))
    if checked_at is None: return None
    raw_promos = entry.get("promotions", [])
    if not isinstance(raw_promos, list): raw_promos=[]
    legacy = entry.get("schema_version") != CACHE_SCHEMA_VERSION
    if legacy and raw_promos: return None
    ttl = promotion_max_age_hours if raw_promos and promotion_max_age_hours is not None else max_age_hours
    if datetime.now(UTC) - checked_at > timedelta(hours=max(1, ttl)): return None
    promos=[]
    for raw in raw_promos:
        if isinstance(raw, dict):
            try: promo = promotion_from_dict(raw)
            except (TypeError, ValueError): continue
            if is_trustworthy(promo): promos.append(promo)
    return promos


def set_cached_promotions(cache: dict, key: str, promotions: Iterable[Promotion]) -> None:
    cache[key] = {
        "schema_version": CACHE_SCHEMA_VERSION,
        "checked_at": datetime.now(UTC).isoformat(),
        "promotions": [promotion_to_dict(p) for p in promotions],
    }


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"announced_campaigns": {}}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"announced_campaigns": {}}
    if not isinstance(data, dict):
        return {"announced_campaigns": {}}
    data.setdefault("announced_campaigns", {})
    return data


def save_state(state: dict) -> None:
    tmp = STATE_PATH.with_suffix(".tmp")
    try:
        tmp.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(STATE_PATH)
    except OSError:
        tmp.unlink(missing_ok=True)


def due_campaigns(catalog: dict, state: dict, now: datetime | None = None) -> list[dict]:
    current = (now or datetime.now(UTC)).astimezone(UTC)
    announced = state.get("announced_campaigns", {})
    due: list[dict] = []
    campaigns = catalog.get("campaigns", []) if isinstance(catalog, dict) else []
    if not isinstance(campaigns, list):
        return due

    for campaign in campaigns:
        if not isinstance(campaign, dict) or not campaign.get("enabled", True):
            continue
        campaign_id = str(campaign.get("id", "")).strip()
        start = _parse_datetime(str(campaign.get("starts_at", "")))
        if not campaign_id or not start or campaign_id in announced:
            continue
        notice_hours = int(campaign.get("notice_hours_before", 4) or 4)
        window_start = start - timedelta(hours=max(0, notice_hours))
        # Também aceita até 30 min após o início, para não perder aviso por reinício.
        if window_start <= current <= start + timedelta(minutes=30):
            due.append(campaign)
    return due


def mark_campaign_announced(state: dict, campaign_id: str) -> None:
    announced = state.setdefault("announced_campaigns", {})
    announced[campaign_id] = datetime.now(UTC).isoformat()
    save_state(state)
