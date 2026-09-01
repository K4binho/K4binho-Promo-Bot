import unicodedata
from dataclasses import dataclass, field

MIN_HISTORY_OBS = 4

CATEGORY_KEYWORDS = {
    "informatica": [
        "notebook", " notebook", "laptop", "computador", "pc gamer", "desktop",
        "ssd", "nvme", "hd externo", "monitor", "monitor gamer", "ultrawide",
        "teclado mecanico", "teclado gamer", "mouse gamer", "mousepad",
        "roteador", "placa de video", "placa video", "rtx", "gtx", "radeon", "gpu",
        "memoria ram", "ddr4", "ddr5", "processador", "ryzen", "intel core",
        "core i3", "core i5", "core i7", "core i9", "cpu",
        "cooler", "water cooler", "air cooler", "ventoinha", "fan cooler",
        "placa mae", "placa-mae", "gabinete gamer", "gabinete", "fonte atx",
        "webcam", "nobreak", "impressora", "pendrive", "cadeira gamer",
        "microfone", "capturadora", "dissipador", "pasta termica",
    ],
    "celular": [
        "smartphone", "celular", "iphone", "galaxy s", "galaxy a", "galaxy z",
        "xiaomi", "redmi", "poco x", "poco f", "moto g", "moto e", "moto edge",
        "capinha", "capa protetora celular", "pelicula de vidro", "smartwatch",
        "relogio inteligente", "band ", "mi band",
    ],
    "games": [
        "playstation", "ps5", "ps4", "xbox series", "xbox one", "console xbox",
        "nintendo switch", "controle dualsense", "controle xbox", "controle ps5",
        "controle ps4", "cartao psn", "gift card steam", "volante gamer",
        "joystick", "vr headset", "oculos vr",
    ],
    "audio": [
        "fone bluetooth", "fone de ouvido", "fone sem fio", "fone tws", "earbud",
        "airpods", "headset gamer", "headset", "caixa de som", "soundbar",
        "caixa de som bluetooth", "jbl", "sound bar",
    ],
    "ferramentas": [
        "furadeira", "parafusadeira", "serra", "esmerilhadeira", "chave de impacto",
        "lixadeira", "makita", "dewalt", "trena", "alicate", "jogo de soquete",
        "jogo de chaves", "morsa", "policorte", "plaina", "tupia", "solda",
    ],
    "carregador": [
        "carregador turbo", "carregador rapido", "carregador veicular",
        "power bank", "carregador portatil", "cabo usb-c", "cabo usb c",
        "fonte carregador", "carregador de pilha", "estacao de carregamento",
    ],
    "automacao": [
        "alexa", "echo dot", "lampada inteligente", "tomada inteligente",
        "camera wifi", "camera ip", "fechadura digital", "smart home", "google nest",
        "sonoff", "tuya", "sensor de presenca", "interruptor inteligente",
        "campainha inteligente",
    ],
}

COMMERCIAL_WEIGHTS = {
    "quality": 0.40,
    "conversion": 0.40,
    "retention": 0.15,
    "confidence": 0.05,
}

PLUS_WEIGHTS = {
    "quality": 0.50,
    "conversion": 0.0,
    "retention": 0.40,
    "confidence": 0.10,
}


def _normalize(text: str) -> str:
    text = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in text if not unicodedata.combining(c))


def category_match(title: str) -> str:
    norm = _normalize(title)
    for area, keywords in CATEGORY_KEYWORDS.items():
        for kw in keywords:
            if kw in norm:
                return area
    return ""


@dataclass
class ScoreResult:
    total: int
    price_subtotal: int
    reasons: list[str]
    quality: int = 0
    conversion: int = 0
    retention: int = 0
    confidence: int = 0
    final: float = 0.0
    history_confidence: str = "low"


def _clamp(value: int, lo: int = 0, hi: int = 100) -> int:
    return max(lo, min(hi, value))


