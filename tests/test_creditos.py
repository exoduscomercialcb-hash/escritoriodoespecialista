"""Créditos fixados do Inside Sales lidos da aba "CRÉDITOS FIXADOS" (Google simulado; dados inventados)."""
import httpx2

from app.creditos import atualizar_creditos, creditos_da_planilha
from app.dados import guardar, ler

from .conftest import cfg_teste
from .test_google import CHAVE

TITULOS = ["Placa", "Nome preservado", "Responsável pela meta", "Origem fixada", "Competência", "Data do crédito",
           "Quantidade", "Cotação Power CRM", "Código SGA", "Regra", "Autorização", "Conferência CRM"]
LINHAS = [TITULOS,
          ["ABC1D23", "Associado Inventado Um", "VENDEDORA", "Parceiro", "2026-10", "28/10/2026", "1", "x", "Não informado"],
          ["Não informada", "ASSOCIADO INVENTADO DOIS", "Vendedora", "Indicador", "2026-10", "", "1", "", "13957"],
          ["", "", "", "linha vazia"],
          ["abc-1d24", "Associado Inventado Tres", "VENDEDORA", "", "outubro"]]


def test_linhas_da_aba_viram_o_formato_do_creditos_fixados():
    assert creditos_da_planilha(LINHAS) == [
        {"placa": "ABC1D23", "nome": "Associado Inventado Um", "resp": "VENDEDORA", "comp": "2026-10", "cv": ""},
        {"placa": "", "nome": "ASSOCIADO INVENTADO DOIS", "resp": "VENDEDORA", "comp": "2026-10", "cv": "13957"},
        {"placa": "ABC1D24", "nome": "Associado Inventado Tres", "resp": "VENDEDORA", "comp": "", "cv": ""},
    ]
    assert creditos_da_planilha([]) == [] and creditos_da_planilha([TITULOS]) == []


def _google(resposta):
    def responder(pedido):
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": 3600})
        assert "CR%C3%89DITOS%20FIXADOS" in str(pedido.url)
        return resposta
    return httpx2.Client(transport=httpx2.MockTransport(responder))


CFG = cfg_teste(google_service_account_json=CHAVE, planilha_inside_sales="planilha-inventada")


def test_busca_le_a_planilha_e_guarda(db):
    itens = atualizar_creditos(db, CFG, http=_google(httpx2.Response(200, json={"values": LINHAS})))
    assert len(itens) == 3 and ler(db, "creditos_fixados") == itens


def test_planilha_fora_do_ar_vale_a_ultima_lista(db):
    guardar(db, "creditos_fixados", [{"placa": "ABC1D23", "resp": "VENDEDORA"}], "planilha")
    db.commit()
    assert atualizar_creditos(db, CFG, http=_google(httpx2.Response(500))) == [{"placa": "ABC1D23", "resp": "VENDEDORA"}]
    assert atualizar_creditos(db, cfg_teste()) == [{"placa": "ABC1D23", "resp": "VENDEDORA"}]  # sem Google configurado
