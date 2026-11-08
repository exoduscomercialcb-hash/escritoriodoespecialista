"""Cadastro pela coordenação: um por um no painel ou colando a planilha do Excel.

Todos os nomes, CPFs e telefones daqui são inventados.
"""
from sqlalchemy import select

from app.db import Pessoa

from .conftest import ADMIN, cpf_inventado, criar_pessoa, entrar, pre_cadastro, primeiro_acesso

TITULOS = "Nome\tTipo de conta\tCPF\tEquipe\tNome no SGA\tLíder\tWhatsApp"


def planilha(*linhas: str, titulos: str = TITULOS) -> str:
    return "\n".join([titulos, *linhas]) + "\n"


def test_importa_lideres_e_liderados_colados_do_excel(admin, db):
    texto = planilha(
        f"Especialista Um Inventado\tLiderado\t{cpf_inventado(21)}\tpe no chao\tespecialista um inventado\tLider Inventado\t21987650001",
        f"Lider Inventado\tLíder\t{cpf_inventado(20)}\tPé no Chão\tLIDER INVENTADO\t\t(21) 98765-0000",
        f"Financeiro Inventado\tFinanceiro\t{cpf_inventado(22)}\t\t\t\t",
    )
    r = admin.post("/api/admin/importar", json={"texto": texto}).json()
    assert r == {"importado": True, "criados": 3, "atualizados": 0, "erros": [], "lideres_pela_equipe": 0,
                 "ligado_ao_admin": False}
    pessoas = {p.nome: p for p in db.scalars(select(Pessoa).where(Pessoa.cpf.is_not(None)))}
    lider, esp = pessoas["Lider Inventado"], pessoas["Especialista Um Inventado"]
    assert (lider.tipo, lider.equipe, lider.whatsapp, lider.situacao) == ("lider", "Pé no Chão", "21987650000", "ativo")
    assert (esp.tipo, esp.lider_id, esp.email) == ("especialista", lider.id, None)  # "Nome no SGA" é ignorado
    assert pessoas["Financeiro Inventado"].tipo == "financeiro"


def test_importar_de_novo_atualiza_sem_duplicar(admin, db):
    linha = f"Lider Inventado\tLíder\t{cpf_inventado(30)}\tElite\t\t\t"
    admin.post("/api/admin/importar", json={"texto": planilha(linha)})
    r = admin.post("/api/admin/importar", json={"texto": planilha(linha.replace("Elite", "Águias"))}).json()
    assert (r["criados"], r["atualizados"]) == (0, 1)
    assert [p.equipe for p in db.scalars(select(Pessoa).where(Pessoa.cpf == cpf_inventado(30)))] == ["Águias"]


def test_planilha_com_erro_nao_grava_nada(admin, db):
    texto = planilha(
        f"Pessoa Certa\tCadastro\t{cpf_inventado(40)}\t\t\t\t",
        "Pessoa Cpf Errado\tCadastro\t123.456.789-00\t\t\t\t",
        f"Pessoa Tipo Errado\tGerente\t{cpf_inventado(41)}\t\t\t\t",
        f"Pessoa Repetida\tCadastro\t{cpf_inventado(40)}\t\t\t\t",
        f"Pessoa Equipe Errada\tCadastro\t{cpf_inventado(42)}\tSem Nome\t\t\t",
        f"Liderado Sem Lider\tEspecialista\t{cpf_inventado(43)}\tLua\t\tLider Que Nao Existe\t",
    )
    r = admin.post("/api/admin/importar", json={"texto": texto}).json()
    assert r["importado"] is False
    assert [(e["linha"], e["mensagem"][:22]) for e in r["erros"]] == [
        (3, "CPF inválido. Confira "), (4, "Tipo de conta “Gerente"), (5, "CPF repetido (também n"),
        (6, "Equipe “Sem Nome” desc"), (7, "Líder “Lider Que Nao E")]
    assert db.scalars(select(Pessoa).where(Pessoa.cpf.is_not(None))).all() == []


def test_planilha_csv_com_ponto_e_virgula_e_colunas_minimas(admin, db):
    texto = f"nome;tipo;cpf\nCadastro Inventado;cadastro;{cpf_inventado(50)}\n"
    assert admin.post("/api/admin/importar", json={"texto": texto}).json()["criados"] == 1
    r = admin.post("/api/admin/importar", json={"texto": "nome;cpf\nFulano;123\n"})
    assert r.status_code == 400 and "Faltando: Tipo de conta" in r.json()["erro"]
    assert admin.post("/api/admin/importar", json={"texto": "   "}).status_code == 400


