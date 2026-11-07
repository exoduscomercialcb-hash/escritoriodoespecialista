"""Login com Google obrigatório, ADMIN_EMAILS, bloqueio e rota de teste."""
from urllib.parse import parse_qs, urlsplit

from authlib.integrations.starlette_client import OAuthError
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Acesso, Pessoa
from app.main import criar_app
from app.servicos import MSG_NAO_LIBERADO

from .conftest import ADMIN, HOST, cfg_teste, criar_pessoa, entrar


def test_sem_login_nada_abre(cliente):
    assert cliente.get("/api/eu").json()["estado"] == "anonimo"
    for caminho in ("/api/admin/pessoas", "/api/admin/links", "/api/admin/acessos", "/api/meus-dados/situacao"):
        r = cliente.get(caminho)
        assert r.status_code == 401, caminho
        assert r.json()["erro"] == "Entre com o Google para continuar."
    assert cliente.post("/api/acesso", json={"aba": "menu"}).status_code == 401


def test_login_sem_google_configurado_avisa(cliente):
    r = cliente.get("/auth/login")
    assert r.status_code == 503 and "ainda não foi configurado" in r.text


def _app_com_google():
    return criar_app(cfg_teste(google_client_id="id-inventado.apps.googleusercontent.com",
                               google_client_secret="segredo-inventado"))


def test_login_manda_para_o_google_com_retorno_certo():
    with TestClient(_app_com_google(), base_url=f"https://{HOST}") as c:
        r = c.get("/auth/login", follow_redirects=False)
        assert r.status_code == 302
        destino = urlsplit(r.headers["location"])
        assert destino.netloc == "accounts.google.com"
        q = parse_qs(destino.query)
        assert q["redirect_uri"] == [f"https://{HOST}/auth/callback"]
        assert q["client_id"] == ["id-inventado.apps.googleusercontent.com"]
        assert set(q["scope"][0].split()) == {"openid", "email", "profile"}
        assert q["state"]


def _callback(app, c, monkeypatch, info=None, erro=False):
    async def falso(_request):
        if erro:
            raise OAuthError(error="access_denied")
        return {"userinfo": info}
    monkeypatch.setattr(app.state.oauth.google, "authorize_access_token", falso)
    return c.get("/auth/callback", follow_redirects=False)


def test_callback_do_google_entra_e_registra_acesso(monkeypatch):
    app = _app_com_google()
    with TestClient(app, base_url=f"https://{HOST}") as c:
        r = _callback(app, c, monkeypatch, {"email": ADMIN.upper(), "email_verified": True, "sub": "123",
                                             "name": "Admin Teste"})
        assert r.headers["location"] == "/"
        eu = c.get("/api/eu").json()
        assert eu["estado"] == "ativo" and eu["painel"] is True and eu["pessoa"]["tipo"] == "admin"
        with app.state.Sessao() as s:
            p = s.scalars(select(Pessoa)).one()
            assert p.email == ADMIN and p.google_sub == "123"
            assert [a.aba for a in s.scalars(select(Acesso))] == ["entrada"]


def test_callback_recusa_email_nao_confirmado(monkeypatch):
    app = _app_com_google()
    with TestClient(app, base_url=f"https://{HOST}") as c:
        r = _callback(app, c, monkeypatch, {"email": ADMIN, "email_verified": False, "sub": "1"})
        assert r.headers["location"] == "/?erro=email"
        assert c.get("/api/eu").json()["estado"] == "anonimo"


def test_callback_com_erro_do_google(monkeypatch):
    app = _app_com_google()
    with TestClient(app, base_url=f"https://{HOST}") as c:
        assert _callback(app, c, monkeypatch, erro=True).headers["location"] == "/?erro=google"


def test_admin_emails_vira_admin_ativo_no_primeiro_login(cliente, db):
    entrar(cliente, ADMIN, "Admin Teste")
    p = db.scalars(select(Pessoa).where(Pessoa.email == ADMIN)).one()
    assert (p.tipo, p.situacao, p.aprovado_por) == ("admin", "ativo", "ADMIN_EMAILS")