def quality_score(
    discount_percent: int,
    price: float,
    min_price_30d: float | None,
    avg_price_30d: float | None,
    obs_count: int,
    rating: float | None,
    official_store: bool,
    offer_label: str,
) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    if discount_percent > 50:
        pts += 30
        reasons.append(f"desconto {discount_percent}% (+30)")
    elif discount_percent > 30:
        pts += 20
        reasons.append(f"desconto {discount_percent}% (+20)")
    elif discount_percent >= 15:
        pts += 10
        reasons.append(f"desconto {discount_percent}% (+10)")

    if obs_count >= MIN_HISTORY_OBS and min_price_30d is not None:
        if price <= min_price_30d:
            pts += 30
            reasons.append(f"menor preco 30d (+30)")
        elif avg_price_30d is not None and price < avg_price_30d * 0.9:
            diff = avg_price_30d - price
            pts += 20
            reasons.append(f"R${diff:.0f} abaixo da media (+20)")

    if rating is not None and rating >= 4.5:
        pts += 15
        reasons.append(f"nota {rating} (+15)")
    elif rating is not None and rating >= 4.0:
        pts += 8
        reasons.append(f"nota {rating} (+8)")
    elif rating is None:
        pts -= 10
        reasons.append("sem avaliacoes (-10)")

    if official_store:
        pts += 10
        reasons.append("loja oficial (+10)")

    if offer_label:
        pts += 5
        reasons.append(f"{offer_label} (+5)")

    return _clamp(pts), reasons


def conversion_score(
    price: float,
    sales_count: int,
    discount_percent: int,
    is_best_seller: bool,
    is_trending: bool,
    category: str,
) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    if sales_count >= 5000:
        pts += 25
        reasons.append(f"vendas {sales_count} (+25)")
    elif sales_count >= 1000:
        pts += 20
        reasons.append(f"vendas {sales_count} (+20)")
    elif sales_count >= 100:
        pts += 10
        reasons.append(f"vendas {sales_count} (+10)")

    if price <= 100:
        pts += 15
        reasons.append("preco acessivel (+15)")
    elif price <= 300:
        pts += 10
        reasons.append("preco medio (+10)")
    elif price <= 500:
        pts += 5
        reasons.append("preco alto (+5)")

    if is_best_seller:
        pts += 15
        reasons.append("mais vendido (+15)")

    if is_trending:
        pts += 10
        reasons.append("em alta (+10)")

    category_boost = {
        "informatica": 15, "celular": 12, "games": 10,
        "audio": 8, "ferramentas": 6, "carregador": 4, "automacao": 3,
    }
    if category in category_boost:
        b = category_boost[category]
        pts += b
        reasons.append(f"{category} (+{b})")

    return _clamp(pts), reasons


def retention_score(
    discount_percent: int,
    is_lowest_price: bool,
    category: str,
    is_plus: bool,
    review_score: int | None = None,
    review_count: int | None = None,
    waitlisted: int | None = None,
) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    if is_lowest_price:
        pts += 25
        reasons.append("menor preco historico (+25)")

    if discount_percent >= 60:
        pts += 20
        reasons.append(f"desconto excepcional {discount_percent}% (+20)")
    elif discount_percent >= 40:
        pts += 10
        reasons.append(f"grande desconto {discount_percent}% (+10)")

    if is_plus:
        pts += 15
        reasons.append("conteudo PLUS (+15)")

    if review_score is not None and review_score >= 90:
        pts += 15
        reasons.append(f"review score {review_score}% (+15)")
    elif review_score is not None and review_score >= 80:
        pts += 8
        reasons.append(f"review score {review_score}% (+8)")

    if waitlisted is not None and waitlisted >= 5000:
        pts += 10
        reasons.append(f"muito procurado ({waitlisted} waitlisted) (+10)")
    elif waitlisted is not None and waitlisted >= 1000:
        pts += 5
        reasons.append(f"procurado ({waitlisted} waitlisted) (+5)")

    if category in ("games", "informatica", "celular"):
        pts += 5
        reasons.append(f"categoria atrativa (+5)")

    return _clamp(pts), reasons


def confidence_score(obs_count: int, rating: float | None, sales_count: int) -> tuple[int, list[str]]:
    pts = 0
    reasons: list[str] = []

    if obs_count >= 8:
        pts += 40
        reasons.append(f"historico rico ({obs_count} obs) (+40)")
    elif obs_count >= MIN_HISTORY_OBS:
        pts += 25
        reasons.append(f"historico razoavel ({obs_count} obs) (+25)")
    elif obs_count >= 2:
        pts += 10
        reasons.append(f"pouco historico ({obs_count} obs) (+10)")

    if rating is not None and sales_count >= 100:
        pts += 30
        reasons.append("rating + vendas confiaveis (+30)")
    elif rating is not None:
        pts += 15
        reasons.append("tem rating (+15)")

    if sales_count >= 1000:
        pts += 20
        reasons.append("volume alto (+20)")
    elif sales_count >= 100:
        pts += 10
        reasons.append("volume razoavel (+10)")

    return _clamp(pts), reasons