def test_modelo_da_planilha(admin):
    r = admin.get("/api/admin/modelo-planilha.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    assert r.text.lstrip("﻿").startswith("Nome;Tipo de conta;CPF;Equipe;Líder;WhatsApp;E-mail")


def test_novo_cadastro_pelo_painel(admin, db):
    p = pre_cadastro(admin, nome="Vendedora Inventada", tipo="vendedora_interna", cpf=cpf_inventado(60),
                     whatsapp="(11) 3456-7890", equipe="Exodus Benefícios")
    assert (p["cpf"], p["whatsapp"], p["equipe"]) == (
        "{}.{}.{}-{}".format(cpf_inventado(60)[:3], cpf_inventado(60)[3:6], cpf_inventado(60)[6:9], cpf_inventado(60)[9:]),
        "(11) 3456-7890", "Exodus Benefícios")
    assert p["faltando"] == []
    r = admin.post("/api/admin/pessoas", json={"nome": "Outra Pessoa", "tipo": "cadastro", "cpf": cpf_inventado(60)})
    assert r.status_code == 400 and "Já existe um cadastro com esse CPF" in r.json()["erro"]
    r = admin.post("/api/admin/pessoas", json={"nome": "Outra Pessoa", "tipo": "cadastro", "cpf": "000"})
    assert r.status_code == 400


def test_coordenacao_nao_cadastra_administrador(novo_cliente, db):
    criar_pessoa(db, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
    c = novo_cliente()
    entrar(c, "coord@exemplo.com.br")
    assert c.post("/api/admin/pessoas", json={"nome": "X Y Z", "tipo": "admin", "cpf": cpf_inventado(70)}).status_code == 403


def test_filtro_aguardando_e_busca_por_cpf(admin, db):
    pre_cadastro(admin, nome="Ainda Nao Entrou", tipo="cadastro", cpf=cpf_inventado(80))
    nomes = lambda **q: [p["nome"] for p in admin.get("/api/admin/pessoas", params=q).json()["pessoas"]]  # noqa: E731
    assert nomes(situacao="aguardando") == ["Ainda Nao Entrou"]
    assert nomes(q=cpf_inventado(80)[2:8]) == ["Ainda Nao Entrou"]
    assert "Admin Teste" not in nomes(situacao="aguardando")


def test_editar_cpf_e_whatsapp(admin, db):
    a = pre_cadastro(admin, nome="Pessoa A Inventada", tipo="cadastro", cpf=cpf_inventado(90))
    pre_cadastro(admin, nome="Pessoa B Inventada", tipo="cadastro", cpf=cpf_inventado(91))
    url = f"/api/admin/pessoas/{a['id']}"
    assert "outro cadastro com esse CPF" in admin.patch(url, json={"cpf": cpf_inventado(91)}).json()["erro"]
    r = admin.patch(url, json={"whatsapp": "21 99999-0000"}).json()["pessoa"]
    assert r["whatsapp"] == "(21) 99999-0000"


def test_planilha_no_formato_do_sistema_atual(admin, db):
    """Mesmo formato da planilha de acessos de hoje (dados inventados): Usuário, TIPO DE CONTA, Nome, Equipe(s),
    CPF, Matrícula SGA (ignorada); tipos "liderado", "líder", "INSIDE SALES", "SENHA MASTER" e "SENHA FINANCEIRO"."""
    titulos = "Usuário\tTIPO DE CONTA\tNome\tEquipe(s)\tCPF\tMatrícula SGA"
    texto = planilha(
        f"VENDEDORA UM\tINSIDE SALES\tVendedora Um Inventada\tEXODUS BENEFICIOS\t{cpf_inventado(101)}\t501",
        f"ADMIN TESTE\tSENHA MASTER\tAdmin Teste Completo\tRECREIO\t{cpf_inventado(102)}\t502",
        f"LIDER LUA\tlíder\tLider Lua Inventado\tLUA\t{cpf_inventado(103)}\t503",
        f"LIDER ELITE\tlíder\tLider Elite Inventado\tELITE\t{cpf_inventado(104)}\t504",
        f"LIDERADO LUA\tliderado\tLiderado Lua Inventado\tLUA\t{cpf_inventado(105)}\t505",
        f"LIDERADO DOIS\tliderado\tLiderado Duas Equipes\tELITE, LUA\t{cpf_inventado(106)}\t506",
        f"LIDERADO CASA\tliderado\tLiderado Sem Lider\tEXODUS BENEFICIOS, RECREIO, ÁGUIAS\t{cpf_inventado(107)}\t507",
        f"FINANCEIRO\tSENHA FINANCEIRO\tFinanceiro Inventado\t\t{cpf_inventado(108)}\t508",
        titulos=titulos)
    r = admin.post("/api/admin/importar", json={"texto": texto}).json()
    assert r["importado"] is True, r
    assert (r["criados"], r["atualizados"], r["lideres_pela_equipe"], r["ligado_ao_admin"]) == (7, 1, 1, True)

    por_nome = {p.nome: p for p in db.scalars(select(Pessoa))}
    admin_p = por_nome["Admin Teste Completo"]  # a linha SENHA MASTER virou o próprio administrador
    assert (admin_p.tipo, admin_p.email, admin_p.cpf, admin_p.equipe) == ("admin", ADMIN, cpf_inventado(102), "Recreio")
    assert por_nome["Vendedora Um Inventada"].tipo == "vendedora_interna"
    assert por_nome["Financeiro Inventado"].tipo == "financeiro"
    lua, duas, casa = (por_nome[n] for n in ("Liderado Lua Inventado", "Liderado Duas Equipes", "Liderado Sem Lider"))
    assert (lua.tipo, lua.lider_id) == ("especialista", por_nome["Lider Lua Inventado"].id)  # matrícula ignorada
    assert (duas.equipe, duas.lider_id) == ("Elite, Lua", None)  # dois líderes possíveis: fica para escolher
    assert (casa.equipe, casa.lider_id) == ("Exodus Benefícios, Recreio, Águias", None)
    assert len([p for p in por_nome.values() if p.tipo == "admin"]) == 1

    # quem tem mais de uma equipe aparece no filtro de cada uma
    nomes = lambda eq: {x["nome"] for x in admin.get("/api/admin/pessoas", params={"q": eq}).json()["pessoas"]}  # noqa: E731
    assert "Liderado Duas Equipes" in nomes("elite") and "Liderado Duas Equipes" in nomes("lua")


def test_varias_equipes_no_painel(admin, db):
    p = pre_cadastro(admin, nome="Especialista Inventado", cpf=cpf_inventado(110), equipe="lua, Elite")
    assert (p["equipe"], p["equipes"]) == ("Lua, Elite", ["Lua", "Elite"])
    assert "matricula_sga" not in p and "nome_sga" not in p
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"equipe": "Águias, Águias"})
    assert r.json()["pessoa"]["equipe"] == "Águias"
    assert "desconhecida" in admin.patch(f"/api/admin/pessoas/{p['id']}", json={"equipe": "Lua, Marte"}).json()["erro"]


