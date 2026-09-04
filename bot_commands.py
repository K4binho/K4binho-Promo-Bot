import logging
import re
import secrets
import threading
import time
from html import escape

import httpx

import alert_store
import analytics
import deal_hunter
import forum_topics
import rate_limit
import telegram
import telegram_listener
import topics_store

GET_CHAT_MEMBER_URL = "https://api.telegram.org/bot{token}/getChatMember"
log = logging.getLogger("k4binho")
_alerts_lock = alert_store.LOCK
_realtime_listener: telegram_listener.TelegramRealtimeListener | None = None

# Preenchidos por configure(). Sem isso os comandos ainda respondem, mas a caca
# fica desligada (sem credencial de loja nao ha o que consultar).
_config = None
_command_limiter = rate_limit.SlidingWindowLimiter(12, 60.0)
_hunt_limiter = rate_limit.SlidingWindowLimiter(10, 3600.0)
_hunt_global_limiter = rate_limit.SlidingWindowLimiter(30, 60.0)
_hunt_pool_lock = threading.Lock()
_hunt_in_flight: set[str] = set()


def configure(cfg) -> None:
    """Liga a caca ativa e ajusta os limites a partir do .env."""
    global _config, _command_limiter, _hunt_limiter, _hunt_global_limiter
    _config = cfg
    _command_limiter = rate_limit.SlidingWindowLimiter(cfg.command_rate_limit_per_minute, 60.0)
    _hunt_limiter = rate_limit.SlidingWindowLimiter(cfg.hunt_rate_limit_per_hour, 3600.0)
    _hunt_global_limiter = rate_limit.SlidingWindowLimiter(
        cfg.hunt_global_rate_limit_per_minute, 60.0
    )


def _is_forum_topic(msg: dict) -> bool:
    return msg.get("message_thread_id") is not None


def _is_admin(token: str, chat_id: str, user_id: int | str | None) -> bool:
    if user_id is None:
        return False
    try:
        resp = httpx.get(GET_CHAT_MEMBER_URL.format(token=token), params={"chat_id": chat_id, "user_id": user_id}, timeout=10)
        resp.raise_for_status()
        return resp.json().get("result", {}).get("status", "") in {"creator", "administrator"}
    except httpx.HTTPError as exc:
        log.warning("[Commands] nao foi possivel validar admin chat=%s: %s", chat_id, exc)
        return False


def handle_update(token: str, update: dict, alerts: dict[str, list[dict]], admin_chat_id: str = "") -> None:
    callback = update.get("callback_query")
    if callback:
        _handle_hunt_callback(token, callback)
        return
    msg = update.get("message")
    if not msg or not msg.get("text"):
        return
    text = msg["text"].strip()
    chat_id = str(msg["chat"]["id"])
    thread_id = msg.get("message_thread_id")
    user_id = msg.get("from", {}).get("id")

    # Qualquer pessoa manda comando no privado do bot. Limita antes de tocar em
    # arquivo ou rede: sem isso um chat sozinho enfileira busca em loja em
    # rajada. Silencioso de proposito ao estourar — responder alimenta o flood.
    if text.startswith("/"):
        allowed, retry_in = _command_limiter.check(chat_id)
        if not allowed:
            log.info("[Commands] rate limit chat=%s (%.0fs)", chat_id, retry_in)
            return

    # Topics de grupos sao superficie administrativa: comandos so executam
    # para creator/administrator. Se a API nao confirmar, bloqueia.
    if _is_forum_topic(msg) and text.startswith("/") and not _is_admin(token, chat_id, user_id):
        log.info("[Commands] bloqueado em topico chat=%s thread=%s user=%s", chat_id, thread_id, user_id)
        return

    # Caca fica fora da lock de alertas: sao ~2-4s de rede, e a lock e a mesma
    # que as fontes usam pra checar alerta no meio do ciclo.
    if text.startswith("/buscar "):
        _handle_search(token, chat_id, text[8:].strip(), thread_id)
        return

    with _alerts_lock:
        if text.startswith("/alerta "):
            _handle_add_alert(token, chat_id, text[8:].strip(), alerts, thread_id)
        elif text == "/meusalertas":
            _handle_list_alerts(token, chat_id, alerts, thread_id)
        elif text.startswith("/cancelar "):
            _handle_cancel_alert(token, chat_id, text[10:].strip(), alerts, thread_id)
        elif text == "/status" and admin_chat_id and chat_id == admin_chat_id:
            _handle_status(token, chat_id, alerts, thread_id)
        elif text == "/start":
            _handle_start(token, chat_id, thread_id)
        elif text.startswith("/topico ") and _is_admin(token, chat_id, user_id):
            _handle_register_topic(token, chat_id, text[8:].strip(), thread_id)
        elif text == "/topicos" and _is_admin(token, chat_id, user_id):
            _handle_list_topics(token, chat_id, thread_id)
        elif text.startswith("/criartopico ") and _is_admin(token, chat_id, user_id):
            _handle_create_topic(token, chat_id, text[13:].strip(), thread_id)
        elif text.startswith("/renomeartopico ") and _is_admin(token, chat_id, user_id):
            _handle_rename_topic(token, chat_id, text[16:].strip(), thread_id)
        elif text == "/fechartopico" and _is_admin(token, chat_id, user_id):
            _handle_close_topic(token, chat_id, thread_id)
        elif text == "/reabrirtopico" and _is_admin(token, chat_id, user_id):
            _handle_reopen_topic(token, chat_id, thread_id)
        elif text.startswith("/removertopico ") and _is_admin(token, chat_id, user_id):
            _handle_unregister_topic(token, chat_id, text[15:].strip(), thread_id)


