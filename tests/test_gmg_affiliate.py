from unittest.mock import patch

import gmg_cj


def test_selects_brl_product_catalog_and_ignores_bundle():
    catalogs = [
        {"Id": "bundle", "Name": "BRL Affiliate Bundle Catalog"},
        {"Id": "usd", "Name": "USD Affiliate Product Catalog"},
        {"Id": "brl", "Name": "BRL Affiliate Product Catalog"},
    ]

    assert gmg_cj.select_product_catalog(catalogs, "BRL")["Id"] == "brl"


def test_resolve_discovers_program_and_catalog_when_ids_are_empty():
    program = {"CampaignId": "15105", "AdvertiserId": "3149423"}
    catalogs = [{"Id": "9625", "Name": "BRL Affiliate Product Catalog"}]

    with patch.object(gmg_cj, "find_gmg_program", return_value=program), patch.object(
        gmg_cj, "list_catalogs", return_value=catalogs
    ) as list_catalogs:
        resolved = gmg_cj.resolve_program_and_catalog("sid", "token")

    assert resolved == ("15105", "9625")
    list_catalogs.assert_called_once_with("sid", "token", campaign_id="15105")


def test_resolve_preserves_manual_ids_without_network_calls():
    with patch.object(gmg_cj, "find_gmg_program") as find_program:
        resolved = gmg_cj.resolve_program_and_catalog(
            "sid", "token", program_id="manual-program", catalog_id="manual-catalog"
        )

    assert resolved == ("manual-program", "manual-catalog")
    find_program.assert_not_called()


def test_catalog_items_follow_pagination_up_to_last_page():
    pages = [
        {"Items": [{"Id": "1"}], "@numpages": "2"},
        {"Items": [{"Id": "2"}], "@numpages": "2"},
    ]
    with patch.object(gmg_cj, "_get", side_effect=pages) as get:
        items = gmg_cj.fetch_catalog_items(
            "sid", "token", "catalog", page_size=1000, max_pages=10
        )

    assert [item["Id"] for item in items] == ["1", "2"]
    assert get.call_count == 2
    assert get.call_args_list[0].kwargs["Page"] == 1
    assert get.call_args_list[1].kwargs["Page"] == 2


def test_catalog_items_respect_page_limit():
    page = {"Items": [{"Id": "1"}], "@numpages": "99"}
    with patch.object(gmg_cj, "_get", return_value=page) as get:
        gmg_cj.fetch_catalog_items(
            "sid", "token", "catalog", page_size=500, max_pages=3
        )

    assert get.call_count == 3


def test_promotion_from_deal_embedded_code_is_scoped_to_product():
    deal = gmg_cj.GmgDeal(
        item_id="42", title="Jogo X", price=50.0, original_price=100.0,
        discount_percent=50.0, permalink="https://track", image_url="",
        promo_code="GMG10", promo_description="10% em jogos selecionados",
        promo_is_platform_wide=False,
    )
    promo = gmg_cj.promotion_from_deal(deal)
    assert promo is not None
    assert promo.code == "GMG10"
    assert promo.scope == "product"
    assert promo.product_ids == ["42"]


def test_promotion_from_deal_platform_fallback_is_scoped_to_platform():
    deal = gmg_cj.GmgDeal(
        item_id="42", title="Jogo X", price=50.0, original_price=100.0,
        discount_percent=50.0, permalink="https://track", image_url="",
        promo_code="ACCOUNTWIDE", promo_description="Cupom geral da conta",
        promo_is_platform_wide=True,
    )
    promo = gmg_cj.promotion_from_deal(deal)
    assert promo.scope == "platform"
    assert promo.product_ids == []


def test_promotion_from_deal_without_code_returns_none():
    deal = gmg_cj.GmgDeal(
        item_id="1", title="Jogo", price=10.0, original_price=None,
        discount_percent=0.0, permalink="", image_url="",
    )
    assert gmg_cj.promotion_from_deal(deal) is None


def test_merge_promotions_rejects_layout_false_positive_code():
    import promotion_engine

    deal = gmg_cj.GmgDeal(
        item_id="9", title="Jogo Y", price=20.0, original_price=40.0,
        discount_percent=50.0, permalink="", image_url="",
        promo_code="ATIVADO", promo_description="", promo_is_platform_wide=True,
    )
    embedded = gmg_cj.promotion_from_deal(deal)
    merged = promotion_engine.merge_promotions([embedded])
    assert merged == []


def test_manual_catalog_coupon_applies_when_no_embedded_code():
    import promotion_engine

    deal = gmg_cj.GmgDeal(
        item_id="9", title="Jogo Y", price=20.0, original_price=40.0,
        discount_percent=50.0, permalink="", image_url="",
    )
    catalog = {
        "gmg": [
            {"enabled": True, "kind": "coupon", "code": "GMGLOJA5", "scope": "platform"}
        ]
    }
    embedded = gmg_cj.promotion_from_deal(deal)
    catalog_promos = promotion_engine.promotions_for_item(
        catalog, "gmg", deal.title, deal.price, product_id=deal.item_id
    )
    merged = promotion_engine.merge_promotions(
        [embedded] if embedded else [], catalog_promos
    )
    assert len(merged) == 1
    assert merged[0].code == "GMGLOJA5"
