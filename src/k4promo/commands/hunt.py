"""``/buscar`` — pesquisa ativa em background (Fase 3, seção 13).

Pesquisa AliExpress, Shopee e Steam em paralelo (thread própria, não bloqueia
o listener), separa resultado em "jogo" (Steam) e "produto" (AliExpress/
Shopee), e — se encontrar os dois tipos — pergunta com botões inline qual o
usuário quer ver. Resultado pendente expira em ~10 min e é reaproveitado no
callback (nunca rechama as APIs ao clicar no botão).
"""

from __future__ import annotations

import logging
import os
import threading
import time
from dataclasses import dataclass
from html import escape as _esc

import httpx

from k4promo import telegram
from k4promo.providers import aliexpress, shopee
from k4promo.services.rate_limit import WindowRateLimiter

log = logging.getLogger("k4binho")

STEAM_SEARCH_URL = "https://store.steampowered.com/api/storesearch/"
PENDING_TTL_SECONDS = 600  # ~10 minutos
MAX_RESULTS_PER_KIND = 5
KINDS = ("jogo", "produto")


def _env_int(name: str, default: int) -> int:
    raw = os.getenv(name)
    if raw is None or not raw.strip():
        return default
    try:
        return int(raw.strip())
    except ValueError:
        return default


@dataclass
class HuntResult:
    source: str
    title: str
    price: float | None
    link: str


# Estado das buscas pendentes por chat (resultado + expiração). Mantido em
# memória — não precisa sobreviver a um restart do processo.
_pending: dict[str, dict] = {}
_pending_lock = threading.Lock()

_chat_limiter: WindowRateLimiter | None = None
_global_limiter: WindowRateLimiter | None = None
_limiter_lock = threading.Lock()


def _get_limiters() -> tuple[WindowRateLimiter, WindowRateLimiter]:
    global _chat_limiter, _global_limiter
    if _chat_limiter is None or _global_limiter is None:
        with _limiter_lock:
            if _chat_limiter is None:
                _chat_limiter = WindowRateLimiter(
                    _env_int("HUNT_RATE_LIMIT_PER_HOUR", 10), 3600
                )
            if _global_limiter is None:
                _global_limiter = WindowRateLimiter(
                    _env_int("HUNT_GLOBAL_RATE_LIMIT_PER_MINUTE", 30), 60
                )
    return _chat_limiter, _global_limiter


def reset_for_testing() -> None:
    """Só pra testes: zera estado pendente e limiters."""
    global _chat_limiter, _global_limiter
    with _pending_lock:
        _pending.clear()
    _chat_limiter = None
    _global_limiter = None


def _expire_pending(now: float) -> None:
    with _pending_lock:
        expired = [
            chat_id for chat_id, entry in _pending.items()
            if not entry.get("searching") and entry.get("expires_at", 0) < now
        ]
        for chat_id in expired:
            del _pending[chat_id]


def _search_steam(query: str, limit: int = MAX_RESULTS_PER_KIND) -> list[HuntResult]:
    resp = httpx.get(
        STEAM_SEARCH_URL,
        params={"term": query, "l": "brazilian", "cc": "br"},
        headers={"Accept": "application/json"},
        timeout=10,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])[:limit]
    results = []
    for item in items:
        price_info = item.get("price") or {}
        final_cents = price_info.get("final")
        price = final_cents / 100 if isinstance(final_cents, (int, float)) else None
        app_id = item.get("id")
        results.append(
            HuntResult(
                source="steam",
                title=str(item.get("name", "")),
                price=price,
                link=f"https://store.steampowered.com/app/{app_id}/" if app_id else "",
            )
        )
    return results


def _search_aliexpress(cfg, query: str, limit: int = MAX_RESULTS_PER_KIND) -> list[HuntResult]:
    deals = aliexpress.fetch_deals(
        cfg.aliexpress_app_key, cfg.aliexpress_app_secret, cfg.aliexpress_tracking_id,
        keywords=query, page_size=limit,
    )
    return [
        HuntResult(source="aliexpress", title=d.title, price=d.price, link=d.permalink)
        for d in deals[:limit]
    ]


def _search_shopee(cfg, query: str, limit: int = MAX_RESULTS_PER_KIND) -> list[HuntResult]:
    deals = shopee.fetch_deals(
        cfg.shopee_app_id, cfg.shopee_app_secret, keyword=query, limit=limit,
    )
    return [
        HuntResult(source="shopee", title=d.title, price=d.price, link=d.permalink)
        for d in deals[:limit]
    ]


def _format_price(price: float | None) -> str:
    if price is None:
        return ""
    brl = f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f" — <b>{brl}</b>"


def _format_results(kind: str, query: str, results: list[HuntResult]) -> str:
    label = "🎮 Jogos" if kind == "jogo" else "📦 Produtos"
    if not results:
        return f"{label} — nada encontrado para \"{_esc(query)}\"."
    lines = [f"{label} encontrados para \"{_esc(query)}\":\n"]
    for r in results:
        lines.append(f"• <a href=\"{_esc(r.link)}\">{_esc(r.title)}</a>{_format_price(r.price)}")
    return "\n".join(lines)


