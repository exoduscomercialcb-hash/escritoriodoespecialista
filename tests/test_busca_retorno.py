"""Busca automática (app/busca/retorno.py) de ponta a ponta, com SGA, Power CRM e BI falsos, em memória.

Todos os dados daqui são inventados (associados, especialistas, placas, telefones). Nunca usar dados reais.
Data da busca: 09/11/2026, 03:52 (Brasília). Meses das adesões: set/26, out/26 e nov/26.
"""
from __future__ import annotations

import copy
import threading
from datetime import date, datetime

import pytest

from app.busca.entrada import Entrada, ErroBusca
from app.busca.retorno import rodar
from app.config import FUSO
from app.fontes.sga import SGABloqueado

from .conftest import cpf_inventado

AGORA = datetime(2026, 11, 9, 3, 52, tzinfo=FUSO)
SIT = {"1": "ATIVO", "18": "ATIVO - PENDENTE INSTALACAO", "16": "AGUARDANDO INSTALACAO", "19": "ATIVO - DISPENSA INSTALACAO",
       "6": "CANCELADO", "4": "INADIMPLENTE", "2": "INATIVO", "10": "RETIRADA"}
ESP_UM = "ESPECIALISTA INVENTADO UM"      # equipe Lua (cooperativa 2)
ESP_DOIS = "ESPECIALISTA INVENTADA DOIS"  # equipe Pé no Chão (cooperativa 3)


def veiculo(cv, coop, esp, sit, placa, contrato, assoc):
    return {"codigo_veiculo": cv, "codigo_cooperativa": coop, "nome_voluntario": esp, "codigo_situacao": sit,
            "descricao_situacao": SIT[sit], "placa": placa, "chassi": "CHASSIINVENTADO%d" % cv, "data_contrato": contrato,
            "codigo_associado": assoc, "cpf_associado": cpf_inventado(assoc), "modelo": "MODELO INVENTADO",
            "data_alteracao": contrato}


def dados(extras_setembro: int = 0):
    vs = [
        veiculo(101, "2", ESP_UM, "1", "ABC1D23", "2026-09-10", 5001),     # adesão de set, 1º boleto pago
        veiculo(102, "2", ESP_UM, "1", "ABC1D24", "2026-10-05", 5002),     # adesão de out, 1º boleto em aberto
        veiculo(103, "3", ESP_DOIS, "18", "ABC1D25", "2026-11-02", 5003),  # adesão de nov, sem boleto ainda
        veiculo(104, "3", ESP_DOIS, "16", "ABC1D26", "2026-03-15", 5005),  # base antiga (mesmo associado do 105)
        veiculo(106, "3", ESP_DOIS, "19", "ABC1D28", "2025-12-01", 5006),  # base antiga
        veiculo(105, "2", ESP_UM, "6", "ABC1D27", "2026-02-01", 5005),     # cancelado em out
        veiculo(107, "2", ESP_UM, "6", "ABC1D29", "2026-10-01", 5007),     # contrato de out cancelado no mesmo mês
    ]
    for i in range(extras_setembro):                                        # para o teste da fila depois do bloqueio
        vs.append(veiculo(200 + i, "2", ESP_UM, "1", "ABC1E%02d" % i, "2026-09-%02d" % (1 + i % 28), 6000 + i))
    historico = [
        {"codigo_veiculo": 105, "data_alteracao": "2026-10-20", "hora_alteracao": "10:00:00", "valor_anterior": "1",
         "valor_posterior": "6", "codigo_situacaomotivo": "7", "observacao": "Observação inventada"},
        {"codigo_veiculo": 107, "data_alteracao": "2026-10-15", "hora_alteracao": "09:00:00", "valor_anterior": "1",
         "valor_posterior": "6", "codigo_situacaomotivo": "7", "observacao": ""},
    ]
    boletos = [
        {"data_vencimento": "2026-10-10", "data_vencimento_original": "2026-10-10", "data_emissao": "2026-09-15",
         "situacao_boleto": "BAIXADO", "data_pagamento": "2026-10-08",
         "veiculos": [{"placa": "ABC1D23", "codigo_veiculo": 101, "data_inicio_contrato_veiculo": "2026-09-10"}]},
        {"data_vencimento": "2026-11-05", "data_vencimento_original": "2026-11-05", "data_emissao": "2026-10-06",
         "situacao_boleto": "ABERTO", "data_pagamento": None,
         "veiculos": [{"placa": "ABC1D24", "codigo_veiculo": 102, "data_inicio_contrato_veiculo": "2026-10-05"}]},
    ]
    atendimentos = [{"codigo_tipo_atendimento": "100029", "codigo_status_atendimento": "1", "data_cadastro": "2026-10-06",
                     "hora_cadastro": "10:00:00", "placa": "ABC1D24", "codigo_veiculo": 102}]
    return vs, historico, boletos, atendimentos


