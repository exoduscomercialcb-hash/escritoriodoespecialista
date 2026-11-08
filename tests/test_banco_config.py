"""Endereço e senha do banco (erro de 07/11: senha escrita à mão no meio do endereço quebrava a conexão).

As senhas daqui são inventadas.
"""
import logging

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError

import app.main as principal
from app.config import ConfigInvalida, carregar, montar_url_do_banco
from app.db import descrever_banco, motivo_da_falha

from .conftest import HOST, cfg_teste

COPIADO = "postgresql://postgres.projetoinventado:[YOUR-PASSWORD]@aws-0-us-east-1.pooler.supabase.com:5432/postgres"


def test_senha_separada_entra_no_lugar_do_your_password():
    url = montar_url_do_banco(COPIADO, "SenhaInventada2026")
    u = make_url(url)
    assert (u.username, u.password, u.host, u.port, u.database) == (
        "postgres.projetoinventado", "SenhaInventada2026", "aws-0-us-east-1.pooler.supabase.com", 5432, "postgres")


def test_senha_com_simbolos_nao_quebra_o_endereco():
    for senha in ("abc@2026", "a#b/c:d?e%f", "tem espaço"):
        u = make_url(montar_url_do_banco(COPIADO, senha))
        assert u.password == senha and u.host == "aws-0-us-east-1.pooler.supabase.com"


def test_senha_separada_vale_mais_que_a_escrita_no_endereco():
    escrito = COPIADO.replace("[YOUR-PASSWORD]", "SenhaVelha")
    assert make_url(montar_url_do_banco(escrito, "SenhaNova")).password == "SenhaNova"
    assert make_url(montar_url_do_banco(escrito, "")).password == "SenhaVelha"  # sem DATABASE_PASSWORD


def test_enter_no_fim_da_senha_e_ignorado():
    assert make_url(montar_url_do_banco(COPIADO, "SenhaInventada\n")).password == "SenhaInventada"


@pytest.mark.parametrize("url,senha,trecho", [
    (COPIADO.replace("[YOUR-PASSWORD]", "abc\n]"), "", "quebra de linha"),
    (COPIADO, "", "DATABASE_PASSWORD"),
    ("aws-0-us-east-1.pooler.supabase.com", "Senha", "formato do Supabase"),
])
def test_endereco_errado_explica_em_portugues(url, senha, trecho):
    with pytest.raises(ConfigInvalida, match=trecho) as e:
        montar_url_do_banco(url, senha)
    assert "abc" not in str(e.value)


def test_carregar_usa_database_password():
    cfg = carregar({"DATABASE_URL": COPIADO, "DATABASE_PASSWORD": "SenhaInventada2026"})
    assert cfg.database_url.startswith("postgresql+psycopg://postgres.projetoinventado:SenhaInventada2026@")


def test_descricao_do_banco_nunca_mostra_a_senha():
    texto = descrever_banco(montar_url_do_banco(COPIADO, "SenhaInventada2026"))
    assert "SenhaInventada2026" not in texto
    assert texto == ("usuário postgres.projetoinventado, servidor aws-0-us-east-1.pooler.supabase.com, porta 5432, "
                     "senha recebida com 18 caracteres")


@pytest.mark.parametrize("original,esperado", [
    ('FATAL:  password authentication failed for user "postgres"', "recusou a senha"),
    ("FATAL:  Tenant or user not found", "não achou o projeto"),
    ("failed to resolve host 'x': Name or service not known", "não foi encontrado"),
    ("connection timeout expired", "não respondeu"),
    ("outra coisa", "erro de conexão"),
])
def test_motivo_da_falha(original, esperado):
    assert esperado in motivo_da_falha(Exception(original))


def test_falha_no_banco_ao_ligar_da_mensagem_clara_sem_senha(monkeypatch, caplog):
    def falha(_engine):
        raise OperationalError("SELECT 1", {}, Exception(
            'connection failed: FATAL:  password authentication failed for user "postgres" SenhaInventada2026'))
    monkeypatch.setattr(principal, "iniciar_banco", falha)
    cfg = cfg_teste(database_url=montar_url_do_banco(COPIADO, "SenhaInventada2026").replace(
        "postgresql://", "postgresql+psycopg://"))
    app = principal.criar_app(cfg)
    with caplog.at_level(logging.ERROR, logger="escritorio"):
        with pytest.raises(RuntimeError, match="Banco de dados indisponível"):
            with TestClient(app, base_url=f"https://{HOST}"):
                pass
    assert "o Supabase recusou a senha" in caplog.text
    assert "servidor aws-0-us-east-1.pooler.supabase.com" in caplog.text
    assert "SenhaInventada2026" not in caplog.text


def test_migracao_acrescenta_colunas_na_tabela_antiga(tmp_path):
    """O banco do Supabase já tinha a tabela pessoas sem CPF e WhatsApp (etapa 1 de 07/11)."""
    from sqlalchemy import inspect, text

    from app.db import criar_engine, iniciar_banco
    engine = criar_engine(f"sqlite:///{tmp_path / 'antigo.db'}")
    with engine.begin() as conn:
        conn.execute(text("CREATE TABLE pessoas (id INTEGER PRIMARY KEY, nome VARCHAR(120), email VARCHAR(254), "
                          "google_sub VARCHAR(64), tipo VARCHAR(30), equipe VARCHAR(40), nome_sga VARCHAR(160), "
                          "lider_id INTEGER, situacao VARCHAR(12), link_id INTEGER, criado_em DATETIME, "
                          "aprovado_em DATETIME, aprovado_por VARCHAR(254))"))
        conn.execute(text("INSERT INTO pessoas (nome, tipo, situacao) VALUES ('Pessoa Antiga Inventada', 'admin', 'ativo')"))
    iniciar_banco(engine)
    iniciar_banco(engine)  # de novo, sem erro
    colunas = {c["name"] for c in inspect(engine).get_columns("pessoas")}
    assert {"cpf", "whatsapp", "vinculado_em"} <= colunas
    assert any(i["name"] == "ix_pessoas_cpf" and i["unique"] for i in inspect(engine).get_indexes("pessoas"))
    with engine.connect() as conn:
        assert conn.execute(text("SELECT nome FROM pessoas")).scalar() == "Pessoa Antiga Inventada"
    engine.dispose()
