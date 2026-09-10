"""Ponto de entrada: carrega configuração, inicializa serviços, registra as
fontes, executa o ciclo e encerra de forma limpa.

Nenhuma regra de negócio mora aqui. Cada fonte é um ``run(ctx)`` registrado em
``COMMERCIAL_CYCLES``/``EDITORIAL_CYCLES``; adicionar uma loja é acrescentar uma
linha nessas tuplas.
"""

from __future__ import annotations

import logging
import signal
import socket
import sys
import time

from k4promo.config import Config
from k4promo.providers.mercadolivre import service as mercadolivre_cycle
from k4promo.services import campaigns, click_server, digest, plus_editorial, showcase
from k4promo.services.context import CycleContext
from k4promo.services.cycles import aliexpress, gmg, kabum, nuuvem, shopee, steam
from k4promo.services.orchestrator import run_sources_concurrently
from k4promo.storage import alert_store, click_store, price_history
from k4promo.storage import deal_store as ds
from k4promo.storage.atomic import ensure_writable
from k4promo.storage.paths import data_dir
from k4promo.storage.postgres_state import PostgresState
from k4promo.storage.seen_store import expire_plus, load_seen, save_seen
from k4promo.telegram.listener import Listener

log = logging.getLogger("k4binho")

LOCK_PORT = 47591
_lock_socket: socket.socket | None = None

# As sete fontes rodam em paralelo (uma thread cada, ver orchestrator.py).
# GMG é comercial mas publica no tópico de jogos; Steam e Nuuvem são
# editoriais. A ordem aqui só define a ordem de log de "tarefa iniciada".
ALL_SOURCES = (
    ("Mercado Livre", mercadolivre_cycle.run),
    ("Shopee", shopee.run),
    ("Ali", aliexpress.run),
    ("Kabum", kabum.run),
    ("GMG", gmg.run),
    ("Steam", steam.run),
    ("Nuuvem", nuuvem.run),
)
_EDITORIAL_NAMES = {"GMG", "Steam", "Nuuvem"}


def _acquire_single_instance_lock() -> bool:
    global _lock_socket
    _lock_socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        _lock_socket.bind(("127.0.0.1", LOCK_PORT))
        _lock_socket.listen(1)
        return True
    except OSError:
        return False


def _release_lock() -> None:
    global _lock_socket
    if _lock_socket is not None:
        try:
            _lock_socket.close()
        except OSError:
            pass
        _lock_socket = None


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    # Evita que URLs com token/chave apareçam no bot.log via logging interno do
    # httpx/httpcore. Erros do projeto continuam sendo registrados.
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)


def _load_context(cfg: Config, dry_run: bool) -> CycleContext:
    seen = load_seen()
    published_deals = ds.load_deals()
    postgres_state = PostgresState(cfg.database_url) if cfg.database_url else None
    if postgres_state is not None:
        seen, published_deals = postgres_state.load_state(seen, published_deals)

    ctx = CycleContext(
        cfg=cfg,
        dry_run=dry_run,
        seen=seen,
        history=price_history.load_history(),
        published_deals=published_deals,
        alerts=alert_store.load_alerts(),
        click_links=click_store.load_links(),
        postgres_state=postgres_state,
    )
    expired = expire_plus(ctx.seen)
    if expired:
        log.info("[Seen] %d jogo(s) PLUS expirados (>7 dias), liberados pra re-post.", expired)
        _persist_core_state(ctx)
    return ctx


def _persist_core_state(ctx: CycleContext) -> None:
    if ctx.postgres_state is not None:
        ctx.postgres_state.persist(ctx.seen, ctx.published_deals)
    else:
        save_seen(ctx.seen)
        ds.save_deals(ctx.published_deals)


def _persist(ctx: CycleContext) -> None:
    _persist_core_state(ctx)
    price_history.save_history(ctx.history)


def _run_source(name: str, run_fn, ctx: CycleContext) -> int:
    """Uma fonte com problema não pode derrubar o ciclo inteiro.

    Usado para tarefas que continuam sequenciais (campanhas, PLUS fallback).
    As sete fontes comerciais/editoriais rodam via ``run_sources_concurrently``.
    """
    try:
        return run_fn(ctx)
    except Exception as exc:
        log.error("[%s] ciclo falhou: %s", name, exc)
        return 0
    finally:
        with ctx.lock:
            _persist_core_state(ctx)


