"""Conferir veículo no SGA (Painel > Atualizações): poucas chamadas e o diagnóstico das regras da busca.

SGA falso e dados inventados (placas, chassis, nomes e códigos não existem).
"""
from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

import httpx2
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

import app.busca.conferir as cf
from app.atualizacoes import TRAVA_SGA, trava_ativa, travar
from app.busca.completa import TRAVA_BUSCA
from app.dados import guardar
from app.db import Atualizacao
from app.fontes.sga import BASE
from app.main import criar_app

from .conftest import ADMIN, HOST, cfg_teste, criar_pessoa, entrar

CFG = cfg_teste(sga_token="token-inventado", sga_usuario="usuario-inventado", sga_senha="senha-inventada")
HOJE = datetime(2026, 11, 27, 12, 0, tzinfo=timezone.utc)
PLACA = "TST1A23"
CHASSI = "9ZZZZZ00000000001"
LOGIN_OK = httpx2.Response(200, json={"token_usuario": "acesso-inventado"})


def veiculo(**mudancas) -> dict:
    v = {"codigo_veiculo": 900001, "placa": PLACA, "chassi": CHASSI, "data_contrato": "2026-11-03",
         "codigo_situacao": "1", "descricao_situacao": "ATIVO", "nome_voluntario": "ESPECIALISTA INVENTADO",
         "codigo_cooperativa": "2", "data_alteracao": "2026-11-04", "codigo_associado": 700001,
         "modelo": "SCOOTER INVENTADA", "nome": "ASSOCIADO INVENTADO"}
    v.update(mudancas)
    return v


class SGAFalso:
    """Responde por endereço e guarda o que recebeu. `ficha` e `listagem` são as respostas da ficha e da lista."""

    def __init__(self, ficha=None, listagem=None):
        self.ficha = ficha
        self.listagem = listagem
        self.pedidos: list[tuple[str, str, dict | None]] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        caminho = pedido.url.path.removeprefix("/api/sga/v2")
        corpo = json.loads(pedido.content) if pedido.content else None
        self.pedidos.append((pedido.method, caminho, corpo))
        if caminho == "/usuario/autenticar":
            return LOGIN_OK
        if caminho.startswith("/veiculo/buscar/"):
            r = self.ficha
        elif caminho == "/listar/veiculo":
            r = self.listagem
        else:  # pragma: no cover - a conferência não chama mais nada
            raise AssertionError(f"chamada inesperada: {caminho}")
        return r if isinstance(r, httpx2.Response) else httpx2.Response(200, json=r)

    def cliente(self):
        return httpx2.Client(transport=httpx2.MockTransport(self), base_url=BASE)

    def caminhos(self):
        return [c for _m, c, _b in self.pedidos]


@pytest.fixture(autouse=True)
def _relogio(monkeypatch):
    monkeypatch.setattr(cf, "agora", lambda: HOJE)
    monkeypatch.setattr(cf, "INTERVALO", 0.0)


def _dados(db, ades=None):
    guardar(db, "all", {"meses_base": ["2026-09", "2026-10", "2026-11"], "ades": ades or []}, "busca")
    guardar(db, "busca", {"feita_em": "2026-11-27T06:10:00-03:00"}, "busca")
    guardar(db, "esp:ESPECIALISTA INVENTADO", {"nome": "Especialista Inventado", "sga": ["ESPECIALISTA INVENTADO"],
                                              "eqs": ["Lua"]}, "importacao")
    db.commit()


ADE = {"m": "2026-11", "n": "Associado Inventado", "esp": "Especialista Inventado", "t": "LUA", "pl": PLACA,
       "dc": "03/11/2026"}


def _itens(r):
    return {i["item"]: i for i in r["diagnostico"]}


def _conferir(db, falso, busca=PLACA, **kw):
    return cf.conferir_veiculo(db, CFG, busca, http=falso.cliente(), **kw)


