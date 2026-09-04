"""Migra/saneia promotion_cache.json para o schema atual (v2).

Uso:
    python migrate_promotion_cache.py            # aplica e sobrescreve o cache
    python migrate_promotion_cache.py --dry-run  # so mostra o que mudaria

O que faz, por entrada do cache:
  - Reconstroi cada promocao salva e aplica promotion_engine.is_trustworthy
    (a mesma regra que ja bloqueia cupons de layout tipo "COMO"/"ATIVADO"
    na exibicao). Promocoes nao confiaveis sao descartadas.
  - Reescreve a entrada com schema_version=2, preservando o `checked_at`
    original (a idade do cache nao muda so por causa da migracao).
  - Entradas cujo `checked_at` nao pode ser interpretado sao descartadas
    (forcam rescan, comportamento seguro).

Isso resolve o descarte em massa que ocorria porque 189 das 285 entradas
tinham schema_version != 2: antes, get_cached_promotions() so reaproveitava
uma entrada legada quando ela guardava "nenhuma promocao"; qualquer entrada
legada com promocao (mesmo que legitima) forcava rescan sempre. Depois da
migracao, entradas com promocao confiavel voltam a ser reaproveitadas
normalmente dentro do TTL configurado.

Faz backup do arquivo original em promotion_cache.json.bak antes de
sobrescrever (a menos que --dry-run seja usado).
"""

import argparse
import json
import shutil
import sys
from pathlib import Path

import promotion_engine as pe

CACHE_PATH = Path(__file__).parent / "promotion_cache.json"


def migrate(cache: dict) -> tuple[dict, dict]:
    """Retorna (novo_cache, estatisticas)."""
    stats = {
        "entries_total": len(cache),
        "entries_upgraded": 0,
        "entries_dropped_bad_checked_at": 0,
        "promotions_kept": 0,
        "promotions_dropped_untrustworthy": 0,
    }
    new_cache: dict = {}

    for key, entry in cache.items():
        if not isinstance(entry, dict):
            stats["entries_dropped_bad_checked_at"] += 1
            continue
        checked_at = entry.get("checked_at", "")
        if pe._parse_datetime(str(checked_at)) is None:
            stats["entries_dropped_bad_checked_at"] += 1
            continue

        raw_promos = entry.get("promotions", [])
        if not isinstance(raw_promos, list):
            raw_promos = []

        kept = []
        for raw in raw_promos:
            if not isinstance(raw, dict):
                continue
            try:
                promo = pe.promotion_from_dict(raw)
            except (TypeError, ValueError):
                continue
            if pe.is_trustworthy(promo):
                kept.append(pe.promotion_to_dict(promo))
                stats["promotions_kept"] += 1
            else:
                stats["promotions_dropped_untrustworthy"] += 1

        already_v2 = entry.get("schema_version") == pe.CACHE_SCHEMA_VERSION
        if not already_v2 or len(kept) != len(raw_promos):
            stats["entries_upgraded"] += 1

        new_cache[key] = {
            "schema_version": pe.CACHE_SCHEMA_VERSION,
            "checked_at": checked_at,
            "promotions": kept,
        }

    return new_cache, stats


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="so mostra as estatisticas, nao escreve nada")
    parser.add_argument("--path", default=str(CACHE_PATH), help="caminho do promotion_cache.json")
    args = parser.parse_args()

    path = Path(args.path)
    if not path.exists():
        print(f"Nada a migrar: {path} nao existe.")
        return 0

    try:
        cache = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        print(f"ERRO: {path} nao e um JSON valido: {exc}", file=sys.stderr)
        return 1
    if not isinstance(cache, dict):
        print(f"ERRO: {path} nao contem um objeto JSON na raiz.", file=sys.stderr)
        return 1

    new_cache, stats = migrate(cache)

    print("Resumo da migracao:")
    for k, v in stats.items():
        print(f"  {k}: {v}")
    print(f"  entries_final: {len(new_cache)}")

    if args.dry_run:
        print("\n--dry-run: nada foi escrito em disco.")
        return 0

    backup = path.with_suffix(".json.bak")
    shutil.copy2(path, backup)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(new_cache, ensure_ascii=False, indent=2), encoding="utf-8")
    tmp.replace(path)
    print(f"\nBackup salvo em {backup}")
    print(f"Cache migrado escrito em {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
