import json
import os
import tempfile
import threading
from datetime import UTC, datetime, timedelta
from pathlib import Path

STORE_PATH = Path(__file__).parent / "seen.json"
PLUS_PREFIXES = ("steam:", "nuuvem:", "gmg:")
PLUS_EXPIRE_DAYS = 7

_save_lock = threading.Lock()


def load_seen() -> dict[str, str]:
    if not STORE_PATH.exists():
        return {}
    try:
        raw = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    if isinstance(raw, list):
        now = datetime.now(UTC).isoformat()
        return {item: now for item in raw}
    if isinstance(raw, dict):
        return raw
    return {}


def save_seen(seen: dict[str, str]) -> None:
    """Grava de forma atomica (arquivo temp + rename) e serializada entre
    threads, pra nao corromper o arquivo se duas fontes salvarem ao mesmo
    tempo nem perder o arquivo inteiro se o processo morrer no meio da
    escrita.
    """
    payload = json.dumps(dict(seen), ensure_ascii=False, separators=(",", ":"))
    with _save_lock:
        fd, tmp_path = tempfile.mkstemp(
            dir=STORE_PATH.parent, prefix=STORE_PATH.name + ".", suffix=".tmp"
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(payload)
            os.replace(tmp_path, STORE_PATH)
        except OSError:
            if os.path.exists(tmp_path):
                os.unlink(tmp_path)
            raise


def mark_seen(seen: dict[str, str], item_id: str) -> None:
    seen[item_id] = datetime.now(UTC).isoformat()


def expire_plus(seen: dict[str, str], days: int = PLUS_EXPIRE_DAYS) -> int:
    cutoff = datetime.now(UTC) - timedelta(days=days)
    expired = []
    for item_id, ts in seen.items():
        if not any(item_id.startswith(p) for p in PLUS_PREFIXES):
            continue
        try:
            when = datetime.fromisoformat(ts)
            if when < cutoff:
                expired.append(item_id)
        except (TypeError, ValueError):
            continue
    for item_id in expired:
        del seen[item_id]
    return len(expired)