def test_veiculo_que_aparece_tudo_ok(db):
    _dados(db, [ADE])
    v = veiculo()
    falso = SGAFalso([v], {"veiculos": [veiculo(nome=None)], "total_veiculos": 1})
    r = _conferir(db, falso)
    assert r["ok"] is True and r["campo"] == "placa"
    assert r["conclusao"] == "Tudo certo: aparece em novembro de 2026, LUA, Especialista Inventado."
    assert all(i["ok"] is True for i in r["diagnostico"]), r["diagnostico"]
    assert {"Data do contrato", "Mês do card de comprovantes", "Vem na listagem por data de contrato", "Situação ativa",
            "Não saiu no mesmo mês", "Equipe (cooperativa)", "Especialista (voluntário)",
            "Está nos dados atuais"} <= set(_itens(r))
    # login + ficha + 1 página da lista do dia do contrato, como a busca completa lê
    assert falso.caminhos() == ["/usuario/autenticar", f"/veiculo/buscar/{PLACA}/placa", "/listar/veiculo"]
    assert falso.pedidos[2][2] == {"data_contrato": "03/11/2026", "data_contrato_final": "03/11/2026",
                                   "quantidade_por_pagina": 100, "inicio_paginacao": 0}
    assert r["chamadas"] == 3
    assert r["sga"]["chassi"] == CHASSI and "nome" not in r["sga"]  # o nome do associado não sai na resposta
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("sga", "conferência", True)
    assert PLACA not in a.mensagem and CHASSI not in a.mensagem and "INVENTAD" not in a.mensagem.upper()
    assert "3 chamada(s)" in a.mensagem


def test_scooter_sem_placa_achada_pelo_chassi_no_pacote(db):
    _dados(db, [dict(ADE, pl="", ch=CHASSI)])
    v = veiculo(placa="")
    r = _conferir(db, SGAFalso([v], {"veiculos": [v], "total_veiculos": 1}), busca=CHASSI.lower())
    assert r["campo"] == "chassi" and r["conclusao"].startswith("Tudo certo: aparece em novembro de 2026")


def test_contrato_antes_de_outubro(db):
    _dados(db)
    v = veiculo(data_contrato="2026-09-15", data_alteracao="2026-09-15")
    r = _conferir(db, SGAFalso([v], {"veiculos": [v], "total_veiculos": 1}))
    assert _itens(r)["Mês do card de comprovantes"]["ok"] is False
    assert r["conclusao"].startswith("Este veículo fica de fora porque o contrato é de setembro de 2026 e o card "
                                     "de comprovantes só mostra a partir de outubro de 2026")


def test_situacao_nao_ativa(db):
    _dados(db)
    v = veiculo(codigo_situacao="3", descricao_situacao="INADIMPLENTE")
    r = _conferir(db, SGAFalso([v], {"veiculos": [v], "total_veiculos": 1}))
    item = _itens(r)["Situação ativa"]
    assert item["ok"] is False and "INADIMPLENTE" in item["texto"]
    assert "fica de fora porque a situação é INADIMPLENTE" in r["conclusao"]


def test_cancelado_no_mesmo_mes(db):
    _dados(db)
    v = veiculo(codigo_situacao="6", descricao_situacao="CANCELADO", data_alteracao="2026-11-20")
    r = _conferir(db, SGAFalso([v], {"veiculos": [v], "total_veiculos": 1}))
    assert _itens(r)["Não saiu no mesmo mês"]["ok"] is False


def test_cooperativa_desconhecida(db):
    _dados(db)
    v = veiculo(codigo_cooperativa="42")
    r = _conferir(db, SGAFalso([v], {"veiculos": [v], "total_veiculos": 1}))
    item = _itens(r)["Equipe (cooperativa)"]
    assert item["ok"] is False and "42" in item["texto"]
    assert "fica de fora porque a cooperativa 42 não é de nenhuma equipe" in r["conclusao"]


