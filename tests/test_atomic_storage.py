"""Testes da Fase 5 (seção 19): persistência segura.

Escrita atômica (arquivo permanece íntegro mesmo se a gravação falhar no
meio), concorrência de gravação (sem corrupção quando duas threads gravam o
mesmo arquivo ao mesmo tempo), compatibilidade com JSON antigo (round-trip
dos módulos de storage), diretório de dados criado automaticamente, e
detecção de falta de permissão de escrita.
"""

from __future__ import annotations

import json
import threading

import pytest

from k4promo.storage import atomic
from k4promo.storage.atomic import atomic_write_json, atomic_write_text, ensure_writable


def test_atomic_write_text_grava_conteudo_correto(tmp_path):
    path = tmp_path / "arquivo.json"
    atomic_write_text(path, '{"a": 1}')
    assert path.read_text(encoding="utf-8") == '{"a": 1}'


def test_atomic_write_json_serializa_e_le_de_volta(tmp_path):
    path = tmp_path / "estado.json"
    atomic_write_json(path, {"seen": ["a", "b"], "n": 3})
    assert json.loads(path.read_text(encoding="utf-8")) == {"seen": ["a", "b"], "n": 3}


def test_atomic_write_cria_diretorio_pai_se_faltar(tmp_path):
    path = tmp_path / "sub" / "dir" / "estado.json"
    atomic_write_json(path, {"ok": True})
    assert path.exists()
    assert json.loads(path.read_text(encoding="utf-8")) == {"ok": True}


def test_atomic_write_nao_deixa_arquivo_tmp_para_tras(tmp_path):
    path = tmp_path / "estado.json"
    atomic_write_json(path, {"ok": True})
    leftovers = [p for p in tmp_path.iterdir() if p.name != "estado.json"]
    assert leftovers == []


def test_arquivo_original_fica_intacto_se_a_gravacao_falhar(tmp_path, monkeypatch):
    path = tmp_path / "estado.json"
    atomic_write_json(path, {"versao": "antiga"})

    def _fsync_quebrado(fd):
        raise OSError("disco cheio (simulado)")

    monkeypatch.setattr(atomic.os, "fsync", _fsync_quebrado)
    with pytest.raises(OSError):
        atomic_write_json(path, {"versao": "nova"})

    # O arquivo original nunca foi tocado — só o tmp teria sido descartado.
    assert json.loads(path.read_text(encoding="utf-8")) == {"versao": "antiga"}
    leftovers = [p for p in tmp_path.iterdir() if p.name != "estado.json"]
    assert leftovers == []


def test_escritas_concorrentes_no_mesmo_arquivo_nunca_corrompem(tmp_path):
    path = tmp_path / "concorrente.json"
    atomic_write_json(path, {})
    erros = []

    def escrever(n):
        try:
            # payload "grande" pra aumentar a chance de round-robin do SO
            # intercalar bytes se a escrita não fosse atômica.
            atomic_write_json(path, {"writer": n, "padding": "x" * 5000})
        except Exception as exc:  # pragma: no cover - só se algo realmente falhar
            erros.append(exc)

    threads = [threading.Thread(target=escrever, args=(n,)) for n in range(12)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert erros == []
    # O arquivo final é SEMPRE um JSON válido e completo de algum writer —
    # nunca uma mistura truncada de duas escritas.
    data = json.loads(path.read_text(encoding="utf-8"))
    assert set(data.keys()) == {"writer", "padding"}
    assert len(data["padding"]) == 5000


def test_ensure_writable_cria_diretorio_que_nao_existe(tmp_path):
    alvo = tmp_path / "novo" / "diretorio"
    ensure_writable(alvo)
    assert alvo.is_dir()


def test_ensure_writable_levanta_oserror_com_mensagem_clara(tmp_path):
    # Um arquivo comum no lugar onde um diretório era esperado: mkdir falha
    # de forma determinística, independente de usuário/permissões do SO.
    caminho_invalido = tmp_path / "isso_e_um_arquivo"
    caminho_invalido.write_text("x", encoding="utf-8")

    with pytest.raises(OSError, match="[Ss]em permissao|[Nn]ot a directory|already exists"):
        ensure_writable(caminho_invalido)