def _data_br(s: str) -> date:
    d, m, a = map(int, s.split("/"))
    return date(a, m, d)


class SGAFalso:
    """Imita o ClienteSGA (app/fontes/sga.py): .post e .get já com o login resolvido; {} no 406; None no 404."""

    def __init__(self, extras_setembro: int = 0, bloquear_em: str | None = None):
        self.veiculos, self.historico, self.boletos, self.atendimentos = dados(extras_setembro)
        self.bloquear_em = bloquear_em
        self.bloqueado = False
        self.chamadas_depois_do_bloqueio = 0
        self.chamadas: list[str] = []
        self.corpos_boleto: list[dict] = []
        self._trava = threading.Lock()

    def _chamada(self, caminho: str) -> None:
        with self._trava:
            self.chamadas.append(caminho)
            if self.bloqueado:
                self.chamadas_depois_do_bloqueio += 1
                raise SGABloqueado("o SGA respondeu BLOQUEADO (teste)")
            if self.bloquear_em and caminho.startswith(self.bloquear_em):
                self.bloqueado = True
                raise SGABloqueado(f"o SGA respondeu BLOQUEADO em {caminho} (teste)")

    @staticmethod
    def _pagina(lista, corpo, chave):
        off, qtd = int(corpo.get("inicio_paginacao") or 0), int(corpo["quantidade_por_pagina"])
        if not lista:
            return {}  # o 406 "nenhum veículo encontrado", que o cliente devolve como {}
        return {chave: lista[off:off + qtd], "total_veiculos": len(lista)}

    def post(self, caminho: str, corpo: dict):
        self._chamada(caminho)
        if caminho == "/listar/veiculo":
            if "codigo_situacao" in corpo:
                sel = [v for v in self.veiculos if v["codigo_situacao"] == corpo["codigo_situacao"]]
            else:
                d0, d1 = _data_br(corpo["data_contrato"]), _data_br(corpo["data_contrato_final"])
                sel = [v for v in self.veiculos if d0 <= date.fromisoformat(v["data_contrato"]) <= d1]
            return self._pagina([dict(v) for v in sel], corpo, "veiculos")
        if caminho == "/listar/alteracao-veiculos":
            d0, d1 = _data_br(corpo["data_inicial"]), _data_br(corpo["data_final"])
            sel = [dict(h) for h in self.historico if d0 <= date.fromisoformat(h["data_alteracao"]) <= d1]
            p = int(corpo["inicio_paginacao"]) * 1000
            return sel[p:p + 1000] if sel[p:p + 1000] else {}
        if caminho == "/listar/boleto-associado-veiculo":
            self.corpos_boleto.append(dict(corpo))
            d0, d1 = _data_br(corpo["data_vencimento_inicial"]), _data_br(corpo["data_vencimento_final"])
            sel = [copy.deepcopy(b) for b in self.boletos if d0 <= date.fromisoformat(b["data_vencimento"]) <= d1
                   and any(v["placa"] == corpo.get("placa") for v in b["veiculos"])]
            return sel or {}
        if caminho == "/listar/historico-atendimento-associado":
            return [dict(a) for a in self.atendimentos if a["codigo_tipo_atendimento"] == corpo["codigo_tipo_atendimento"]] or {}
        raise AssertionError("caminho do SGA não esperado no teste: " + caminho)

    def get(self, caminho: str):
        self._chamada(caminho)
        if caminho == "/listar/situacaomotivo/ativo":
            return [{"codigo": "7", "descricao": "MOTIVO INVENTADO"}]
        if caminho == "/listar/status-atendimento/todos":
            return [{"codigo_statusatendimentoassociado": "1", "descricao": "CONCLUIDO"},
                    {"codigo_statusatendimentoassociado": "20", "descricao": "DESVINCULADO PAGO"},
                    {"codigo_statusatendimentoassociado": "21", "descricao": "AGUARDANDO REMOÇÃO"}]
        if caminho.startswith("/veiculo/buscar/") and caminho.endswith("/codigo"):
            cv = int(caminho.split("/")[3])
            for v in self.veiculos:
                if v["codigo_veiculo"] == cv:
                    return [dict(v, nome="ASSOCIADO INVENTADO %d" % cv, ddd_celular="21", telefone_celular="900000%03d" % (cv % 1000),
                                 ano_modelo=2020, tipo="AUTOMOVEL", categoria="PASSEIO", cpf=v["cpf_associado"])]
            return None
        raise AssertionError("caminho do SGA não esperado no teste: " + caminho)


