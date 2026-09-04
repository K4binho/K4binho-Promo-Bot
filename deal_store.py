import json
import logging
import os
import tempfile
import threading
import unicodedata
from datetime import UTC, datetime, timedelta
from pathlib import Path

STORE_PATH = Path(__file__).parent / "deal_store.json"

log = logging.getLogger("k4binho")

_save_lock = threading.Lock()


def load_deals() -> dict[str, dict]:
    if not STORE_PATH.exists():
        return {}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}
    return data if isinstance(data, dict) else {}


def save_deals(deals: dict[str, dict]) -> None:
    """Grava de forma atomica (arquivo temp + rename) e serializada entre
    threads -- ver seen_store.save_seen, mesmo motivo.
    """
    payload = json.dumps(dict(deals), ensure_ascii=False, separators=(",", ":"))
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


def _normalize_text(text: str) -> str:
    """Normaliza titulo/URL pra comparacao de duplicidade entre IDs diferentes.

    Usado quando a mesma loja relista o mesmo produto com um item_id novo:
    sem SKU/EAN disponiveis nas APIs de origem, titulo+URL normalizados sao
    o sinal mais forte que temos pra reconhecer "e o mesmo produto de novo".
    """
    norm = unicodedata.normalize("NFKD", (text or "").lower())
    norm = "".join(c for c in norm if not unicodedata.combining(c))
    return " ".join(norm.split())


def normalize_title(title: str) -> str:
    return _normalize_text(title)[:80]


def normalize_url(url: str) -> str:
    """Remove querystring/fragmento pra comparar a URL 'base' do produto."""
    base = (url or "").split("?", 1)[0].split("#", 1)[0]
    return _normalize_text(base)


def record_published(
    deals: dict[str, dict],
    item_id: str,
    price: float,
    *,
    promotion_signature: str = "",
    title: str = "",
    url: str = "",
    message_id: int | None = None,
    thread_id: int | None = None,
    reason: str = "published",
) -> None:
    entry = deals.get(item_id, {})
    best_price = entry.get("best_price")
    try:
        best_price = min(float(best_price), price) if best_price is not None else price
    except (TypeError, ValueError):
        best_price = price
    republish_count = int(entry.get("republish_count", 0) or 0)
    if reason != "published":
        republish_count += 1
    deals[item_id] = {
        "price": round(price, 2),
        "best_price": round(best_price, 2),
        "posted_at": datetime.now(UTC).isoformat(),
        "first_posted_at": entry.get("first_posted_at") or datetime.now(UTC).isoformat(),
        "promotion_signature": promotion_signature,
        "normalized_title": normalize_title(title) if title else entry.get("normalized_title", ""),
        "normalized_url": normalize_url(url) if url else entry.get("normalized_url", ""),
        "message_id": message_id if message_id is not None else entry.get("message_id"),
        "thread_id": thread_id if thread_id is not None else entry.get("thread_id"),
        "republish_count": republish_count,
        "last_reason": reason,
    }


def find_duplicate_id(deals: dict[str, dict], item_id: str, *, title: str = "", url: str = "", prefix: str = "") -> str | None:
    """Acha um item_id ja publicado com o mesmo titulo/URL normalizados.

    Cobre o caso de relist com item_id novo (a loja gerou outro anuncio pro
    mesmo produto). `prefix`, quando informado, restringe a busca a chaves
    da mesma origem (ex: "ali:") pra nao cruzar produtos de lojas diferentes
    que por acaso tenham titulo parecido. Retorna o item_id existente, ou
    None se nao achar.
    """
    if item_id in deals:
        return None
    norm_title = normalize_title(title) if title else ""
    norm_url = normalize_url(url) if url else ""
    if not norm_title and not norm_url:
        return None
    for existing_id, entry in deals.items():
        if prefix and not existing_id.startswith(prefix):
            continue
        if norm_url and entry.get("normalized_url") == norm_url:
            return existing_id
        if norm_title and entry.get("normalized_title") == norm_title:
            return existing_id
    return None


