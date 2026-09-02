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
