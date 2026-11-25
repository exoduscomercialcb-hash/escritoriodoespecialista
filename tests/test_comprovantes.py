"""Comprovantes de adesão lidos do Drive (Google simulado; placas, nomes e ids inventados)."""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import httpx2
from sqlalchemy import select

import app.comprovantes as cp
from app.atualizacoes import travar
from app.busca.completa import TRAVA_BUSCA
from app.dados import guardar, ler
from app.db import Atualizacao, Documento, Pacote

from .conftest import cfg_teste, criar_pessoa, entrar
from .test_google import CHAVE

RAIZ = "pasta-comp-inventada"
CFG = cfg_teste(google_service_account_json=CHAVE, drive_pasta_comprovantes=RAIZ)
SP = timezone(timedelta(hours=-3))
PASTAS = [{"id": "pasta-mes-inventada", "parents": [RAIZ]},
          {"id": "pasta-equipe-inventada", "parents": ["pasta-mes-inventada"]},
          {"id": "pasta-esp-inventada", "parents": ["pasta-equipe-inventada"]},
          {"id": "pasta-print-inventada", "parents": ["pasta-prints-inventada"]}]


def arq(n: int, desc, pasta: str = "pasta-esp-inventada", criado: str = "2026-11-10T12:00:00.000Z") -> dict:
    return {"id": f"arquivo-inventado-{n:02d}", "name": f"comprovante-{n}.jpg", "createdTime": criado,
            "description": desc if isinstance(desc, str) else json.dumps(desc),
            "webViewLink": f"https://drive.google.com/file/d/arquivo-inventado-{n:02d}/view", "parents": [pasta]}


def desc(**campos) -> dict:
    base = {"placa": "ABC-1D23", "mes": "2026-11", "equipe": "Lua", "especialista": "Especialista Inventado",
            "associado": "Associado Inventado", "valor": "150,00", "lider": "Lider Inventado",
            "enviado": "2026-11-10T12:00:00.000Z"}
    base.update(campos)
    return {k: v for k, v in base.items() if v is not None}


class DriveFalso:
    def __init__(self, arquivos, erro: httpx2.Response | None = None, durante=None):
        self.arquivos, self.erro, self.durante = arquivos, erro, durante
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(pedido)
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "acesso-inventado", "expires_in": 3600})
        if self.erro is not None:
            return self.erro
        q = pedido.url.params.get("q", "")
        if "fullText contains 'placa'" in q:
            if self.durante:
                self.durante()
            return httpx2.Response(200, json={"files": self.arquivos})
        return httpx2.Response(200, json={"files": PASTAS})

    def cliente(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))


def _google(arquivos):
    from app.fontes.google import ClienteGoogle
    return ClienteGoogle(CHAVE, http=DriveFalso(arquivos).cliente())


def _pacotes(db):
    def ades():
        return [{"m": "2026-11", "n": "Associado Inventado", "pl": "ABC-1D23", "dc": "05/11/2026"},
                {"m": "2026-11", "n": "Associado Inventado Dois", "pl": "", "ch": "CHASSIINVENTADO01",
                 "dc": "06/11/2026"},
                {"m": "2026-09", "n": "Associado Inventado Tres", "pl": "ABC1D23", "dc": "05/09/2026"}]
    guardar(db, "all", {"meses_base": ["2026-11"], "ades": ades()}, "importacao")
    guardar(db, "t:LUA", {"ades": ades()}, "busca")
    guardar(db, "e:ESPECIALISTA INVENTADO", {"ades": ades()}, "importacao")
    db.commit()


def test_descricao_valida_vira_item_e_o_que_nao_e_comprovante_e_ignorado():
    arquivos = [arq(1, desc()),
                arq(2, {"mes": "2026-11", "equipe": "Lua", "obs": "print do WhatsApp"}),  # sem placa nem chassi
                arq(3, "placa do carro no print"),  # descrição que não é JSON
                arq(4, desc(mes=None)),  # sem mês
                arq(5, desc(placa=None, chassi="chassiinventado01", mes="Novembro/2026", valor=99.9)),
                arq(6, desc(), pasta="pasta-print-inventada")]  # pasta dos prints de reativação: não é comprovante
    itens = cp.ler_do_drive(_google(arquivos), RAIZ)
    assert [i["url"].split("/")[5] for i in itens] == ["arquivo-inventado-01", "arquivo-inventado-05"]
    um, cinco = itens
    assert um == {"mes": "2026-11", "pl": "ABC1D23", "ch": "", "eq": "Lua", "esp": "Especialista Inventado",
                  "vi": 150.0, "valor": 150.0, "url": "https://drive.google.com/file/d/arquivo-inventado-01/view",
                  "enviado": "2026-11-10T12:00:00.000Z", "conferido": None, "arquivo": "comprovante-1.jpg"}
    assert (cinco["pl"], cinco["ch"], cinco["mes"], cinco["vi"]) == ("", "CHASSIINVENTADO01", "2026-11", 99.9)
    # sem a pasta, vale o que a consulta trouxe (o print de reativação com placa entraria)
    assert len(cp.ler_do_drive(_google(arquivos))) == 3


