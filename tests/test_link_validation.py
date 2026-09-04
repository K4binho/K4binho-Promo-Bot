from unittest.mock import patch

import httpx

import link_validation as lv


class _Resp:
    def __init__(self, status_code):
        self.status_code = status_code


def test_empty_link_is_considered_broken():
    assert lv.link_is_broken("") is True


def test_404_is_broken():
    with patch.object(lv.httpx, "head", return_value=_Resp(404)):
        assert lv.link_is_broken("https://x") is True


def test_410_is_broken():
    with patch.object(lv.httpx, "head", return_value=_Resp(410)):
        assert lv.link_is_broken("https://x") is True


def test_200_is_not_broken():
    with patch.object(lv.httpx, "head", return_value=_Resp(200)):
        assert lv.link_is_broken("https://x") is False


def test_405_falls_back_to_get():
    with patch.object(lv.httpx, "head", return_value=_Resp(405)), \
            patch.object(lv.httpx, "get", return_value=_Resp(200)) as get:
        assert lv.link_is_broken("https://x") is False
    get.assert_called_once()


def test_network_error_does_not_block_publish():
    with patch.object(lv.httpx, "head", side_effect=httpx.ConnectTimeout("timeout")):
        assert lv.link_is_broken("https://x") is False


def test_5xx_does_not_block_publish():
    with patch.object(lv.httpx, "head", return_value=_Resp(503)):
        assert lv.link_is_broken("https://x") is False


def test_image_unreachable_network_error_is_lenient():
    with patch.object(lv.httpx, "head", side_effect=httpx.ConnectTimeout("timeout")):
        assert lv.image_is_reachable("https://img") is True


def test_image_404_is_not_reachable():
    with patch.object(lv.httpx, "head", return_value=_Resp(404)):
        assert lv.image_is_reachable("https://img") is False


def test_empty_image_url_is_not_reachable():
    assert lv.image_is_reachable("") is False