def test_quem_nao_tem_cadastro_ve_aviso(cliente, db):
    assert entrar(cliente, "desconhecido@exemplo.com.br").headers["location"] == "/"
    eu = cliente.get("/api/eu").json()
    assert eu == {"estado": "sem_cadastro", "email": "desconhecido@exemplo.com.br", "nome": "Pessoa Teste",
                  "link": None, "mensagem": MSG_NAO_LIBERADO}
    assert MSG_NAO_LIBERADO == "Seu acesso ainda não foi liberado. Fale com a coordenação."
    assert db.scalars(select(Pessoa)).all() == []  # sem link, ninguém é criado
    assert cliente.get("/api/admin/pessoas").status_code == 401


def test_pendente_e_bloqueado_nao_entram(cliente, db):
    criar_pessoa(db, nome="Pendente Teste", email="pendente@exemplo.com.br", situacao="pendente")
    criar_pessoa(db, nome="Bloqueado Teste", email="bloqueado@exemplo.com.br", situacao="bloqueado")
    for email, estado in (("pendente@exemplo.com.br", "pendente"), ("bloqueado@exemplo.com.br", "bloqueado")):
        entrar(cliente, email)
        eu = cliente.get("/api/eu").json()
        assert eu["estado"] == estado and eu["mensagem"] == MSG_NAO_LIBERADO
        assert cliente.get("/api/meus-dados/situacao").status_code == 401


def test_bloqueio_vale_na_hora(admin, novo_cliente, db):
    p = criar_pessoa(db, nome="Especialista Teste", email="esp@exemplo.com.br", tipo="cadastro")
    c = novo_cliente()
    entrar(c, "esp@exemplo.com.br")
    assert c.get("/api/eu").json()["estado"] == "ativo"
    assert admin.patch(f"/api/admin/pessoas/{p.id}", json={"situacao": "bloqueado"}).status_code == 200
    assert c.get("/api/meus-dados/situacao").status_code == 401
    assert c.get("/api/eu").json()["estado"] == "anonimo"


def test_aprovado_depois_do_login_so_entra_de_novo(admin, novo_cliente, db):
    p = criar_pessoa(db, nome="Cadastro Teste", email="cad@exemplo.com.br", tipo="cadastro", situacao="pendente")
    c = novo_cliente()
    entrar(c, "cad@exemplo.com.br")
    assert c.get("/api/eu").json()["estado"] == "pendente"
    admin.patch(f"/api/admin/pessoas/{p.id}", json={"situacao": "ativo"})
    eu = c.get("/api/eu").json()
    assert eu["estado"] == "anonimo" and "liberado" in eu["aviso"]


def test_sair_encerra_a_sessao(admin):
    assert admin.get("/auth/sair", follow_redirects=False).headers["location"] == "/"
    assert admin.get("/api/eu").json()["estado"] == "anonimo"


def test_rota_de_teste_nao_existe_fora_do_modo_teste():
    with TestClient(criar_app(cfg_teste(modo_teste=False)), base_url=f"https://{HOST}") as c:
        assert c.get("/teste/entrar", params={"email": ADMIN}).status_code == 404


def test_cookie_da_sessao_seguro_em_producao():
    with TestClient(criar_app(cfg_teste(cookie_seguro=True)), base_url=f"https://{HOST}") as c:
        r = entrar(c, ADMIN)
        cookie = r.headers["set-cookie"].lower()
        assert "secure" in cookie and "httponly" in cookie and "samesite=lax" in cookie


def test_botao_atualizar_meus_dados_preparado(admin):
    s = admin.get("/api/meus-dados/situacao").json()
    assert s["disponivel"] is False
    assert s["texto"] == ("Puxa do SGA os seus contratos e boletos mais recentes. Pode usar 1 vez a cada 15 minutos. "
                          "O sistema também atualiza sozinho de hora em hora.")
