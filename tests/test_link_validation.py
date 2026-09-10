"""Testes da Fase 6 (seção 20): validação de link.

Regras: link vazio é inválido; 404/410 são definitivamente inválidos; 405 no
HEAD tenta GET antes de decidir; timeout/DNS/5xx são inconclusivos e NÃO
bloqueiam; cache de curta duração evita bater o mesmo link duas vezes.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest import mock

import httpx
import pytest

from k4promo import telegram
from k4promo.domain import topics
from k4promo.domain.models import Offer
from k4promo.services import analytics, link_validation
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.scoring import ScoreResult


def _resp(status: int, url: str = "https://loja.com/produto") -> httpx.Response:
    return httpx.Response(status, request=httpx.Request("HEAD", url))


@pytest.fixture(autouse=True)
def _clear():
    link_validation.clear_cache()
    yield
    link_validation.clear_cache()


# ---------------------------------------------------------------------------
# check_link / is_blocked
# ---------------------------------------------------------------------------

def test_link_vazio_e_invalido():
    assert link_validation.is_blocked("") is True
    assert link_validation.is_blocked("   ") is True


@mock.patch.object(httpx, "head")
def test_404_e_invalido(head):
    head.return_value = _resp(404)
    assert link_validation.is_blocked("https://loja.com/x") is True


@mock.patch.object(httpx, "head")
def test_410_e_invalido(head):
    head.return_value = _resp(410)
    assert link_validation.is_blocked("https://loja.com/x") is True


@mock.patch.object(httpx, "head")
def test_200_e_valido(head):
    head.return_value = _resp(200)
    assert link_validation.is_blocked("https://loja.com/x") is False


@mock.patch.object(httpx, "get")
@mock.patch.object(httpx, "head")
def test_405_no_head_tenta_get(head, get):
    head.return_value = _resp(405)
    get.return_value = _resp(200)
    assert link_validation.is_blocked("https://loja.com/x") is False
    get.assert_called_once()


@mock.patch.object(httpx, "get")
@mock.patch.object(httpx, "head")
def test_405_no_head_e_404_no_get_e_invalido(head, get):
    head.return_value = _resp(405)
    get.return_value = _resp(404)
    assert link_validation.is_blocked("https://loja.com/x") is True


@mock.patch.object(httpx, "head", side_effect=httpx.ConnectTimeout("timeout"))
def test_timeout_e_inconclusivo_nao_bloqueia(_head):
    assert link_validation.is_blocked("https://loja.com/x") is False


@mock.patch.object(httpx, "head", side_effect=httpx.ConnectError("dns falhou"))
def test_erro_de_dns_e_inconclusivo_nao_bloqueia(_head):
    assert link_validation.is_blocked("https://loja.com/x") is False


@mock.patch.object(httpx, "head")
def test_5xx_e_inconclusivo_nao_bloqueia(head):
    head.return_value = _resp(503)
    assert link_validation.is_blocked("https://loja.com/x") is False


@mock.patch.object(httpx, "head")
def test_cache_evita_checar_o_mesmo_link_duas_vezes(head):
    head.return_value = _resp(404)
    link_validation.check_link("https://loja.com/x")
    link_validation.check_link("https://loja.com/x")
    assert head.call_count == 1


@mock.patch.object(httpx, "head")
def test_cache_expira_apos_o_ttl(head, monkeypatch):
    monkeypatch.setattr(link_validation, "CACHE_TTL_SECONDS", 0.05)
    head.return_value = _resp(404)
    link_validation.check_link("https://loja.com/x")
    import time
    time.sleep(0.07)
    link_validation.check_link("https://loja.com/x")
    assert head.call_count == 2


# ---------------------------------------------------------------------------
# Publisher: link bloqueado não publica; inconclusivo publica normalmente
# ---------------------------------------------------------------------------

def _cfg():
    return SimpleNamespace(
        telegram_bot_token="token", telegram_channel_id="channel",
        telegram_thread_id=None, telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        click_tracking_enabled=False,
    )


def _offer():
    return Offer(source="shopee", offer_id="1", title="Air Fryer", price=99.0,
                 permalink="https://loja/1", original_price=199.0, image_url="https://img",
                 discount_percent=50)


def _result():
    return ScoreResult(total=80, price_subtotal=30, reasons=[], quality=70,
                       conversion=60, retention=40, confidence=50, final=80.0)


class TestPublisherLinkValidation:
    def setup_method(self):
        self.ctx = CycleContext(cfg=_cfg())
        self.publisher = Publisher(self.ctx)

    @mock.patch.object(telegram, "send_message")
    @mock.patch.object(httpx, "head")
    def test_link_404_nao_publica(self, head, send_message):
        head.return_value = _resp(404)
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://loja/1", log_tag="Shopee",
        )
        assert ok is False
        send_message.assert_not_called()

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", return_value=1)
    @mock.patch.object(httpx, "head", side_effect=httpx.ConnectTimeout("timeout"))
    def test_link_com_timeout_publica_normalmente(self, _head, send_message, _rec):
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://loja/1", log_tag="Shopee",
        )
        assert ok is True
        send_message.assert_called_once()
