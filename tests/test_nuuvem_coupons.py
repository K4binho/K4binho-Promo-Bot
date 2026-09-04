"""Cobre o parser de cupons da Nuuvem (fetch_coupons). A pagina muda de
layout HTML a cada campanha; estes testes usam marcacao deliberadamente
diferente da usada no parser antigo (sem classes/tags "coupon") pra provar
que a extracao agora depende só do texto visível, não da marcação exata."""
from unittest.mock import patch

import httpx

import nuuvem


class _Resp:
    def __init__(self, text, status_code=200):
        self.text = text
        self.status_code = status_code


_SAMPLE_HTML = """
<main>
  <h1>Cupons Disponíveis</h1>
  <section>
    <h4>Cupom: PALAMIGO</h4>
    <p>Descrição: 8% de desconto para o lançamento oficial de Palworld</p>
    <small>Usos extremamente limitados, por isso podem acabar a qualquer momento.</small>
    <p>Países: LATAM</p>
    <a href="/item/palworld">Acesse Agora</a>
  </section>
  <section>
    <h4>Cupom: VIETNAM5</h4>
    <p>Descrição: 5% de desconto para o lançamento de Hell Let Loose: Vietnam</p>
    <p>Países: LATAM</p>
    <a href="/item/hell-let-loose-vietnam">Acesse Agora</a>
  </section>
  <section>
    <h4>Cupom: MEUGTAMINHAVIDA</h4>
    <p>Descrição: Garanta sua pré-venda de GTA 6 com desconto.</p>
    <a href="/lp/gta-6">Acesse Agora</a>
  </section>
  <section>
    <h4>Cupom de R$30 em compras</h4>
    <p>Descrição: Ao comprar Capcom Arcade Stadium Complete Pack, receberá um cupom de R$30.</p>
  </section>
</main>
"""


def test_fetch_coupons_parses_layout_without_coupon_css_classes():
    with patch.object(nuuvem.httpx, "get", return_value=_Resp(_SAMPLE_HTML)):
        coupons = nuuvem.fetch_coupons()
    codes = {c.code: c for c in coupons}
    assert "PALAMIGO" in codes
    assert codes["PALAMIGO"].discount == "8%"
    assert "palworld" in codes["PALAMIGO"].game.lower()
    assert "VIETNAM5" in codes
    assert "vietnam" in codes["VIETNAM5"].game.lower()


def test_fetch_coupons_skips_code_without_identifiable_discount():
    # MEUGTAMINHAVIDA nao tem percentual/valor extraivel -> nao ha evidencia
    # suficiente do beneficio, nao deve ser anunciado.
    with patch.object(nuuvem.httpx, "get", return_value=_Resp(_SAMPLE_HTML)):
        coupons = nuuvem.fetch_coupons()
    assert "MEUGTAMINHAVIDA" not in {c.code for c in coupons}


def test_fetch_coupons_skips_reward_without_explicit_code():
    # "Cupom de R$30 em compras" nao tem um CODIGO pra resgatar (beneficio
    # automatico), entao nao deve virar um NuuvemCoupon com codigo falso.
    with patch.object(nuuvem.httpx, "get", return_value=_Resp(_SAMPLE_HTML)):
        coupons = nuuvem.fetch_coupons()
    assert all(c.code.isupper() and c.code.isalnum() for c in coupons)


def test_fetch_coupons_matches_deal_title_via_match_coupon():
    with patch.object(nuuvem.httpx, "get", return_value=_Resp(_SAMPLE_HTML)):
        coupons = nuuvem.fetch_coupons()
    match = nuuvem._match_coupon("Palworld - Deluxe Edition", coupons)
    assert match is not None
    assert match.code == "PALAMIGO"


def test_fetch_coupons_http_error_returns_empty():
    with patch.object(nuuvem.httpx, "get", side_effect=httpx.ConnectTimeout("timeout")):
        assert nuuvem.fetch_coupons() == []


