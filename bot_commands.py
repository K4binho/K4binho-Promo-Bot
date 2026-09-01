import logging
import re
import threading

import httpx

import alert_store
import analytics
import telegram

GETUPDATE_URL = "https://api.telegram.org/bot{token}/getUpdates"
GET_CHAT_MEMBER_URL = "https://api.telegram.org/bot{token}/getChatMember"

log = logging.getLogger("k4binho")
_alerts_lock = threading.RLock()


def _is_forum_topic(msg: dict) -> bool:
    return msg.get("message_thread_id") is not None


def _is_admin(token: str, chat_id: str, user_id: int | str | None) -> bool:
    if user_id is None:
        return False
    try:
        resp = httpx.get(
            GET_CHAT_MEMBER_URL.format(token=token),
            params={"chat_id": chat_id, "user_id": user_id},
            timeout=10,
        )
        resp.raise_for_status()
        status = resp.json().get("result", {}).get("status", "")
        return status in {"creator", "administrator"}
    except httpx.HTTPError as exc:
        log.warning("[Commands] nao foi possivel validar admin chat=%s: %s", chat_id, exc)
        return False


def handle_update(
    token: str,
    update: dict,
    alerts: dict[str, list[dict]],
    admin_chat_id: str = "",
) -> None:
    msg = update.get("message")
    if not msg or not msg.get("text"):
        return

    text = msg["text"].strip()
    chat_id = str(msg["chat"]["id"])
    thread_id = msg.get("message_thread_id")
    user_id = msg.get("from", {}).get("id")

    # Em grupos com Topics/Forum, qualquer comando do bot e administrativo.
    # A checagem e feita via getChatMember e falha de forma fechada.
    if _is_forum_topic(msg) and text.startswith("/"):
        if not _is_admin(token, chat_id, user_id):
            log.info(
                "[Commands] comando bloqueado em topico chat=%s thread=%s user=%s",
                chat_id, thread_id, user_id,
            )
            return

    with _alerts_lock:
        if text.startswith("/alerta "):
            _handle_add_alert(token, chat_id, text[8:].strip(), alerts, thread_id=thread_id)
        elif text == "/meusalertas":
            _handle_list_alerts(token, chat_id, alerts, thread_id=thread_id)
        elif text.startswith("/cancelar "):
            _handle_cancel_alert(token, chat_id, text[10:].strip(), alerts, thread_id=thread_id)
        elif text == "/status" and admin_chat_id and chat_id == admin_chat_id:
            _handle_status(token, chat_id, alerts, thread_id=thread_id)
        elif text == "/start":
            _handle_start(token, chat_id, thread_id=thread_id)


