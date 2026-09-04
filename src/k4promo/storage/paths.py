"""Onde ficam os arquivos de estado operacional.

Antes do pacote, cada módulo resolvia o próprio caminho com
``Path(__file__).parent``, que por acaso era a raiz do projeto. Depois da
reorganização isso apontaria para dentro de ``src/k4promo/...`` e o bot
perderia todo o estado já gravado (``seen.json``, histórico de preço,
analytics, cupons em cache).

A regra agora é explícita: os dados moram no diretório de trabalho, que é a
raiz do projeto (os atalhos ``.bat``/``.vbs`` fazem ``cd`` para lá antes de
iniciar). ``K4PROMO_DATA_DIR`` permite apontar para outro lugar sem tocar no
código.
"""

from __future__ import annotations

import os
from pathlib import Path


def data_dir() -> Path:
    """Diretório onde o estado é lido e gravado."""
    override = os.getenv("K4PROMO_DATA_DIR", "").strip()
    return Path(override).expanduser() if override else Path.cwd()


def data_path(name: str) -> Path:
    """Caminho de um arquivo de estado pelo nome."""
    return data_dir() / name