def _persist_after_source(ctx: CycleContext) -> None:
    """Grava estado core sob o lock ao fim de cada fonte concorrente."""
    with ctx.lock:
        _persist_core_state(ctx)


def _wrap_with_persist(run_fn):
    def _wrapped(ctx: CycleContext) -> int:
        try:
            return run_fn(ctx)
        finally:
            _persist_after_source(ctx)

    return _wrapped


def run_once(ctx: CycleContext, last_digest_date: str = "") -> tuple[int, str]:
    """Executa um ciclo completo. Devolve (publicações, data do digest)."""
    ctx.begin_cycle()
    ctx.reset_cycle_queues()

    posted = _run_source("Campanhas", campaigns.run, ctx)

    sources = [(name, _wrap_with_persist(run_fn)) for name, run_fn in ALL_SOURCES]
    results = run_sources_concurrently(
        sources,
        ctx,
        max_workers=ctx.cfg.source_max_concurrency,
        timeout_seconds=ctx.cfg.source_timeout_seconds,
    )
    _persist_core_state(ctx)

    plus_posted = 0
    for result in results:
        posted += result.posted
        if result.name in _EDITORIAL_NAMES:
            plus_posted += result.posted

    if plus_posted == 0:
        posted += _run_source("PLUS", plus_editorial.run, ctx)

    # A vitrine só copia o que já foi publicado nos outros tópicos.
    posted += showcase.run_cycle(ctx)
    price_history.save_history(ctx.history)
    return posted, digest.run(ctx, last_digest_date)


def main() -> None:
    _setup_logging()

    if not _acquire_single_instance_lock():
        log.critical("Outra instancia do bot ja esta rodando. Saindo.")
        sys.exit(0)

    cfg = Config()
    errors = cfg.validate()
    if errors:
        log.critical("Configuracao invalida:")
        for err in errors:
            log.critical("  - %s", err)
        log.critical("Copie .env.example para .env e preencha.")
        _release_lock()
        sys.exit(1)

    try:
        ensure_writable(data_dir())
    except OSError as exc:
        log.critical("Diretorio de dados sem permissao de escrita: %s", exc)
        log.critical(
            "Verifique K4PROMO_DATA_DIR (ou a pasta atual, se a variavel "
            "nao estiver definida) e as permissoes do usuario que roda o bot."
        )
        _release_lock()
        sys.exit(1)

    once = "--once" in sys.argv
    dry_run = "--dry-run" in sys.argv
    ctx = _load_context(cfg, dry_run)
    last_digest_date = ""

    if cfg.click_tracking_enabled and not dry_run:
        click_server.start(cfg.click_server_port, ctx.click_links)

    # Listener em tempo real: substitui o antigo poll_commands() síncrono
    # (chamado uma vez por ciclo). Roda em thread própria desde já, então
    # comandos são respondidos mesmo com um ciclo demorado em andamento.
    listener = Listener(cfg, ctx)
    listener.start()

    stopping = False

    def _stop(signum, _frame):
        nonlocal stopping
        stopping = True
        log.info("Sinal %s recebido; encerrando apos o ciclo atual.", signum)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _stop)
        except (ValueError, OSError):
            pass

    log.info(
        "Bot iniciado. Score minimo: %d. Historico minimo: %d. Click tracking: %s.",
        cfg.score_min, cfg.min_history_observations,
        "ON" if cfg.click_tracking_enabled else "OFF",
    )

    try:
        while True:
            posted, last_digest_date = run_once(ctx, last_digest_date)
            log.info("Ciclo concluido. %d ofertas postadas.", posted)
            if once or dry_run or stopping:
                break
            time.sleep(cfg.poll_interval_seconds)
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuario.")
    finally:
        listener.stop()
        _persist(ctx)
        if ctx.postgres_state is not None:
            ctx.postgres_state.close()
        _release_lock()
        log.info("Estado salvo. Bot encerrado.")


if __name__ == "__main__":
    main()
