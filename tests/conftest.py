"""Fixtures compartilhadas da suíte.

Autouse: por padrão nenhum teste faz uma requisição HTTP de verdade pra
validar link (Fase 6, services/link_validation.py) — todo link é tratado
como válido (HEAD 200), assim a suíte não depende de rede real nem fica
lenta/instável. Testes que precisam do comportamento real de validação
(tests/test_link_validation.py) sobrescrevem ``httpx.head``/``httpx.get``
localmente, o que funciona normalmente por cima deste fixture.
"""

from __future__ import annotations

import httpx
import pytest

from k4promo.services import link_validation


@pytest.fixture(autouse=True)
def _no_real_link_validation_network(monkeypatch):
    def _fake_head(url, *args, **kwargs):
        return httpx.Response(200, request=httpx.Request("HEAD", url))

    monkeypatch.setattr(httpx, "head", _fake_head)
    link_validation.clear_cache()
    yield
    link_validation.clear_cache()
