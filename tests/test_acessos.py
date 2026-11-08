"""Acessos: quem entrou, quando, quantas vezes e quais abas abriu."""
from datetime import datetime, timezone

from sqlalchemy import select

from app.db import Acesso
from app.servicos import ip_resumido
from app.tempo import formatar

from .conftest import ADMIN, criar_pessoa, entrar


def test_ip_resumido():
    assert ip_resumido("201.17.33.140") == "201.17.33.x"
    assert ip_resumido("2804:14c:5b81:9a00::1") == "2804:14c:5b81::x"
    assert ip_resumido("nao-e-ip") is None
    assert ip_resumido(None) is None


def test_horario_de_brasilia():
    assert formatar(datetime(2026, 11, 7, 13, 42, tzinfo=timezone.utc)) == "07/11/2026 10:42"
    assert formatar(datetime(2026, 11, 7, 13, 42)) == "07/11/2026 10:42"  # SQLite devolve sem fuso (UTC)


def test_login_e_abas_sao_registrados(admin, novo_cliente, db):
    criar_pessoa(db, nome="Cadastro Inventado", email="c@exemplo.com.br", tipo="cadastro", equipe="Lua")
    c = novo_cliente()
    entrar(c, "c@exemplo.com.br")
    entrar(c, "c@exemplo.com.br")
    for aba in ("menu", "menu", "admin_links"):
        assert c.post("/api/acesso", json={"aba": aba}).status_code == 200
    assert c.post("/api/acesso", json={"aba": "entrada"}).status_code == 400  # entrada só pelo login
    assert c.post("/api/acesso", json={"aba": "<script>"}).status_code == 400

    rel = admin.get("/api/admin/acessos").json()
    linha = next(r for r in rel["resumo"] if r["nome"] == "Cadastro Inventado")
    assert linha["entradas"] == 2 and linha["equipe"] == "Lua"
    assert linha["abas"] == {"menu": 2, "admin_links": 1}
    assert linha["ultimo_txt"] and linha["primeiro_txt"]
    eventos = [e for e in rel["eventos"] if e["nome"] == "Cadastro Inventado"]
    assert [e["aba"] for e in eventos] == ["admin_links", "menu", "menu", "entrada", "entrada"]
    assert all(e["ip"] in (None, "testclient") or e["ip"].endswith(".x") for e in eventos)


def test_filtros_por_pessoa_equipe_e_periodo(admin, db):
    a = criar_pessoa(db, nome="Pessoa Lua", email="lua@exemplo.com.br", tipo="cadastro", equipe="Lua")
    b = criar_pessoa(db, nome="Pessoa Elim", email="elim@exemplo.com.br", tipo="cadastro", equipe="Elim")
    # 07/03 02:30 em UTC = 06/03 23:30 em Brasília (datas no passado para não misturar com o login de hoje)
    db.add(Acesso(pessoa_id=a.id, aba="entrada", data_hora=datetime(2026, 3, 7, 2, 30, tzinfo=timezone.utc)))
    db.add(Acesso(pessoa_id=b.id, aba="entrada", data_hora=datetime(2026, 3, 7, 15, 0, tzinfo=timezone.utc)))
    db.commit()
    nomes = lambda **q: sorted(r["nome"] for r in admin.get("/api/admin/acessos", params=q).json()["resumo"])  # noqa: E731
    assert nomes(de="2026-03-06", ate="2026-03-06") == ["Pessoa Lua"]
    assert nomes(de="2026-03-07", ate="2026-03-07") == ["Pessoa Elim"]
    assert nomes(equipe="Elim") == ["Pessoa Elim"]
    assert nomes(pessoa_id=a.id) == ["Pessoa Lua"]
    assert admin.get("/api/admin/acessos", params={"de": "06/11/2026"}).status_code == 400
    ev = admin.get("/api/admin/acessos", params={"pessoa_id": a.id}).json()["eventos"]
    assert ev[0]["data_hora_txt"] == "06/03/2026 23:30"


def test_admin_tambem_e_registrado(admin, db):
    abas = [a.aba for a in db.scalars(select(Acesso))]
    assert abas == ["entrada"]
    assert admin.get("/api/admin/acessos").json()["resumo"][0]["nome"] == "Admin Teste"
    assert ADMIN