def cotacoes_de_enchimento(n: int) -> list[dict]:
    """Cotações que não são venda concretizada: só para passar da trava das 100 cotações (16/11)."""
    return [{"quotationCode": "Q-ENCHIMENTO-%03d" % i, "cardStatus": 1, "isShelved": "N"} for i in range(n)]


class PowerCRMFalso:
    def __init__(self, extras=(), enchimento: int = 120):
        self.paginas = 0
        self.extras, self.enchimento = list(extras), enchimento

    def pagina(self, de: str, ate: str, numero: int) -> list[dict]:
        self.paginas += 1
        if numero > 0:
            return []
        return [self._principal()] + copy.deepcopy(self.extras) + cotacoes_de_enchimento(self.enchimento)

    @staticmethod
    def _principal() -> dict:
        return {"quotationCode": "Q-INVENTADA-1", "cardStatus": 5, "isShelved": "N", "vehiclePlates": "ABC-1D23",
                 "vehicleChassi": "", "clientName": "ASSOCIADO INVENTADO UM", "clientMobile": "5521900000101",
                 "monthlyPaymentsPrice": "R$ 150,00", "monthlyPaymentDiscount": "R$ 15,00", "sentToHinovaDate": "10/09/2026",
                 "createdDate": "08/09/2026", "responsibleSalesman": "VENDEDORA INVENTADA", "clientCity": "CIDADE INVENTADA",
                 "vehicleBrand": "MARCA INVENTADA", "vehicleModel": "MODELO INVENTADO", "observationsDatabase": ""}


class BIForaDoAr:
    """O BI não responde: o script segue o caminho "BI não lido" (mantém margem e boletos da leitura anterior)."""

    def get(self, *a, **k):
        raise RuntimeError("BI fora do ar (teste)")

    post = get


def old_minimo() -> dict:
    """O mínimo que o script lê do pacote "all" anterior (o último mês lido foi out/26)."""
    return {"atualizado": "2026-10-31T03:52-03:00", "meses_base": ["2026-08", "2026-09", "2026-10"],
            "meses_ad": ["2026-09", "2026-10"],
            "series": {"ALL|equipe": {"base": [3, 4, 4], "ad": [1, 1], "va": [1, 0]},
                       "LUA|equipe": {"base": [1, 2, 2], "ad": [1, 1], "va": [1, 0]}},
            "det": {}, "vcache": {}, "vesp": {}, "reat": [], "pend": None, "desc": {"d": {}, "tk": {}}, "vimap": {},
            "canc": [], "div_ex": {}, "vi_hist": {}, "desc_vi": {}, "notif_vistos": [], "notif_vistos_coord": []}


ESPECIALISTAS = [
    {"id": 1, "nome": "Especialista Inventado Um", "sga": [ESP_UM], "eqs": ["LUA"], "carteira": None, "rot": "", "ld": None},
    {"id": 2, "nome": "Especialista Inventada Dois", "sga": [ESP_DOIS], "eqs": ["PÉ NO CHÃO"], "carteira": None, "rot": ""},
]


def entrada(sga=None, powercrm="padrao", old=None, registro=None) -> Entrada:
    return Entrada(agora=AGORA, old=old if old is not None else old_minimo(), especialistas=copy.deepcopy(ESPECIALISTAS),
                   listas={"Especialista Inventada Dois": [{"mat": "5003"}]}, comp_marks={"regras": {}}, comp_registro=[],
                   sga=sga or SGAFalso(), powercrm=PowerCRMFalso() if powercrm == "padrao" else powercrm,
                   http_bi=BIForaDoAr(), log=(lambda *a: registro.append(a)) if registro is not None else (lambda *a: None))


def _linhas(registro):
    return [" ".join(map(str, a)) for a in registro]


