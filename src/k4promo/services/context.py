"""Estado compartilhado de um ciclo.

Antes esses dados eram globais de módulo (``_click_links``, ``_plus_candidates``,
``_showcase_candidates``) e parâmetros repetidos em cada ``run_*_cycle``. Um
contexto explícito deixa claro o que cada ciclo lê e escreve, e torna os testes
independentes entre si.
"""

from __future__ import annotations

import threading
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
    postgres_state: Any | None = field(default=None, repr=False, compare=False)

    # Filas montadas durante o ciclo e consumidas no fim dele.
    plus_candidates: list[dict] = field(default_factory=list)
    showcase_candidates: list[dict] = field(default_factory=list)

    # Identidades reservadas enquanto uma publicação está sendo concluída.
    # Além de ``seen``, bloqueiam dois IDs diferentes do mesmo produto.
    publication_reservations: set[tuple[str, str]] = field(default_factory=set)
    # Mapeia ID de relistagem para chave histórica canônica.
    republish_keys: dict[str, str] = field(default_factory=dict)

    # Cada ciclo recebe uma geração. Worker que estourou timeout fica inválido
    # quando próximo ciclo começa, mesmo que sua thread ainda esteja viva.
    cycle_epoch: int = 0
    _worker_epoch: threading.local = field(
        default_factory=threading.local, repr=False, compare=False
    )

    # Protege publicação (envio Telegram + gravação de estado compartilhado)
    # quando várias fontes rodam em threads simultâneas. Um RLock permite
    # que o mesmo thread reentre (ex.: publish() chamando showcase.register()
    # que também toca estado protegido) sem deadlock.
    lock: threading.RLock = field(default_factory=threading.RLock, repr=False, compare=False)

    def reset_cycle_queues(self) -> None:
        """Zera o que vale só para o ciclo corrente."""
        self.plus_candidates.clear()
        self.showcase_candidates.clear()
        if self.postgres_state is not None:
            self.postgres_state.clear_reservations()
        self.publication_reservations.clear()
        self.republish_keys.clear()

    def begin_cycle(self) -> int:
        """Abre nova geração e invalida workers de fonte atrasados."""
        with self.lock:
            self.cycle_epoch += 1
            return self.cycle_epoch

    def worker_is_current(self) -> bool:
        """Diz se thread atual pertence ao ciclo corrente.

        Chamadas fora do orquestrador não têm geração local e permanecem
        compatíveis com testes e usos diretos de ``Publisher``.
        """
        worker_epoch = getattr(self._worker_epoch, "value", None)
        return worker_epoch is None or worker_epoch == self.cycle_epoch

    def set_worker_epoch(self, epoch: int | None) -> None:
        """Marca thread atual como worker de ``epoch``."""
        if epoch is None:
            try:
                del self._worker_epoch.value
            except AttributeError:
                pass
        else:
            self._worker_epoch.value = epoch

    def current_epoch(self) -> int:
        """Devolve geração atual."""
        with self.lock:
            return self.cycle_epoch

    def worker_epoch(self) -> int | None:
        """Devolve geração marcada na thread atual."""
        return getattr(self._worker_epoch, "value", None)

    def begin_source_worker(self) -> int:
        """Marca thread atual com geração corrente e devolve geração."""
        epoch = self.current_epoch()
        self._worker_epoch.value = epoch
        return epoch

    def end_source_worker(self) -> None:
        """Remove marca de worker da thread atual."""
        try:
            del self._worker_epoch.value
        except AttributeError:
            pass

    def reserve_publication(
        self, identity: tuple[str, str], item_key: str = ""
    ) -> bool:
        """Reserva identidade; false se já reservada."""
        with self.lock:
            if identity in self.publication_reservations:
                return False
            if self.postgres_state is not None:
                if not self.postgres_state.reserve_publication(identity, item_key):
                    return False
            self.publication_reservations.add(identity)
            return True

    def release_publication(self, identity: tuple[str, str]) -> None:
        """Libera reserva após falha de envio."""
        with self.lock:
            if self.postgres_state is not None:
                self.postgres_state.release_publication(identity)
            self.publication_reservations.discard(identity)
