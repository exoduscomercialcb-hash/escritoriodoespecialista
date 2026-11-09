"""Busca automática (app/busca/retorno.py) de ponta a ponta, com SGA, Power CRM e BI falsos, em memória.

Todos os dados daqui são inventados (associados, especialistas, placas, telefones). Nunca usar dados reais.
Data da busca: 09/11/2026, 03:52 (Brasília). Meses das adesões: set/26, out/26 e nov/26.
"""
from __future__ import annotations

import copy
import threading
from datetime import date, datetime

import pytest

from app.busca.entrada import Entrada
from app.busca.retorno import rodar
from app.config import FUSO
from app.fontes.sga import SGABloqueado

from .conftest import cpf_inventado

AGORA = datetime(2026, 11, 9, 3, 52, tzinfo=FUSO)
SIT = {"1": "ATIVO", "18": "ATIVO - PENDENTE INSTALACAO", "16": "AGUARDANDO INSTALACAO", "19": "ATIVO - DISPENSA INSTALACAO",
       "6": "CANCELADO"}
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
            return [{"codigo_statusatendimentoassociado": "1", "descricao": "CONCLUIDO"}]
        if caminho.startswith("/veiculo/buscar/") and caminho.endswith("/codigo"):
            cv = int(caminho.split("/")[3])
            for v in self.veiculos:
                if v["codigo_veiculo"] == cv:
                    return [dict(v, nome="ASSOCIADO INVENTADO %d" % cv, ddd_celular="21", telefone_celular="900000%03d" % (cv % 1000),
                                 ano_modelo=2020, tipo="AUTOMOVEL", categoria="PASSEIO", cpf=v["cpf_associado"])]
            return None
        raise AssertionError("caminho do SGA não esperado no teste: " + caminho)


class PowerCRMFalso:
    def __init__(self):
        self.paginas = 0

    def pagina(self, de: str, ate: str, numero: int) -> list[dict]:
        self.paginas += 1
        if numero > 0:
            return []
        return [{"quotationCode": "Q-INVENTADA-1", "cardStatus": 5, "isShelved": "N", "vehiclePlates": "ABC-1D23",
                 "vehicleChassi": "", "clientName": "ASSOCIADO INVENTADO UM", "clientMobile": "5521900000101",
                 "monthlyPaymentsPrice": "R$ 150,00", "monthlyPaymentDiscount": "R$ 15,00", "sentToHinovaDate": "10/09/2026",
                 "createdDate": "08/09/2026", "responsibleSalesman": "VENDEDORA INVENTADA", "clientCity": "CIDADE INVENTADA",
                 "vehicleBrand": "MARCA INVENTADA", "vehicleModel": "MODELO INVENTADO", "observationsDatabase": ""}]


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
    assert s.resumo == {"atualizado": "2026-11-09T03:52-03:00", "base_hoje": 5, "cancelados_recentes": 2, "bi": False}
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
                                  "/listar/historico-atendimento-associado", "/listar/status-atendimento/todos",
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