def check_promotion_revival(deals: dict[str, dict], item_id: str, current_price: float, promotion_signature: str, *, min_drop_percent: float = 5.0, min_drop_amount: float = 20.0, cooldown_hours: int = 6, now: datetime | None = None) -> tuple[bool, float | None]:
    entry=deals.get(item_id)
    if not entry or not promotion_signature: return False, None
    if str(entry.get("promotion_signature","") or "") == promotion_signature: return False, None
    try: previous=float(entry.get("price"))
    except (TypeError, ValueError): return False, None
    if previous <= 0 or current_price >= previous: return False, previous
    raw=str(entry.get("posted_at","") or "")
    if raw:
        try:
            posted=datetime.fromisoformat(raw)
            if posted.tzinfo is None: posted=posted.replace(tzinfo=UTC)
            current=now or datetime.now(UTC)
            if current-posted.astimezone(UTC) < timedelta(hours=max(0,cooldown_hours)): return False, previous
        except ValueError: pass
    amount=previous-current_price; pct=(amount/previous)*100
    return (pct >= min_drop_percent or amount >= min_drop_amount), previous


def check_price_drop(
    deals: dict[str, dict],
    item_id: str,
    current_price: float,
    min_drop_percent: int = 10,
    min_drop_amount: float = 20.0,
) -> tuple[bool, float | None]:
    entry = deals.get(item_id)
    if not entry:
        return False, None
    previous_price = entry["price"]
    if current_price >= previous_price:
        return False, None
    drop_amount = previous_price - current_price
    drop_percent = (drop_amount / previous_price) * 100
    if drop_percent >= min_drop_percent or drop_amount >= min_drop_amount:
        return True, previous_price
    return False, None


def should_republish(
    deals: dict[str, dict],
    item_id: str,
    current_price: float,
    *,
    promotion_signature: str = "",
    min_drop_percent: float = 10.0,
    min_drop_amount: float = 20.0,
    min_repost_days: int | None = None,
    now: datetime | None = None,
) -> tuple[bool, str, float | None]:
    """Decide se um item ja publicado (esta em `seen`) pode ser republicado.

    Motivos possiveis, em ordem de prioridade (a spec exige registrar o
    motivo da republicacao):
      - "menor_preco_historico": preco atual eh o menor ja registrado pra esse item
      - "novo_cupom": apareceu cupom/promocao diferente da ultima vez, com preco menor
      - "queda_de_preco": preco caiu o suficiente desde a ultima publicacao
      - "periodo_configurado": passou o periodo minimo configurado pra reanunciar

    Retorna (deve_republicar, motivo, preco_anterior). Nao deve ser chamado
    para itens que ainda nao foram publicados (item_id not in deals) -- isso
    e "publicacao nova", nao republicacao.
    """
    entry = deals.get(item_id)
    if not entry:
        return False, "", None
    try:
        previous_price = float(entry.get("price"))
    except (TypeError, ValueError):
        previous_price = None
    try:
        best_price = float(entry.get("best_price", previous_price))
    except (TypeError, ValueError):
        best_price = previous_price

    if best_price is not None and current_price < best_price:
        drop_amount = best_price - current_price
        drop_percent = (drop_amount / best_price) * 100 if best_price > 0 else 0
        if drop_percent >= min_drop_percent or drop_amount >= min_drop_amount:
            return True, "menor_preco_historico", previous_price

    if promotion_signature and str(entry.get("promotion_signature", "") or "") != promotion_signature:
        if previous_price is not None and current_price < previous_price:
            return True, "novo_cupom", previous_price

    if previous_price is not None and previous_price > 0 and current_price < previous_price:
        drop_amount = previous_price - current_price
        drop_percent = (drop_amount / previous_price) * 100
        if drop_percent >= min_drop_percent or drop_amount >= min_drop_amount:
            return True, "queda_de_preco", previous_price

    if min_repost_days is not None:
        raw = str(entry.get("posted_at", "") or "")
        if raw:
            try:
                posted = datetime.fromisoformat(raw)
                if posted.tzinfo is None:
                    posted = posted.replace(tzinfo=UTC)
                current = now or datetime.now(UTC)
                if current - posted.astimezone(UTC) >= timedelta(days=max(0, min_repost_days)):
                    return True, "periodo_configurado", previous_price
            except ValueError:
                pass

    return False, "", previous_price