def test_nao_vem_na_listagem_por_data(db):
    """O caso a investigar: a ficha está certa (ativo, Lua, contrato de novembro), mas a lista do dia não traz."""
    _dados(db)
    outros = [veiculo(codigo_veiculo=900002, placa="TST2B34"), veiculo(codigo_veiculo=900003, placa="TST3C45")]
    falso = SGAFalso([veiculo()], {"veiculos": outros, "total_veiculos": 2})
    r = _conferir(db, falso)
    itens = _itens(r)
    assert itens["Vem na listagem por data de contrato"]["ok"] is False
    assert [i for i, x in itens.items() if x["ok"] is False] == ["Vem na listagem por data de contrato",
                                                                  "Está nos dados atuais"]
    assert r["conclusao"].startswith("Este veículo fica de fora porque o SGA não devolve este veículo na listagem "
                                     "por data de contrato de 03/11/2026")
    assert r["listagem"] is None and r["sga"]["codigo_veiculo"] == 900001
    a = db.scalars(select(Atualizacao)).one()
    assert "Vem na listagem por data de contrato" in a.mensagem and PLACA not in a.mensagem


def test_lista_com_mais_de_uma_pagina_nao_afirma(db):
    _dados(db)
    falso = SGAFalso([veiculo()], {"veiculos": [veiculo(codigo_veiculo=900002)], "total_veiculos": 250})
    r = _conferir(db, falso)
    assert _itens(r)["Vem na listagem por data de contrato"]["ok"] is None
    assert falso.caminhos().count("/listar/veiculo") == 1  # uma página só


def test_cadastro_diferente_na_listagem_vale_o_da_listagem(db):
    """A busca completa usa o registro da lista por data: se a cooperativa lá for outra, vale a de lá."""
    _dados(db)
    falso = SGAFalso([veiculo()], {"veiculos": [veiculo(codigo_cooperativa="")], "total_veiculos": 1})
    r = _conferir(db, falso)
    assert r["sga"]["codigo_cooperativa"] == "2" and r["listagem"]["codigo_cooperativa"] == ""
    assert _itens(r)["Equipe (cooperativa)"]["ok"] is False


def test_busca_por_chassi_nao_aceita_pelo_sga(db):
    _dados(db)
    falso = SGAFalso(httpx2.Response(400, json={"mensagem": "campo inválido"}))
    r = _conferir(db, falso, busca=CHASSI)
    assert r["ok"] is True and r["sga"] is None and r["diagnostico"] == []
    assert any("não aceitou a busca por chassi" in a and "código 400" in a for a in r["avisos"])
    assert "inválido" not in json.dumps(r, ensure_ascii=False)  # não repete o texto do SGA
    assert falso.caminhos() == ["/usuario/autenticar", f"/veiculo/buscar/{CHASSI}/chassi"]  # sem novas tentativas
    assert r["conclusao"] == "O SGA não devolveu nenhum veículo para essa busca."


def test_chassi_nao_aceito_com_a_data_procura_na_lista_do_dia(db):
    _dados(db)
    v = veiculo(placa="")
    falso = SGAFalso(httpx2.Response(404, text="Veículo não encontrado"), {"veiculos": [v], "total_veiculos": 1})
    r = _conferir(db, falso, busca=CHASSI, data="2026-11-03")
    assert any("não achou nenhum veículo" in a for a in r["avisos"])
    assert any("achado na listagem de 03/11/2026" in a for a in r["avisos"])
    assert r["listagem"]["codigo_veiculo"] == 900001 and r["chamadas"] == 3
    assert _itens(r)["Vem na listagem por data de contrato"]["ok"] is True


def test_busca_invalida(admin, app):
    app.state.cfg = CFG
    r = admin.post("/api/admin/conferir-veiculo", json={"busca": "abc"})
    assert r.status_code == 400 and "placa" in r.json()["erro"]


def test_bloqueado_pausa_o_sga(db):
    _dados(db)
    falso = SGAFalso(httpx2.Response(403, text="Token BLOQUEADO"))
    falso_login = SGAFalso()
    # o login do SGA falso aceita a 1ª vez e recusa a conferência do bloqueio: é bloqueio de verdade
    logins = iter([LOGIN_OK, httpx2.Response(403, text="BLOQUEADO")])

    def responder(pedido):
        if pedido.url.path.endswith("/usuario/autenticar"):
            falso_login.pedidos.append(pedido)
            return next(logins)
        return falso(pedido)

    http = httpx2.Client(transport=httpx2.MockTransport(responder), base_url=BASE)
    r = cf.conferir_veiculo(db, CFG, PLACA, http=http)
    assert r["ok"] is False and "pausado até" in r["mensagem"]
    assert trava_ativa(db, TRAVA_SGA) is not None
    a = db.scalars(select(Atualizacao)).one()
    assert (a.tipo, a.ok) == ("conferência", False)