def poll_commands(token: str, alerts: dict[str, list[dict]], last_update_id: int, admin_chat_id: str = "") -> int:
    """Compatibility entrypoint used by bot.py; starts one realtime listener."""
    global _realtime_listener
    if _realtime_listener is None:
        _realtime_listener = telegram_listener.TelegramRealtimeListener(
            token,
            lambda update: handle_update(token, update, alerts, admin_chat_id=admin_chat_id),
        )
        _realtime_listener.start()
    return last_update_id


def _send(token: str, chat_id: str, text: str, thread_id: int | None = None) -> None:
    # interactive: resposta a pessoa nao espera a rajada do ciclo no canal.
    telegram.send_message(token, chat_id, text, thread_id=thread_id, interactive=True)


def _handle_start(token: str, chat_id: str, thread_id: int | None = None) -> None:
    _send(token, chat_id, (
        "🔔 <b>K4binho — Alertas Personalizados</b>\n\nComandos:\n"
        "<code>/buscar rtx 5070</code> — caça a oferta agora nas lojas\n"
        "<code>/alerta rtx 5070</code> — alerta por palavra-chave\n"
        "<code>/alerta ssd abaixo de 500</code> — alerta com preço máximo\n"
        "<code>/meusalertas</code> — ver alertas ativos\n"
        "<code>/cancelar 1</code> — cancelar alerta pelo número\n\n"
        "🛠️ <b>Admin (dentro do tópico):</b>\n"
        "<code>/topico chave</code> — registra o tópico atual\n"
        "<code>/criartopico chave | Nome</code> — cria e registra um tópico novo\n"
        "<code>/renomeartopico Novo Nome</code> — renomeia o tópico atual\n"
        "<code>/fechartopico</code> / <code>/reabrirtopico</code>\n"
        "<code>/topicos</code> — lista os tópicos registrados"
    ), thread_id)


_ALERT_PRICE_RE = re.compile(
    r"(.+?)\s+(?:abaixo|menos|ate|at[ée]|max|m[áa]ximo|por)\s*(?:de\s+)?"
    r"(?:r\$\s*)?(\d{1,3}(?:\.\d{3})+|\d+)(?:,(\d{1,2}))?\s*$",
    re.IGNORECASE,
)