def final_score(
    quality: int,
    conversion: int,
    retention: int,
    confidence: int,
    weights: dict[str, float] | None = None,
) -> float:
    w = weights or COMMERCIAL_WEIGHTS
    return (
        quality * w["quality"]
        + conversion * w["conversion"]
        + retention * w["retention"]
        + confidence * w["confidence"]
    )


def score(
    deal,
    min_price_30d: float | None,
    obs_count: int,
    is_best_seller: bool,
    is_trending: bool,
    avg_price_30d: float | None = None,
    effective_price: float | None = None,
    promotion_savings: float = 0.0,
    promotion_code: str = "",
) -> ScoreResult:
    from price_history import history_confidence

    category = category_match(deal.title)
    scored_price = min(deal.price, effective_price) if effective_price is not None else deal.price
    effective_discount = deal.discount_percent
    if deal.original_price and deal.original_price > scored_price:
        effective_discount = round((deal.original_price - scored_price) / deal.original_price * 100)

    is_lowest = (
        obs_count >= MIN_HISTORY_OBS
        and min_price_30d is not None
        and scored_price <= min_price_30d
    )

    q, q_reasons = quality_score(
        discount_percent=effective_discount,
        price=scored_price,
        min_price_30d=min_price_30d,
        avg_price_30d=avg_price_30d,
        obs_count=obs_count,
        rating=deal.rating,
        official_store=deal.official_store,
        offer_label=deal.offer_label,
    )

    conv, conv_reasons = conversion_score(
        price=scored_price,
        sales_count=deal.sales_count,
        discount_percent=effective_discount,
        is_best_seller=is_best_seller,
        is_trending=is_trending,
        category=category,
    )

    ret, ret_reasons = retention_score(
        discount_percent=effective_discount,
        is_lowest_price=is_lowest,
        category=category,
        is_plus=False,
    )

    conf, conf_reasons = confidence_score(
        obs_count=obs_count,
        rating=deal.rating,
        sales_count=deal.sales_count,
    )

    promo_reasons: list[str] = []
    if promotion_savings > 0 and deal.price > 0:
        savings_pct = promotion_savings / deal.price * 100
        if savings_pct >= 15:
            q = _clamp(q + 20)
            conv = _clamp(conv + 15)
            promo_reasons.append(f"cupom reduz {savings_pct:.0f}% (+20 qualidade/+15 conversao)")
        elif savings_pct >= 8:
            q = _clamp(q + 12)
            conv = _clamp(conv + 10)
            promo_reasons.append(f"cupom reduz {savings_pct:.0f}% (+12 qualidade/+10 conversao)")
        else:
            q = _clamp(q + 6)
            conv = _clamp(conv + 5)
            promo_reasons.append(f"cupom reduz R${promotion_savings:.0f} (+6 qualidade/+5 conversao)")
        if promotion_code:
            conv = _clamp(conv + 5)
            promo_reasons.append(f"cupom {promotion_code} identificado (+5 conversao)")

    all_reasons = q_reasons + conv_reasons + ret_reasons + conf_reasons + promo_reasons
    f = final_score(q, conv, ret, conf)

    price_subtotal = 0
    disc = effective_discount
    if disc > 30:
        price_subtotal += 30
    elif disc >= 15:
        price_subtotal += 15
    if is_lowest:
        price_subtotal += 30
    if promotion_savings > 0:
        # Cupom confirmado é evidência real de preço, mas não substitui sozinho
        # todos os outros sinais.
        price_subtotal += 20 if promotion_savings / max(deal.price, 1) >= 0.08 else 10

    total = round(f)

    return ScoreResult(
        total=total,
        price_subtotal=price_subtotal,
        reasons=all_reasons,
        quality=q,
        conversion=conv,
        retention=ret,
        confidence=conf,
        final=f,
        history_confidence=history_confidence(obs_count),
    )