def test_termina_e_devolve_os_pacotes_de_todos_os_acessos():
    registro = []
    s = rodar(entrada(registro=registro))
    assert "all" in s.pacotes
    assert {"t:LUA", "t:PE NO CHAO", "t:RECREIO"} <= set(s.pacotes)   # um pacote por equipe com líder (dicionário LEAD)
    assert {"e:ESPECIALISTA INVENTADO UM", "e:ESPECIALISTA INVENTADA DOIS"} <= set(s.pacotes)
    assert s.resumo.pop("chamadas_sga") > 0
    assert s.resumo == {"atualizado": "2026-11-09T03:52-03:00", "base_hoje": 5, "cancelados_recentes": 2, "bi": False,
                        "inadimplentes": 0, "inativos": 0, "retirada": 0, "voltaram_ativos": 0,
                        "sga_bloqueado_no_fim": None}
    assert any("chamadas ao SGA nesta atualização" in x for x in _linhas(registro))
    assert s.novos_cancelados == {}
    assert any("BI Brasil Atuarial não respondeu" in x for x in _linhas(registro))
    # pacotes já sem criptografia, no formato que a página desenha
    geral = s.pacotes["all"]
    assert geral["meses_base"] == ["2026-08", "2026-09", "2026-10", "2026-11"]
    assert geral["meses_ad"] == ["2026-09", "2026-10", "2026-11"]
    assert "iv" not in geral and "c" not in geral
    assert s.pacotes["e:ESPECIALISTA INVENTADO UM"]["cptok"] is None


def test_base_ativa_de_hoje_bate_com_os_veiculos_do_sga():
    s = rodar(entrada())
    ser = s.pacotes["all"]["series"]
    assert ser["ALL|equipe"]["base"] == [3, 4, 4, 5]       # meses fechados mantidos; hoje = 5 ativos
    assert ser["LUA|equipe"]["base"] == [1, 2, 2, 2]
    assert ser["PÉ NO CHÃO|equipe"]["base"] == [0, 0, 0, 3]  # chave nova: começo com zeros
    assert ser["ESP|" + ESP_UM]["base"][-1] == 2
    assert s.pacotes["t:LUA"]["series"]["LUA|equipe"]["base"][-1] == 2
    assert s.pacotes["e:ESPECIALISTA INVENTADA DOIS"]["series"]["ALL|equipe"]["base"][-1] == 3


def test_adesoes_validacao_cancelados_e_descontos():
    s = rodar(entrada())
    g = s.pacotes["all"]
    # set: 101 (1º boleto pago); out: 102 (107 foi cancelado no mesmo mês e não entra); nov: 103
    assert g["series"]["ALL|equipe"]["ad"] == [1, 1, 1]
    assert g["series"]["ALL|equipe"]["va"] == [1, 0, 0]
    assert [r["pl"] for r in g["pend"]["rows"]] == ["ABC1D24"]
    assert g["pend"]["meses"] == ["2026-09", "2026-10"]
    assert {c["pl"] for c in g["canc"]} == {"ABC1D27", "ABC1D29"}
    c105 = next(c for c in g["canc"] if c["pl"] == "ABC1D27")
    assert c105["mot"] == "Motivo inventado" and c105["ov"] == ["ABC1D26 · MODELO INVENTADO"]
    assert {c["pl"] for c in s.pacotes["t:LUA"]["canc"]} == {"ABC1D27", "ABC1D29"}
    assert g["desc"]["d"]["2026-09"] == {"LUA": [1, 0, 1, 0]}           # desconto fora do plantão
    assert g["desc"]["tk"]["2026-09"] == {"LUA": [135.0, 1]}
    a102 = next(a for a in g["ades"] if a["pl"] == "ABC1D24")
    assert a102["inst"] == "R" and a102["bol"] == "Em aberto"
    assert g["resg"] == {"5003": {"dc": "2026-11-02", "tp": "novo", "pl": "ABC1D25", "sit": "Ativo - Pendente Instalacao"}}
    assert g["vcache"] == {"101|2026-09-10": {"ok": True, "pg": "2026-10-08"}}


def test_sem_power_crm_mantem_os_descontos_anteriores():
    registro = []
    old = old_minimo()
    old["desc"] = {"d": {"2026-09": {"LUA": [9, 0, 0, 0]}}, "tk": {}}
    s = rodar(entrada(powercrm=None, old=old, registro=registro))
    assert s.pacotes["all"]["desc"]["d"]["2026-09"] == {"LUA": [9, 0, 0, 0]}
    assert any("descontos não recalculados" in x for x in _linhas(registro))


def test_nao_altera_o_estado_anterior_recebido():
    old = old_minimo()
    antes = copy.deepcopy(old)
    rodar(entrada(old=old))
    assert old == antes


@pytest.mark.parametrize("onde", ["/listar/veiculo", "/listar/alteracao-veiculos", "/listar/boleto-associado-veiculo",
                                  "/listar/situacaomotivo/ativo", "/veiculo/buscar/"])
def test_sga_bloqueado_sobe_sem_ser_engolido(onde):
    sga = SGAFalso(bloquear_em=onde)
    with pytest.raises(SGABloqueado):
        rodar(entrada(sga=sga))
    assert sga.bloqueado


