"""Importação do sistema atual e o pacote de cada pessoa (/api/dados). Exportação inventada, sem dados reais."""
import copy

from .conftest import criar_pessoa, entrar

EXPORTACAO = {
    "gerado_em": "2026-11-08T05:52:00-03:00",
    "evo": {
        "all": {"meses_base": ["2026-05", "2026-11"], "series": {"ALL|equipe": {"base": [10, 12]}}, "visao": "geral"},
        "t": {"PÉ NO CHÃO": {"team": "PÉ NO CHÃO", "visao": "equipe pe no chao"}, "LUA": {"team": "LUA", "visao": "equipe lua"}},
        "e": {"Fulano Inventado": {"esp": "Fulano Inventado", "visao": "do fulano"},
              "Ciclana Inventada": {"esp": "Ciclana Inventada", "visao": "da ciclana"}},
    },
    "especialistas": [
        {"nome": "Fulano Inventado", "sga": ["FULANO DE TAL INVENTADO"], "eqs": ["LUA"],
         "rows": [{"n": "ASSOCIADO UM INVENTADO"}, {"n": "ASSOCIADO DOIS INVENTADO"}]},
        {"nome": "Ciclana Inventada", "sga": [], "eqs": ["PÉ NO CHÃO"], "rows": [{"n": "ASSOCIADO TRES INVENTADO"}]},
    ],
    "motivos": {"m": 1},
    "rtcfg": {"prazos": {}},
    "banco": {"comp": {"regras": {}}, "cancenv": {}},
}


def _importar(admin, exp=None):
    r = admin.post("/api/admin/importar-sistema-atual", json=exp or EXPORTACAO)
    assert r.status_code == 200, r.text
    return r.json()


def test_importar_e_resumo(admin, db):
    criar_pessoa(db, nome="Fulano de Tal Inventado", email="fulano@exemplo.com.br", tipo="especialista", equipe="Lua")
    criar_pessoa(db, nome="Sem Pacote Inventado", email="sem@exemplo.com.br", tipo="especialista", equipe="Elim")
    r = _importar(admin)
    assert (r["importado"], r["meses"], r["especialistas"], r["linhas_remarketing"]) == (True, ["2026-05", "2026-11"], 2, 3)
    assert r["equipes"] == ["LUA", "PE NO CHAO"]
    assert [x["nome"] for x in r["sem_ligacao"]] == ["Sem Pacote Inventado"]  # aparece no painel para corrigir o nome
    assert admin.get("/api/admin/importacao").json()["linhas_remarketing"] == 3
    # importar de novo substitui (não soma)
    menor = copy.deepcopy(EXPORTACAO)
    menor["especialistas"] = menor["especialistas"][:1]
    assert _importar(admin, menor)["linhas_remarketing"] == 2