def test_mes_e_valor_da_descricao():
    assert [cp._mes(x) for x in ("2026-11", "11/2026", "Novembro/2026", "novembro de 2026", "nov 26", "x", "")] == \
        ["2026-11"] * 5 + [None, None]
    assert [cp._valor(x) for x in (150, "150", "150.5", "R$ 1.234,56", "", None, "abc")] == \
        [150.0, 150.0, 150.5, 1234.56, None, None, None]


def test_valor_lido_da_compconf_vence_o_informado(db):
    itens = cp.ler_do_drive(_google([arq(1, desc()), arq(2, desc(placa="DEF2G34"))]), RAIZ)
    db.add(Documento(colecao="compconf", doc_id="2026-11-ABC1D23-2026-11-10T12:00:00.000Z",
                     dados=json.dumps({"lido": "140,00", "conferido": False})))
    # sem compconf: vem do registro anterior (importação), casando pelo arquivo
    guardar(db, "comp_registro", [{"mes": "2026-11", "pl": "DEF2G34", "valor": 145, "vi": 150, "conferido": True,
                                   "url": "https://drive.google.com/open?id=arquivo-inventado-02",
                                   "enviado": "2026-11-10T12:00:00.000Z"},
                                  {"mes": "2026-10", "pl": "GHI3J45", "valor": 80, "vi": 80,
                                   "url": "https://drive.google.com/file/d/arquivo-inventado-99/view",
                                   "enviado": "2026-10-02T10:00:00.000Z"}], "importacao")
    db.commit()
    reg = {c["pl"]: c for c in cp.montar_registro(db, itens)}
    assert (reg["ABC1D23"]["valor"], reg["ABC1D23"]["vi"], reg["ABC1D23"]["conferido"]) == (140.0, 150.0, False)
    assert (reg["DEF2G34"]["valor"], reg["DEF2G34"]["conferido"]) == (145, True)
    assert reg["DEF2G34"]["url"].endswith("/d/arquivo-inventado-02/view")  # o do Drive substitui o anterior
    assert reg["GHI3J45"]["valor"] == 80  # o que já estava no registro e não veio do Drive fica
    assert len(reg) == 3


