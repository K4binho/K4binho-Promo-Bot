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

from k4promo.commands import admin as bot_commands
from k4promo.config import Config
from k4promo.providers.mercadolivre import service as mercadolivre_cycle
from k4promo.services import campaigns, click_server, digest, plus_editorial, showcase
from k4promo.services.context import CycleContext
from k4promo.services.cycles import aliexpress, gmg, kabum, nuuvem, shopee, steam
from k4promo.storage import alert_store, click_store, deal_store as ds, price_history
from k4promo.storage.seen_store import expire_plus, load_seen, save_seen

log = logging.getLogger("k4binho")

LOCK_PORT = 47591
_lock_socket: socket.socket | None = None

# Lojas com comissão rodam primeiro. GMG é comercial mas publica no tópico de
# jogos; Steam e Nuuvem são editoriais e fecham a fila.
COMMERCIAL_CYCLES = (
    ("Shopee", shopee.run),
    ("Ali", aliexpress.run),
    ("Kabum", kabum.run),
)
EDITORIAL_CYCLES = (
    ("GMG", gmg.run),
    ("Steam", steam.run),
    ("Nuuvem", nuuvem.run),
)


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
    ctx = CycleContext(
        cfg=cfg,
        dry_run=dry_run,
        seen=load_seen(),
        history=price_history.load_history(),
        published_deals=ds.load_deals(),
        alerts=alert_store.load_alerts(),
        click_links=click_store.load_links(),
    )
    expired = expire_plus(ctx.seen)
    if expired:
        log.info("[Seen] %d jogo(s) PLUS expirados (>7 dias), liberados pra re-post.", expired)
        save_seen(ctx.seen)
    return ctx


def _persist(ctx: CycleContext) -> None:
    save_seen(ctx.seen)
    ds.save_deals(ctx.published_deals)
    price_history.save_history(ctx.history)


def _run_source(name: str, run_fn, ctx: CycleContext) -> int:
    """Uma fonte com problema não pode derrubar o ciclo inteiro."""
    try:
        return run_fn(ctx)
    except Exception as exc:
        log.error("[%s] ciclo falhou: %s", name, exc)
        return 0
    finally:
        save_seen(ctx.seen)


def run_once(ctx: CycleContext, last_digest_date: str = "") -> tuple[int, str]:
    """Executa um ciclo completo. Devolve (publicações, data do digest)."""
    ctx.reset_cycle_queues()

    posted = campaigns.run(ctx)
    posted += _run_source("ML", mercadolivre_cycle.run, ctx)
    ds.save_deals(ctx.published_deals)

    for name, run_fn in COMMERCIAL_CYCLES:
        posted += _run_source(name, run_fn, ctx)

    plus_posted = 0
    for name, run_fn in EDITORIAL_CYCLES:
        published = _run_source(name, run_fn, ctx)
        plus_posted += published
        posted += published

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

    once = "--once" in sys.argv
    dry_run = "--dry-run" in sys.argv
    ctx = _load_context(cfg, dry_run)
    last_digest_date = ""
    last_update_id = 0

    if cfg.click_tracking_enabled and not dry_run:
        click_server.start(cfg.click_server_port, ctx.click_links)

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
            last_update_id = bot_commands.poll_commands(
                cfg.telegram_bot_token, ctx.alerts, last_update_id,
                admin_chat_id=cfg.telegram_admin_chat_id,
            )
            posted, last_digest_date = run_once(ctx, last_digest_date)
            log.info("Ciclo concluido. %d ofertas postadas.", posted)
            if once or dry_run or stopping:
                break
            time.sleep(cfg.poll_interval_seconds)
    except KeyboardInterrupt:
        log.info("Interrompido pelo usuario.")
    finally:
        _persist(ctx)
        _release_lock()
        log.info("Estado salvo. Bot encerrado.")


if __name__ == "__main__":
    main()
