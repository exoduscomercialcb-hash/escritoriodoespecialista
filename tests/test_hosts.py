"""Escolha da página pelo endereço de entrada (host)."""
import pytest
from fastapi.testclient import TestClient

from app.config import ConfigInvalida, carregar
from app.hosts import ESCRITORIO, NEUTRA, nome_do_host, pagina_do_host
from app.main import criar_app

from .conftest import ADMIN, HOST, HOST_RENDER, cfg_teste, entrar


@pytest.mark.parametrize("host,esperado", [
    ("escritorio.exodusbeneficios.com.br", "escritorio.exodusbeneficios.com.br"),
    ("Escritorio.ExodusBeneficios.com.br:443", "escritorio.exodusbeneficios.com.br"),
    ("escritorio.exodusbeneficios.com.br.", "escritorio.exodusbeneficios.com.br"),
    ("[::1]:8000", "[::1]"),
    ("", ""),
    (None, ""),
])
def test_nome_do_host(host, esperado):
    assert nome_do_host(host) == esperado


@pytest.mark.parametrize("host,pagina", [
    (HOST, ESCRITORIO),
    (HOST.upper() + ":443", ESCRITORIO),
    (HOST_RENDER, ESCRITORIO),
    ("exodusbeneficios.com.br", NEUTRA),
    ("outro.exodusbeneficios.com.br", NEUTRA),
    ("escritorio.exodusbeneficios.com.br.golpe.com", NEUTRA),
    ("qualquer-coisa.onrender.com", NEUTRA),
    ("", NEUTRA),
    (None, NEUTRA),
])
def test_pagina_do_host(host, pagina):
    assert pagina_do_host(host, cfg_teste()) == pagina


def test_escritorio_no_dominio_e_no_onrender(novo_cliente):
    for host in (HOST, HOST_RENDER):
        r = novo_cliente(host).get("/")
        assert r.status_code == 200
        assert "Escritório do Especialista" in r.text and "/static/escritorio.js" in r.text


def test_endereco_desconhecido_mostra_pagina_neutra(novo_cliente):
    c = novo_cliente("site-desconhecido.com.br")
    r = c.get("/")
    assert r.status_code == 200
    assert "Endereço não encontrado" in r.text
    assert "Escritório" not in r.text and "Exodus" not in r.text and "Google" not in r.text
    # nada do sistema responde nesse endereço: nem a API, nem o login, nem os arquivos
    for caminho in ("/api/eu", "/auth/login", "/static/escritorio.js", f"/teste/entrar?email={ADMIN}", "/cadastro/abc"):
        r = c.get(caminho, follow_redirects=False)
        assert r.status_code == 404, caminho
        assert "Endereço não encontrado" in r.text
    assert "escritorio_sessao" not in c.cookies


def test_sessao_de_um_endereco_nao_vale_no_desconhecido(novo_cliente):
    c = novo_cliente()
    entrar(c, ADMIN)
    assert c.get("/api/admin/pessoas").status_code == 200
    r = c.get("https://site-desconhecido.com.br/api/admin/pessoas")
    assert r.status_code == 404


def test_saude_responde_em_qualquer_endereco(novo_cliente):
    assert novo_cliente("10.0.0.5").get("/saude").json() == {"ok": True}


def test_config_render_inclui_endereco_onrender_e_tira_localhost():
    env = {"RENDER": "true", "RENDER_EXTERNAL_HOSTNAME": "escritorio-xyz.onrender.com",
           "DATABASE_URL": "postgresql://u:p@banco.exemplo:5432/postgres", "SESSION_SECRET": "x" * 40,
           "GOOGLE_OAUTH_CLIENT_ID": "id", "GOOGLE_OAUTH_CLIENT_SECRET": "segredo", "ADMIN_EMAILS": ADMIN,
           "MODO_TESTE": "1"}
    cfg = carregar(env)
    assert cfg.hosts_escritorio == {HOST, "escritorio-xyz.onrender.com"}
    assert cfg.modo_teste is False  # no Render a rota de teste nunca liga
    assert cfg.cookie_seguro is True
    assert cfg.database_url.startswith("postgresql+psycopg://")
    assert cfg.busca_automatica is True  # no Render a busca diária liga sozinha
    assert carregar({**env, "BUSCA_AUTOMATICA": "0"}).busca_automatica is False  # e desliga pela variável
    assert carregar({}).busca_automatica is False  # no computador, nunca


def test_config_render_recusa_variavel_faltando():
    with pytest.raises(ConfigInvalida, match="DATABASE_URL"):
        carregar({"RENDER": "true", "SESSION_SECRET": "x" * 40})
    with pytest.raises(ConfigInvalida, match="32 caracteres"):
        carregar({"RENDER": "true", "DATABASE_URL": "postgresql://a", "SESSION_SECRET": "curto",
                  "GOOGLE_OAUTH_CLIENT_ID": "a", "GOOGLE_OAUTH_CLIENT_SECRET": "b", "ADMIN_EMAILS": ADMIN})


def test_hosts_extras_pela_variavel():
    cfg = carregar({"HOSTS_ESCRITORIO": "Escritorio.ExodusBeneficios.com.br, homologa.exodusbeneficios.com.br"})
    assert pagina_do_host("homologa.exodusbeneficios.com.br", cfg) == ESCRITORIO


def test_cabecalhos_de_seguranca(cliente):
    r = cliente.get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]
    assert r.headers["x-content-type-options"] == "nosniff"


def test_neutra_tambem_tem_cabecalhos(novo_cliente):
    r = novo_cliente("site-desconhecido.com.br").get("/")
    assert "frame-ancestors 'none'" in r.headers["content-security-policy"]


def test_app_sobe_com_config_padrao_do_computador(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    app = criar_app(carregar({}))
    with TestClient(app, base_url="http://localhost") as c:
        assert c.get("/api/eu").json()["estado"] == "anonimo"
        assert c.get("/teste/entrar", params={"email": ADMIN}).status_code == 404  # sem MODO_TESTE