def poll_commands(
    token: str,
    alerts: dict[str, list[dict]],
    last_update_id: int,
    admin_chat_id: str = "",
) -> int:
    """Legacy one-shot polling kept for compatibility/tests.

    Production should use telegram_listener.TelegramRealtimeListener.
    """
    try:
        resp = httpx.get(
            GETUPDATE_URL.format(token=token),
            params={"offset": last_update_id + 1, "timeout": 0},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[Commands] polling: %s", exc)
        return last_update_id

    updates = resp.json().get("result", [])
    for update in updates:
        last_update_id = max(last_update_id, update.get("update_id", 0))
        handle_update(token, update, alerts, admin_chat_id=admin_chat_id)

    if updates:
        with _alerts_lock:
            alert_store.save_alerts(alerts)

    return last_update_id


def _send(token: str, chat_id: str, text: str, thread_id: int | None = None) -> None:
    telegram.send_message(token, chat_id, text, thread_id=thread_id)


def _handle_start(token: str, chat_id: str, thread_id: int | None = None) -> None:
    text = (
        "🔔 <b>K4binho — Alertas Personalizados</b>\n\n"
        "Comandos:\n"
        "<code>/alerta rtx 5070</code> — alerta por palavra-chave\n"
        "<code>/alerta ssd abaixo 500</code> — alerta com preço máximo\n"
        "<code>/meusalertas</code> — ver alertas ativos\n"
        "<code>/cancelar 1</code> — cancelar alerta pelo número"
    )
    _send(token, chat_id, text, thread_id)


def _parse_alert_text(text: str) -> tuple[str, float | None]:
    m = re.match(r"(.+?)\s+abaixo\s+(\d+(?:[.,]\d+)?)\s*$", text, re.IGNORECASE)
    if m:
        keywords = m.group(1).strip()
        price = float(m.group(2).replace(",", "."))
        return keywords, price
    return text.strip(), None


def _handle_add_alert(token: str, chat_id: str, text: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    if not text:
        _send(token, chat_id, "Use: <code>/alerta rtx 5070</code> ou <code>/alerta ssd abaixo 500</code>", thread_id)
        return
    keywords, max_price = _parse_alert_text(text)
    if len(keywords) < 2:
        _send(token, chat_id, "Palavra-chave muito curta. Use pelo menos 2 caracteres.", thread_id)
        return
    user_alerts = alert_store.get_alerts(alerts, chat_id)
    if len(user_alerts) >= 10:
        _send(token, chat_id, "Limite de 10 alertas atingido. Cancele algum com /cancelar.", thread_id)
        return
    alert_store.add_alert(alerts, chat_id, keywords, max_price=max_price)
    alert_store.save_alerts(alerts)
    price_info = f" abaixo de R$ {max_price:.2f}" if max_price else ""
    _send(token, chat_id, f"✅ Alerta criado: <b>{keywords}</b>{price_info}\n\nVocê será notificado quando encontrarmos.", thread_id)
    log.info("[Alerta] chat=%s criou alerta: %s%s", chat_id, keywords, price_info)


def _handle_list_alerts(token: str, chat_id: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    user_alerts = alert_store.get_alerts(alerts, chat_id)
    if not user_alerts:
        _send(token, chat_id, "Nenhum alerta ativo.\n\nCrie com: <code>/alerta rtx 5070</code>", thread_id)
        return
    lines = ["🔔 <b>Seus alertas:</b>\n"]
    for i, a in enumerate(user_alerts, 1):
        desc = a["keywords"]
        if a.get("max_price"):
            desc += f" (abaixo de R$ {a['max_price']:.2f})"
        lines.append(f"{i}. {desc}")
    lines.append("\nPara cancelar: <code>/cancelar 1</code>")
    _send(token, chat_id, "\n".join(lines), thread_id)


def _handle_cancel_alert(token: str, chat_id: str, text: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    try:
        index = int(text) - 1
    except ValueError:
        _send(token, chat_id, "Use: <code>/cancelar 1</code> (número do alerta)", thread_id)
        return
    if alert_store.remove_alert(alerts, chat_id, index):
        alert_store.save_alerts(alerts)
        _send(token, chat_id, f"✅ Alerta #{index + 1} cancelado.", thread_id)
        log.info("[Alerta] chat=%s cancelou alerta #%d", chat_id, index + 1)
    else:
        _send(token, chat_id, "Número inválido. Veja /meusalertas.", thread_id)


def _handle_status(token: str, chat_id: str, alerts: dict[str, list[dict]], thread_id: int | None = None) -> None:
    from datetime import datetime, timezone
    now = datetime.now(timezone.utc).astimezone()
    entries = analytics.load_entries()
    today = now.strftime("%Y-%m-%d")
    today_entries = [e for e in entries if e.get("timestamp", "").startswith(today)]
    published = [e for e in today_entries if e.get("action") == "published"]
    commercial = [e for e in published if e.get("deal_type") == "commercial"]
    plus = [e for e in published if e.get("deal_type") == "plus"]
    total_users = len(alerts)
    total_alerts = sum(len(v) for v in alerts.values())
    sources = {}
    for e in published:
        s = e.get("source", "?")
        sources[s] = sources.get(s, 0) + 1
    source_lines = []
    for name, label in [("ml", "ML"), ("aliexpress", "AliExpress"), ("steam", "Steam"), ("nuuvem", "Nuuvem"), ("gmg", "GMG")]:
        source_lines.append(f"{label}: {sources.get(name, 0)} publicadas hoje")
    text = (
        f"🤖 <b>K4BINHO STATUS</b>\n\n" + "\n".join(source_lines)
        + f"\n\nPublicadas hoje: {len(published)}"
        f"\nComercial: {len(commercial)}"
        f"\nPLUS: {len(plus)}"
        f"\n\nAlertas ativos: {total_alerts}"
        f"\nUsuarios com alertas: {total_users}"
        f"\n\nHorario: {now.strftime('%H:%M')}"
    )
    _send(token, chat_id, text, thread_id)


def notify_alert_match(token: str, chat_id: str, alert: dict, title: str, price: float, link: str) -> None:
    price_brl = f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    text = (
        f"🔔 <b>ALERTA PERSONALIZADO</b>\n\n"
        f"<b>{title}</b>\n\n"
        f"Encontrado por <b>{price_brl}</b>\n"
        f"Palavra-chave: {alert['keywords']}\n\n"
        f"<a href=\"{link}\">VER OFERTA</a>"
    )
    try:
        telegram.send_message(token, chat_id, text)
    except httpx.HTTPError as exc:
        log.error("[Alerta] falha ao notificar chat=%s: %s", chat_id, exc)
