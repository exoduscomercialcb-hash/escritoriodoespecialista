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
from app.db import Base, criar_engine, iniciar_banco
from app.main import criar_app

from .conftest import ADMIN, HOST, cfg_teste, cpf_inventado, entrar, primeiro_acesso

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
        planilha = ("Nome\tTipo de conta\tCPF\tEquipe\tNome no SGA\tLíder\n"
                    f"Lider Inventado\tLíder\t{cpf_inventado(1)}\tElim\tLIDER INVENTADO\t\n"
                    f"Especialista Inventado\tEspecialista\t{cpf_inventado(2)}\tElim\tESPECIALISTA INVENTADO\tLider Inventado\n")
        r = adm.post("/api/admin/importar", json={"texto": planilha}).json()
        assert (r["importado"], r["criados"]) == (True, 2), r
        primeiro_acesso(c, cpf_inventado(2), "esp@exemplo.com.br")
        assert c.get("/api/eu").json()["pessoa"]["lider_nome"] == "Lider Inventado"
        assert c.post("/api/acesso", json={"aba": "menu"}).status_code == 200
        rel = adm.get("/api/admin/acessos", params={"equipe": "Elim"}).json()
        assert [(x["nome"], x["entradas"], x["abas"]) for x in rel["resumo"]] == [
            ("Especialista Inventado", 1, {"menu": 1})]
        assert adm.get("/api/admin/pessoas", params={"situacao": "aguardando"}).json()["pessoas"][0]["nome"] == \
            "Lider Inventado"