def test_email_cadastrado_pela_coordenacao(admin, novo_cliente, db):
    """Os novos já entram com o e-mail certo: a pessoa só consegue entrar com ele."""
    p = pre_cadastro(admin, nome="Novo Com Email", tipo="cadastro", cpf=cpf_inventado(120), email="Novo.Email@Exemplo.com.br")
    assert p["email"] == "novo.email@exemplo.com.br" and p["aguardando_primeiro_acesso"] is True
    r = admin.post("/api/admin/pessoas", json={"nome": "Outro", "tipo": "cadastro", "cpf": cpf_inventado(121),
                                               "email": "novo.email@exemplo.com.br"})
    assert r.status_code == 400 and "esse e-mail" in r.json()["erro"]
    assert "E-mail inválido" in admin.post("/api/admin/pessoas", json={
        "nome": "Outro", "tipo": "cadastro", "cpf": cpf_inventado(121), "email": "sem-arroba"}).json()["erro"]

    # entra pela tela (CPF + WhatsApp + Google) com o e-mail cadastrado: libera e grava o telefone
    c = novo_cliente()
    c.post("/api/primeiro-acesso", json={"cpf": cpf_inventado(120), "whatsapp": "21 98888-7777"})
    assert entrar(c, "novo.email@exemplo.com.br").headers["location"] == "/"
    eu = c.get("/api/eu").json()["pessoa"]
    assert eu["whatsapp"] == "(21) 98888-7777" and eu["aguardando_primeiro_acesso"] is False and eu["vinculado_em_txt"]

    # com outra conta Google, não entra
    c2 = novo_cliente()
    c2.post("/api/primeiro-acesso", json={"cpf": cpf_inventado(120), "whatsapp": "21 98888-7777"})
    entrar(c2, "outra@exemplo.com.br")
    assert c2.get("/api/eu").json()["estado"] == "sem_cadastro"
    r = c2.post("/api/primeiro-acesso", json={"cpf": cpf_inventado(120), "whatsapp": "21 98888-7777"})
    assert r.status_code == 400 and "outra conta Google" in r.json()["erro"]