def test_depois_do_bloqueio_a_fila_das_linhas_de_execucao_nao_chama_o_sga():
    sga = SGAFalso(extras_setembro=30, bloquear_em="/listar/boleto-associado-veiculo")
    with pytest.raises(SGABloqueado):
        rodar(entrada(sga=sga))
    assert sga.chamadas_depois_do_bloqueio <= 1   # no máximo a que já estava em andamento na outra linha de execução


@pytest.mark.parametrize("onde", ["/listar/status-atendimento/todos", "/listar/historico-atendimento-associado"])
def test_bloqueio_no_trecho_final_termina_sem_insistir_e_mantem_as_instalacoes(onde):
    """Caso de 10/11: o SGA bloqueava sempre no trecho final (instalações), que é opcional no script original.
    A busca termina com o que já leu, não chama mais o SGA e mantém as instalações da busca anterior."""
    primeira = rodar(entrada())
    com_inst = [a for a in primeira.pacotes["all"]["ades"] if a.get("inst")]
    assert com_inst  # os dados inventados têm instalação lançada
    sga = SGAFalso(bloquear_em=onde)
    s = rodar(entrada(sga=sga, old=primeira.pacotes["all"]))
    assert "BLOQUEADO" in s.resumo["sga_bloqueado_no_fim"]
    assert sga.chamadas_depois_do_bloqueio == 0
    assert s.resumo["base_hoje"] == 5 and "all" in s.pacotes and "t:LUA" in s.pacotes
    depois = {(a["m"], a["pl"]): (a.get("inst"), a.get("instd")) for a in s.pacotes["all"]["ades"]}
    for a in com_inst:
        assert depois[(a["m"], a["pl"])] == (a["inst"], a["instd"])


# ---------------------------------------------------------------- mudanças do sistema atual de 09/11 a 24/11

def _cotacao(codigo, placa, nome, desconto="R$ 0,00", vendedor="VENDEDORA INVENTADA"):
    q = PowerCRMFalso._principal()
    q.update(quotationCode=codigo, vehiclePlates=placa, clientName=nome, monthlyPaymentDiscount=desconto,
             sentToHinovaDate="10/10/2026", createdDate="08/10/2026", responsibleSalesman=vendedor)
    return q


@pytest.mark.parametrize("minimo, plantao", [(2, True), (3, False)])
def test_plantao_por_condicao_da_equipe(minimo, plantao):
    """14/11 (PLT_COND): com "min" ativações da equipe no mês, o desconto destes associados conta como plantão."""
    sga = SGAFalso()
    sga.veiculos += [veiculo(301, "5", "ESPECIALISTA INVENTADO MAGNATAS", "1", "ABC2M01", "2026-10-12", 7001),
                     veiculo(302, "5", "ESPECIALISTA INVENTADO MAGNATAS", "1", "ABC2M02", "2026-10-13", 7002)]
    pc = PowerCRMFalso(extras=[_cotacao("Q-INVENTADA-M1", "ABC2M01", "ASSOCIADO PLANTAO INVENTADO SOBRENOME", "R$ 20,00"),
                               _cotacao("Q-INVENTADA-M2", "ABC2M02", "ASSOCIADO COMUM INVENTADO")])
    e = entrada(sga=sga, powercrm=pc)
    e.plt_cond = [{"t": "MAGNATAS", "min": minimo, "desde": "2026-10", "nomes": ["ASSOCIADO PLANTAO INVENTADO"]}]
    g = rodar(e).pacotes["all"]
    assert g["desc"]["d"]["2026-10"]["MAGNATAS"] == ([2, 1, 0, 0] if plantao else [2, 0, 1, 0])
    a = next(a for a in g["ades"] if a["pl"] == "ABC2M01")
    assert a["pt"] == ("P" if plantao else "F")


def test_plantao_por_condicao_so_vale_a_partir_do_mes_indicado():
    sga = SGAFalso()
    sga.veiculos += [veiculo(301, "5", "ESPECIALISTA INVENTADO MAGNATAS", "1", "ABC2M01", "2026-10-12", 7001)]
    e = entrada(sga=sga, powercrm=PowerCRMFalso(extras=[_cotacao("Q-INVENTADA-M1", "ABC2M01", "ASSOCIADO PLANTAO", "R$ 20,00")]))
    e.plt_cond = [{"t": "MAGNATAS", "min": 1, "desde": "2026-11", "nomes": ["ASSOCIADO PLANTAO"]}]
    assert rodar(e).pacotes["all"]["desc"]["d"]["2026-10"]["MAGNATAS"] == [1, 0, 1, 0]