def test_formato_errado_e_permissao(admin, novo_cliente, db):
    r = admin.post("/api/admin/importar-sistema-atual", json={"evo": {}})
    assert r.status_code == 400 and "evo.all" in r.json()["erro"]
    r = admin.post("/api/admin/importar-sistema-atual", content="não é json", headers={"Content-Type": "application/json"})
    assert r.status_code == 400
    criar_pessoa(db, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
    c = novo_cliente()
    entrar(c, "coord@exemplo.com.br")
    assert c.post("/api/admin/importar-sistema-atual", json=EXPORTACAO).status_code == 403


def test_cada_um_ve_o_seu_pacote(admin, novo_cliente, db):
    _importar(admin)
    pessoas = {
        "geral@exemplo.com.br": ("coordenacao", None, "Coordenacao Inventada"),
        "fin@exemplo.com.br": ("financeiro", None, "Financeiro Inventado"),
        "lider@exemplo.com.br": ("lider", "Pé no Chão", "Lider Inventado"),
        "fulano@exemplo.com.br": ("especialista", "Lua", "Fulano de Tal Inventado"),  # casa pelo nome do SGA
        "ciclana@exemplo.com.br": ("especialista", "Pé no Chão", "Ciclana Inventada"),  # casa pelo nome
        "outro@exemplo.com.br": ("especialista", "Lua", "Outro Inventado"),  # não casa
    }
    for email, (tipo, equipe, nome) in pessoas.items():
        criar_pessoa(db, nome=nome, email=email, tipo=tipo, equipe=equipe)
    vistos = {}
    for email in pessoas:
        c = novo_cliente()
        entrar(c, email)
        vistos[email] = c.get("/api/dados").json()

    geral = vistos["geral@exemplo.com.br"]
    assert geral["pacote"]["visao"] == "geral" and geral["perfil"]["admin"] is True
    assert sorted(len(s["rows"]) for s in geral["specs"]) == [1, 2] and geral["dados_de"] == "2026-11-08T05:52:00-03:00"
    fin = vistos["fin@exemplo.com.br"]
    assert fin["pacote"]["visao"] == "geral" and fin["perfil"]["fin"] is True and fin["specs"] == []
    lider = vistos["lider@exemplo.com.br"]
    assert lider["pacote"]["visao"] == "equipe pe no chao" and [s["nome"] for s in lider["specs"]] == ["Ciclana Inventada"]
    fulano = vistos["fulano@exemplo.com.br"]
    assert fulano["pacote"]["visao"] == "do fulano" and [len(s["rows"]) for s in fulano["specs"]] == [2]
    assert "da ciclana" not in str(fulano) and "ASSOCIADO TRES" not in str(fulano)  # só os dados dele
    assert vistos["ciclana@exemplo.com.br"]["pacote"]["visao"] == "da ciclana"
    outro = vistos["outro@exemplo.com.br"]
    assert outro["pacote"] is None and outro["specs"] == []


def test_dados_exigem_login(cliente):
    assert cliente.get("/api/dados").status_code == 401


def test_banco_de_marcacoes(admin, novo_cliente, db):
    criar_pessoa(db, nome="Especialista Inventado", email="esp@exemplo.com.br", tipo="especialista", equipe="Lua")
    criar_pessoa(db, nome="Financeiro Inventado", email="fin@exemplo.com.br", tipo="financeiro")
    esp, fin = novo_cliente(), novo_cliente()
    entrar(esp, "esp@exemplo.com.br")
    entrar(fin, "fin@exemplo.com.br")
    # "enviados": qualquer pessoa logada grava; atualizar documento que não existe devolve 404 (a página usa o set)
    assert esp.patch("/api/banco/enviados/abc123", json={"c1": 1}).status_code == 404
    assert esp.put("/api/banco/enviados/abc123", json={"c1": 1}).json() == {"ok": True}
    assert esp.patch("/api/banco/enviados/abc123", json={"c2": 2}).json() == {"ok": True}
    assert esp.get("/api/banco/enviados/abc123").json() == {"exists": True, "data": {"c1": 1, "c2": 2}}
    assert fin.get("/api/banco/enviados").json()["docs"] == [{"id": "abc123", "data": {"c1": 1, "c2": 2}}]
    # atualização junta objetos dentro de objetos (prints da reativação: {"p": {chave: print}})
    esp.put("/api/banco/reativ/lider1", json={"p": {"a": {"n": 1}}, "x": 1})
    esp.patch("/api/banco/reativ/lider1", json={"p": {"b": {"n": 2}}})
    assert esp.get("/api/banco/reativ/lider1").json()["data"] == {"p": {"a": {"n": 1}, "b": {"n": 2}}, "x": 1}
    # "comp" (baixas): só administrador, coordenação e financeiro gravam; todos leem
    r = esp.put("/api/banco/comp/2026-11", json={"ABC1D23": {"b": 1}})
    assert r.status_code == 400 and "coordenação e o financeiro" in r.json()["erro"]
    assert fin.put("/api/banco/comp/2026-11", json={"ABC1D23": {"b": 1}}).status_code == 200
    assert esp.get("/api/banco/comp/2026-11").json()["data"] == {"ABC1D23": {"b": 1}}
    # coleção desconhecida, identificador estranho, sem login, sem JSON
    assert esp.get("/api/banco/pessoas").status_code == 400
    assert esp.put("/api/banco/enviados/a b", json={}).status_code == 400
    assert novo_cliente().get("/api/banco/enviados").status_code == 401
    assert esp.put("/api/banco/enviados/x1", content="{}").status_code == 415
    novo = esp.post("/api/banco/cancenv", json={"k": 1}).json()["id"]
    assert esp.get(f"/api/banco/cancenv/{novo}").json()["data"] == {"k": 1}
    assert esp.delete(f"/api/banco/cancenv/{novo}", headers={"Content-Type": "application/json"}).json() == {"ok": True}
    assert esp.get(f"/api/banco/cancenv/{novo}").json()["exists"] is False


def test_importacao_traz_as_marcacoes(admin, db):
    exp = copy.deepcopy(EXPORTACAO)
    exp["banco"] = {"enviados": {"h1": {"c9": 5}}, "comp": {"regras": {"ABC": {"plt": True}}}, "outra": {"x": {}}}
    r = _importar(admin, exp)
    assert r["marcacoes"] == 2  # a coleção desconhecida é ignorada
    assert admin.get("/api/banco/comp/regras").json()["data"] == {"ABC": {"plt": True}}
