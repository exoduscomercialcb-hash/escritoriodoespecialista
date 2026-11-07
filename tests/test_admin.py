"""Painel do administrador: quem abre, aprovação, edição e bloqueio."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Pessoa
from app.main import criar_app

from .conftest import ADMIN, HOST, cfg_teste, criar_link, criar_pessoa, entrar


def test_admin_ve_o_painel(admin):
    eu = admin.get("/api/eu").json()
    assert eu["painel"] is True
    op = admin.get("/api/admin/opcoes").json()
    assert [t["id"] for t in op["tipos"]] == ["admin", "coordenacao", "financeiro", "cadastro", "lider",
                                             "vendedora_interna", "especialista"]
    assert op["equipes"] == ["Recreio", "Lua", "Elite", "Águias", "Pé no Chão", "Tubarões", "Magnatas", "Elim"]
    for caminho in ("/api/admin/pessoas", "/api/admin/links", "/api/admin/acessos"):
        assert admin.get(caminho).status_code == 200


def test_quem_nao_e_admin_nao_abre_o_painel(novo_cliente, db):
    for i, tipo in enumerate(["coordenacao", "financeiro", "cadastro", "lider", "vendedora_interna", "especialista"]):
        criar_pessoa(db, nome=f"Pessoa {tipo}", email=f"p{i}@exemplo.com.br", tipo=tipo)
        c = novo_cliente()
        entrar(c, f"p{i}@exemplo.com.br")
        assert c.get("/api/eu").json()["painel"] is False
        for caminho in ("/api/admin/pessoas", "/api/admin/links", "/api/admin/acessos", "/api/admin/opcoes"):
            assert c.get(caminho).status_code == 403, (tipo, caminho)
        assert c.post("/api/admin/links", json={"tipo": "admin"}).status_code == 403


def test_especialista_so_recebe_os_dados_dele(admin, novo_cliente, db):
    criar_pessoa(db, nome="Outra Pessoa", email="outra@exemplo.com.br", tipo="cadastro")
    criar_pessoa(db, nome="Especialista Inventado", email="esp@exemplo.com.br", tipo="especialista",
                 equipe="Lua", nome_sga="ESPECIALISTA INVENTADO")
    c = novo_cliente()
    entrar(c, "esp@exemplo.com.br")
    eu = c.get("/api/eu").json()
    assert eu["pessoa"]["nome"] == "Especialista Inventado" and eu["pessoa"]["equipe"] == "Lua"
    assert "Outra Pessoa" not in str(eu)
    assert c.get("/api/admin/pessoas").status_code == 403


def test_coordenacao_abre_o_painel_so_se_liberado():
    app = criar_app(cfg_teste(painel_coordenacao=True))
    with TestClient(app, base_url=f"https://{HOST}") as adm, TestClient(app, base_url=f"https://{HOST}") as c:
        entrar(adm, ADMIN)
        with app.state.Sessao() as s:
            alvo = criar_pessoa(s, nome="Admin Dois", email="admin2@exemplo.com.br", tipo="admin")
            criar_pessoa(s, nome="Coordenacao Teste", email="coord@exemplo.com.br", tipo="coordenacao")
            alvo_id = alvo.id
        entrar(c, "coord@exemplo.com.br")
        assert c.get("/api/eu").json()["painel"] is True
        assert c.get("/api/admin/pessoas").status_code == 200
        r = c.post("/api/admin/links", json={"tipo": "admin"})
        assert r.status_code == 400 and "Só o administrador" in r.json()["erro"]
        r = c.patch(f"/api/admin/pessoas/{alvo_id}", json={"situacao": "bloqueado"})
        assert r.status_code == 400 and "Só o administrador" in r.json()["erro"]
        link_admin = criar_link(adm, "admin")
        assert c.patch(f"/api/admin/links/{link_admin['id']}", json={"ativo": False}).status_code == 403


def _pendente(admin, novo_cliente, tipo="especialista", email="novo@exemplo.com.br"):
    link = criar_link(admin, tipo)
    c = novo_cliente()
    entrar(c, email, link=link["codigo"])
    assert c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Especialista Novo Inventado"}).status_code == 200
    pessoas = admin.get("/api/admin/pessoas", params={"situacao": "pendente"}).json()["pessoas"]
    return next(p for p in pessoas if p["email"] == email), c


def test_aprovar_especialista_exige_sga_equipe_e_lider(admin, novo_cliente, db):
    lider = criar_pessoa(db, nome="Lider Inventado", email="lider@exemplo.com.br", tipo="lider", equipe="Elite",
                         nome_sga="LIDER INVENTADO")
    p, c = _pendente(admin, novo_cliente)
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"})
    assert r.status_code == 400
    assert r.json()["erro"] == "Para aprovar como especialista, preencha: equipe, nome no SGA, líder."
    assert c.get("/api/eu").json()["estado"] == "pendente"

    nao_lider = criar_pessoa(db, nome="Nao Lider", email="naolider@exemplo.com.br", tipo="cadastro")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"lider_id": nao_lider.id})
    assert r.status_code == 400 and "líder da lista" in r.json()["erro"]

    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={
        "situacao": "ativo", "equipe": "Elite", "nome_sga": "  especialista   novo inventado ", "lider_id": lider.id})
    assert r.status_code == 200, r.text
    feito = r.json()["pessoa"]
    assert feito["situacao"] == "ativo" and feito["nome_sga"] == "ESPECIALISTA NOVO INVENTADO"
    assert feito["lider_nome"] == "Lider Inventado" and feito["aprovado_por"] == ADMIN

    entrar(c, "novo@exemplo.com.br")  # agora entra
    assert c.get("/api/eu").json()["estado"] == "ativo"


def test_nome_sga_completo_nao_confunde_nomes_parecidos(admin, novo_cliente, db):
    """O vínculo com o SGA é o nome exato (caso Rodrigo Moraes Luiz × Rodrigo Moraes Venâncio, com nomes inventados)."""
    lider = criar_pessoa(db, nome="Lider Inventado", email="lider@exemplo.com.br", tipo="lider", equipe="Elite",
                         nome_sga="LIDER INVENTADO")
    a, _ = _pendente(admin, novo_cliente, email="a@exemplo.com.br")
    b, _ = _pendente(admin, novo_cliente, email="b@exemplo.com.br")
    for p, sga in ((a, "FULANO SICRANO LUIZ"), (b, "FULANO SICRANO VENANCIO")):
        r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo", "equipe": "Elite",
                                                               "nome_sga": sga, "lider_id": lider.id})
        assert r.status_code == 200
    sgas = {p.email: p.nome_sga for p in db.scalars(select(Pessoa).where(Pessoa.email.in_(["a@exemplo.com.br",
                                                                                           "b@exemplo.com.br"])))}
    assert sgas == {"a@exemplo.com.br": "FULANO SICRANO LUIZ", "b@exemplo.com.br": "FULANO SICRANO VENANCIO"}


def test_requisitos_de_lider_e_vendedora(admin, novo_cliente):
    p, _ = _pendente(admin, novo_cliente, tipo="lider", email="l@exemplo.com.br")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"})
    assert r.json()["erro"] == "Para aprovar como líder, preencha: equipe, nome no SGA."
    p, _ = _pendente(admin, novo_cliente, tipo="vendedora_interna", email="v@exemplo.com.br")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"})
    assert r.json()["erro"] == "Para aprovar como vendedora interna, preencha: nome no SGA."
    p, _ = _pendente(admin, novo_cliente, tipo="financeiro", email="f@exemplo.com.br")
    assert admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"}).status_code == 200


def test_editar_valida_os_campos(admin, db):
    p = criar_pessoa(db, nome="Cadastro Inventado", email="c@exemplo.com.br", tipo="cadastro")
    url = f"/api/admin/pessoas/{p.id}"
    assert admin.patch(url, json={"equipe": "Equipe Que Nao Existe"}).status_code == 400
    assert admin.patch(url, json={"tipo": "gerente"}).status_code == 400
    assert admin.patch(url, json={"situacao": "sumido"}).status_code == 400
    assert admin.patch(url, json={"nome": "x"}).status_code == 400
    assert admin.patch("/api/admin/pessoas/9999", json={"nome": "Ninguem Aqui"}).status_code == 404
    r = admin.patch(url, json={"equipe": "Águias", "nome": "Cadastro Renomeado"})
    assert r.json()["pessoa"]["equipe"] == "Águias" and r.json()["pessoa"]["nome"] == "Cadastro Renomeado"


def test_admin_nao_se_bloqueia_nem_perde_o_admin(admin, db):
    eu = admin.get("/api/eu").json()["pessoa"]
    for corpo in ({"situacao": "bloqueado"}, {"tipo": "coordenacao"}):
        r = admin.patch(f"/api/admin/pessoas/{eu['id']}", json=corpo)
        assert r.status_code == 400 and "próprio" in r.json()["erro"]
    assert admin.patch(f"/api/admin/pessoas/{eu['id']}", json={"nome": "Admin Renomeado"}).status_code == 200


def test_admin_emails_nao_pode_ser_bloqueado_por_outro_admin(novo_cliente, db):
    c1 = novo_cliente()
    entrar(c1, ADMIN)
    criar_pessoa(db, nome="Admin Dois", email="admin2@exemplo.com.br", tipo="admin")
    c2 = novo_cliente()
    entrar(c2, "admin2@exemplo.com.br")
    alvo = db.scalars(select(Pessoa).where(Pessoa.email == ADMIN)).one()
    r = c2.patch(f"/api/admin/pessoas/{alvo.id}", json={"situacao": "bloqueado"})
    assert r.status_code == 400 and "ADMIN_EMAILS" in r.json()["erro"]


def test_lista_de_cadastros_filtra_e_busca(admin, db):
    criar_pessoa(db, nome="Ana Inventada", email="ana@exemplo.com.br", tipo="cadastro", situacao="pendente")
    criar_pessoa(db, nome="Bruno Inventado", email="bruno@exemplo.com.br", tipo="lider", equipe="Lua",
                 nome_sga="BRUNO INVENTADO")
    nomes = lambda **q: [p["nome"] for p in admin.get("/api/admin/pessoas", params=q).json()["pessoas"]]  # noqa: E731
    assert nomes()[0] == "Ana Inventada"  # pendentes primeiro
    assert nomes(situacao="pendente") == ["Ana Inventada"]
    assert nomes(q="lua") == ["Bruno Inventado"]
    assert nomes(q="BRUNO INV") == ["Bruno Inventado"]
