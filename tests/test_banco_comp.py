"""Documento do mês em "comp" (comprovante de adesões): o caminho que a página faz desde 12/11.

A página só grava o campo que mudou (update); se o documento do mês ainda não existe, cria com set na primeira
marcação. Nunca regrava o documento inteiro. Só administrador, coordenação e financeiro gravam em "comp".
"""
from .conftest import criar_pessoa, entrar


def test_primeira_marcacao_cria_o_documento_do_mes_sem_apagar_o_dos_outros(admin, novo_cliente, db):
    criar_pessoa(db, nome="Financeiro Inventado", email="fin@exemplo.com.br", tipo="financeiro")
    criar_pessoa(db, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
    criar_pessoa(db, nome="Cadastro Inventado", email="cad@exemplo.com.br", tipo="cadastro")
    criar_pessoa(db, nome="Lider Inventado", email="lider@exemplo.com.br", tipo="lider", equipe="Lua")
    fin, coord, cad, lider = (novo_cliente() for _ in range(4))
    for c, email in ((fin, "fin@exemplo.com.br"), (coord, "coord@exemplo.com.br"), (cad, "cad@exemplo.com.br"),
                     (lider, "lider@exemplo.com.br")):
        entrar(c, email)
    assert admin.put("/api/banco/comp/regras", json={"TST1A01": {"nc": True}}).status_code == 200

    # a lista da coleção diz quais documentos existem (a página guarda os ids para saber se cria ou atualiza)
    assert [d["id"] for d in fin.get("/api/banco/comp").json()["docs"]] == ["regras"]
    assert fin.get("/api/banco/comp/2026-11").json() == {"exists": False, "data": None}
    assert fin.patch("/api/banco/comp/2026-11", json={"TST2B01": {"pg": 150}}).status_code == 404  # "not-found"
    assert fin.put("/api/banco/comp/2026-11", json={"TST2B01": {"pg": 150, "pgl": "avulso"}}).status_code == 200
    assert [d["id"] for d in fin.get("/api/banco/comp").json()["docs"]] == ["2026-11", "regras"]

    # depois de criado, cada um atualiza só a sua adesão e o resto do mês fica
    assert coord.patch("/api/banco/comp/2026-11", json={"TST2B02": {"ok": True}}).status_code == 200
    assert fin.patch("/api/banco/comp/2026-11", json={"TST2B01": {"pg": 200}}).status_code == 200
    assert fin.get("/api/banco/comp/2026-11").json()["data"] == {"TST2B01": {"pg": 200, "pgl": "avulso"},
                                                                 "TST2B02": {"ok": True}}

    # cadastro (vê tudo na página) e líder não gravam em "comp", nem criando o documento do mês
    for c in (cad, lider):
        assert c.put("/api/banco/comp/2026-12", json={"X": {"pg": 1}}).status_code == 400
        assert c.patch("/api/banco/comp/2026-11", json={"X": {"pg": 1}}).status_code == 400
    assert lider.get("/api/banco/comp/2026-12").json()["exists"] is False
