"""Testes do rate limiter genérico usado por comandos e /buscar."""

from __future__ import annotations

import time

from k4promo.services.rate_limit import WindowRateLimiter


def test_permite_ate_o_limite_e_depois_bloqueia():
    limiter = WindowRateLimiter(max_events=3, window_seconds=60)
    assert limiter.allow("chat1") is True
    assert limiter.allow("chat1") is True
    assert limiter.allow("chat1") is True
    assert limiter.allow("chat1") is False


def test_chaves_diferentes_sao_independentes():
    limiter = WindowRateLimiter(max_events=1, window_seconds=60)
    assert limiter.allow("chat1") is True
    assert limiter.allow("chat2") is True
    assert limiter.allow("chat1") is False
    assert limiter.allow("chat2") is False


def test_chave_global_none_funciona_como_limite_unico():
    limiter = WindowRateLimiter(max_events=2, window_seconds=60)
    assert limiter.allow(None) is True
    assert limiter.allow(None) is True
    assert limiter.allow(None) is False


def test_janela_expira_e_libera_novos_eventos():
    limiter = WindowRateLimiter(max_events=1, window_seconds=0.05)
    assert limiter.allow("chat1") is True
    assert limiter.allow("chat1") is False
    time.sleep(0.07)
    assert limiter.allow("chat1") is True


def test_prune_all_remove_chaves_sem_eventos_recentes():
    limiter = WindowRateLimiter(max_events=1, window_seconds=0.05)
    limiter.allow("chat1")
    time.sleep(0.07)
    limiter.prune_all()
    assert "chat1" not in limiter._events
