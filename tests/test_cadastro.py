"""Links de cadastro: cada link cria pessoa pendente do tipo dele."""
from datetime import timedelta

from sqlalchemy import select

from app.db import LinkCadastro, Pessoa
from app.servicos import MSG_NAO_LIBERADO
from app.tempo import agora

from .conftest import criar_link, criar_pessoa, entrar

NOVO = "novo.especialista@exemplo.com.br"


def test_link_de_cadastro_cria_pessoa_pendente(admin, novo_cliente, db):
    link = criar_link(admin, "especialista")
    assert link["url"] == "https://escritorio.exodusbeneficios.com.br/cadastro/" + link["codigo"]
    c = novo_cliente()
    assert c.get(f"/api/cadastro/{link['codigo']}").json() == {"valido": True, "tipo": "especialista",
                                                               "tipo_nome": "Especialista"}
    assert c.get(f"/cadastro/{link['codigo']}").status_code == 200

    r = entrar(c, NOVO, "Nome Do Google", link=link["codigo"])
    assert r.headers["location"] == f"/cadastro/{link['codigo']}"
    eu = c.get("/api/eu").json()
    assert eu["estado"] == "sem_cadastro" and eu["link"] == link["codigo"]

    r = c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "  Especialista   Inventado  "})
    assert r.status_code == 200 and r.json() == {"estado": "pendente", "mensagem": MSG_NAO_LIBERADO}
    p = db.scalars(select(Pessoa).where(Pessoa.email == NOVO)).one()
    assert (p.nome, p.tipo, p.situacao, p.link_id) == ("Especialista Inventado", "especialista", "pendente",
                                                       link["id"])
    assert db.get(LinkCadastro, link["id"]).usos == 1
    assert c.get("/api/eu").json()["estado"] == "pendente"
    assert c.get("/api/meus-dados/situacao").status_code == 401  # pendente não entra

    # mandar de novo não duplica
    r = c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Outra Vez"})
    assert r.status_code == 400 and "já tem cadastro" in r.json()["erro"]
    assert len(db.scalars(select(Pessoa).where(Pessoa.email == NOVO)).all()) == 1


def test_cada_link_cadastra_o_seu_tipo(admin, novo_cliente, db):
    for i, tipo in enumerate(["coordenacao", "financeiro", "cadastro", "lider", "vendedora_interna", "admin"]):
        link = criar_link(admin, tipo)
        c = novo_cliente()
        entrar(c, f"pessoa{i}@exemplo.com.br", link=link["codigo"])
        assert c.post(f"/api/cadastro/{link['codigo']}", json={"nome": f"Pessoa Inventada {i}"}).status_code == 200
        p = db.scalars(select(Pessoa).where(Pessoa.email == f"pessoa{i}@exemplo.com.br")).one()
        assert (p.tipo, p.situacao) == (tipo, "pendente")


def test_link_invalido_desativado_ou_vencido(admin, novo_cliente, db):
    c = novo_cliente()
    assert c.get("/api/cadastro/nao-existe").json()["valido"] is False

    link = criar_link(admin)
    assert admin.patch(f"/api/admin/links/{link['id']}", json={"ativo": False}).json()["link"]["situacao"] == "desativado"
    assert c.get(f"/api/cadastro/{link['codigo']}").json()["valido"] is False
    entrar(c, NOVO, link=link["codigo"])
    assert c.get("/api/eu").json()["link"] is None  # link desativado não é guardado
    r = c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Especialista Inventado"})
    assert r.status_code == 400 and "não vale mais" in r.json()["erro"]

    vencido = criar_link(admin)
    db.get(LinkCadastro, vencido["id"]).validade = agora() - timedelta(minutes=1)
    db.commit()
    assert c.get(f"/api/cadastro/{vencido['codigo']}").json()["valido"] is False
    links = {lk["id"]: lk for lk in admin.get("/api/admin/links").json()["links"]}
    assert links[vencido["id"]]["situacao"] == "vencido"
    assert db.scalars(select(Pessoa).where(Pessoa.email == NOVO)).all() == []


def test_validade_do_link(admin):
    r = admin.post("/api/admin/links", json={"tipo": "especialista", "validade": "2020-01-01"})
    assert r.status_code == 400 and "hoje ou depois" in r.json()["erro"]
    assert admin.post("/api/admin/links", json={"tipo": "especialista", "validade": "31/12"}).status_code == 400
    link = criar_link(admin, validade="2099-12-31")
    assert link["validade_txt"] == "31/12/2099" and link["situacao"] == "ativo"
    assert admin.post("/api/admin/links", json={"tipo": "gerente"}).status_code == 400


def test_cadastro_exige_google_e_nome(admin, novo_cliente):
    link = criar_link(admin)
    c = novo_cliente()
    r = c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Especialista Inventado"})
    assert r.status_code == 400 and "Entre com o Google" in r.json()["erro"]
    entrar(c, NOVO, link=link["codigo"])
    assert c.post(f"/api/cadastro/{link['codigo']}", json={"nome": "Al"}).status_code == 400
    assert c.post(f"/api/cadastro/{link['codigo']}", json={}).status_code == 422


def test_quem_ja_tem_cadastro_nao_usa_link(admin, novo_cliente, db):
    criar_pessoa(db, nome="Ja Cadastrada", email="ja@exemplo.com.br", tipo="cadastro")
    link = criar_link(admin)
    c = novo_cliente()
    assert entrar(c, "ja@exemplo.com.br", link=link["codigo"]).headers["location"] == "/"
    assert db.get(LinkCadastro, link["id"]).usos == 0


def test_envio_de_outro_site_e_recusado(admin, novo_cliente):
    link = criar_link(admin)
    c = novo_cliente()
    entrar(c, NOVO, link=link["codigo"])
    url = f"/api/cadastro/{link['codigo']}"
    assert c.post(url, data={"nome": "Especialista Inventado"}).status_code == 415
    r = c.post(url, json={"nome": "Especialista Inventado"}, headers={"Origin": "https://golpe.exemplo"})
    assert r.status_code == 403
    r = c.post(url, json={"nome": "Especialista Inventado"},
               headers={"Origin": "https://escritorio.exodusbeneficios.com.br"})
    assert r.status_code == 200