def _parse_alert_text(text: str) -> tuple[str, float | None]:
    m = _ALERT_PRICE_RE.match(text)
    if not m:
        return text.strip(), None
    inteiro = m.group(2).replace(".", "")
    centavos = m.group(3) or "0"
    return m.group(1).strip(), float(f"{inteiro}.{centavos}")


def _handle_add_alert(token: str, chat_id: str, text: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    if not text:
        _send(token, chat_id, "Use: <code>/alerta rtx 5070</code> ou <code>/alerta ssd abaixo de 500</code>", thread_id); return
    keywords, max_price = _parse_alert_text(text)
    if len(keywords) < 2:
        _send(token, chat_id, "Palavra-chave muito curta. Use pelo menos 2 caracteres.", thread_id); return
    limite = _config.max_alerts_per_chat if _config else 10
    if len(alert_store.get_alerts(alerts, chat_id)) >= limite:
        _send(token, chat_id, f"Limite de {limite} alertas atingido. Cancele algum com /cancelar.", thread_id); return
    alert_store.add_alert(alerts, chat_id, keywords, max_price=max_price)
    alert_store.save_alerts(alerts)
    price_info = f" abaixo de R$ {max_price:.2f}" if max_price else ""
    _send(token, chat_id, f"✅ Alerta criado: <b>{keywords}</b>{price_info}\n\n🔎 Já estou caçando...", thread_id)
    log.info("[Alerta] chat=%s criou alerta: %s%s", chat_id, keywords, price_info)
    _hunt_async(token, chat_id, keywords, max_price, thread_id, origin="alerta")


def _handle_list_alerts(token: str, chat_id: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    user_alerts = alert_store.get_alerts(alerts, chat_id)
    if not user_alerts:
        _send(token, chat_id, "Nenhum alerta ativo.\n\nCrie com: <code>/alerta rtx 5070</code>", thread_id); return
    lines = ["🔔 <b>Seus alertas:</b>\n"]
    for i, a in enumerate(user_alerts, 1):
        desc = a["keywords"] + (f" (abaixo de R$ {a['max_price']:.2f})" if a.get("max_price") else "")
        lines.append(f"{i}. {desc}")
    lines.append("\nPara cancelar: <code>/cancelar 1</code>")
    _send(token, chat_id, "\n".join(lines), thread_id)


def _handle_cancel_alert(token: str, chat_id: str, text: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    try: index = int(text) - 1
    except ValueError:
        _send(token, chat_id, "Use: <code>/cancelar 1</code> (número do alerta)", thread_id); return
    user_alerts = alert_store.get_alerts(alerts, chat_id)
    nome = user_alerts[index]["keywords"] if 0 <= index < len(user_alerts) else ""
    if alert_store.remove_alert(alerts, chat_id, index):
        alert_store.save_alerts(alerts)
        _send(token, chat_id, f"✅ Alerta #{index + 1} (<b>{nome}</b>) cancelado. Não vou mais te avisar sobre ele.", thread_id)
        log.info("[Alerta] chat=%s cancelou alerta: %s", chat_id, nome)
    else:
        _send(token, chat_id, "Número inválido. Veja /meusalertas.", thread_id)


def _handle_status(token: str, chat_id: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone(); today = now.strftime("%Y-%m-%d")
    published = [e for e in analytics.load_entries() if e.get("timestamp", "").startswith(today) and e.get("action") == "published"]
    commercial = [e for e in published if e.get("deal_type") == "commercial"]
    plus = [e for e in published if e.get("deal_type") == "plus"]
    sources = {}
    for e in published: sources[e.get("source", "?")] = sources.get(e.get("source", "?"), 0) + 1
    source_lines = [f"{label}: {sources.get(name, 0)} publicadas hoje" for name, label in [("ml", "ML"), ("aliexpress", "AliExpress"), ("steam", "Steam"), ("nuuvem", "Nuuvem"), ("gmg", "GMG")]]
    text = (f"🤖 <b>K4BINHO STATUS</b>\n\n" + "\n".join(source_lines) + f"\n\nPublicadas hoje: {len(published)}\nComercial: {len(commercial)}\nPLUS: {len(plus)}\n\nAlertas ativos: {sum(len(v) for v in alerts.values())}\nUsuarios com alertas: {len(alerts)}\n\nHorario: {now.strftime('%H:%M')}")
    _send(token, chat_id, text, thread_id)


def notify_alert_match(token: str, chat_id: str, alert: dict, title: str, price: float, link: str) -> None:
    price_brl = f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    text = f"🔔 <b>ALERTA PERSONALIZADO</b>\n\n<b>{title}</b>\n\nEncontrado por <b>{price_brl}</b>\nPalavra-chave: {alert['keywords']}\n\n<a href=\"{link}\">VER OFERTA</a>"
    try: telegram.send_message(token, chat_id, text, interactive=True)
    except httpx.HTTPError as exc: log.error("[Alerta] falha ao notificar chat=%s: %s", chat_id, exc)


# --- Caca ativa (pedido do usuario = prioridade 0) --------------------
#
# Pedido nao espera o ciclo editorial: consulta loja na hora e responde com
# preco real. Roda em thread propria pra nao travar o listener de comandos, e
# passa por tres limites antes de gastar rede.

_SOURCE_LABEL = {
    "aliexpress": "🔴 ALIEXPRESS",
    "shopee": "🟠 SHOPEE",
    "steam": "🎮 STEAM",
}
_KIND_LABEL = {deal_hunter.GAME_KIND: "🎮 Jogo", deal_hunter.ITEM_KIND: "📦 Produto"}

# Resultado guardado entre a pergunta ("jogo ou item?") e o clique no botao.
# Sem isso o clique teria que refazer a busca — 3 chamadas de API paga de novo.
_HUNT_PENDING_TTL = 600.0
_HUNT_PENDING_MAX = 200
_hunt_pending: dict[str, dict] = {}
_hunt_pending_lock = threading.Lock()


def _remember_hunt(chat_id: str, keywords: str, max_price: float | None,
                   thread_id: int | None, results: list) -> str:
    nonce = secrets.token_hex(6)
    now = time.monotonic()
    with _hunt_pending_lock:
        # Poda por idade e por tamanho: o nonce vem de clique, e clique vem de fora.
        stale = [k for k, v in _hunt_pending.items() if now - v["at"] > _HUNT_PENDING_TTL]
        for k in stale:
            _hunt_pending.pop(k, None)
        while len(_hunt_pending) >= _HUNT_PENDING_MAX:
            _hunt_pending.pop(next(iter(_hunt_pending)), None)
        _hunt_pending[nonce] = {
            "chat_id": chat_id,
            "keywords": keywords,
            "max_price": max_price,
            "thread_id": thread_id,
            "results": results,
            "at": now,
        }
    return nonce


def _kind_question_markup(nonce: str, games: list, items: list) -> dict:
    return {
        "inline_keyboard": [[
            {"text": f"🎮 Jogo ({len(games)})", "callback_data": f"hunt:{nonce}:{deal_hunter.GAME_KIND}"},
            {"text": f"📦 Produto ({len(items)})", "callback_data": f"hunt:{nonce}:{deal_hunter.ITEM_KIND}"},
        ]]
    }


def _format_kind_question(keywords: str, max_price: float | None,
                          games: list, items: list) -> str:
    alvo = f" abaixo de {_brl(max_price)}" if max_price else ""
    return (
        f"🔎 <b>{escape(keywords)}</b>{alvo}\n\n"
        f"Achei os dois. O que você quer?\n"
        f"🎮 <b>{len(games)} jogo(s)</b> — a partir de {_brl(games[0].price)}\n"
        f"📦 <b>{len(items)} produto(s)</b> — a partir de {_brl(items[0].price)}"
    )


def _format_hunt_reply(keywords: str, results: list, max_price: float | None,
                       limit: int, kind: str = "") -> str:
    alvo = f" abaixo de {_brl(max_price)}" if max_price else ""
    if not results:
        return (
            f"🔎 <b>{escape(keywords)}</b>{alvo}\n\n"
            "Nada encontrado agora nas lojas que consulto (AliExpress, Shopee, Steam).\n"
            "O alerta continua ativo — te aviso quando aparecer."
        )
    titulo = f" · {_KIND_LABEL[kind]}" if kind in _KIND_LABEL else ""
    lines = [f"🔎 <b>{escape(keywords)}</b>{alvo}{titulo}", ""]
    for r in results[:limit]:
        loja = _SOURCE_LABEL.get(r.source, r.source.upper())
        desconto = f" ({r.discount_percent}% OFF)" if r.discount_percent else ""
        lines.append(f"{loja}")
        lines.append(f"📦 <a href=\"{escape(r.link)}\">{escape(r.title[:70])}</a>")
        lines.append(f"<b>{_brl(r.price)}</b>{desconto}")
        lines.append("")
    return "\n".join(lines).rstrip()


def _handle_hunt_callback(token: str, callback: dict) -> None:
    """Responde ao botao 'jogo ou produto' usando o resultado ja buscado."""
    callback_id = str(callback.get("id", ""))
    data = str(callback.get("data", ""))
    chat_id = str((callback.get("message") or {}).get("chat", {}).get("id", ""))
    thread_id = (callback.get("message") or {}).get("message_thread_id")
    telegram.answer_callback_query(token, callback_id)

    parts = data.split(":")
    if len(parts) != 3 or parts[0] != "hunt":
        return
    _, nonce, kind = parts
    allowed, _retry = _command_limiter.check(chat_id)
    if not allowed:
        log.info("[Commands] rate limit callback chat=%s", chat_id)
        return
    with _hunt_pending_lock:
        entry = _hunt_pending.get(nonce)
    # Nonce so vale pro chat que pediu: callback_data viaja e pode ser repetido.
    if entry is None or entry["chat_id"] != chat_id:
        _send(token, chat_id, "Essa busca expirou. Refaça com <code>/buscar</code>.", thread_id)
        return
    games, items = deal_hunter.split_kinds(entry["results"])
    escolhido = games if kind == deal_hunter.GAME_KIND else items
    limit = _config.hunt_results_per_reply if _config else 3
    _send(token, chat_id,
          _format_hunt_reply(entry["keywords"], escolhido, entry["max_price"], limit, kind),
          thread_id)



def _brl(value: float) -> str:
    return f"R$ {value:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def _run_hunt(token: str, chat_id: str, keywords: str, max_price: float | None,
              thread_id: int | None, origin: str) -> None:
    cfg = _config
    try:
        results = deal_hunter.hunt(
            keywords,
            max_price=max_price,
            aliexpress_app_key=cfg.aliexpress_app_key,
            aliexpress_app_secret=cfg.aliexpress_app_secret,
            aliexpress_tracking_id=cfg.aliexpress_tracking_id,
            shopee_app_id=cfg.shopee_app_id,
            shopee_app_secret=cfg.shopee_app_secret,
            per_source_limit=cfg.hunt_per_source_limit,
        )
        log.info("[Caca] %s chat=%s %r: %d resultado(s)", origin, chat_id, keywords, len(results))
        games, items = deal_hunter.split_kinds(results)
        # Loja mistura jogo com bugiganga tematica: 'skyrim' devolve o jogo na
        # Steam e caneca na Shopee. Com os dois presentes, quem pediu escolhe.
        if games and items:
            nonce = _remember_hunt(chat_id, keywords, max_price, thread_id, results)
            telegram.send_message(
                token, chat_id,
                _format_kind_question(keywords, max_price, games, items),
                thread_id=thread_id,
                reply_markup=_kind_question_markup(nonce, games, items),
            )
            return
        kind = deal_hunter.GAME_KIND if games else deal_hunter.ITEM_KIND
        _send(token, chat_id,
              _format_hunt_reply(keywords, results, max_price, cfg.hunt_results_per_reply,
                                 kind if results else ""),
              thread_id)
    except httpx.HTTPError as exc:
        log.error("[Caca] falha chat=%s %r: %s", chat_id, keywords, exc)
        _send(token, chat_id, "❌ As lojas não responderam agora. Tente de novo em alguns minutos.", thread_id)
    finally:
        with _hunt_pool_lock:
            _hunt_in_flight.discard(chat_id)


def _hunt_async(token: str, chat_id: str, keywords: str, max_price: float | None,
                thread_id: int | None, origin: str) -> bool:
    """Dispara a caca em background. Retorna False se recusada (limite/desligada)."""
    if _config is None or not _config.hunt_enabled:
        return False

    allowed, retry_in = _hunt_limiter.check(chat_id)
    if not allowed:
        _send(token, chat_id,
              f"⏳ Muitas buscas seguidas. Tente de novo em {int(retry_in // 60) + 1} min.",
              thread_id)
        return False
    # Limite global: varios chats somam, e cada caca sao 3 chamadas de API paga.
    allowed, _retry = _hunt_global_limiter.check("__global__")
    if not allowed:
        _send(token, chat_id, "⏳ Muita busca na fila agora. Tente de novo em 1 min.", thread_id)
        return False
    # Uma caca por chat de cada vez: sem isso 10 comandos = 10 threads de rede.
    with _hunt_pool_lock:
        if chat_id in _hunt_in_flight:
            _send(token, chat_id, "⏳ Já estou buscando o seu último pedido. Aguarde.", thread_id)
            return False
        _hunt_in_flight.add(chat_id)

    threading.Thread(
        target=_run_hunt,
        args=(token, chat_id, keywords, max_price, thread_id, origin),
        name=f"hunt-{chat_id}",
        daemon=True,
    ).start()
    return True


def _handle_search(token: str, chat_id: str, text: str, thread_id: int | None = None) -> None:
    if not text:
        _send(token, chat_id, "Use: <code>/buscar rtx 5070</code> ou <code>/buscar ssd abaixo de 500</code>", thread_id)
        return
    keywords, max_price = _parse_alert_text(text)
    if len(keywords) < 2:
        _send(token, chat_id, "Palavra-chave muito curta. Use pelo menos 2 caracteres.", thread_id)
        return
    if _config is None or not _config.hunt_enabled:
        _send(token, chat_id, "Busca ativa está desligada. Use <code>/alerta</code> para ser avisado.", thread_id)
        return
    if _hunt_async(token, chat_id, keywords, max_price, thread_id, origin="buscar"):
        _send(token, chat_id, f"🔎 Caçando <b>{escape(keywords)}</b> nas lojas...", thread_id)


# --- Gerenciamento de tópicos (fórum) ---------------------------------
#
# A Bot API nao permite listar topicos existentes, entao um admin precisa
# registrar cada topico uma vez (comando /topico) ou deixar o bot criar
# um novo (comando /criartopico). Depois disso o bot.py pode consultar
# topics_store.resolve_thread_id(chave) para postar automaticamente no
# topico certo.


def _handle_register_topic(token: str, chat_id: str, key: str, thread_id: int | None) -> None:
    if thread_id is None:
        _send(token, chat_id, "Use esse comando <b>dentro do tópico</b> que você quer registrar.", thread_id)
        return
    if not key:
        _send(token, chat_id, "Use: <code>/topico xbox</code> (envie dentro do tópico desejado)", thread_id); return
    topics = topics_store.load_topics()
    topics_store.register_topic(topics, key, thread_id)
    topics_store.save_topics(topics)
    _send(token, chat_id, f"✅ Tópico atual registrado como <b>{key}</b>.", thread_id)
    log.info("[Topicos] chat=%s registrou thread=%s como '%s'", chat_id, thread_id, key)


def _handle_unregister_topic(token: str, chat_id: str, key: str, thread_id: int | None) -> None:
    if not key:
        _send(token, chat_id, "Use: <code>/removertopico xbox</code>", thread_id); return
    topics = topics_store.load_topics()
    if topics_store.unregister_topic(topics, key):
        topics_store.save_topics(topics)
        _send(token, chat_id, f"✅ Registro de <b>{key}</b> removido (o tópico em si não foi apagado).", thread_id)
    else:
        _send(token, chat_id, f"Nenhum tópico registrado como <b>{key}</b>.", thread_id)


def _handle_list_topics(token: str, chat_id: str, thread_id: int | None) -> None:
    topics = topics_store.load_topics()
    if not topics:
        _send(token, chat_id, "Nenhum tópico registrado ainda. Use <code>/topico chave</code> dentro de um tópico.", thread_id)
        return
    lines = ["🗂️ <b>Tópicos registrados:</b>\n"]
    for key, entry in sorted(topics.items()):
        lines.append(f"• <b>{key}</b> → thread {entry.get('thread_id')}")
    _send(token, chat_id, "\n".join(lines), thread_id)


def _handle_create_topic(token: str, chat_id: str, text: str, thread_id: int | None) -> None:
    # Formato: /criartopico chave | Nome bonito do tópico
    if "|" in text:
        key, name = (p.strip() for p in text.split("|", 1))
    else:
        key = name = text.strip()
    if not key or not name:
        _send(token, chat_id, "Use: <code>/criartopico xbox | 🎮 XBOX</code>", thread_id); return
    try:
        result = forum_topics.create_forum_topic(token, chat_id, name)
    except (httpx.HTTPError, RuntimeError) as exc:
        log.error("[Topicos] falha ao criar topico chat=%s: %s", chat_id, exc)
        _send(token, chat_id, "❌ Não consegui criar o tópico. O bot é admin com permissão de gerenciar tópicos?", thread_id)
        return
    new_thread_id = result.get("message_thread_id")
    topics = topics_store.load_topics()
    topics_store.register_topic(topics, key, new_thread_id, name=name)
    topics_store.save_topics(topics)
    _send(token, chat_id, f"✅ Tópico <b>{name}</b> criado e registrado como <b>{key}</b>.", thread_id)


def _handle_rename_topic(token: str, chat_id: str, new_name: str, thread_id: int | None) -> None:
    if thread_id is None:
        _send(token, chat_id, "Use esse comando <b>dentro do tópico</b> que você quer renomear.", thread_id); return
    if not new_name:
        _send(token, chat_id, "Use: <code>/renomeartopico 🎮 XBOX SERIES</code>", thread_id); return
    try:
        forum_topics.edit_forum_topic(token, chat_id, thread_id, name=new_name)
    except (httpx.HTTPError, RuntimeError) as exc:
        log.error("[Topicos] falha ao renomear thread=%s: %s", thread_id, exc)
        _send(token, chat_id, "❌ Não consegui renomear. O bot é admin com permissão de gerenciar tópicos?", thread_id)
        return
    topics = topics_store.load_topics()
    for entry in topics.values():
        if entry.get("thread_id") == thread_id:
            entry["name"] = new_name
    topics_store.save_topics(topics)
    _send(token, chat_id, f"✅ Tópico renomeado para <b>{new_name}</b>.", thread_id)


def _handle_close_topic(token: str, chat_id: str, thread_id: int | None) -> None:
    if thread_id is None:
        _send(token, chat_id, "Use esse comando <b>dentro do tópico</b> que você quer fechar.", thread_id); return
    try:
        forum_topics.close_forum_topic(token, chat_id, thread_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        log.error("[Topicos] falha ao fechar thread=%s: %s", thread_id, exc)
        _send(token, chat_id, "❌ Não consegui fechar o tópico.", thread_id)
        return
    _send(token, chat_id, "✅ Tópico fechado.", thread_id)


def _handle_reopen_topic(token: str, chat_id: str, thread_id: int | None) -> None:
    if thread_id is None:
        _send(token, chat_id, "Use esse comando <b>dentro do tópico</b> que você quer reabrir.", thread_id); return
    try:
        forum_topics.reopen_forum_topic(token, chat_id, thread_id)
    except (httpx.HTTPError, RuntimeError) as exc:
        log.error("[Topicos] falha ao reabrir thread=%s: %s", thread_id, exc)
        _send(token, chat_id, "❌ Não consegui reabrir o tópico.", thread_id)
        return
    _send(token, chat_id, "✅ Tópico reaberto.", thread_id)