def test_leitura_completa_aplica_nos_pacotes(app, db):
    _pacotes(db)
    db.add(Documento(colecao="comp", doc_id="2026-11", dados=json.dumps({"ABC1D23": {"pg": True, "pgby": "Fin"}})))
    db.add(Documento(colecao="comp", doc_id="regras", dados=json.dumps({"CHASSIINVENTADO01": {"nc": True}})))
    db.commit()
    arquivos = [arq(1, desc(valor="150,00")),
                arq(2, desc(valor="155,00", enviado="2026-11-12T09:00:00.000Z"), criado="2026-11-12T09:00:00.000Z"),
                arq(3, desc(placa="", chassi="CHASSIINVENTADO01", valor="120,00"))]
    falso = DriveFalso(arquivos)
    r = cp.atualizar_comprovantes(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is True, r
    assert "3 lido(s)" in r["mensagem"] and "(atualizado)" in r["mensagem"] and "6 adesão(ões)" in r["mensagem"]
    db.expire_all()
    for chave in ("all", "t:LUA", "e:ESPECIALISTA INVENTADO"):
        placa, chassi, setembro = ler(db, chave)["ades"]
        # o mais recente do mês vence
        assert placa["cp"] == {"v": 155.0, "url": "https://drive.google.com/file/d/arquivo-inventado-02/view",
                               "at": "2026-11-12T09:00:00.000Z", "vc": None, "vi": 155.0}, chave
        assert placa["mk"] == {"pg": True, "pgby": "Fin"}
        # sem placa: casa pelo chassi
        assert chassi["cp"]["v"] == 120.0 and chassi["mk"] == {"nc": True}
        assert "cp" not in setembro and "mk" not in setembro  # antes de out/26 não muda
    assert {p.chave: p.origem for p in db.scalars(select(Pacote).where(Pacote.chave.in_(["all", "t:LUA"])))} == \
        {"all": "importacao", "t:LUA": "busca"}  # a origem do pacote não muda
    assert db.get(Pacote, "comp_registro").origem == "drive" and len(ler(db, "comp_registro")) == 3
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("drive", "comprovantes", True)
    # de novo, sem nada novo: não grava nada
    r = cp.atualizar_comprovantes(app.state.Sessao, CFG, http=DriveFalso(arquivos).cliente())
    assert r["ok"] is True and "(sem mudança)" in r["mensagem"] and "0 adesão(ões)" in r["mensagem"]


def test_erro_do_google_nao_mexe_em_nada(app, db):
    _pacotes(db)
    guardar(db, "comp_registro", [{"mes": "2026-11", "pl": "ABC1D23", "valor": 1}], "importacao")
    db.commit()
    antes = {p.chave: p.dados for p in db.scalars(select(Pacote))}
    falso = DriveFalso([arq(1, desc())], erro=httpx2.Response(500, text="detalhe-cru-inventado"))
    r = cp.atualizar_comprovantes(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is False and r["mensagem"].startswith("Google:") and "Nada foi gravado" in r["mensagem"]
    assert "detalhe-cru-inventado" not in r["mensagem"]
    db.expire_all()
    assert {p.chave: p.dados for p in db.scalars(select(Pacote))} == antes
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("drive", "comprovantes", False) and "detalhe-cru" not in a.mensagem


def test_nao_roda_com_a_busca_rodando(app, db):
    _pacotes(db)
    travar(db, TRAVA_BUSCA, datetime.now(timezone.utc) + timedelta(hours=1), "busca completa em andamento")
    falso = DriveFalso([arq(1, desc())])
    r = cp.atualizar_comprovantes(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is False and "busca completa está rodando" in r["mensagem"]
    assert falso.pedidos == [] and db.scalars(select(Atualizacao)).first() is None
    assert "cp" not in ler(db, "all")["ades"][0]


def test_busca_que_comeca_durante_a_leitura_nao_e_sobrescrita(app, db):
    _pacotes(db)

    def busca_comecou():
        with app.state.Sessao() as outra:
            travar(outra, TRAVA_BUSCA, datetime.now(timezone.utc) + timedelta(hours=1), "busca completa em andamento")

    r = cp.atualizar_comprovantes(app.state.Sessao, CFG, http=DriveFalso([arq(1, desc())], durante=busca_comecou)
                                  .cliente())
    assert r["ok"] is False and "Nada foi gravado" in r["mensagem"]
    db.expire_all()
    assert ler(db, "comp_registro") is None and "cp" not in ler(db, "all")["ades"][0]


def test_sem_chave_ou_sem_pasta_explica(app, db):
    r = cp.atualizar_comprovantes(app.state.Sessao, cfg_teste())
    assert r["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["mensagem"]
    r = cp.atualizar_comprovantes(app.state.Sessao, cfg_teste(google_service_account_json=CHAVE))
    assert r["ok"] is False and "DRIVE_PASTA_COMPROVANTES" in r["mensagem"]


def test_horarios_do_agendador(db):
    assert cp.ultimo_horario_comprovantes(datetime(2026, 11, 9, 7, 30, tzinfo=SP)) == \
        datetime(2026, 11, 9, 7, 25, tzinfo=SP)
    assert cp.ultimo_horario_comprovantes(datetime(2026, 11, 9, 16, 50, tzinfo=SP)) == \
        datetime(2026, 11, 9, 15, 25, tzinfo=SP)  # 16:25 não tem (a busca completa é às 16:00)
    assert cp.ultimo_horario_comprovantes(datetime(2026, 11, 9, 6, 0, tzinfo=SP)) == \
        datetime(2026, 11, 8, 22, 25, tzinfo=SP)
    assert cp.leitura_devida(db, datetime(2026, 11, 9, 7, 26, tzinfo=SP)) is True
    assert cp.leitura_devida(db, datetime(2026, 11, 9, 7, 20, tzinfo=SP)) is False  # 06:00 a 07:25: nada
    assert cp.leitura_devida(db, datetime(2026, 11, 9, 16, 50, tzinfo=SP)) is False  # 15:25 já passou da janela
    db.add(Atualizacao(fonte="drive", tipo="comprovantes", inicio=datetime(2026, 11, 9, 10, 26, tzinfo=timezone.utc)))
    db.commit()
    assert cp.leitura_devida(db, datetime(2026, 11, 9, 7, 40, tzinfo=SP)) is False  # já leu depois das 07:25
    assert cp.leitura_devida(db, datetime(2026, 11, 9, 8, 25, tzinfo=SP)) is True


def test_botao_so_para_o_administrador(admin, novo_cliente, db):
    criar_pessoa(db, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
    c = novo_cliente()
    entrar(c, "coord@exemplo.com.br")
    assert c.post("/api/admin/atualizacoes/comprovantes", json={}).status_code == 403
    assert admin.post("/api/admin/atualizacoes/comprovantes", content="x").status_code == 415
    r = admin.post("/api/admin/atualizacoes/comprovantes", json={}).json()
    assert r["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["mensagem"]  # app de teste: sem a chave
    assert admin.get("/api/admin/atualizacoes").json()["comprovantes_automatico"] is False
    assert "Ler comprovantes agora" in admin.get("/static/escritorio.html").text