def test_trocar_o_email_desliga_a_conta_antiga(admin, novo_cliente, db):
    p = pre_cadastro(admin, nome="Troca De Conta", tipo="cadastro", cpf=cpf_inventado(130))

    primeiro_acesso(novo_cliente(), cpf_inventado(130), "antiga@exemplo.com.br")
    r = admin.patch(f"/api/admin/pessoas/{p['id']}", json={"email": "nova@exemplo.com.br"})
    assert r.json()["pessoa"]["email"] == "nova@exemplo.com.br" and r.json()["pessoa"]["aguardando_primeiro_acesso"]
    velha = novo_cliente()
    entrar(velha, "antiga@exemplo.com.br")
    assert velha.get("/api/eu").json()["estado"] == "sem_cadastro"  # nem pelo e-mail, nem pela conta Google antiga
    nova = novo_cliente()
    entrar(nova, "nova@exemplo.com.br")
    assert nova.get("/api/eu").json()["estado"] == "ativo"
    eu = admin.get("/api/eu").json()["pessoa"]
    r = admin.patch(f"/api/admin/pessoas/{eu['id']}", json={"email": "outro.admin@exemplo.com.br"})
    assert r.status_code == 400 and "não pode ser trocado" in r.json()["erro"]


def test_planilha_com_coluna_de_email(admin, db):
    texto = planilha(f"Pessoa Com Email\tCadastro\t{cpf_inventado(140)}\t\t\t\t\tpessoa@exemplo.com.br",
                     titulos="Nome\tTipo de conta\tCPF\tEquipe\tNome no SGA\tLíder\tWhatsApp\tE-mail")
    assert admin.post("/api/admin/importar", json={"texto": texto}).json()["criados"] == 1
    assert db.scalars(select(Pessoa).where(Pessoa.cpf == cpf_inventado(140))).one().email == "pessoa@exemplo.com.br"
    outro = planilha(f"Outra Pessoa\tCadastro\t{cpf_inventado(141)}\t\t\t\t\tpessoa@exemplo.com.br",
                     titulos="Nome\tTipo de conta\tCPF\tEquipe\tNome no SGA\tLíder\tWhatsApp\tE-mail")
    r = admin.post("/api/admin/importar", json={"texto": outro}).json()
    assert r["importado"] is False and "outro cadastro" in r["erros"][0]["mensagem"]


def test_baixar_planilha_de_cadastros(admin, novo_cliente, db):
    pre_cadastro(admin, nome="=Formula Inventada", tipo="cadastro", cpf=cpf_inventado(150), whatsapp="21987654321")
    r = admin.get("/api/admin/cadastros.csv")
    assert r.status_code == 200 and "attachment" in r.headers["content-disposition"]
    linhas = r.text.lstrip("﻿").splitlines()
    assert linhas[0] == ("Nome;CPF;Telefone (WhatsApp);E-mail Google;Tipo de conta;Equipe(s);Líder;"
                         "Situação;1º acesso")
    linha = next(x for x in linhas if "Formula Inventada" in x)
    assert linha.startswith("'=Formula Inventada;")  # não vira fórmula no Excel
    assert "(21) 98765-4321" in linha and "aguardando 1º acesso" in linha
    c = novo_cliente()
    criar_pessoa(db, nome="Sem Painel", email="sem@exemplo.com.br", tipo="cadastro")
    entrar(c, "sem@exemplo.com.br")
    assert c.get("/api/admin/cadastros.csv").status_code == 403
