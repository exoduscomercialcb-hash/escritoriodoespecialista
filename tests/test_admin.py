"""Painel do administrador: quem abre, aprovação, edição e bloqueio."""
from fastapi.testclient import TestClient
from sqlalchemy import select

from app.db import Pessoa
from app.main import criar_app

from .conftest import ADMIN, HOST, cfg_teste, cpf_inventado, criar_pessoa, entrar, pre_cadastro, primeiro_acesso


def test_admin_ve_o_painel(admin):
    eu = admin.get("/api/eu").json()
    assert eu["painel"] is True
    op = admin.get("/api/admin/opcoes").json()
    assert [t["id"] for t in op["tipos"]] == ["admin", "coordenacao", "financeiro", "cadastro", "lider",
                                             "vendedora_interna", "especialista"]
    assert op["equipes"] == ["Recreio", "Lua", "Elite", "Águias", "Pé no Chão", "Tubarões", "Magnatas", "Elim",
                             "Exodus Benefícios"]
    for caminho in ("/api/admin/pessoas", "/api/admin/acessos"):
        assert admin.get(caminho).status_code == 200


def test_quem_nao_e_admin_nao_abre_o_painel(novo_cliente, db):
    for i, tipo in enumerate(["coordenacao", "financeiro", "cadastro", "lider", "vendedora_interna", "especialista"]):
        criar_pessoa(db, nome=f"Pessoa {tipo}", email=f"p{i}@exemplo.com.br", tipo=tipo)
        c = novo_cliente()
        entrar(c, f"p{i}@exemplo.com.br")
        assert c.get("/api/eu").json()["painel"] is False
        for caminho in ("/api/admin/pessoas", "/api/admin/acessos", "/api/admin/opcoes"):
            assert c.get(caminho).status_code == 403, (tipo, caminho)
        assert c.post("/api/admin/importar", json={"texto": "x"}).status_code == 403


def test_especialista_so_recebe_os_dados_dele(admin, novo_cliente, db):
    criar_pessoa(db, nome="Outra Pessoa", email="outra@exemplo.com.br", tipo="cadastro")
    criar_pessoa(db, nome="Especialista Inventado", email="esp@exemplo.com.br", tipo="especialista",
                 equipe="Lua")
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
        r = c.post("/api/admin/pessoas", json={"nome": "Admin Tres", "tipo": "admin", "cpf": cpf_inventado(150)})
        assert r.status_code == 400 and "Só o administrador" in r.json()["erro"]
        r = c.patch(f"/api/admin/pessoas/{alvo_id}", json={"situacao": "bloqueado"})
        assert r.status_code == 400 and "Só o administrador" in r.json()["erro"]


_CPFS = iter(range(200, 400))


def _pendente(admin, novo_cliente, tipo="especialista", email="novo@exemplo.com.br"):
    """Um cadastro pendente que já fez o primeiro acesso (CPF + Google) e espera a aprovação."""
    cpf = cpf_inventado(next(_CPFS))
    p = pre_cadastro(admin, nome="Especialista Novo Inventado", tipo=tipo, cpf=cpf)
    assert admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "pendente"}).status_code == 200
    c = novo_cliente()
    primeiro_acesso(c, cpf, email)
    pessoas = admin.get("/api/admin/pessoas", params={"situacao": "pendente"}).json()["pessoas"]
    return next(p for p in pessoas if p["email"] == email), c


def test_aprovar_especialista_exige_equipe_e_lider(admin, novo_cliente, db):
    lider = criar_pessoa(db, nome="Lider Inventado", email="lider@exemplo.com.br", tipo="lider", equipe="Elite")
    p, c = _pendente(admin, novo_cliente)
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"})
    assert r.status_code == 400
    assert r.json()["erro"] == "Para aprovar como especialista, preencha: equipe, líder."
    assert c.get("/api/eu").json()["estado"] == "pendente"

    nao_lider = criar_pessoa(db, nome="Nao Lider", email="naolider@exemplo.com.br", tipo="cadastro")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"lider_id": nao_lider.id})
    assert r.status_code == 400 and "líder da lista" in r.json()["erro"]

    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={
        "situacao": "ativo", "equipe": "Elite", "lider_id": lider.id})
    assert r.status_code == 200, r.text
    feito = r.json()["pessoa"]
    assert feito["situacao"] == "ativo" and feito["equipe"] == "Elite" and "nome_sga" not in feito
    assert feito["lider_nome"] == "Lider Inventado" and feito["aprovado_por"] == ADMIN

    entrar(c, "novo@exemplo.com.br")  # agora entra
    assert c.get("/api/eu").json()["estado"] == "ativo"


def test_requisitos_de_lider_e_vendedora(admin, novo_cliente):
    p, _ = _pendente(admin, novo_cliente, tipo="lider", email="l@exemplo.com.br")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"})
    assert r.json()["erro"] == "Para aprovar como líder, preencha: equipe."
    p, _ = _pendente(admin, novo_cliente, tipo="vendedora_interna", email="v@exemplo.com.br")
    assert admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "ativo"}).status_code == 200
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
    esp = criar_pessoa(db, nome="Especialista Incompleto", email="inc@exemplo.com.br", tipo="especialista")
    r2 = admin.patch(f"/api/admin/pessoas/{esp.id}", json={"nome": "Especialista Ainda Incompleto"})
    assert r2.status_code == 200  # editar quem já é ativo não exige equipe/líder (isso só vale para aprovar)
    assert r2.json()["pessoa"]["faltando"] == ["equipe", "líder"]
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
    criar_pessoa(db, nome="Bruno Inventado", email="bruno@exemplo.com.br", tipo="lider", equipe="Lua")
    nomes = lambda **q: [p["nome"] for p in admin.get("/api/admin/pessoas", params=q).json()["pessoas"]]  # noqa: E731
    assert nomes()[0] == "Ana Inventada"  # pendentes primeiro
    assert nomes(situacao="pendente") == ["Ana Inventada"]
    assert nomes(q="lua") == ["Bruno Inventado"]
    assert nomes(q="BRUNO INV") == ["Bruno Inventado"]
