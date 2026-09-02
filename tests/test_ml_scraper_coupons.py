import ml_scraper


def _card(*, url: str, price_label: str, coupon_html: str) -> str:
    return f'''class="poly-card"
    <a class="poly-component__title" href="{url}">Produto com cupom</a>
    <span class="andes-money-amount" aria-label="{price_label}"></span>
    {coupon_html}
    '''


def _coupon(value_label: str, suffix: str) -> str:
    return f'''<div class="poly-component__coupons"><div>
    <span aria-label="{value_label}"></span> {suffix}
    </div></div>'''


def test_card_accepts_new_product_url_and_fixed_coupon():
    card = _card(
        url="https://produto.mercadolivre.com.br/MLB-5532075156-produto-_JM",
        price_label="78 reais com 90 centavos",
        coupon_html=_coupon("20 reais", "OFF com Cupom"),
    )

    deal = ml_scraper._parse_card(card)

    assert deal is not None
    assert deal.item_id == "MLB5532075156"
    assert deal.price == 78.9
    assert deal.coupon_amount == 20.0


def test_card_converts_coupon_final_price_to_savings():
    card = _card(
        url="https://www.mercadolivre.com.br/p/MLB23037572?pdp_filters=item_id",
        price_label="229 reais com 90 centavos",
        coupon_html=_coupon("211 reais com 50 centavos", "com Cupom"),
    )

    deal = ml_scraper._parse_card(card)

    assert deal is not None
    assert deal.price == 229.9
    assert deal.coupon_amount == 18.4


def test_coupon_price_above_regular_price_is_rejected():
    card = _card(
        url="https://www.mercadolivre.com.br/p/MLB23037572",
        price_label="100 reais",
        coupon_html=_coupon("120 reais", "com Cupom"),
    )

    deal = ml_scraper._parse_card(card)

    assert deal is not None
    assert deal.coupon_amount is None
