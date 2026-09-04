"""Wrapper fino sobre os métodos de fórum (tópicos) da Bot API do Telegram.

Requer que o bot seja administrador do grupo com a permissão
"Gerenciar Tópicos" (can_manage_topics). Sem isso, todas as chamadas
aqui retornam erro 400 da API do Telegram.

IMPORTANTE: a Bot API não tem um método para *listar* tópicos existentes.
Por isso o mapeamento categoria -> thread_id precisa ser registrado uma vez
(veja topics_store.py e os comandos /topico e /criartopico no bot), seja
porque o próprio bot criou o tópico, seja porque um admin registrou um
tópico já existente.
"""

import logging

import httpx

BASE_URL = "https://api.telegram.org/bot{token}/{method}"

log = logging.getLogger("k4binho")


def _call(token: str, method: str, payload: dict) -> dict:
    url = BASE_URL.format(token=token, method=method)
    resp = httpx.post(url, json=payload, timeout=30)
    resp.raise_for_status()
    data = resp.json()
    if not data.get("ok"):
        raise RuntimeError(f"Telegram API {method} falhou: {data}")
    return data.get("result", {})


def create_forum_topic(
    token: str,
    chat_id: str,
    name: str,
    icon_color: int | None = None,
    icon_custom_emoji_id: str | None = None,
) -> dict:
    """Cria um novo tópico. Retorna dict com 'message_thread_id' e 'name'."""
    payload: dict = {"chat_id": chat_id, "name": name[:128]}
    if icon_color is not None:
        payload["icon_color"] = icon_color
    if icon_custom_emoji_id:
        payload["icon_custom_emoji_id"] = icon_custom_emoji_id
    return _call(token, "createForumTopic", payload)


def edit_forum_topic(
    token: str,
    chat_id: str,
    message_thread_id: int,
    name: str | None = None,
    icon_custom_emoji_id: str | None = None,
) -> None:
    """Renomeia e/ou troca o ícone de um tópico existente."""
    payload: dict = {"chat_id": chat_id, "message_thread_id": message_thread_id}
    if name is not None:
        payload["name"] = name[:128]
    if icon_custom_emoji_id is not None:
        payload["icon_custom_emoji_id"] = icon_custom_emoji_id
    _call(token, "editForumTopic", payload)


def close_forum_topic(token: str, chat_id: str, message_thread_id: int) -> None:
    _call(token, "closeForumTopic", {"chat_id": chat_id, "message_thread_id": message_thread_id})


def reopen_forum_topic(token: str, chat_id: str, message_thread_id: int) -> None:
    _call(token, "reopenForumTopic", {"chat_id": chat_id, "message_thread_id": message_thread_id})


def delete_forum_topic(token: str, chat_id: str, message_thread_id: int) -> None:
    _call(token, "deleteForumTopic", {"chat_id": chat_id, "message_thread_id": message_thread_id})


def get_forum_topic_icon_stickers(token: str) -> list[dict]:
    """Lista os ícones padrão (coloridos) disponíveis para tópicos."""
    return _call(token, "getForumTopicIconStickers", {})
