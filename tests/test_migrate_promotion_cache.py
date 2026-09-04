import json

import migrate_promotion_cache as migrate


def test_drops_untrustworthy_code_and_upgrades_schema():
    cache = {
        "ml:123": {
            "schema_version": None,
            "checked_at": "2026-08-01T10:00:00+00:00",
            "promotions": [
                {"source": "mercadolivre", "code": "COMO", "discount_amount": 10},
            ],
        }
    }
    new_cache, stats = migrate.migrate(cache)
    assert new_cache["ml:123"]["promotions"] == []
    assert new_cache["ml:123"]["schema_version"] == 2
    assert stats["promotions_dropped_untrustworthy"] == 1
    assert stats["promotions_kept"] == 0
    assert stats["entries_upgraded"] == 1


def test_keeps_trustworthy_code_and_preserves_checked_at():
    checked_at = "2026-08-01T10:00:00+00:00"
    cache = {
        "ml:456": {
            "schema_version": 1,
            "checked_at": checked_at,
            "promotions": [
                {"source": "mercadolivre", "code": "VANTAGEMJA", "discount_percent": 10},
            ],
        }
    }
    new_cache, stats = migrate.migrate(cache)
    assert len(new_cache["ml:456"]["promotions"]) == 1
    assert new_cache["ml:456"]["promotions"][0]["code"] == "VANTAGEMJA"
    assert new_cache["ml:456"]["checked_at"] == checked_at
    assert stats["promotions_kept"] == 1


def test_already_v2_entry_with_no_changes_is_not_counted_as_upgraded():
    cache = {
        "ml:789": {
            "schema_version": 2,
            "checked_at": "2026-08-01T10:00:00+00:00",
            "promotions": [],
        }
    }
    new_cache, stats = migrate.migrate(cache)
    assert stats["entries_upgraded"] == 0
    assert new_cache["ml:789"]["schema_version"] == 2


def test_entry_with_unparseable_checked_at_is_dropped():
    cache = {
        "ml:bad": {"schema_version": 2, "checked_at": "not-a-date", "promotions": []}
    }
    new_cache, stats = migrate.migrate(cache)
    assert "ml:bad" not in new_cache
    assert stats["entries_dropped_bad_checked_at"] == 1


def test_non_dict_entry_is_dropped_safely():
    cache = {"ml:weird": "not-a-dict"}
    new_cache, stats = migrate.migrate(cache)
    assert new_cache == {}
    assert stats["entries_dropped_bad_checked_at"] == 1


def test_cli_dry_run_does_not_write_file(tmp_path):
    path = tmp_path / "promotion_cache.json"
    path.write_text(json.dumps({
        "k": {
            "schema_version": None,
            "checked_at": "2026-08-01T10:00:00+00:00",
            "promotions": [{"source": "x", "code": "COMO"}],
        }
    }), encoding="utf-8")
    original = path.read_text(encoding="utf-8")

    # Chama via argv real para cobrir o parser de CLI tambem.
    import sys
    old_argv = sys.argv
    sys.argv = ["migrate_promotion_cache.py", "--dry-run", "--path", str(path)]
    try:
        rc = migrate.main()
    finally:
        sys.argv = old_argv

    assert rc == 0
    assert path.read_text(encoding="utf-8") == original
    assert not (tmp_path / "promotion_cache.json.bak").exists()


def test_cli_writes_backup_and_migrated_file(tmp_path):
    path = tmp_path / "promotion_cache.json"
    path.write_text(json.dumps({
        "k": {
            "schema_version": None,
            "checked_at": "2026-08-01T10:00:00+00:00",
            "promotions": [{"source": "x", "code": "VANTAGEMJA", "discount_percent": 5}],
        }
    }), encoding="utf-8")

    import sys
    old_argv = sys.argv
    sys.argv = ["migrate_promotion_cache.py", "--path", str(path)]
    try:
        rc = migrate.main()
    finally:
        sys.argv = old_argv

    assert rc == 0
    assert (tmp_path / "promotion_cache.json.bak").exists()
    migrated = json.loads(path.read_text(encoding="utf-8"))
    assert migrated["k"]["schema_version"] == 2
    assert migrated["k"]["promotions"][0]["code"] == "VANTAGEMJA"
