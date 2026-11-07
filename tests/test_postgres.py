"""Mesmo fluxo da etapa 1 num Postgres de verdade (o Supabase é Postgres).

Só roda com TESTE_POSTGRES_URL apontando para um banco LOCAL e descartável (o GitHub Actions sobe um).
O teste apaga as tabelas antes de começar, por isso recusa qualquer endereço que não seja da própria máquina.
"""
from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from app.config import url_do_banco
from app.db import Base, Pessoa, criar_engine, iniciar_banco
from app.main import criar_app

from .conftest import ADMIN, HOST, cfg_teste, criar_link, entrar

URL = os.environ.get("TESTE_POSTGRES_URL", "")
pytestmark = pytest.mark.skipif(not URL, reason="sem TESTE_POSTGRES_URL")


@pytest.fixture
def url_limpa():
    assert urlsplit(URL).hostname in {"localhost", "127.0.0.1"}, "TESTE_POSTGRES_URL precisa ser um banco local"
    url = url_do_banco(URL)
    engine = criar_engine(url)
    Base.metadata.drop_all(engine)
    engine.dispose()
    return url


def test_tabelas_com_rls_e_criacao_repetida(url_limpa):
    engine = criar_engine(url_limpa)
    iniciar_banco(engine)
    iniciar_banco(engine)  # ligar o servidor de novo não pode dar erro
    with engine.connect() as conn:
        rls = dict(conn.execute(text("SELECT relname, relrowsecurity FROM pg_class "
                                     "WHERE relname IN ('pessoas', 'links_cadastro', 'acessos')")).all())
    engine.dispose()
    assert rls == {"pessoas": True, "links_cadastro": True, "acessos": True}


def test_fluxo_da_etapa_1_no_postgres(url_limpa):
    app = criar_app(cfg_teste(database_url=url_limpa))
    with TestClient(app, base_url=f"https://{HOST}") as adm, TestClient(app, base_url=f"https://{HOST}") as c:
        entrar(adm, ADMIN, "Admin Teste")
        with app.state.Sessao() as s:
            lider = Pessoa(nome="Lider Inventado", email="lider@exemplo.com.br", tipo="lider", equipe="Elim",
                           nome_sga="LIDER INVENTADO", situacao="ativo")
            s.add(lider)
            s.commit()
            lider_id = lider.id
        link = criar_link(adm, "especialista", validade="2099-01-31")
        assert link["validade_txt"] == "31/01/2099"
        entrar(c, "esp@exemplo.com.br", link=link["codigo"])
        assert c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Especialista Inventado"}).status_code == 200
        p = adm.get("/api/admin/pessoas", params={"situacao": "pendente"}).json()["pessoas"][0]
        r = adm.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo", "equipe": "Elim",
                                                             "nome_sga": "ESPECIALISTA INVENTADO",
                                                             "lider_id": lider_id})
        assert r.status_code == 200, r.text
        entrar(c, "esp@exemplo.com.br")
        assert c.post("/api/acesso", json={"aba": "menu"}).status_code == 200
        rel = adm.get("/api/admin/acessos", params={"equipe": "Elim"}).json()
        assert [(x["nome"], x["entradas"], x["abas"]) for x in rel["resumo"]] == [
            ("Especialista Inventado", 1, {"menu": 1})]
        assert adm.get("/api/admin/links").json()["links"][0]["usos"] == 1
