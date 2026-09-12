"""Classificação editorial de itens GMG por família de jogo."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from k4promo.storage.deal_store import normalize_title


@dataclass(frozen=True)
class GameFamily:
    """Família normalizada e tipo editorial de produto."""

    key: str
    kind: str


# Marcadores encontrados depois do nome do jogo em DLCs, packs e edições.
_DLC_MARKERS = {
    "add-on", "addon", "cosmetic", "cosmetics", "dlc", "expansion", "expansions",
    "equipment", "outfit", "pack", "packs", "season pass", "starter", "support",
    "weapons", "weapon", "upgrade", "soundtrack", "skins",
}
_EDITION_MARKERS = {
    "complete", "deluxe", "gold", "ultimate", "premium", "platinum", "special",
    "definitive", "digital", "goty", "edition", "collection", "bundle",
}
_PLATFORM_RE = re.compile(r"\s+(?:-\s*)?(?:pc|windows|mac|linux|eps)\s*$", re.IGNORECASE)
_SPACE_RE = re.compile(r"\s+")


def classify_game_title(title: str) -> GameFamily:
    """Extrai família sem confundir sequel numerada com DLC/edição."""
    text = normalize_title(title)
    text = _PLATFORM_RE.sub("", text).strip()
    if not text:
        return GameFamily("", "base")

    words = text.split()
    marker_index: int | None = None
    marker_kind = "base"
    for index, word in enumerate(words):
        if word in {"bundle", "collection"}:
            marker_index = index
            marker_kind = "bundle"
            break
        if word in _EDITION_MARKERS:
            marker_index = index
            marker_kind = "edition"
            break
        if word in _DLC_MARKERS:
            marker_index = index
            marker_kind = "dlc"
            break

    if marker_index is not None and marker_index > 0:
        family = " ".join(words[:marker_index])
    else:
        family = text

    # Remove conectores que ficam sobrando antes de marcador removido.
    family = re.sub(r"\s+(?:the|of|and|for|with)$", "", family).strip()
    family = _SPACE_RE.sub(" ", family)
    return GameFamily(family, marker_kind)


def family_priority(kind: str) -> int:
    """Prioriza produto completo/base; DLC fica último."""
    return {"bundle": 3, "edition": 3, "base": 2, "dlc": 1}.get(kind, 1)


def recent_gmg_families(
    published_deals: dict[str, dict], *, cooldown_days: int
) -> set[str]:
    """Famílias publicadas recentemente, usadas para evitar variações repetidas."""
    if cooldown_days <= 0:
        return set()
    cutoff = datetime.now(UTC) - timedelta(days=cooldown_days)
    result: set[str] = set()
    for key, entry in published_deals.items():
        if not key.startswith("gmg:"):
            continue
        raw = str(entry.get("posted_at", "") or "")
        try:
            posted_at = datetime.fromisoformat(raw)
            if posted_at.tzinfo is None:
                posted_at = posted_at.replace(tzinfo=UTC)
        except ValueError:
            continue
        if posted_at.astimezone(UTC) >= cutoff:
            family = classify_game_title(str(entry.get("normalized_title", ""))).key
            if family:
                result.add(family)
    return result


def select_one_per_family(
    scored: list[tuple[int, object, object]], *, max_per_family: int = 1
) -> tuple[list[tuple[int, object, object]], int]:
    """Escolhe melhores itens, evitando DLC fraca junto do jogo principal.

    Edição/bundle só substitui base quando ganha por margem editorial clara;
    DLC/pack só entra quando família não tem base ou produto completo.
    """
    if max_per_family <= 0:
        return [], len(scored)

    groups: dict[str, list[tuple[int, object, object, GameFamily]]] = {}
    for total, offer, result in scored:
        info = classify_game_title(getattr(offer, "title", ""))
        groups.setdefault(info.key or f"__{getattr(offer, 'offer_id', '')}", []).append(
            (total, offer, result, info)
        )

    chosen: list[tuple[int, object, object]] = []
    for candidates in groups.values():
        candidates.sort(key=lambda item: item[0], reverse=True)
        bases = [item for item in candidates if item[3].kind == "base"]
        complete = [item for item in candidates if item[3].kind in {"edition", "bundle"}]
        extras = [item for item in candidates if item[3].kind == "dlc"]

        if complete and bases:
            best_base = bases[0]
            best_complete = complete[0]
            selected = best_complete if best_complete[0] >= best_base[0] + 8 else best_base
        elif complete:
            selected = complete[0]
        elif bases:
            selected = bases[0]
        else:
            selected = extras[0] if extras else candidates[0]
        chosen.append(selected[:3])

    chosen.sort(key=lambda item: item[0], reverse=True)
    # max_per_family permanece parâmetro público para permitir futura expansão;
    # atual limite padrão e seguro é um item por grupo.
    if max_per_family == 1:
        return chosen, len(scored) - len(chosen)
    return chosen, max(0, len(scored) - len(chosen))
