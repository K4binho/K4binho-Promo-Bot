"""Mapeamento persistente: chave de categoria -> tópico (thread_id) do fórum.

A Bot API do Telegram não permite listar tópicos existentes, então esse
arquivo é a "memória" do bot sobre qual tópico corresponde a qual categoria.
É populado pelos comandos /topico (registra o tópico atual) e /criartopico
(cria um tópico novo e já registra) definidos em bot_commands.py.
"""

import json
import logging
from pathlib import Path

STORE_PATH = Path(__file__).parent / "topics_store.json"
log = logging.getLogger("k4binho")


def _normalize_key(key: str) -> str:
    return key.strip().lower()


def load_topics() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_topics(topics: dict[str, dict]) -> None:
    STORE_PATH.write_text(
        json.dumps(topics, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def register_topic(topics: dict[str, dict], key: str, thread_id: int, name: str = "") -> None:
    topics[_normalize_key(key)] = {"thread_id": thread_id, "name": name}


def unregister_topic(topics: dict[str, dict], key: str) -> bool:
    return topics.pop(_normalize_key(key), None) is not None


def resolve_thread_id(topics: dict[str, dict], key: str) -> int | None:
    """Retorna o thread_id do tópico registrado para essa chave, ou None."""
    entry = topics.get(_normalize_key(key))
    return entry.get("thread_id") if entry else None
