"""Gera um ZIP sanitizado do projeto, excluindo arquivos sensiveis."""

import zipfile
from datetime import datetime
from pathlib import Path

PROJECT_DIR = Path(__file__).parent
OUTPUT_DIR = PROJECT_DIR

EXCLUDE = {
    ".env",
    "ml_token.json",
    "seen.json",
    "price_history.json",
    "analytics.jsonl",
    "deal_store.json",
    "alerts.json",
    "click_links.json",
    "clicks.jsonl",
    "digest_state.json",
    "promotion_cache.json",
    "promotion_state.json",
    "promotions.json",
    "bot.log",
}

EXCLUDE_DIRS = {
    "ml_profile",
    "__pycache__",
    ".pytest_cache",
    ".claude",
    ".git",
}


def export() -> Path:
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_name = f"k4binho_export_{timestamp}.zip"
    zip_path = OUTPUT_DIR / zip_name

    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for file in sorted(PROJECT_DIR.rglob("*")):
            if not file.is_file():
                continue
            rel = file.relative_to(PROJECT_DIR)
            parts = rel.parts
            if any(d in EXCLUDE_DIRS for d in parts):
                continue
            if rel.name in EXCLUDE:
                continue
            if rel.suffix in (".pyc", ".zip"):
                # Nunca embute ZIPs antigos dentro do export: eles podem conter
                # snapshots com .env/tokens e ainda inflariam o arquivo final.
                continue
            if rel.name.startswith("k4binho_export_"):
                continue
            zf.write(file, rel)
            print(f"  + {rel}")

    print(f"\nExportado: {zip_path}")
    print(f"Tamanho: {zip_path.stat().st_size / 1024:.1f} KB")
    return zip_path


if __name__ == "__main__":
    export()