def _old_com_reativacao():
    old = old_minimo()
    old["reat"] = [{"mes": "2026-10", "t": "LUA", "esp": "Lider Inventado Lua", "pl": "ABC3R01", "n": "Associado Inventado",
                    "val": False, "sb": "Aguardando 2º boleto"}]
    return old


@pytest.mark.parametrize("situacao, val, sb", [("BAIXADO", True, "Pago em 04/11/2026"), ("ABERTO", False, "Vencido")])
def test_reativacao_conferida_pelo_boleto_seguinte_no_sga(situacao, val, sb):
    """14/11: a reativação de out/26 é validada quando o boleto com vencimento a partir de nov/26 é pago (BAIXADO)."""
    sga = SGAFalso()
    sga.boletos.append({"data_vencimento": "2026-11-05", "data_vencimento_original": "2026-11-05", "data_emissao": "2026-10-20",
                        "situacao_boleto": situacao, "data_pagamento": "2026-11-04" if situacao == "BAIXADO" else None,
                        "veiculos": [{"placa": "ABC3R01", "codigo_veiculo": 401}]})
    g = rodar(entrada(sga=sga, old=_old_com_reativacao())).pacotes["all"]
    r = g["reat"][0]
    assert (r["val"], r["sb"], r["venc"]) == (val, sb, "05/11/2026")
    assert {"placa": "ABC3R01", "data_vencimento_inicial": "01/11/2026", "data_vencimento_final": "31/03/2027"} in sga.corpos_boleto
    i = g["meses_ad"].index("2026-10")
    assert g["series"]["LUA|equipe"]["rt"][i] == 1 and g["series"]["LUA|equipe"]["rv"][i] == (1 if val else 0)


def test_reativacao_ja_validada_nao_consulta_o_sga_de_novo():
    old = _old_com_reativacao()
    old["reat"][0]["val"] = True
    sga = SGAFalso()
    rodar(entrada(sga=sga, old=old))
    assert not any(c.get("placa") == "ABC3R01" for c in sga.corpos_boleto)


def _hist(cv, data, antes, depois, motivo="7"):
    return {"codigo_veiculo": cv, "data_alteracao": data, "hora_alteracao": "10:00:00", "valor_anterior": antes,
            "valor_posterior": depois, "codigo_situacaomotivo": motivo, "observacao": "Observação inventada"}


def _sga_com_inadimplentes(**k):
    """108 inadimplente, 109 inativo, 110 e 111 em retirada (rastreador desvinculado / ainda vinculado), 112 inadimplente que
    voltou a ficar ativo há 2 dias e 113 que voltou há 20 dias (fica fora). Todos de contratos antigos (não são adesões)."""
    sga = SGAFalso(**k)
    for cv, sit in ((108, "4"), (109, "2"), (110, "10"), (111, "10"), (112, "1"), (113, "1")):
        sga.veiculos.append(veiculo(cv, "2", ESP_UM, sit, "ABC4X%02d" % (cv - 100), "2025-05-01", 8000 + cv))
    sga.historico += [_hist(108, "2026-10-25", "1", "4"), _hist(109, "2026-11-03", "1", "2"), _hist(110, "2026-10-28", "1", "10"),
                      _hist(111, "2026-11-01", "1", "10"), _hist(112, "2026-10-10", "1", "4"), _hist(112, "2026-11-07", "4", "1"),
                      _hist(113, "2026-10-05", "1", "4"), _hist(113, "2026-10-20", "4", "1")]
    sga.atendimentos += [
        {"codigo_tipo_atendimento": "100014", "codigo_status_atendimento": "21", "data_cadastro": "2026-10-29",
         "hora_cadastro": "09:00:00", "codigo_veiculo": 110},
        {"codigo_tipo_atendimento": "100014", "codigo_status_atendimento": "20", "data_cadastro": "2026-11-04",
         "hora_cadastro": "09:00:00", "codigo_veiculo": 110},  # o mais recente vale: desvinculado
        {"codigo_tipo_atendimento": "100014", "codigo_status_atendimento": "21", "data_cadastro": "2026-11-02",
         "hora_cadastro": "09:00:00", "codigo_veiculo": 111}]
    return sga