def _run_search(cfg, token: str, chat_id: str, query: str) -> None:
    results: dict[str, list[HuntResult]] = {"jogo": [], "produto": []}

    try:
        results["produto"].extend(_search_aliexpress(cfg, query))
    except Exception as exc:
        log.error("[Buscar] AliExpress falhou: %s", exc)

    try:
        results["produto"].extend(_search_shopee(cfg, query))
    except Exception as exc:
        log.error("[Buscar] Shopee falhou: %s", exc)

    try:
        results["jogo"].extend(_search_steam(query))
    except Exception as exc:
        log.error("[Buscar] Steam falhou: %s", exc)

    results["produto"] = sorted(
        results["produto"][: MAX_RESULTS_PER_KIND * 2],
        key=lambda r: r.price if r.price is not None else float("inf"),
    )[:MAX_RESULTS_PER_KIND]

    now = time.monotonic()
    with _pending_lock:
        _pending[chat_id] = {
            "searching": False,
            "expires_at": now + PENDING_TTL_SECONDS,
            "query": query,
            "results": results,
        }

    jogo_n, produto_n = len(results["jogo"]), len(results["produto"])
    if jogo_n and produto_n:
        keyboard = {
            "inline_keyboard": [[
                {"text": f"🎮 Jogo ({jogo_n})", "callback_data": f"hunt:jogo:{chat_id}"},
                {"text": f"📦 Produto ({produto_n})", "callback_data": f"hunt:produto:{chat_id}"},
            ]]
        }
        telegram.send_message(
            token, chat_id,
            f"Encontrei jogo <b>e</b> produto físico pra \"{_esc(query)}\". Qual você quer ver?",
            reply_markup=keyboard,
        )
    elif jogo_n:
        telegram.send_message(token, chat_id, _format_results("jogo", query, results["jogo"]))
    elif produto_n:
        telegram.send_message(token, chat_id, _format_results("produto", query, results["produto"]))
    else:
        telegram.send_message(token, chat_id, f"Nada encontrado para \"{_esc(query)}\". Tente outros termos.")


def handle_buscar(cfg, token: str, chat_id: str, query: str) -> None:
    """Ponto de entrada chamado pelo listener quando alguém manda /buscar."""
    query = query.strip()
    if not query:
        telegram.send_message(token, chat_id, "Use: <code>/buscar palworld</code>")
        return

    now = time.monotonic()
    _expire_pending(now)

    with _pending_lock:
        current = _pending.get(chat_id)
        if current and current.get("searching"):
            telegram.send_message(token, chat_id, "Você já tem uma busca em andamento. Aguarde.")
            return

    chat_limiter, global_limiter = _get_limiters()
    if not global_limiter.allow(None):
        telegram.send_message(
            token, chat_id, "Muitas buscas agora. Tente de novo em alguns instantes."
        )
        return
    if not chat_limiter.allow(chat_id):
        telegram.send_message(
            token, chat_id, "Limite de buscas por hora atingido. Tente mais tarde."
        )
        return

    with _pending_lock:
        _pending[chat_id] = {
            "searching": True, "expires_at": now + PENDING_TTL_SECONDS,
            "query": query, "results": {"jogo": [], "produto": []},
        }

    telegram.send_message(token, chat_id, f"🔎 Buscando \"{_esc(query)}\"...")
    threading.Thread(
        target=_run_search, args=(cfg, token, chat_id, query),
        daemon=True, name="hunt-search",
    ).start()


def handle_callback(token: str, callback_query: dict) -> bool:
    """Trata um callback de botão do /buscar. Devolve True se era nosso
    (pra o listener não tentar tratar de outra forma)."""
    data = callback_query.get("data", "")
    parts = data.split(":", 2)
    if len(parts) != 3 or parts[0] != "hunt" or parts[1] not in KINDS:
        return False

    kind, owner_chat_id = parts[1], parts[2]
    callback_id = callback_query.get("id", "")
    message = callback_query.get("message") or {}
    actual_chat_id = str((message.get("chat") or {}).get("id", ""))

    # Validação de callback pelo chat que iniciou a busca (seção 15).
    if not actual_chat_id or actual_chat_id != owner_chat_id:
        telegram.answer_callback_query(
            token, callback_id, "Essa busca não é sua.", show_alert=True
        )
        return True

    now = time.monotonic()
    with _pending_lock:
        entry = _pending.get(owner_chat_id)

    if not entry or entry.get("searching") or entry.get("expires_at", 0) < now:
        telegram.answer_callback_query(
            token, callback_id, "Busca expirada. Tente de novo com /buscar.", show_alert=True
        )
        return True

    telegram.answer_callback_query(token, callback_id)
    results = entry["results"].get(kind, [])
    query = entry.get("query", "")
    telegram.send_message(token, actual_chat_id, _format_results(kind, query, results))
    return True
