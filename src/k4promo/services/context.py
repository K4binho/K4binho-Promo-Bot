"""Estado compartilhado de um ciclo.

Antes esses dados eram globais de módulo (``_click_links``, ``_plus_candidates``,
``_showcase_candidates``) e parâmetros repetidos em cada ``run_*_cycle``. Um
contexto explícito deixa claro o que cada ciclo lê e escreve, e torna os testes
independentes entre si.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CycleContext:
    """Tudo que um ciclo precisa para rodar e registrar o que fez."""

    cfg: Any
    dry_run: bool = False

    # Estado persistente carregado no início da execução.
    seen: dict[str, str] = field(default_factory=dict)
    alerts: dict[str, list[dict]] = field(default_factory=dict)
    history: dict[str, list] = field(default_factory=dict)
    published_deals: dict[str, dict] = field(default_factory=dict)
    click_links: dict[str, dict] = field(default_factory=dict)

    # Filas montadas durante o ciclo e consumidas no fim dele.
    plus_candidates: list[dict] = field(default_factory=list)
    showcase_candidates: list[dict] = field(default_factory=list)

    def reset_cycle_queues(self) -> None:
        """Zera o que vale só para o ciclo corrente."""
        self.plus_candidates.clear()
        self.showcase_candidates.clear()
