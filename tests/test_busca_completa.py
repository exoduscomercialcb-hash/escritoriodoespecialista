"""A busca completa: travas, gravação dos pacotes e agendador (script e fontes falsos; dados inventados)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

from sqlalchemy import select

import app.atualizacoes as atu
import app.busca.completa as bc
from app.busca.entrada import ErroBusca, Saida
from app.dados import guardar, ler
from app.db import Atualizacao, Documento
from app.fontes.sga import SGABloqueado

from .conftest import cfg_teste

CFG = cfg_teste(sga_token="token-inventado", sga_usuario="usuario-inventado", sga_senha="senha-inventada")
SP = timezone(timedelta(hours=-3))
CLIENTES = (object(), None, object())  # nada sai da máquina: o script falso não chama ninguém


def _importado(db):
    guardar(db, "all", {"meses_base": ["2026-10"], "base": 1}, "importacao")
    guardar(db, "t:LUA", {"velho": True}, "importacao")
    guardar(db, "esp:FULANO INVENTADO", {"id": 7, "nome": "Fulano Inventado", "sga": ["FULANO INVENTADO"],
                                         "eqs": ["Lua"]}, "importacao")
    guardar(db, "rm:FULANO INVENTADO", [{"placa": "ABC1D23"}], "importacao")
    guardar(db, "comp_registro", [{"placa": "ABC1D23"}], "importacao")
    db.add(Documento(colecao="comp", doc_id="regras", dados='{"ABC1D23": {"val": true}}'))
    db.commit()


def _ultima(db):
    return db.scalars(select(Atualizacao).order_by(Atualizacao.id.desc())).first()


def test_sem_importacao_ou_sem_acessos_nao_roda(app, db):
    r = bc.busca_completa(app.state.Sessao, cfg_teste(), rodar=lambda e: None, clientes=CLIENTES)
    assert r["ok"] is False and "SGA_TOKEN" in r["mensagem"]
    r = bc.busca_completa(app.state.Sessao, CFG, rodar=lambda e: None, clientes=CLIENTES)
    assert r["ok"] is False and "não foram importados" in r["mensagem"]
    assert db.scalars(select(Atualizacao)).all() == []


def test_busca_grava_os_pacotes_e_entrega_a_entrada_certa(app, db):
    _importado(db)
    visto = {}

    def rodar(entrada):
        visto["e"] = entrada
        return Saida(pacotes={"all": {"meses_base": ["2026-11"]}, "t:ELITE": {"novo": 1}, "e:FULANO INVENTADO": {"x": 1}},
                     novos_cancelados={"ELITE": [1]}, resumo={"base_hoje": 42, "cancelados_recentes": 3})

    r = bc.busca_completa(app.state.Sessao, CFG, rodar=rodar, clientes=CLIENTES)
    assert r["ok"] is True and "3 pacote(s)" in r["mensagem"] and "base ativa hoje 42" in r["mensagem"]
    e = visto["e"]
    assert e.old["base"] == 1 and e.especialistas[0]["id"] == 7
    assert e.listas == {"Fulano Inventado": [{"placa": "ABC1D23"}]}
    assert e.comp_marks == {"regras": {"ABC1D23": {"val": True}}} and e.comp_registro == [{"placa": "ABC1D23"}]
    assert e.agora.utcoffset() == timedelta(hours=-3)
    db.expire_all()
    assert ler(db, "all") == {"meses_base": ["2026-11"]} and ler(db, "t:ELITE") == {"novo": 1}
    assert ler(db, "t:LUA") == {"velho": True}  # o que veio da importação e a busca não gerou continua
    assert ler(db, "novos_cancelados") == {"ELITE": [1]} and ler(db, "busca")["resumo"]["base_hoje"] == 42
    assert atu.trava_ativa(db, bc.TRAVA_BUSCA) is None  # a trava de "uma de cada vez" foi solta
    a = _ultima(db)
    assert (a.fonte, a.tipo, a.ok) == ("sga", "agendada", True)

    # a segunda busca apaga o pacote que a primeira gerou e a segunda não gerou mais
    r = bc.busca_completa(app.state.Sessao, CFG, rodar=lambda e: Saida(pacotes={"all": {"m": 2}}), clientes=CLIENTES)
    db.expire_all()
    assert r["ok"] and ler(db, "t:ELITE") is None and ler(db, "t:LUA") == {"velho": True}


def test_bloqueio_do_sga_pausa_e_nao_grava_nada(app, db):
    _importado(db)

    def rodar(entrada):
        raise SGABloqueado("O SGA respondeu BLOQUEADO")

    r = bc.busca_completa(app.state.Sessao, CFG, rodar=rodar, clientes=CLIENTES)
    assert r["ok"] is False and "BLOQUEADO" in r["mensagem"] and "pausado até" in r["mensagem"]
    db.expire_all()
    assert atu.trava_ativa(db, atu.TRAVA_SGA) is not None and ler(db, "all") == {"meses_base": ["2026-10"], "base": 1}
    assert atu.trava_ativa(db, bc.TRAVA_BUSCA) is None
    # pausado: a próxima nem começa
    chamou = []
    r = bc.busca_completa(app.state.Sessao, CFG, rodar=lambda e: chamou.append(1), clientes=CLIENTES)
    assert r["ok"] is False and "pausado" in r["mensagem"] and chamou == []


def test_erros_nao_gravam_e_nao_vazam_texto(app, db):
    _importado(db)

    def quebra(entrada):
        raise ValueError("CPF 000.000.000-00 do associado")  # o texto de um erro inesperado pode ter dados

    r = bc.busca_completa(app.state.Sessao, CFG, rodar=quebra, clientes=CLIENTES)
    assert r["ok"] is False and "ValueError" in r["mensagem"] and "CPF" not in r["mensagem"]
    assert "CPF" not in _ultima(db).mensagem

    def para(entrada):
        raise ErroBusca("base ativa veio vazia")

    r = bc.busca_completa(app.state.Sessao, CFG, rodar=para, clientes=CLIENTES)
    assert r["ok"] is False and "base ativa veio vazia" in r["mensagem"]
    r = bc.busca_completa(app.state.Sessao, CFG, rodar=lambda e: Saida(pacotes={}), clientes=CLIENTES)
    assert r["ok"] is False and "sem o pacote geral" in r["mensagem"]
    db.expire_all()
    assert ler(db, "all")["base"] == 1


def test_uma_busca_de_cada_vez(app, db):
    _importado(db)
    atu.travar(db, bc.TRAVA_BUSCA, datetime.now(timezone.utc) + timedelta(hours=1), "teste")
    r = bc.busca_completa(app.state.Sessao, CFG, rodar=lambda e: None, clientes=CLIENTES)
    assert r["ok"] is False and "Já tem uma busca rodando" in r["mensagem"]


def test_horario_do_agendador(app, db):
    assert bc.ultimo_horario_sga(datetime(2026, 11, 9, 4, 0, tzinfo=SP)) == datetime(2026, 11, 9, 6, 52, tzinfo=timezone.utc)
    assert bc.ultimo_horario_sga(datetime(2026, 11, 9, 3, 0, tzinfo=SP)) == datetime(2026, 11, 8, 6, 52, tzinfo=timezone.utc)
    assert bc.busca_devida(db, datetime(2026, 11, 9, 4, 30, tzinfo=SP)) is True
    assert bc.busca_devida(db, datetime(2026, 11, 9, 10, 0, tzinfo=SP)) is False  # de dia não roda (sistema atual)
    db.add(Atualizacao(fonte="sga", tipo="agendada", inicio=datetime(2026, 11, 9, 6, 55, tzinfo=timezone.utc)))
    db.commit()
    assert bc.busca_devida(db, datetime(2026, 11, 9, 4, 30, tzinfo=SP)) is False  # já rodou depois das 03:52


def test_botao_do_painel(admin, novo_cliente, db, app):
    r = admin.post("/api/admin/atualizacoes/busca", json={}).json()
    assert r["ok"] is False and "SGA_TOKEN" in r["mensagem"]  # app de teste: sem acessos do SGA
    assert admin.get("/api/admin/atualizacoes").json()["busca_automatica"] is False


def test_importacao_apaga_o_que_a_busca_gravou(admin, db):
    guardar(db, "t:SUMIU", {"x": 1}, "busca")
    guardar(db, "busca", {"feita_em": "2026-11-09T07:00:00+00:00"}, "busca")
    db.commit()
    exp = {"gerado_em": "2026-11-09 10:00", "evo": {"all": {"meses_base": ["2026-11"]}, "t": {}, "e": {}},
           "especialistas": []}
    assert admin.post("/api/admin/importar-sistema-atual", json=exp).status_code == 200
    db.expire_all()
    assert ler(db, "t:SUMIU") is None and ler(db, "busca") is None
