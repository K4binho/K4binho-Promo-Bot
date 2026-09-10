"""Testes da Fase 4 (seções 16-18): deduplicação e republicação por fonte.

Cobre os critérios de aceite da seção 30: queda de preço, novo cupom, menor
preço histórico e período configurado autorizam republicação; reaparecer na
API não significa produto novo (chave já vista continua vista); message_id é
armazenado; exclusão do post anterior é best effort.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

import httpx

from k4promo import telegram
from k4promo.domain import topics
from k4promo.domain.models import Offer
from k4promo.services import analytics, dedup
from k4promo.services.context import CycleContext
from k4promo.services.publisher import Publisher
from k4promo.services.scoring import ScoreResult
from k4promo.storage import deal_store as ds


def _cfg(**overrides):
    base = dict(
        telegram_bot_token="token", telegram_channel_id="channel",
        telegram_thread_id=None, telegram_topic_ids=dict(topics.DEFAULT_TOPIC_IDS),
        click_tracking_enabled=False,
        showcase_min_physical_discount=40, showcase_min_game_discount=70,
    )
    base.update(overrides)
    return SimpleNamespace(**base)


def _result():
    return ScoreResult(total=80, price_subtotal=30, reasons=[], quality=70,
                       conversion=60, retention=40, confidence=50, final=80.0)


def _offer(**overrides):
    base = dict(
        source="shopee", offer_id="1", title="Air Fryer", price=99.0,
        permalink="https://loja/1", original_price=199.0, image_url="https://img",
        discount_percent=50,
    )
    base.update(overrides)
    return Offer(**base)


# ---------------------------------------------------------------------------
# Normalização e relistagem sob outro ID
# ---------------------------------------------------------------------------

def test_normalize_title_ignora_pontuacao_caixa_e_espacos():
    assert ds.normalize_title("  Air Fryer -- 5L!! ") == ds.normalize_title("air fryer 5l")


def test_normalize_url_ignora_query_string_e_barra_final():
    a = ds.normalize_url("https://loja.com/produto/123?utm=x&ref=y")
    b = ds.normalize_url("https://loja.com/produto/123/")
    assert a == b


def test_find_by_normalized_title_encontra_mesma_loja():
    deals = {"shopee:1": {"normalized_title": "air fryer 5l"}}
    found = ds.find_by_normalized_title(deals, "shopee", "air fryer 5l")
    assert found == ("shopee:1", deals["shopee:1"])


def test_find_by_normalized_title_nunca_cruza_lojas():
    deals = {"kabum:1": {"normalized_title": "air fryer 5l"}}
    found = ds.find_by_normalized_title(deals, "shopee", "air fryer 5l")
    assert found is None


def test_find_by_normalized_title_ml_usa_chave_sem_prefixo():
    deals = {"MLB1": {"normalized_title": "air fryer 5l"}, "shopee:9": {"normalized_title": "air fryer 5l"}}
    found = ds.find_by_normalized_title(deals, "ml", "air fryer 5l")
    assert found == ("MLB1", deals["MLB1"])


def test_find_by_normalized_title_aceita_aliases_do_aliexpress():
    deals = {
        "ali:1": {"normalized_title": "controle sem fio"},
        "aliexpress:2": {"normalized_title": "outro produto"},
    }
    assert ds.find_by_normalized_title(
        deals, "aliexpress", "controle sem fio"
    ) == ("ali:1", deals["ali:1"])


# ---------------------------------------------------------------------------
# record_published — schema completo, aditivo
# ---------------------------------------------------------------------------

def test_record_published_grava_message_id_e_thread_id():
    deals = {}
    ds.record_published(
        deals, "shopee:1", 99.0, title="Air Fryer", url="https://loja/1",
        message_id=555, thread_id=2198,
    )
    entry = deals["shopee:1"]
    assert entry["message_id"] == 555
    assert entry["thread_id"] == 2198
    assert entry["normalized_title"] == "air fryer"
    assert entry["republish_count"] == 0
    assert entry["first_posted_at"] == entry["posted_at"]


def test_record_published_incrementa_republish_count_e_mantem_first_posted_at():
    deals = {}
    ds.record_published(deals, "shopee:1", 100.0)
    first = deals["shopee:1"]["first_posted_at"]
    ds.record_published(deals, "shopee:1", 90.0, reason="queda_de_preco")
    entry = deals["shopee:1"]
    assert entry["republish_count"] == 1
    assert entry["first_posted_at"] == first
    assert entry["last_reason"] == "queda_de_preco"


def test_record_published_best_price_acompanha_o_minimo_historico():
    deals = {}
    ds.record_published(deals, "shopee:1", 100.0)
    ds.record_published(deals, "shopee:1", 120.0)  # subiu de novo
    assert deals["shopee:1"]["best_price"] == 100.0
    assert deals["shopee:1"]["price"] == 120.0


def test_record_published_preserva_message_id_quando_nao_informado_de_novo():
    deals = {}
    ds.record_published(deals, "shopee:1", 100.0, message_id=555)
    ds.record_published(deals, "shopee:1", 90.0)
    assert deals["shopee:1"]["message_id"] == 555


# ---------------------------------------------------------------------------
# Regras individuais novas da Fase 4
# ---------------------------------------------------------------------------

def test_check_lowest_price_ever():
    deals = {"shopee:1": {"price": 100.0, "best_price": 100.0}}
    is_lowest, prev = ds.check_lowest_price_ever(deals, "shopee:1", 90.0)
    assert is_lowest is True
    assert prev == 100.0


def test_check_lowest_price_ever_falso_se_nao_bate_o_piso():
    deals = {"shopee:1": {"price": 150.0, "best_price": 90.0}}
    is_lowest, _ = ds.check_lowest_price_ever(deals, "shopee:1", 100.0)
    assert is_lowest is False


def test_check_period_elapsed_respeita_min_days():
    old = (datetime.now(UTC) - timedelta(days=10)).isoformat()
    deals = {"shopee:1": {"posted_at": old, "price": 100.0}}
    assert ds.check_period_elapsed(deals, "shopee:1", min_days=7) is True
    assert ds.check_period_elapsed(deals, "shopee:1", min_days=30) is False


def test_check_period_elapsed_desativado_com_min_days_zero():
    old = (datetime.now(UTC) - timedelta(days=999)).isoformat()
    deals = {"shopee:1": {"posted_at": old, "price": 100.0}}
    assert ds.check_period_elapsed(deals, "shopee:1", min_days=0) is False


# ---------------------------------------------------------------------------
# should_republish — regra unificada, com prioridade
# ---------------------------------------------------------------------------

def test_should_republish_item_nunca_visto_nao_republica():
    should, reason, _ = ds.should_republish({}, "shopee:1", 100.0)
    assert should is False
    assert reason == ""


def test_should_republish_menor_preco_historico_tem_prioridade():
    deals = {
        "shopee:1": {
            "price": 100.0, "best_price": 100.0,
            "posted_at": datetime.now(UTC).isoformat(),
            "promotion_signature": "",
        }
    }
    should, reason, _ = ds.should_republish(deals, "shopee:1", 50.0, promotion_signature="CUPOM10")
    # 50.0 é menor que o piso histórico (100) E teria drop E teria cupom novo —
    # menor_preco_historico vence por prioridade.
    assert should is True
    assert reason == "menor_preco_historico"


def test_should_republish_queda_de_preco_quando_nao_e_novo_piso():
    deals = {
        "shopee:1": {
            "price": 100.0, "best_price": 60.0,  # já esteve mais barato antes
            "posted_at": datetime.now(UTC).isoformat(),
            "promotion_signature": "",
        }
    }
    should, reason, prev = ds.should_republish(deals, "shopee:1", 80.0)
    assert should is True
    assert reason == "queda_de_preco"
    assert prev == 100.0


def test_should_republish_periodo_configurado_sem_mudanca_de_preco():
    old = (datetime.now(UTC) - timedelta(days=15)).isoformat()
    deals = {
        "shopee:1": {
            "price": 100.0, "best_price": 100.0, "posted_at": old,
            "promotion_signature": "",
        }
    }
    should, reason, _ = ds.should_republish(deals, "shopee:1", 100.0, repost_min_days=7)
    assert should is True
    assert reason == "periodo_configurado"


def test_should_republish_nada_muda_nao_republica():
    deals = {
        "shopee:1": {
            "price": 100.0, "best_price": 100.0,
            "posted_at": datetime.now(UTC).isoformat(),
            "promotion_signature": "",
        }
    }
    should, reason, _ = ds.should_republish(deals, "shopee:1", 100.0)
    assert should is False
    assert reason == ""


# ---------------------------------------------------------------------------
# dedup.reinject_republishable
# ---------------------------------------------------------------------------

def test_reinject_ignora_oferta_que_nunca_foi_vista():
    ctx = CycleContext(cfg=_cfg())
    offer = _offer()
    result = dedup.reinject_republishable(ctx, [offer])
    assert result == []


def test_reinject_devolve_oferta_ja_vista_com_queda_de_preco():
    ctx = CycleContext(cfg=_cfg())
    ctx.seen["shopee:1"] = "2026-01-01T00:00:00"
    ds.record_published(ctx.published_deals, "shopee:1", 60.0)   # piso histórico
    ds.record_published(ctx.published_deals, "shopee:1", 100.0)  # subiu de novo

    offer = _offer(price=80.0)  # caiu, mas não é o menor preço já visto (60)
    result = dedup.reinject_republishable(ctx, [offer])

    assert len(result) == 1
    reoffer, reason, prev_price = result[0]
    assert reoffer is offer
    assert reason == "queda_de_preco"
    assert prev_price == 100.0


def test_reinject_nao_devolve_oferta_ja_vista_sem_mudanca():
    ctx = CycleContext(cfg=_cfg())
    ctx.seen["shopee:1"] = "2026-01-01T00:00:00"
    ds.record_published(ctx.published_deals, "shopee:1", 100.0)

    offer = _offer(price=100.0)
    result = dedup.reinject_republishable(ctx, [offer])

    assert result == []


# ---------------------------------------------------------------------------
# Publisher: message_id armazenado + exclusão best-effort do post anterior
# ---------------------------------------------------------------------------

class TestPublisherRepublish:
    def setup_method(self):
        self.ctx = CycleContext(cfg=_cfg())
        self.publisher = Publisher(self.ctx)

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", return_value=999)
    def test_publish_expoe_message_id_e_thread_id(self, _send, _rec):
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        )
        assert ok is True
        assert self.publisher.last_message_id == 999
        assert self.publisher.last_thread_id == 2198

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "delete_message")
    @mock.patch.object(telegram, "send_message", return_value=1001)
    def test_publish_apaga_post_anterior_quando_e_republicacao(self, _send, delete, _rec):
        self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg novo", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
            previous_message=(555, 2198),
        )
        delete.assert_called_once_with("token", "channel", 555)

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "delete_message", side_effect=httpx.HTTPError("boom"))
    @mock.patch.object(telegram, "send_message", return_value=1002)
    def test_falha_ao_apagar_post_anterior_nao_bloqueia_republicacao(self, _send, _delete, _rec):
        ok = self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg novo", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
            previous_message=(555, 2198),
        )
        assert ok is True

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "delete_message")
    @mock.patch.object(telegram, "send_message")
    def test_sem_previous_message_nao_tenta_apagar_nada(self, _send, delete, _rec):
        self.publisher.publish(
            _offer(), topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        )
        delete.assert_not_called()

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", return_value=1003)
    def test_id_diferente_com_mesmo_titulo_e_bloqueado(self, _send, _rec):
        first = _offer(offer_id="1")
        relisted = _offer(offer_id="2", permalink="https://loja/2")
        assert self.publisher.publish(
            first, topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        ) is True
        assert self.publisher.publish(
            relisted, topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l2", log_tag="Shopee",
        ) is False

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", return_value=1004)
    def test_mesmo_titulo_em_lojas_diferentes_pode_publicar(self, _send, _rec):
        shopee = _offer(source="shopee", offer_id="1")
        kabum = _offer(source="kabum", offer_id="1")
        assert self.publisher.publish(
            shopee, topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://shopee", log_tag="Shopee",
        ) is True
        assert self.publisher.publish(
            kabum, topic=topics.TECNOLOGIA, text="msg", result=_result(),
            score=80, link="https://kabum", log_tag="Kabum",
        ) is True

    @mock.patch.object(analytics, "record_deal")
    @mock.patch.object(telegram, "send_message", side_effect=[httpx.HTTPError("boom"), 1005])
    def test_falha_envio_libera_reserva_para_retry(self, _send, _rec):
        offer = _offer()
        assert self.publisher.publish(
            offer, topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        ) is False
        assert self.publisher.publish(
            offer, topic=topics.CASA_COZINHA, text="msg", result=_result(),
            score=80, link="https://l", log_tag="Shopee",
        ) is True

    def test_relistagem_mapeia_id_novo_para_chave_historica(self):
        self.ctx.seen["shopee:1"] = "2026-01-01T00:00:00"
        ds.record_published(
            self.ctx.published_deals, "shopee:1", 100.0,
            title="Air Fryer", message_id=555, thread_id=2198,
        )
        relisted = _offer(offer_id="2", price=70.0, permalink="https://loja/2")
        result = dedup.reinject_republishable(self.ctx, [relisted])
        assert len(result) == 1
        assert self.ctx.republish_keys == {"shopee:2": "shopee:1"}
        assert result[0][1] == "menor_preco_historico"

    def test_relistagem_com_queda_preserva_oferta_para_republicacao(self):
        self.ctx.seen["shopee:1"] = "2026-01-01T00:00:00"
        ds.record_published(
            self.ctx.published_deals, "shopee:1", 100.0,
            title="Air Fryer", message_id=555, thread_id=2198,
        )
        relisted = _offer(offer_id="2", price=70.0)
        filtered = dedup.drop_relisted(
            [relisted], self.ctx.published_deals,
            source_of=lambda _offer: "shopee", seen=self.ctx.seen,
        )
        assert filtered == [relisted]