def test_sga_pausado_ou_busca_rodando_nao_chama(db):
    _dados(db)
    falso = SGAFalso([veiculo()], {"veiculos": [], "total_veiculos": 0})
    travar(db, TRAVA_BUSCA, datetime.now(timezone.utc) + timedelta(hours=1), "busca completa em andamento")
    r = _conferir(db, falso)
    assert r["ok"] is False and "busca completa está rodando" in r["mensagem"]
    travar(db, TRAVA_SGA, datetime.now(timezone.utc) + timedelta(hours=1), "o SGA respondeu BLOQUEADO no login")
    r = _conferir(db, falso)
    assert r["ok"] is False and "SGA pausado até" in r["mensagem"] and "Nada foi consultado" in r["mensagem"]
    assert falso.pedidos == [] and db.scalars(select(Atualizacao)).all() == []


def test_rota_do_administrador(admin, app, db):
    _dados(db, [ADE])
    app.state.cfg = CFG
    falso = SGAFalso([veiculo()], {"veiculos": [veiculo()], "total_veiculos": 1})
    app.state.http_sga = falso.cliente()
    try:
        r = admin.post("/api/admin/conferir-veiculo", json={"busca": "tst-1a23"}).json()
    finally:
        del app.state.http_sga
    assert r["ok"] is True and r["campo"] == "placa" and r["conclusao"].startswith("Tudo certo")
    assert len(falso.pedidos) == 3


def test_rota_com_sga_pausado_nao_chama(admin, app, db):
    app.state.cfg = CFG
    travar(db, TRAVA_SGA, datetime.now(timezone.utc) + timedelta(hours=1), "o SGA respondeu BLOQUEADO no login")
    falso = SGAFalso()
    app.state.http_sga = falso.cliente()
    try:
        r = admin.post("/api/admin/conferir-veiculo", json={"busca": PLACA}).json()
    finally:
        del app.state.http_sga
    assert r["ok"] is False and "SGA pausado" in r["mensagem"] and falso.pedidos == []


def test_so_o_administrador_confere():
    app = criar_app(cfg_teste(painel_coordenacao=True, sga_token="t", sga_usuario="u", sga_senha="s"))
    with TestClient(app, base_url=f"https://{HOST}") as adm, TestClient(app, base_url=f"https://{HOST}") as c, \
            TestClient(app, base_url=f"https://{HOST}") as e:
        entrar(adm, ADMIN)
        with app.state.Sessao() as s:
            criar_pessoa(s, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
            criar_pessoa(s, nome="Especialista Inventado", email="esp@exemplo.com.br", tipo="especialista")
        falso = SGAFalso()
        app.state.http_sga = falso.cliente()
        entrar(c, "coord@exemplo.com.br")
        r = c.post("/api/admin/conferir-veiculo", json={"busca": PLACA})
        assert r.status_code == 403 and "Só o administrador" in r.json()["erro"]
        entrar(e, "esp@exemplo.com.br")
        assert e.post("/api/admin/conferir-veiculo", json={"busca": PLACA}).status_code == 403
        assert falso.pedidos == []


def test_regras_iguais_as_do_script():
    """As cópias de COOP, ACT_S, SAIU e COMP_DESDE têm de continuar iguais às de app/busca/retorno.py."""
    fonte = (Path(cf.__file__).parent / "retorno.py").read_text(encoding="utf-8")

    def valor(nome):
        m = re.search(rf"^\s+{nome} = (.+?)(?:\s+#.*)?$", fonte, re.M)
        assert m, nome
        return eval(m.group(1), {})  # noqa: S307 - literal do próprio repositório

    assert valor("COOP") == cf.COOP
    assert valor("ACT_S") == cf.ACT_S
    assert valor("SAIU") == cf.SAIU
    assert valor("COMP_DESDE") == cf.COMP_DESDE
    assert f'k < "{cf.REGRA_ATIVA_DESDE}" or sit_fim(x, k) in ACT_S' in fonte