def test_inadimplentes_inativos_e_retirada_entram_com_os_cancelados():
    """16/11 e 18/11: inadimplente, inativo e retirada do mês anterior ou do atual aparecem com os cancelados (campo st)."""
    s = rodar(entrada(sga=_sga_com_inadimplentes()))
    canc = {c["pl"]: c for c in s.pacotes["all"]["canc"]}
    assert canc["ABC4X08"]["st"] == "inad" and "rs" not in canc["ABC4X08"]
    assert canc["ABC4X09"]["st"] == "inat" and canc["ABC4X09"]["mot"] == "Motivo inventado"
    assert canc["ABC4X10"]["st"] == "ret" and canc["ABC4X10"]["rr"] == {"ok": True, "st": "Desvinculado Pago", "d": "04/11/2026"}
    assert canc["ABC4X11"]["rr"] == {"ok": False, "st": "Aguardando Remoção", "d": "02/11/2026"}
    assert canc["ABC4X12"]["st"] == "inad"
    assert canc["ABC4X12"]["rs"] == {"dc": "2026-11-07", "tp": "reativado", "sit": "Ativo", "pl": "ABC4X12"}
    assert "ABC4X13" not in canc                       # voltou a ficar ativo há mais de 7 dias
    assert {"ABC1D27", "ABC1D29"} <= set(canc) and not any(canc[p].get("st") for p in ("ABC1D27", "ABC1D29"))
    assert all("_cpf" not in c for c in canc.values())
    assert {"ABC4X08", "ABC4X10"} <= {c["pl"] for c in s.pacotes["t:LUA"]["canc"]}
    assert {"108", "110", "112"} <= set(s.pacotes["all"]["det"])   # as fichas ficam no cache
    r = s.resumo
    assert (r["cancelados_recentes"], r["inadimplentes"], r["inativos"], r["retirada"], r["voltaram_ativos"]) == (2, 1, 1, 2, 1)


def test_retirada_com_bloqueio_no_trecho_final_mantem_o_rastreador_da_busca_anterior():
    primeira = rodar(entrada(sga=_sga_com_inadimplentes()))
    sga = _sga_com_inadimplentes(bloquear_em="/listar/historico-atendimento-associado")
    s = rodar(entrada(sga=sga, old=primeira.pacotes["all"]))
    assert s.resumo["sga_bloqueado_no_fim"] and sga.chamadas_depois_do_bloqueio == 0
    canc = {c["pl"]: c for c in s.pacotes["all"]["canc"]}
    assert canc["ABC4X10"]["rr"]["ok"] is True and canc["ABC4X11"]["rr"]["ok"] is False


def test_fichas_novas_limitadas_a_150_por_busca():
    """18/11: no máximo 150 fichas (/veiculo/buscar) novas por busca; o resto entra nas próximas."""
    def sga_():
        sga = SGAFalso()
        for i in range(160):
            cv = 1000 + i
            sga.veiculos.append(veiculo(cv, "2", ESP_UM, "4", "ABC5Y%03d" % i, "2025-05-01", 9000 + i))
            sga.historico.append(_hist(cv, "2026-10-%02d" % (1 + i % 28), "1", "4"))
        return sga
    fichas = lambda sga: sum(1 for c in sga.chamadas if c.startswith("/veiculo/buscar/"))
    registro = []
    sga = sga_()
    s = rodar(entrada(sga=sga, registro=registro))
    assert fichas(sga) == 150
    assert any("fichas novas limitadas" in x for x in _linhas(registro))
    # as 150 incluem as fichas das adesões e dos cancelados, pedidas antes; das inadimplentes, vêm as mais recentes
    inad = {c["pl"]: c["dc"] for c in s.pacotes["all"]["canc"] if c.get("st") == "inad"}
    datas = {h["codigo_veiculo"]: h["data_alteracao"] for h in sga.historico}
    fora = [datas[v["codigo_veiculo"]] for v in sga.veiculos if v["codigo_veiculo"] >= 1000 and v["placa"] not in inad]
    assert 140 <= len(inad) < 150 and max(fora) <= min(inad.values())
    sga = sga_()
    s2 = rodar(entrada(sga=sga, old=s.pacotes["all"]))   # a busca seguinte só busca as que faltaram
    assert fichas(sga) == 160 - len(inad) and sum(1 for c in s2.pacotes["all"]["canc"] if c.get("st") == "inad") == 160


def test_power_crm_com_menos_de_100_cotacoes_para_sem_gravar():
    """16/11: o Power CRM respondeu erro 500 e a atualização saiu com 0 cotações. Agora para (ErroBusca: nada é gravado)."""
    with pytest.raises(ErroBusca, match="só 1 cotações"):
        rodar(entrada(powercrm=PowerCRMFalso(enchimento=0)))
    with pytest.raises(ErroBusca):
        rodar(entrada(powercrm=PowerCRMFalso(enchimento=98)))   # 99 cotações
    assert rodar(entrada(powercrm=PowerCRMFalso(enchimento=99))).cotacoes   # 100 cotações: segue


