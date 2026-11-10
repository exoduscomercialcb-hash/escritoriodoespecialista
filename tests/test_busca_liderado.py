"""Regra do liderado (09/11) e plantão sem placa, portados do sistema atual. Todos os dados são inventados."""
from __future__ import annotations

import copy

import pytest

import app.busca.completa as bc
from app.busca.entrada import Saida
from app.busca.liderado import aplicar
from app.busca.retorno import rodar
from app.dados import guardar, ler

from .test_busca_completa import CFG, CLIENTES, _importado
from .test_busca_retorno import entrada, old_minimo

AM = ["2026-08", "2026-09", "2026-10"]
LIDER = "Lider Inventado Lua"
LIDERADO = "Liderado Inventado Silva"


def z(n=3):
    return [0] * n


def pacote_geral():
    """Equipe LUA: 2 adesões de out/26 no nome do líder no SGA (uma validada) e 1 de ago/26 (antes da regra)."""
    ades = [
        {"m": "2026-10", "t": "LUA", "esp": LIDER, "pl": "ZZZ1A01", "ok": True},
        {"m": "2026-10", "t": "LUA", "esp": LIDER, "pl": "", "ch": "CHASSIINVENTADO02", "ok": False},
        {"m": "2026-08", "t": "LUA", "esp": LIDER, "pl": "ZZZ1A03", "ok": True},
        {"m": "2026-10", "t": "LUA", "esp": LIDER, "pl": "ZZZ1A04", "ok": True},  # afiliado com o mesmo nome do líder
    ]
    return {"meses_base": AM, "meses_ad": AM, "val_ate": 2, "leaders": {"LUA": LIDER}, "ades": ades,
            "series": {"LUA|equipe": {"base": [5, 5, 5], "ad": [1, 0, 3], "va": [1, 0, 2]},
                       "LUA|propria": {"base": [5, 5, 5], "ad": [1, 0, 3], "va": [1, 0, 2]},
                       "LUA|liderados": {"base": z(), "ad": z(), "va": z()},
                       "LUA|velha": {"ad": z(), "va": z()}},  # série sem base[] (o erro de 09/11)
            "vesp": {"LUA": {"LIDER INVENTADO LUA": {"ad": [1, 0, 3], "va": [1, 0, 2], "rt": z(), "rv": z()}}}}


def cotacoes():
    base = {"cardStatus": 5, "isShelved": "N", "vehicleChassi": ""}
    return [dict(base, vehiclePlates="ZZZ-1A01", nameAffiliate="LIDERADO INVENTADO SILVA SGA"),
            dict(base, vehiclePlates="", vehicleChassi="CHASSIINVENTADO02", nameAffiliate="Liderado Inventado Silva"),
            dict(base, vehiclePlates="ZZZ1A03", nameAffiliate="Liderado Inventado Silva"),
            dict(base, vehiclePlates="ZZZ1A04", nameAffiliate="Lider Inventado Lua"),
            dict(base, vehiclePlates="ZZZ1A05", nameAffiliate="Outro Inventado", cardStatus=3)]  # não concretizada


ESPS = [{"id": 9, "nome": LIDERADO, "sga": ["LIDERADO INVENTADO SILVA"], "eqs": ["LUA"]}]


def pacotes():
    g = pacote_geral()
    return {"all": g, "t:LUA": copy.deepcopy(g),
            "e:LIDERADO INVENTADO SILVA": {"meses_ad": AM, "val_ate": 2, "ades": [],
                                           "series": {"ALL|equipe": {"base": [0, 0, 0], "ad": z(), "va": z()}}}}


