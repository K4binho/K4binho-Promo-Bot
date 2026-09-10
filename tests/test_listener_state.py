"""Testes da persistência do offset (last_update_id) do listener."""

from __future__ import annotations

from k4promo.storage import listener_state


def test_load_sem_arquivo_devolve_zero(tmp_path, monkeypatch):
    monkeypatch.setattr(listener_state, "OFFSET_PATH", tmp_path / "listener_offset.json")
    assert listener_state.load_last_update_id() == 0


def test_save_e_load_round_trip(tmp_path, monkeypatch):
    path = tmp_path / "listener_offset.json"
    monkeypatch.setattr(listener_state, "OFFSET_PATH", path)
    listener_state.save_last_update_id(42)
    assert listener_state.load_last_update_id() == 42


def test_load_com_json_invalido_devolve_zero(tmp_path, monkeypatch):
    path = tmp_path / "listener_offset.json"
    path.write_text("{ nao é json", encoding="utf-8")
    monkeypatch.setattr(listener_state, "OFFSET_PATH", path)
    assert listener_state.load_last_update_id() == 0
