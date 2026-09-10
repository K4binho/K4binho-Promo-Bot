"""Execução concorrente das fontes (lojas) com isolamento real.

Cada fonte roda em sua própria thread. Uma fonte que lança exceção ou
estoura o timeout não impede as demais: o resultado dela vira 0 e o ciclo
segue. O contexto compartilhado (``CycleContext``) é protegido por um lock
único (``ctx.lock``); ``Publisher.publish`` e os pontos que gravam estado
compartilhado usam esse lock para serializar o que precisa ser serializado
(envio ao Telegram, gravação de JSON), enquanto a coleta/avaliação de cada
fonte roda livre em paralelo.

Isso é a solução "lock centralizado" citada no plano de hardening: uma fila
de publicação dedicada é a evolução natural, mas o lock já garante ausência
de corrupção de estado com o modelo atual de ``run(ctx) -> int``.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import NamedTuple

from k4promo.services.context import CycleContext

log = logging.getLogger("k4binho")


class SourceResult(NamedTuple):
    name: str
    posted: int
    ok: bool
    timed_out: bool


RunFn = Callable[[CycleContext], int]


def run_sources_concurrently(
    sources: list[tuple[str, RunFn]],
    ctx: CycleContext,
    *,
    max_workers: int = 5,
    timeout_seconds: float = 180,
) -> list[SourceResult]:
    """Roda todas as fontes em paralelo, respeitando ``max_workers``.

    - Uma exceção em uma fonte é logada e produz resultado 0; as demais
      fontes continuam normalmente.
    - Um timeout faz a fonte ser considerada "abandonada" (0 publicações);
      a thread pode continuar rodando em segundo plano até terminar
      sozinha, mas o ciclo não espera por ela.
    - A ordem de conclusão é a ordem real de término, não a de submissão.
    """
    if not sources:
        return []

    results: list[SourceResult] = []
    max_workers = max(1, min(max_workers, len(sources)))

    # Gerenciado manualmente (sem `with`): o `__exit__` do ThreadPoolExecutor
    # chama shutdown(wait=True), que bloquearia até a(s) thread(s) travada(s)
    # terminarem sozinhas — exatamente o que o timeout existe pra evitar.
    pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="source")
    try:
        future_to_name = {}
        for name, run_fn in sources:
            log.info("[%s] tarefa iniciada.", name)
            future = pool.submit(_run_source, name, run_fn, ctx)
            future_to_name[future] = name

        pending = set(future_to_name)
        deadline = time.monotonic() + timeout_seconds
        while pending:
            remaining = max(0.0, deadline - time.monotonic())
            done, pending = wait(pending, timeout=remaining, return_when=FIRST_COMPLETED)
            if not done:
                # Deadline global estourado: as pendentes são consideradas
                # abandonadas. A thread pode seguir rodando sozinha (sync,
                # não cancelável), mas o ciclo não espera mais por ela.
                for fut in list(pending):
                    name = future_to_name[fut]
                    log.error("[%s] timeout (%ss); fonte abandonada.", name, timeout_seconds)
                    results.append(SourceResult(name, 0, ok=False, timed_out=True))
                break
            for fut in done:
                name = future_to_name[fut]
                try:
                    posted = fut.result()
                    results.append(SourceResult(name, posted, ok=True, timed_out=False))
                except Exception as exc:
                    log.error("[%s] falhou; demais fontes continuarão: %s", name, exc)
                    results.append(SourceResult(name, 0, ok=False, timed_out=False))
    finally:
        # wait=False: não bloqueia pela(s) thread(s) abandonada(s) por
        # timeout. Threads sync (httpx/Playwright) não são canceláveis de
        # fora, então elas terminam sozinhas em segundo plano.
        pool.shutdown(wait=False, cancel_futures=True)

    return results


def _run_source(name: str, run_fn: RunFn, ctx: CycleContext) -> int:
    """Roda fonte dentro da geração corrente."""
    ctx.begin_source_worker()
    try:
        posted = run_fn(ctx)
        log.info("[%s] concluída: %d oferta(s).", name, posted)
        return posted
    finally:
        ctx.end_source_worker()