def test_adesao_no_nome_do_lider_conta_para_o_liderado():
    p = pacotes()
    st = aplicar(p, cotacoes(), None, ESPS)
    for chave in ("all", "t:LUA"):
        o = p[chave]
        out = [a for a in o["ades"] if a["m"] == "2026-10"]
        assert [(a["esp"], a.get("esp_sga")) for a in out] == [(LIDERADO, LIDER), (LIDERADO, LIDER), (LIDER, None)]
        assert o["ades"][2]["esp"] == LIDER and "esp_sga" not in o["ades"][2]  # ago/26: antes da regra
        s = o["series"]
        assert s["LUA|propria"]["ad"] == [1, 0, 1] and s["LUA|propria"]["va"] == [1, 0, 1]
        assert s["LUA|liderados"]["ad"] == [0, 0, 2] and s["LUA|liderados"]["va"] == [0, 0, 1]
        assert s["LUA|lid:LIDERADO INVENTADO SILVA"]["ad"] == [0, 0, 2]
        assert [a + b for a, b in zip(s["LUA|propria"]["ad"], s["LUA|liderados"]["ad"])] == s["LUA|equipe"]["ad"]
        assert o["vesp"]["LUA"]["LIDER INVENTADO LUA"]["ad"] == [1, 0, 1]
        assert o["vesp"]["LUA"]["LIDERADO INVENTADO SILVA"]["va"] == [0, 0, 1]
    e = p["e:LIDERADO INVENTADO SILVA"]
    assert len(e["ades"]) == 2 and e["series"]["ALL|equipe"]["ad"] == [0, 0, 2] and e["series"]["ALL|equipe"]["va"] == [0, 0, 1]
    assert st["movidas"] == 4 and st["no_pacote_do_liderado"] == 2 and st["fonte"] == "power_crm"


def test_toda_serie_fica_com_base():
    """Erro de 09/11: série de liderado sem base[] travou o painel dos líderes ("reading 'length'")."""
    p = pacotes()
    st = aplicar(p, cotacoes(), None, ESPS)
    for o in p.values():
        assert all(isinstance(s.get("base"), list) for s in o["series"].values())
    assert p["all"]["series"]["LUA|lid:LIDERADO INVENTADO SILVA"]["base"] == [0, 0, 0]
    assert p["all"]["series"]["LUA|velha"]["base"] == [0, 0, 0]
    assert st["base_corrigida"] == 2  # a série velha no "all" e no "t:LUA"


def test_rodar_duas_vezes_nao_move_de_novo():
    p = pacotes()
    aplicar(p, cotacoes(), None, ESPS)
    antes = copy.deepcopy(p)
    st = aplicar(p, cotacoes(), None, ESPS)
    assert p == antes and st["movidas"] == 0


def test_sem_power_crm_vale_o_que_a_busca_anterior_ja_tinha_movido():
    old = pacote_geral()
    aplicar({"all": old}, cotacoes(), None, ESPS)  # a busca anterior moveu as duas de out/26
    p = pacotes()
    st = aplicar(p, None, old, ESPS)
    assert [a["esp"] for a in p["all"]["ades"] if a["m"] == "2026-10"] == [LIDERADO, LIDERADO, LIDER]
    assert p["t:LUA"]["series"]["LUA|liderados"]["ad"] == [0, 0, 2]
    assert st["fonte"] == "busca_anterior" and st["movidas"] == 4


def test_a_busca_completa_aplica_a_regra_antes_de_gravar(app, db):
    _importado(db)
    guardar(db, "esp:LIDERADO INVENTADO SILVA", ESPS[0], "importacao")
    db.commit()

    def rodar_falso(e):
        return Saida(pacotes=pacotes(), cotacoes=cotacoes())

    r = bc.busca_completa(app.state.Sessao, CFG, rodar=rodar_falso, clientes=CLIENTES)
    assert r["ok"] is True
    g = ler(db, "all")
    assert [a["esp"] for a in g["ades"] if a["m"] == "2026-10"] == [LIDERADO, LIDERADO, LIDER]
    assert ler(db, "e:LIDERADO INVENTADO SILVA")["series"]["ALL|equipe"]["ad"] == [0, 0, 2]


@pytest.mark.parametrize("chave", ["CHASSIINVENTADO101", "NOME:ASSOCIADO INVENTADO 101"])
def test_plantao_sem_placa_pelo_chassi_ou_pelo_nome(chave):
    """Plantão 30-31/10 (09/11): veículos sem placa entram na lista pelo chassi ou por NOME:<nome>."""
    old = old_minimo()
    old["det"] = {"101": {"nome": "ASSOCIADO INVENTADO 101", "chassi": "CHASSIINVENTADO101"}}
    e = entrada(old=old)
    e.comp_marks = {"regras": {chave: {"plt": True}}}
    s = rodar(e)
    assert s.pacotes["all"]["desc"]["d"]["2026-09"] == {"LUA": [1, 1, 0, 0]}  # o desconto conta como plantão
    assert s.cotacoes and s.cotacoes[0]["quotationCode"] == "Q-INVENTADA-1"
