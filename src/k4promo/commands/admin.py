import logging
import os
import re
from html import escape as _esc

import httpx

from k4promo import telegram
from k4promo.domain import topics
from k4promo.services import analytics
from k4promo.storage import alert_store
from k4promo.telegram.client import sanitize as _sanitize_log

GETUPDATE_URL = "https://api.telegram.org/bot{token}/getUpdates"

log = logging.getLogger("k4binho")


def _max_alerts_per_chat() -> int:
    raw = os.getenv("MAX_ALERTS_PER_CHAT", "10")
    try:
        return int(raw)
    except ValueError:
        return 10


def dispatch_message(
    token: str,
    chat_id: str,
    text: str,
    alerts: dict[str, list[dict]],
    admin_chat_id: str = "",
) -> None:
    """Roteia uma mensagem de comando pro handler certo.

    Compartilhado entre ``poll_commands`` (compatibilidade) e o listener em
    tempo real (``telegram/listener.py``), pra não duplicar a lógica de
    comandos em dois lugares.
    """
    text = text.strip()
    if text.startswith("/alerta "):
        _handle_add_alert(token, chat_id, text[8:].strip(), alerts)
    elif text == "/meusalertas":
        _handle_list_alerts(token, chat_id, alerts)
    elif text.startswith("/cancelar "):
        _handle_cancel_alert(token, chat_id, text[10:].strip(), alerts)
    elif text == "/status" and admin_chat_id and chat_id == admin_chat_id:
        _handle_status(token, chat_id, alerts)
    elif text == "/start":
        _handle_start(token, chat_id)
    # /buscar é tratado à parte pelo listener (precisa de estado de busca
    # pendente e roda em background) — ver k4promo.commands.hunt.


def poll_commands(
    token: str,
    alerts: dict[str, list[dict]],
    last_update_id: int,
    admin_chat_id: str = "",
) -> int:
    """Polling síncrono e pontual (timeout=0, sem long poll). Mantido por
    compatibilidade com ``--once``/scripts antigos; o processo principal usa
    o listener em tempo real (``telegram/listener.py``), que roda em thread
    própria e não fica preso à cadência dos ciclos."""
    try:
        resp = httpx.get(
            GETUPDATE_URL.format(token=token),
            params={"offset": last_update_id + 1, "timeout": 0},
            timeout=10,
        )
        resp.raise_for_status()
    except httpx.HTTPError as exc:
        log.error("[Commands] polling: %s", _sanitize_log(str(exc), token))
        return last_update_id

    updates = resp.json().get("result", [])
    for update in updates:
        last_update_id = max(last_update_id, update.get("update_id", 0))
        msg = update.get("message")
        if not msg or not msg.get("text"):
            continue
        dispatch_message(
            token, str(msg["chat"]["id"]), msg["text"], alerts, admin_chat_id
        )

    if updates:
        alert_store.save_alerts(alerts)

    return last_update_id


def _handle_start(token: str, chat_id: str) -> None:
    text = (
        "🔔 <b>K4binho — Alertas Personalizados</b>\n\n"
        "Comandos:\n"
        "<code>/alerta rtx 5070</code> — alerta por palavra-chave\n"
        "<code>/alerta ssd abaixo 500</code> — alerta com preço máximo\n"
        "<code>/meusalertas</code> — ver alertas ativos\n"
        "<code>/cancelar 1</code> — cancelar alerta pelo número\n"
        "<code>/buscar palworld</code> — buscar um jogo ou produto agora"
    )
    telegram.send_message(token, chat_id, text)


def _parse_alert_text(text: str) -> tuple[str, float | None]:
    m = re.match(r"(.+?)\s+abaixo\s+(\d+(?:[.,]\d+)?)\s*$", text, re.IGNORECASE)
    if m:
        keywords = m.group(1).strip()
        price = float(m.group(2).replace(",", "."))
        return keywords, price
    return text.strip(), None