def test_power_crm_com_poucas_cotacoes_na_busca_completa_nao_grava_nada(app, db):
    import app.busca.completa as bc
    from app.dados import guardar, ler

    from .test_busca_completa import CFG
    guardar(db, "all", old_minimo(), "importacao")
    for x in ESPECIALISTAS:
        guardar(db, "esp:" + x["nome"].upper(), x, "importacao")
    db.commit()
    r = bc.busca_completa(app.state.Sessao, CFG, clientes=(SGAFalso(), PowerCRMFalso(enchimento=0), BIForaDoAr()))
    assert r["ok"] is False and "só 1 cotações" in r["mensagem"] and "nada foi gravado" in r["mensagem"]
    db.expire_all()
    assert ler(db, "all") == old_minimo() and ler(db, "busca") is None


VENDEDORA = {"id": 3, "nome": "Vendedora Inventada", "sga": [], "eqs": ["EXODUS BENEFÍCIOS"], "carteira": None, "rot": "",
             "ld": {"team": "EXODUS BENEFÍCIOS", "cart": "CARTEIRA INVENTADA", "pc": ["VENDEDORA INVENTADA"], "meta": 15}}


def test_credito_fixado_fica_com_o_especialista_e_duplica_para_a_vendedora_interna():
    """19/11: venda da vendedora interna transferida a outro especialista: fica com ele E conta para ela (vf/vfm)."""
    e = entrada()
    e.especialistas.append(copy.deepcopy(VENDEDORA))
    e.creditos_fixados = [{"placa": "ABC-1D24", "resp": "Vendedora Inventada", "comp": "2026-10"}]
    s = rodar(e)
    g = s.pacotes["all"]
    a = next(a for a in g["ades"] if a["pl"] == "ABC1D24")
    assert (a["esp"], a["vf"], a["vfm"]) == ("Especialista Inventado Um", "Vendedora Inventada", "2026-10")
    assert g["series"]["LUA|equipe"]["ad"] == [1, 1, 0]        # continua na equipe do especialista
    v = s.pacotes["e:VENDEDORA INVENTADA"]
    fx = [a for a in v["ades"] if a.get("fx")]
    assert [(a["pl"], a["t"], a["m"]) for a in fx] == [("ABC1D24", "VI", "2026-10")]
    assert v["series"]["VI|equipe"]["ad"] == [0, 1, 0]
    assert g["vib"] == [{"nome": "Vendedora Inventada", "key": "VENDEDORA INVENTADA", "first": "VENDEDORA",
                         "t": "EXODUS BENEFÍCIOS", "meta": 15}]


def test_sem_creditos_fixados_nada_muda():
    e = entrada()
    e.especialistas.append(copy.deepcopy(VENDEDORA))
    s = rodar(e)
    assert not any(a.get("vf") for a in s.pacotes["all"]["ades"])
    assert not any(a.get("fx") for a in s.pacotes["e:VENDEDORA INVENTADA"]["ades"])


def test_vpend_evita_consultar_de_novo_o_1o_boleto_que_ainda_nao_venceu():
    """18/11: 1º boleto em aberto que ainda não venceu fica no cache vpend; por 3 dias não é consultado de novo."""
    def sga_():
        sga = SGAFalso()
        sga.boletos.append({"data_vencimento": "2026-12-02", "data_vencimento_original": "2026-12-02",
                            "data_emissao": "2026-11-03", "situacao_boleto": "ABERTO", "data_pagamento": None,
                            "veiculos": [{"placa": "ABC1D25", "codigo_veiculo": 103}]})
        return sga
    consultas = lambda sga: sum(1 for c in sga.corpos_boleto if c.get("placa") == "ABC1D25")
    sga = sga_()
    primeira = rodar(entrada(sga=sga))
    assert consultas(sga) == 1
    vp = primeira.pacotes["all"]["vpend"]
    assert vp == {"103|2026-11-02": {"ok": False, "mot": "1º boleto não pago", "sb": "Em aberto", "venc": "2026-12-02",
                                     "at": "2026-11-09"}}
    sga = sga_()
    s = rodar(entrada(sga=sga, old=primeira.pacotes["all"]))   # mesma data: vem do cache
    assert consultas(sga) == 0
    a = next(a for a in s.pacotes["all"]["ades"] if a["pl"] == "ABC1D25")
    assert a["bol"] == "Em aberto" and a["venc"] == "02/12/2026"
    assert s.pacotes["all"]["vpend"] == vp
    sga = sga_()
    e = entrada(sga=sga, old=primeira.pacotes["all"])
    e.agora = datetime(2026, 11, 13, 3, 52, tzinfo=FUSO)        # 4 dias depois: confere de novo
    rodar(e)
    assert consultas(sga) == 1
