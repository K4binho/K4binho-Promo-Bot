"""Launcher de compatibilidade.

O bot foi reorganizado em ``src/k4promo``. Este arquivo existe só para que
`python bot.py` (e os atalhos .bat/.vbs) continuem funcionando sem instalar o
pacote. A forma recomendada é `pip install -e .` e depois `python -m k4promo`.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

from k4promo.main import main  # noqa: E402

if __name__ == "__main__":
    main()
