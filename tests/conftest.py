"""Base dos testes: servidor com banco SQLite em memória e login de teste (sem Google).

Todos os nomes e e-mails daqui são inventados. Nunca usar dados de associados nem de pessoas reais.
"""
from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.config import Config
from app.db import Pessoa
from app.main import criar_app

HOST = "escritorio.exodusbeneficios.com.br"
HOST_RENDER = "escritorio-teste.onrender.com"
ADMIN = "admin.teste@exemplo.com.br"


def cfg_teste(**mudancas) -> Config:
    base = dict(database_url="sqlite://", session_secret="s" * 48, admin_emails=frozenset({ADMIN}),
                hosts_escritorio=frozenset({HOST, HOST_RENDER, "localhost", "127.0.0.1"}), modo_teste=True,
                cookie_seguro=False)
    base.update(mudancas)
    return Config(**base)


@pytest.fixture
def app():
    return criar_app(cfg_teste())


@pytest.fixture
def novo_cliente(app):
    """Cada cliente é um navegador separado (com a sua própria sessão), todos no mesmo banco."""
    abertos = []

    def fabrica(host: str = HOST) -> TestClient:
        c = TestClient(app, base_url=f"https://{host}")
        c.__enter__()
        abertos.append(c)
        return c

    yield fabrica
    for c in abertos:
        c.__exit__(None, None, None)


@pytest.fixture
def cliente(novo_cliente):
    return novo_cliente()


@pytest.fixture
def db(app, cliente):  # "cliente" garante que o servidor ligou e criou as tabelas
    s = app.state.Sessao()
    yield s
    s.close()


def entrar(c: TestClient, email: str, nome: str = "Pessoa Teste", link: str | None = None):
    params = {"email": email, "nome": nome}
    if link:
        params["link"] = link
    return c.get("/teste/entrar", params=params, follow_redirects=False)


@pytest.fixture
def admin(novo_cliente):
    c = novo_cliente()
    assert entrar(c, ADMIN, "Admin Teste").headers["location"] == "/"
    return c


def criar_pessoa(db, **campos) -> Pessoa:
    dados = dict(nome="Pessoa Inventada", tipo="especialista", situacao="ativo")
    dados.update(campos)
    p = Pessoa(**dados)
    db.add(p)
    db.commit()
    return p


def cpf_inventado(n: int) -> str:
    """CPF com dígitos verificadores certos, mas inventado (nunca usar CPF de pessoa real nos testes)."""
    digitos = [int(d) for d in str(100000000 + n)]
    for tamanho in (9, 10):
        soma = sum(d * (tamanho + 1 - i) for i, d in enumerate(digitos))
        digitos.append((soma * 10 % 11) % 10)
    return "".join(map(str, digitos))


def pre_cadastro(admin_cliente: TestClient, **campos) -> dict:
    corpo = {"nome": "Especialista Inventado", "tipo": "especialista", "cpf": cpf_inventado(1)}
    corpo.update(campos)
    r = admin_cliente.post("/api/admin/pessoas", json=corpo)
    assert r.status_code == 200, r.text
    return r.json()["pessoa"]


def primeiro_acesso(c: TestClient, cpf: str, email: str, whatsapp: str = "(21) 98765-4321"):
    """Como a pessoa faz: no endereço do escritório, informa CPF e WhatsApp e entra com o Google (aqui, login de teste)."""
    r = c.post("/api/primeiro-acesso", json={"cpf": cpf, "whatsapp": whatsapp})
    assert r.status_code == 200 and r.json()["proximo"] == "/auth/login", r.text
    return entrar(c, email)


__all__ = ["ADMIN", "HOST", "HOST_RENDER", "Pessoa", "cfg_teste", "cpf_inventado", "criar_pessoa", "entrar",
           "pre_cadastro", "primeiro_acesso"]
