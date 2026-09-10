"""Testes da Fase 1: independência real das fontes.

Cobrem os critérios de aceite:
- falha em uma fonte não impede as demais;
- timeout em uma fonte não paralisa as demais;
- o resultado reporta quantas ofertas cada fonte publicou;
- gravações no CycleContext feitas por fontes concorrentes não se perdem.
"""

from __future__ import annotations

import threading
import time
from types import SimpleNamespace

from k4promo.services.context import CycleContext
from k4promo.services.orchestrator import run_sources_concurrently


def _cfg():
    return SimpleNamespace()


def test_falha_em_uma_fonte_nao_impede_as_demais():
    ctx = CycleContext(cfg=_cfg())

    def falha(_ctx):
        raise RuntimeError("boom")

    def ok(_ctx):
        return 2

    results = run_sources_concurrently(
        [("Quebrada", falha), ("Boa", ok)], ctx, max_workers=2, timeout_seconds=5
    )
    by_name = {r.name: r for r in results}

    assert by_name["Quebrada"].posted == 0
    assert by_name["Quebrada"].ok is False
    assert by_name["Boa"].posted == 2
    assert by_name["Boa"].ok is True


def test_timeout_em_uma_fonte_nao_bloqueia_as_demais():
    ctx = CycleContext(cfg=_cfg())

    def trava(_ctx):
        time.sleep(5)
        return 99

    def rapida(_ctx):
        return 1

    started = time.monotonic()
    results = run_sources_concurrently(
        [("Travada", trava), ("Rapida", rapida)], ctx, max_workers=2, timeout_seconds=0.3
    )
    elapsed = time.monotonic() - started
    by_name = {r.name: r for r in results}

    # O ciclo não deve esperar os 5s da fonte travada.
    assert elapsed < 3
    assert by_name["Travada"].timed_out is True
    assert by_name["Travada"].posted == 0
    assert by_name["Rapida"].posted == 1


def test_resultado_reporta_publicacoes_por_fonte():
    ctx = CycleContext(cfg=_cfg())

    def fonte_a(_ctx):
        return 3

    def fonte_b(_ctx):
        return 0

    results = run_sources_concurrently(
        [("A", fonte_a), ("B", fonte_b)], ctx, max_workers=2, timeout_seconds=5
    )
    by_name = {r.name: r.posted for r in results}
    assert by_name == {"A": 3, "B": 0}


def test_max_workers_respeita_limite_configurado():
    ctx = CycleContext(cfg=_cfg())
    lock = threading.Lock()
    concurrent_now = 0
    max_seen = 0

    def fonte(_ctx):
        nonlocal concurrent_now, max_seen
        with lock:
            concurrent_now += 1
            max_seen = max(max_seen, concurrent_now)
        time.sleep(0.05)
        with lock:
            concurrent_now -= 1
        return 1

    sources = [(f"F{i}", fonte) for i in range(6)]
    run_sources_concurrently(sources, ctx, max_workers=2, timeout_seconds=5)

    assert max_seen <= 2


def test_escritas_concorrentes_no_ctx_lock_nao_se_perdem():
    ctx = CycleContext(cfg=_cfg())
    contador = {"n": 0}

    def incrementa(_ctx):
        for _ in range(200):
            with ctx.lock:
                contador["n"] += 1
        return 0

    sources = [(f"F{i}", incrementa) for i in range(5)]
    run_sources_concurrently(sources, ctx, max_workers=5, timeout_seconds=10)

    assert contador["n"] == 5 * 200
