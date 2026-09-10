from __future__ import annotations

from datetime import UTC, datetime

from k4promo.storage.postgres_state import PostgresState


class _Transaction:
    def __init__(self, connection):
        self.connection = connection

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class _Cursor:
    def __init__(self, connection):
        self.connection = connection
        self.rows = []
        self.rowcount = 0

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def execute(self, statement, params=()):
        sql = " ".join(statement.split()).lower()
        self.rows = []
        self.rowcount = 0
        if sql.startswith("create "):
            return
        if "select 1 from k4promo_state_migrations" in sql:
            self.rows = [(1,)] if params[0] in self.connection.migrations else []
            return
        if sql.startswith("insert into k4promo_state_migrations"):
            self.connection.migrations.add(params[0])
            self.rowcount = 1
            return
        if sql.startswith("select item_key, seen_at"):
            self.rows = list(self.connection.seen.items())
            return
        if sql.startswith("select item_key, price, best_price"):
            self.rows = list(self.connection.deals.values())
            return
        if sql.startswith("delete from k4promo_seen"):
            self.connection.seen.clear()
            self.rowcount = 1
            return
        if sql.startswith("delete from k4promo_published_deals"):
            self.connection.deals.clear()
            self.rowcount = 1
            return
        if sql.startswith("delete from k4promo_publication_reservations"):
            if "owner_id = %s" in sql and len(params) == 1:
                owner = params[0]
                keys = [key for key, row in self.connection.reservations.items()
                        if row[3] == owner]
            else:
                key = (params[0], params[1])
                keys = [key] if key in self.connection.reservations else []
                if keys and self.connection.reservations[key][3] != params[2]:
                    keys = []
            for key in keys:
                del self.connection.reservations[key]
            self.rowcount = len(keys)
            return
        if sql.startswith("insert into k4promo_publication_reservations"):
            key = (params[0], params[1])
            if key not in self.connection.reservations:
                self.connection.reservations[key] = params
                self.rowcount = 1
            return
        raise AssertionError(f"Unhandled SQL: {statement}")

    def executemany(self, statement, rows):
        sql = " ".join(statement.split()).lower()
        rows = list(rows)
        self.rowcount = len(rows)
        if "into k4promo_seen" in sql:
            for item_key, timestamp in rows:
                self.connection.seen[item_key] = timestamp
            return
        if "into k4promo_published_deals" in sql:
            for row in rows:
                self.connection.deals[row[0]] = row
            return
        raise AssertionError(f"Unhandled SQL: {statement}")

    def fetchone(self):
        return self.rows[0] if self.rows else None

    def fetchall(self):
        return self.rows


class _Connection:
    def __init__(self):
        self.seen = {}
        self.deals = {}
        self.migrations = set()
        self.reservations = {}
        self.closed = False

    def transaction(self):
        return _Transaction(self)

    def cursor(self):
        return _Cursor(self)

    def close(self):
        self.closed = True


def _state(connection):
    return PostgresState("postgresql://private", connect=lambda _dsn: connection)


def test_load_state_imports_json_once_and_preserves_metadata():
    connection = _Connection()
    state = _state(connection)
    timestamp = datetime(2026, 1, 1, tzinfo=UTC).isoformat()
    seen = {"shopee:1": timestamp}
    deals = {
        "shopee:1": {
            "price": 99.9,
            "best_price": 89.9,
            "posted_at": timestamp,
            "first_posted_at": timestamp,
            "promotion_signature": "CUPOM10",
            "normalized_title": "air fryer",
            "normalized_url": "loja/1",
            "message_id": 123,
            "thread_id": 2198,
            "republish_count": 2,
            "last_reason": "queda_de_preco",
        }
    }

    loaded_seen, loaded_deals = state.load_state(seen, deals)
    assert loaded_seen["shopee:1"] == timestamp
    assert loaded_deals["shopee:1"]["message_id"] == 123
    assert loaded_deals["shopee:1"]["last_reason"] == "queda_de_preco"

    loaded_seen, loaded_deals = state.load_state({"new": timestamp}, {})
    assert "new" not in loaded_seen
    assert loaded_deals["shopee:1"]["normalized_title"] == "air fryer"


def test_persist_replaces_core_state_in_one_backend():
    connection = _Connection()
    state = _state(connection)
    state.load_state({}, {})
    state.persist(
        {"kabum:2": "2026-02-01T00:00:00+00:00"},
        {"kabum:2": {"price": 50.0}},
    )
    seen, deals = state.load_state({}, {})
    assert seen == {"kabum:2": "2026-02-01T00:00:00+00:00"}
    assert deals["kabum:2"]["price"] == 50.0


def test_reservation_is_atomic_and_releasable():
    connection = _Connection()
    state = _state(connection)
    state.load_state({}, {})
    identity = ("shopee", "air fryer")
    assert state.reserve_publication(identity, "shopee:1") is True
    assert state.reserve_publication(identity, "shopee:2") is False
    state.release_publication(identity)
    assert state.reserve_publication(identity, "shopee:2") is True
    state.clear_reservations()
    assert connection.reservations == {}
