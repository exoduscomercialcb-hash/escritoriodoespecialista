"""Primeiro acesso no endereço único do escritório (decisões de 08/11).

Só entra quem a coordenação cadastrou antes (nome, tipo de conta e CPF). No primeiro acesso, a pessoa informa
CPF e WhatsApp e entra com o Google; depois, só "Entrar com Google". Não existe mais link de cadastro.
Todos os nomes, CPFs, e-mails e telefones daqui são inventados.
"""
from sqlalchemy import select

from app.db import Acesso, Pessoa

from .conftest import cpf_inventado, criar_pessoa, entrar, pre_cadastro, primeiro_acesso

NOVO = "novo.especialista@exemplo.com.br"


def _post(c, cpf, whatsapp="21987654321"):
    return c.post("/api/primeiro-acesso", json={"cpf": cpf, "whatsapp": whatsapp})


def test_cpf_antes_do_google_libera_e_grava_o_whatsapp(admin, novo_cliente, db):
    p = pre_cadastro(admin, nome="Especialista Inventado", cpf=cpf_inventado(7), equipe="Lua")
    assert p["aguardando_primeiro_acesso"] is True and p["situacao"] == "ativo"
    c = novo_cliente()
    cpf = cpf_inventado(7)
    r = _post(c, f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}", "+55 (21) 98765-4321")
    assert r.json() == {"ok": True, "proximo": "/auth/login"}
    assert entrar(c, NOVO, "Nome Do Google").headers["location"] == "/"

    eu = c.get("/api/eu").json()
    assert eu["estado"] == "ativo" and eu["pessoa"]["nome"] == "Especialista Inventado"
    pessoa = db.get(Pessoa, p["id"])
    db.refresh(pessoa)
    assert (pessoa.email, pessoa.whatsapp) == (NOVO, "21987654321") and pessoa.vinculado_em is not None
    assert [a.aba for a in db.scalars(select(Acesso).where(Acesso.pessoa_id == p["id"]))] == ["entrada"]
    # da próxima vez, entra direto pelo Google, sem CPF
    c2 = novo_cliente()
    assert entrar(c2, NOVO).headers["location"] == "/"
    assert c2.get("/api/eu").json()["estado"] == "ativo"


def test_google_antes_do_cpf_tambem_funciona(admin, novo_cliente, db):
    """Quem clica direto em "Entrar com Google" no primeiro acesso não fica sem saída: informa o CPF depois."""
    p = pre_cadastro(admin, nome="Lider Inventado", tipo="lider", cpf=cpf_inventado(8))
    c = novo_cliente()
    entrar(c, NOVO)
    assert c.get("/api/eu").json()["estado"] == "sem_cadastro"
    assert db.get(Pessoa, p["id"]).email is None  # só o Google, sem CPF, não liga a conta a ninguém
    r = _post(c, cpf_inventado(8), "(11) 3456-7890")
    assert r.json() == {"ok": True, "proximo": "/"}
    eu = c.get("/api/eu").json()
    assert eu["estado"] == "ativo" and eu["pessoa"]["tipo"] == "lider" and eu["pessoa"]["whatsapp"] == "(11) 3456-7890"


def test_cpf_sem_cadastro_nao_entra(admin, novo_cliente, db):
    r = _post(novo_cliente(), cpf_inventado(99))
    assert r.status_code == 400
    assert r.json()["erro"] == "Não encontramos um cadastro com esse CPF. Fale com a coordenação."


def test_cpf_e_whatsapp_invalidos(admin, novo_cliente):
    pre_cadastro(admin, cpf=cpf_inventado(5))
    c = novo_cliente()
    assert "CPF inválido" in _post(c, "123.456.789-00").json()["erro"]
    assert "CPF inválido" in _post(c, "111.111.111-11").json()["erro"]
    assert "WhatsApp inválido" in _post(c, cpf_inventado(5), "98765").json()["erro"]
    assert c.post("/api/primeiro-acesso", json={"cpf": cpf_inventado(5)}).status_code == 422


def test_cpf_ja_ligado_a_outra_conta(admin, novo_cliente):
    pre_cadastro(admin, cpf=cpf_inventado(6))
    primeiro_acesso(novo_cliente(), cpf_inventado(6), NOVO)
    r = _post(novo_cliente(), cpf_inventado(6))
    assert r.status_code == 400 and "já está ligado a uma conta Google" in r.json()["erro"]


def test_conta_google_ja_ligada_nao_pega_outro_cpf(admin, novo_cliente, db):
    pre_cadastro(admin, nome="Pessoa Um Inventada", tipo="cadastro", cpf=cpf_inventado(12))
    pre_cadastro(admin, nome="Pessoa Dois Inventada", tipo="cadastro", cpf=cpf_inventado(13))
    c = novo_cliente()
    primeiro_acesso(c, cpf_inventado(12), NOVO)
    admin.patch(f"/api/admin/pessoas/{c.get('/api/eu').json()['pessoa']['id']}", json={"situacao": "pendente"})
    entrar(c, NOVO)  # pendente: fica com a sessão do Google, mas já tem cadastro
    r = _post(c, cpf_inventado(13))
    assert r.status_code == 400 and "já está ligada a outro cadastro" in r.json()["erro"]


def test_bloqueado_nao_faz_primeiro_acesso(admin, novo_cliente):
    p = pre_cadastro(admin, cpf=cpf_inventado(9))
    admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "bloqueado"})
    r = _post(novo_cliente(), cpf_inventado(9))
    assert r.status_code == 400 and "não foi liberado" in r.json()["erro"]


def test_bloqueado_entre_o_cpf_e_o_google_nao_entra(admin, novo_cliente, db):
    p = pre_cadastro(admin, cpf=cpf_inventado(10))
    c = novo_cliente()
    _post(c, cpf_inventado(10))
    admin.patch(f"/api/admin/pessoas/{p['id']}", json={"situacao": "bloqueado"})
    entrar(c, NOVO)
    assert c.get("/api/eu").json()["estado"] == "sem_cadastro"
    assert db.get(Pessoa, p["id"]).email is None


def test_envio_de_outro_site_e_recusado(admin, novo_cliente):
    pre_cadastro(admin, cpf=cpf_inventado(11))
    c = novo_cliente()
    corpo = {"cpf": cpf_inventado(11), "whatsapp": "21987654321"}
    assert c.post("/api/primeiro-acesso", data=corpo).status_code == 415
    assert c.post("/api/primeiro-acesso", json=corpo, headers={"Origin": "https://golpe.exemplo"}).status_code == 403
    assert c.post("/api/primeiro-acesso", json=corpo,
                  headers={"Origin": "https://escritorio.exodusbeneficios.com.br"}).status_code == 200


def test_quem_ja_tem_conta_entra_direto(admin, novo_cliente, db):
    criar_pessoa(db, nome="Ja Cadastrada", email="ja@exemplo.com.br", tipo="cadastro")
    c = novo_cliente()
    assert entrar(c, "ja@exemplo.com.br").headers["location"] == "/"
    assert c.get("/api/eu").json()["estado"] == "ativo"


def test_nao_existe_mais_link_de_cadastro(admin, novo_cliente):
    assert admin.get("/api/admin/links").status_code == 404
    assert novo_cliente().get("/cadastro/qualquer").status_code == 404
