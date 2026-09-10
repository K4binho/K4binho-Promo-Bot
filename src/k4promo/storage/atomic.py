"""Escrita atômica de arquivos de estado (Fase 5, seção 19).

Todo JSON operacional grava por aqui: escreve num arquivo temporário
*único* no MESMO diretório do arquivo final, dá flush + fsync, e só então
substitui o arquivo final com ``os.replace()`` — atômico no mesmo sistema
de arquivos (POSIX e Windows). Um crash no meio da escrita nunca deixa o
arquivo original truncado ou corrompido: ou o replace aconteceu (dado
novo, completo) ou não aconteceu (dado antigo, intacto).

Um lock por caminho serializa escritas concorrentes dentro do processo —
ex.: o listener e uma fonte gravando ``alerts.json``/``seen.json`` quase ao
mesmo tempo — sem depender de cada chamador lembrar de usar ``ctx.lock``.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Any

log = logging.getLogger("k4binho")

_locks: dict[Path, threading.Lock] = {}
_locks_guard = threading.Lock()


def _lock_for(path: Path) -> threading.Lock:
    with _locks_guard:
        lock = _locks.get(path)
        if lock is None:
            lock = threading.Lock()
            _locks[path] = lock
        return lock


def atomic_write_text(path: Path, text: str) -> None:
    """Grava ``text`` em ``path`` atomicamente. Cria o diretório se faltar."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with _lock_for(path):
        fd, tmp_name = tempfile.mkstemp(
            prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
        )
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(text)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(OSError):
                os.unlink(tmp_name)
            raise


def atomic_write_json(path: Path, data: Any, *, indent: int | None = None) -> None:
    separators = (",", ": ") if indent else (",", ":")
    payload = json.dumps(data, ensure_ascii=False, indent=indent, separators=separators)
    atomic_write_text(path, payload)


def ensure_writable(directory: Path) -> None:
    """Confirma que dá pra criar e escrever nesse diretório. Levanta
    ``OSError``/``PermissionError`` com uma mensagem clara se não der —
    quem chama decide o que fazer (main.py aborta a inicialização)."""
    try:
        directory.mkdir(parents=True, exist_ok=True)
        probe = directory / ".k4promo_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
    except OSError as exc:
        raise OSError(
            f"Sem permissao de escrita em '{directory}': {exc}"
        ) from exc
