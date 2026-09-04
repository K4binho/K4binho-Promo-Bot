"""Cliente da Telegram Bot API.

Só transporte: montar o payload e enviar. O layout das mensagens vive em
``formatters.py``.
"""

from __future__ import annotations

import httpx

MESSAGE_URL = "https://api.telegram.org/bot{token}/sendMessage"
PHOTO_URL = "https://api.telegram.org/bot{token}/sendPhoto"


def send_message(token: str, channel_id: str, text: str,
                 thread_id: int | None = None,
                 image_url: str | None = None) -> None:
    if image_url:
        url = PHOTO_URL.format(token=token)
        payload = {
            "chat_id": channel_id,
            "photo": image_url,
            "caption": text,
            "parse_mode": "HTML",
        }
    else:
        url = MESSAGE_URL.format(token=token)
        payload = {
            "chat_id": channel_id,
            "text": text,
            "parse_mode": "HTML",
            "disable_web_page_preview": False,
        }
    if thread_id is not None:
        payload["message_thread_id"] = thread_id
    resp = httpx.post(url, json=payload, timeout=30)
    resp.raise_for_status()