def _handle_add_alert(
    token: str, chat_id: str, text: str, alerts: dict[str, list[dict]]
) -> None:
    if not text:
        telegram.send_message(token, chat_id, "Use: <code>/alerta rtx 5070</code> ou <code>/alerta ssd abaixo 500</code>")
        return

    keywords, max_price = _parse_alert_text(text)
    if len(keywords) < 2:
        telegram.send_message(token, chat_id, "Palavra-chave muito curta. Use pelo menos 2 caracteres.")
        return

    user_alerts = alert_store.get_alerts(alerts, chat_id)
    max_alerts = _max_alerts_per_chat()
    if len(user_alerts) >= max_alerts:
        telegram.send_message(
            token, chat_id,
            f"Limite de {max_alerts} alertas atingido. Cancele algum com /cancelar.",
        )
        return

    alert_store.add_alert(alerts, chat_id, keywords, max_price=max_price)

    price_info = f" abaixo de R$ {max_price:.2f}" if max_price else ""
    telegram.send_message(
        token, chat_id,
        f"✅ Alerta criado: <b>{_esc(keywords)}</b>{price_info}\n\nVocê será notificado quando encontrarmos.",
    )
    log.info("[Alerta] chat=%s criou alerta: %s%s", chat_id, keywords, price_info)


def _handle_list_alerts(
    token: str, chat_id: str, alerts: dict[str, list[dict]]
) -> None:
    user_alerts = alert_store.get_alerts(alerts, chat_id)
    if not user_alerts:
        telegram.send_message(token, chat_id, "Nenhum alerta ativo.\n\nCrie com: <code>/alerta rtx 5070</code>")
        return

    lines = ["🔔 <b>Seus alertas:</b>\n"]
    for i, a in enumerate(user_alerts, 1):
        desc = _esc(a["keywords"])
        if a.get("max_price"):
            desc += f" (abaixo de R$ {a['max_price']:.2f})"
        lines.append(f"{i}. {desc}")
    lines.append("\nPara cancelar: <code>/cancelar 1</code>")
    telegram.send_message(token, chat_id, "\n".join(lines))


def _handle_cancel_alert(
    token: str, chat_id: str, text: str, alerts: dict[str, list[dict]]
) -> None:
    try:
        index = int(text) - 1
    except ValueError:
        telegram.send_message(token, chat_id, "Use: <code>/cancelar 1</code> (número do alerta)")
        return

    if alert_store.remove_alert(alerts, chat_id, index):
        telegram.send_message(token, chat_id, f"✅ Alerta #{index + 1} cancelado.")
        log.info("[Alerta] chat=%s cancelou alerta #%d", chat_id, index + 1)
    else:
        telegram.send_message(token, chat_id, "Número inválido. Veja /meusalertas.")


def _handle_status(token: str, chat_id: str, alerts: dict[str, list[dict]]) -> None:
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
    per_topic = {}
    for e in published:
        s = e.get("source", "?")
        sources[s] = sources.get(s, 0) + 1
        t = e.get("topic") or "sem_topico"
        per_topic[t] = per_topic.get(t, 0) + 1

    source_lines = []
    for name, label in [
        ("ml", "ML"), ("shopee", "Shopee"), ("aliexpress", "AliExpress"),
        ("kabum", "KaBuM"), ("gmg", "GMG"), ("steam", "Steam"), ("nuuvem", "Nuuvem"),
    ]:
        count = sources.get(name, 0)
        source_lines.append(f"{label}: {count} publicadas hoje")

    topic_lines = []
    for topic_key, count in sorted(per_topic.items(), key=lambda kv: -kv[1]):
        topic_lines.append(f"{topics.topic_label(topic_key)}: {count}")

    text = (
        f"🤖 <b>K4BINHO STATUS</b>\n\n"
        + "\n".join(source_lines)
        + ("\n\n<b>Por tópico</b>\n" + "\n".join(topic_lines) if topic_lines else "")
        + f"\n\nPublicadas hoje: {len(published)}"
        f"\nComercial: {len(commercial)}"
        f"\nPLUS: {len(plus)}"
        f"\n\nAlertas ativos: {total_alerts}"
        f"\nUsuarios com alertas: {total_users}"
        f"\n\nHorario: {now.strftime('%H:%M')}"
    )
    telegram.send_message(token, chat_id, text)


def notify_alert_match(
    token: str,
    chat_id: str,
    alert: dict,
    title: str,
    price: float,
    link: str,
) -> None:
    price_brl = f"R$ {price:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    text = (
        f"🔔 <b>ALERTA PERSONALIZADO</b>\n\n"
        f"<b>{_esc(title)}</b>\n\n"
        f"Encontrado por <b>{price_brl}</b>\n"
        f"Palavra-chave: {_esc(alert['keywords'])}\n\n"
        f"<a href=\"{_esc(link)}\">VER OFERTA</a>"
    )
    try:
        telegram.send_message(token, chat_id, text)
    except httpx.HTTPError as exc:
        log.error("[Alerta] falha ao notificar chat=%s: %s", chat_id, _sanitize_log(str(exc), token))