_CAMPAIGN_SAMPLE_HTML = """
<section>
  <p>Use o cupom e garanta 15% OFF em suas compras!</p>
  <small>*Válido para produtos selecionados de PC. Uso limitado.</small>
  <button>COMEMORENUU<span>Copiado!</span></button>
</section>
<section>
  <p>Use o cupom e garanta 10% OFF em suas compras!</p>
  <small>*Válido para produtos selecionados de PC. Uso limitado.</small>
  <button>ANUUVERSARIO<span>Copiado!</span></button>
</section>
"""


def test_fetch_campaign_coupons_parses_platform_wide_codes():
    with patch.object(nuuvem.httpx, "get", return_value=_Resp(_CAMPAIGN_SAMPLE_HTML)):
        coupons = nuuvem.fetch_campaign_coupons()
    codes = {c.code: c for c in coupons}
    assert codes["COMEMORENUU"].discount == "15%"
    assert codes["COMEMORENUU"].game == ""
    assert codes["ANUUVERSARIO"].discount == "10%"


def test_best_platform_coupon_picks_highest_discount():
    coupons = [
        nuuvem.NuuvemCoupon(code="ANUUVERSARIO", discount="10%", game="", region="BR"),
        nuuvem.NuuvemCoupon(code="COMEMORENUU", discount="15%", game="", region="BR"),
    ]
    best = nuuvem._best_platform_coupon(coupons)
    assert best.code == "COMEMORENUU"


def test_best_platform_coupon_ignores_product_specific():
    coupons = [nuuvem.NuuvemCoupon(code="PALAMIGO", discount="8%", game="Palworld", region="BR")]
    assert nuuvem._best_platform_coupon(coupons) is None


def test_fetch_campaign_coupons_no_event_returns_empty():
    with patch.object(nuuvem.httpx, "get", return_value=_Resp("<p>Nada por aqui.</p>")):
        assert nuuvem.fetch_campaign_coupons() == []


def test_fetch_coupons_non_200_returns_empty():
    with patch.object(nuuvem.httpx, "get", return_value=_Resp("", status_code=500)):
        assert nuuvem.fetch_coupons() == []


def _itad_response(title="Some Random Game"):
    return {
        "list": [
            {
                "type": "game",
                "id": "g1",
                "title": title,
                "deal": {
                    "price": {"amount": 45.0},
                    "regular": {"amount": 90.0},
                    "cut": 50,
                },
                "assets": {},
            }
        ]
    }


class _JsonResp:
    def __init__(self, payload):
        self._payload = payload
        self.status_code = 200

    def json(self):
        return self._payload

    def raise_for_status(self):
        pass


def test_fetch_deals_attaches_platform_coupon_when_no_product_coupon():
    itad_first = _JsonResp(_itad_response())
    itad_empty = _JsonResp({"list": []})
    platform_coupon = nuuvem.NuuvemCoupon(code="COMEMORENUU", discount="15%", game="", region="BR")
    with patch.object(nuuvem, "fetch_coupons", return_value=[]), \
            patch.object(nuuvem, "fetch_campaign_coupons", return_value=[platform_coupon]), \
            patch.object(nuuvem.httpx, "get", side_effect=[itad_first, itad_empty]):
        deals = nuuvem.fetch_deals("fake-key")
    assert len(deals) == 1
    assert deals[0].coupon is not None
    assert deals[0].coupon.code == "COMEMORENUU"


def test_fetch_deals_prefers_product_specific_coupon_over_platform():
    itad_first = _JsonResp(_itad_response(title="Palworld"))
    itad_empty = _JsonResp({"list": []})
    product_coupon = nuuvem.NuuvemCoupon(code="PALAMIGO", discount="8%", game="Palworld", region="BR")
    platform_coupon = nuuvem.NuuvemCoupon(code="COMEMORENUU", discount="15%", game="", region="BR")
    with patch.object(nuuvem, "fetch_coupons", return_value=[product_coupon]), \
            patch.object(nuuvem, "fetch_campaign_coupons", return_value=[platform_coupon]), \
            patch.object(nuuvem.httpx, "get", side_effect=[itad_first, itad_empty]):
        deals = nuuvem.fetch_deals("fake-key")
    assert deals[0].coupon.code == "PALAMIGO"

