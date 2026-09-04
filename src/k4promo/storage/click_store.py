"""Click tracking — maps deal_id to destination URL, records clicks in JSONL."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from k4promo.storage.paths import data_path

LINKS_PATH = data_path("click_links.json")
CLICKS_PATH = data_path("clicks.jsonl")

log = logging.getLogger("k4binho")


def load_links() -> dict[str, dict]:
    if not LINKS_PATH.exists():
        return {}
    try:
        data = json.loads(LINKS_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_links(links: dict[str, dict]) -> None:
    LINKS_PATH.write_text(
        json.dumps(links, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )


def register_link(
    links: dict[str, dict],
    deal_id: str,
    destination_url: str,
    source: str = "",
    title: str = "",
) -> str:
    links[deal_id] = {
        "url": destination_url,
        "source": source,
        "title": title,
        "created_at": datetime.now(UTC).isoformat(),
    }
    return deal_id


def resolve_link(links: dict[str, dict], deal_id: str) -> str | None:
    entry = links.get(deal_id)
    return entry["url"] if entry else None


def record_click(deal_id: str, source: str = "") -> None:
    entry = {
        "deal_id": deal_id,
        "source": source,
        "timestamp": datetime.now(UTC).isoformat(),
    }
    try:
        with open(CLICKS_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError as exc:
        log.error("[Clicks] falha ao gravar: %s", exc)


def load_clicks(limit: int = 0) -> list[dict]:
    if not CLICKS_PATH.exists():
        return []
    entries = []
    with open(CLICKS_PATH, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if limit > 0:
        return entries[-limit:]
    return entries


def click_stats(clicks: list[dict] | None = None) -> dict[str, dict]:
    if clicks is None:
        clicks = load_clicks()
    stats: dict[str, dict] = {}
    for c in clicks:
        did = c.get("deal_id", "")
        if did not in stats:
            stats[did] = {"clicks": 0, "source": c.get("source", "")}
        stats[did]["clicks"] += 1
    return stats