def score_aliexpress(
    title: str,
    price: float,
    original_price: float | None,
    discount_percent: int,
    sales_count: int = 0,
    commission_rate: float = 0,
    effective_price: float | None = None,
    promotion_savings: float = 0.0,
    promotion_code: str = "",
) -> ScoreResult:
    from price_history import history_confidence

    category = category_match(title)
    scored_price = min(price, effective_price) if effective_price is not None else price
    effective_discount = discount_percent
    if original_price and original_price > scored_price:
        effective_discount = round((original_price - scored_price) / original_price * 100)

    q, q_reasons = quality_score(
        discount_percent=effective_discount,
        price=scored_price,
        min_price_30d=None,
        avg_price_30d=None,
        obs_count=0,
        rating=None,
        official_store=False,
        offer_label="",
    )

    conv, conv_reasons = conversion_score(
        price=scored_price,
        sales_count=sales_count,
        discount_percent=effective_discount,
        is_best_seller=sales_count >= 5000,
        is_trending=False,
        category=category,
    )

    ret, ret_reasons = retention_score(
        discount_percent=effective_discount,
        is_lowest_price=False,
        category=category,
        is_plus=False,
    )

    conf_pts = 0
    conf_reasons: list[str] = []
    if sales_count >= 1000:
        conf_pts += 40
        conf_reasons.append(f"volume alto ali ({sales_count} vendas) (+40)")
    elif sales_count >= 100:
        conf_pts += 20
        conf_reasons.append(f"volume razoavel ali ({sales_count} vendas) (+20)")
    elif sales_count >= 10:
        conf_pts += 5
        conf_reasons.append(f"poucas vendas ali ({sales_count}) (+5)")
    else:
        conf_pts -= 10
        conf_reasons.append("sem vendas ali (-10)")
    conf_pts = _clamp(conf_pts)

    promo_reasons: list[str] = []
    if promotion_savings > 0 and price > 0:
        savings_pct = promotion_savings / price * 100
        q = _clamp(q + (15 if savings_pct >= 10 else 8))
        conv = _clamp(conv + (15 if savings_pct >= 10 else 8))
        promo_reasons.append(f"cupom reduz {savings_pct:.0f}% (+boost comercial)")
        if promotion_code:
            conv = _clamp(conv + 5)
            promo_reasons.append(f"cupom {promotion_code} identificado (+5 conversao)")

    all_reasons = q_reasons + conv_reasons + ret_reasons + conf_reasons + promo_reasons
    f = final_score(q, conv, ret, conf_pts, weights=COMMERCIAL_WEIGHTS)
    total = round(f)

    return ScoreResult(
        total=total,
        price_subtotal=0,
        reasons=all_reasons,
        quality=q,
        conversion=conv,
        retention=ret,
        confidence=conf_pts,
        final=f,
        history_confidence=history_confidence(0),
    )


def score_game(
    title: str,
    price: float,
    original_price: float | None,
    discount_percent: int,
    source: str,
    review_score: int | None = None,
    review_count: int | None = None,
    lowest_price: float | None = None,
    waitlisted: int | None = None,
) -> ScoreResult:
    from price_history import history_confidence

    is_lowest = lowest_price is not None and price <= lowest_price

    q, q_reasons = quality_score(
        discount_percent=discount_percent,
        price=price,
        min_price_30d=lowest_price,
        avg_price_30d=None,
        obs_count=MIN_HISTORY_OBS if lowest_price is not None else 0,
        rating=None,
        official_store=False,
        offer_label="",
    )

    conv, conv_reasons = conversion_score(
        price=price,
        sales_count=0,
        discount_percent=discount_percent,
        is_best_seller=False,
        is_trending=False,
        category="games",
    )

    ret, ret_reasons = retention_score(
        discount_percent=discount_percent,
        is_lowest_price=is_lowest,
        category="games",
        is_plus=True,
        review_score=review_score,
        review_count=review_count,
        waitlisted=waitlisted,
    )

    conf_pts = 0
    conf_reasons: list[str] = []
    if review_count is not None and review_count >= 500:
        conf_pts += 50
        conf_reasons.append(f"jogo conhecido ({review_count} reviews) (+50)")
    elif review_count is not None and review_count >= 100:
        conf_pts += 25
        conf_reasons.append(f"jogo com reviews ({review_count}) (+25)")
    if lowest_price is not None:
        conf_pts += 30
        conf_reasons.append("menor preco ITAD disponivel (+30)")
    conf_pts = _clamp(conf_pts)

    all_reasons = q_reasons + conv_reasons + ret_reasons + conf_reasons
    f = final_score(q, conv, ret, conf_pts, weights=PLUS_WEIGHTS)
    total = round(f)

    return ScoreResult(
        total=total,
        price_subtotal=0,
        reasons=all_reasons,
        quality=q,
        conversion=conv,
        retention=ret,
        confidence=conf_pts,
        final=f,
        history_confidence="high" if lowest_price is not None else "low",
    )
