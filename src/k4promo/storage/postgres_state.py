"""Persistência opcional de estado em PostgreSQL.

JSON continua sendo fallback local. PostgreSQL só ativa quando ``DATABASE_URL``
está definido. Erros não fazem fallback silencioso: voltar para JSON após falha
poderia republicar ofertas já gravadas no banco.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, Callable


_SCHEMA_SQL = (
    """
    CREATE TABLE IF NOT EXISTS k4promo_seen (
        item_key TEXT PRIMARY KEY,
        seen_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS k4promo_published_deals (
        item_key TEXT PRIMARY KEY,
        price DOUBLE PRECISION NOT NULL,
        best_price DOUBLE PRECISION NOT NULL,
        posted_at TIMESTAMPTZ NOT NULL,
        first_posted_at TIMESTAMPTZ NOT NULL,
        promotion_signature TEXT NOT NULL DEFAULT '',
        normalized_title TEXT NOT NULL DEFAULT '',
        normalized_url TEXT NOT NULL DEFAULT '',
        message_id BIGINT,
        thread_id BIGINT,
        republish_count INTEGER NOT NULL DEFAULT 0,
        last_reason TEXT NOT NULL DEFAULT 'novo'
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS k4promo_state_migrations (
        migration_name TEXT PRIMARY KEY,
        applied_at TIMESTAMPTZ NOT NULL
    )
    """,
    """
    CREATE TABLE IF NOT EXISTS k4promo_publication_reservations (
        source TEXT NOT NULL,
        normalized_title TEXT NOT NULL,
        item_key TEXT NOT NULL,
        owner_id TEXT NOT NULL,
        reserved_until TIMESTAMPTZ NOT NULL,
        PRIMARY KEY (source, normalized_title)
    )
    """,
    """
    CREATE INDEX IF NOT EXISTS k4promo_published_deals_source_title_idx
    ON k4promo_published_deals (normalized_title, item_key)
    """,
)

_IMPORT_MIGRATION = "json-state-v1"
_RESERVATION_TTL = timedelta(minutes=10)


def _utc_now() -> datetime:
    return datetime.now(UTC)


def _as_datetime(value: Any, fallback: datetime) -> datetime:
    if isinstance(value, datetime):
        result = value
    else:
        try:
            result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return fallback
    if result.tzinfo is None:
        return result.replace(tzinfo=UTC)
    return result.astimezone(UTC)


def _as_float(value: Any, fallback: float) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _as_int_or_none(value: Any) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


class PostgresState:
    """Backend de ``seen``/``deal_store`` com importação JSON única."""

    def __init__(
        self,
        dsn: str,
        *,
        connect: Callable[[str], Any] | None = None,
    ) -> None:
        self._dsn = dsn
        self._connect_factory = connect
        self._connection: Any | None = None
        self._owner_id = uuid.uuid4().hex

    def _get_connection(self) -> Any:
        if self._connection is not None:
            return self._connection
        try:
            if self._connect_factory is not None:
                self._connection = self._connect_factory(self._dsn)
            else:
                import psycopg

                self._connection = psycopg.connect(self._dsn)
        except ModuleNotFoundError:
            raise RuntimeError(
                "PostgreSQL configurado, mas dependencia psycopg nao instalada"
            ) from None
        except Exception:
            raise RuntimeError("Falha ao conectar PostgreSQL") from None
        return self._connection

    def _transaction(self):
        return self._get_connection().transaction()

    def _run_schema(self) -> None:
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    for statement in _SCHEMA_SQL:
                        cursor.execute(statement)
        except RuntimeError:
            raise
        except Exception:
            self.close()
            raise RuntimeError("Falha ao criar schema PostgreSQL") from None

    def load_state(
        self,
        legacy_seen: dict[str, str],
        legacy_deals: dict[str, dict],
    ) -> tuple[dict[str, str], dict[str, dict]]:
        """Cria schema, importa JSON uma vez e carrega estado do DB."""
        self._run_schema()
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute(
                        "SELECT 1 FROM k4promo_state_migrations "
                        "WHERE migration_name = %s",
                        (_IMPORT_MIGRATION,),
                    )
                    already_imported = cursor.fetchone() is not None
                    if not already_imported:
                        self._import_seen(cursor, legacy_seen)
                        self._import_deals(cursor, legacy_deals)
                        cursor.execute(
                            "INSERT INTO k4promo_state_migrations "
                            "(migration_name, applied_at) VALUES (%s, %s)",
                            (_IMPORT_MIGRATION, _utc_now()),
                        )
        except Exception:
            self.close()
            raise RuntimeError("Falha ao importar estado para PostgreSQL") from None
        return self._load_state()

    @staticmethod
    def _import_seen(cursor: Any, seen: dict[str, str]) -> None:
        rows = [
            (str(item_key), _as_datetime(timestamp, _utc_now()))
            for item_key, timestamp in seen.items()
        ]
        if rows:
            cursor.executemany(
                "INSERT INTO k4promo_seen (item_key, seen_at) VALUES (%s, %s) "
                "ON CONFLICT (item_key) DO NOTHING",
                rows,
            )

    @classmethod
    def _deal_row(cls, item_key: str, entry: dict) -> tuple[Any, ...] | None:
        if not isinstance(entry, dict):
            return None
        price = _as_float(entry.get("price"), float("nan"))
        if price != price:
            return None
        now = _utc_now()
        best_price = _as_float(entry.get("best_price", price), price)
        posted_at = _as_datetime(entry.get("posted_at"), now)
        first_posted_at = _as_datetime(entry.get("first_posted_at"), posted_at)
        return (
            str(item_key), price, best_price, posted_at, first_posted_at,
            str(entry.get("promotion_signature", "") or ""),
            str(entry.get("normalized_title", "") or ""),
            str(entry.get("normalized_url", "") or ""),
            _as_int_or_none(entry.get("message_id")),
            _as_int_or_none(entry.get("thread_id")),
            _as_int_or_none(entry.get("republish_count")) or 0,
            str(entry.get("last_reason", "novo") or "novo"),
        )

    @classmethod
    def _import_deals(cls, cursor: Any, deals: dict[str, dict]) -> None:
        rows = []
        for item_key, entry in deals.items():
            row = cls._deal_row(item_key, entry)
            if row is not None:
                rows.append(row)
        if rows:
            cursor.executemany(
                """INSERT INTO k4promo_published_deals
                (item_key, price, best_price, posted_at, first_posted_at,
                 promotion_signature, normalized_title, normalized_url,
                 message_id, thread_id, republish_count, last_reason)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                ON CONFLICT (item_key) DO NOTHING""",
                rows,
            )

    def _load_state(self) -> tuple[dict[str, str], dict[str, dict]]:
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute(
                        "SELECT item_key, seen_at FROM k4promo_seen"
                    )
                    seen_rows = cursor.fetchall()
                    cursor.execute(
                        """SELECT item_key, price, best_price, posted_at,
                        first_posted_at, promotion_signature, normalized_title,
                        normalized_url, message_id, thread_id, republish_count,
                        last_reason FROM k4promo_published_deals"""
                    )
                    deal_rows = cursor.fetchall()
        except Exception:
            self.close()
            raise RuntimeError("Falha ao carregar estado PostgreSQL") from None

        seen = {
            str(item_key): _as_datetime(timestamp, _utc_now()).isoformat()
            for item_key, timestamp in seen_rows
        }
        deals = {}
        for row in deal_rows:
            (
                item_key, price, best_price, posted_at, first_posted_at,
                promotion_signature, normalized_title, normalized_url,
                message_id, thread_id, republish_count, last_reason,
            ) = row
            deals[str(item_key)] = {
                "price": float(price),
                "best_price": float(best_price),
                "posted_at": _as_datetime(posted_at, _utc_now()).isoformat(),
                "first_posted_at": _as_datetime(first_posted_at, _utc_now()).isoformat(),
                "promotion_signature": promotion_signature or "",
                "normalized_title": normalized_title or "",
                "normalized_url": normalized_url or "",
                "message_id": message_id,
                "thread_id": thread_id,
                "republish_count": int(republish_count or 0),
                "last_reason": last_reason or "novo",
            }
        return seen, deals

    def persist(self, seen: dict[str, str], deals: dict[str, dict]) -> None:
        """Substitui estado DB numa transação única."""
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute("DELETE FROM k4promo_seen")
                    self._import_seen(cursor, seen)
                    cursor.execute("DELETE FROM k4promo_published_deals")
                    self._import_deals(cursor, deals)
        except Exception:
            self.close()
            raise RuntimeError("Falha ao salvar estado PostgreSQL") from None

    def reserve_publication(self, identity: tuple[str, str], item_key: str) -> bool:
        """Reserva identidade de publicação atomically entre processos."""
        source, normalized_title = identity
        expires = _utc_now() + _RESERVATION_TTL
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute(
                        """INSERT INTO k4promo_publication_reservations
                        (source, normalized_title, item_key, owner_id, reserved_until)
                        VALUES (%s, %s, %s, %s, %s)
                        ON CONFLICT (source, normalized_title) DO UPDATE SET
                          item_key = EXCLUDED.item_key,
                          owner_id = EXCLUDED.owner_id,
                          reserved_until = EXCLUDED.reserved_until
                        WHERE k4promo_publication_reservations.reserved_until
                              <= CURRENT_TIMESTAMP""",
                        (source, normalized_title, item_key, self._owner_id, expires),
                    )
                    return cursor.rowcount == 1
        except Exception:
            self.close()
            raise RuntimeError("Falha ao reservar publicação PostgreSQL") from None

    def release_publication(self, identity: tuple[str, str]) -> None:
        source, normalized_title = identity
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute(
                        """DELETE FROM k4promo_publication_reservations
                        WHERE source = %s AND normalized_title = %s
                        AND owner_id = %s""",
                        (source, normalized_title, self._owner_id),
                    )
        except Exception:
            self.close()
            raise RuntimeError("Falha ao liberar reserva PostgreSQL") from None

    def clear_reservations(self) -> None:
        try:
            with self._transaction():
                with self._get_connection().cursor() as cursor:
                    cursor.execute(
                        "DELETE FROM k4promo_publication_reservations WHERE owner_id = %s",
                        (self._owner_id,),
                    )
        except Exception:
            self.close()
            raise RuntimeError("Falha ao limpar reservas PostgreSQL") from None

    def close(self) -> None:
        connection, self._connection = self._connection, None
        if connection is not None:
            try:
                connection.close()
            except Exception:
                pass
