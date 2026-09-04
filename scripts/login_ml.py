"""Login do Mercado Livre: abre o Chrome para autenticar uma vez."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from k4promo.providers.mercadolivre import browser as ml_playwright  # noqa: E402

if __name__ == "__main__":
    ml_playwright.login()
