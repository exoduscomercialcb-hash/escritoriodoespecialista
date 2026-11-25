"""Créditos fixados do Inside Sales: aba "CRÉDITOS FIXADOS" da planilha "Ativação Inside Sales" (regra de 19/11).

Venda fechada pela vendedora interna e transferida a outro especialista a pedido da diretoria: fica com o especialista de
destino e também conta para a vendedora (app/busca/retorno.py, campos vf/vfm). O sistema atual monta o
creditos_fixados.json a partir desta aba antes de cada atualização; aqui a busca lê a aba direto, pela conta de serviço.
Se o Google falhar, vale a última lista lida (pacote "creditos_fixados" do banco).
"""
from __future__ import annotations

import logging
import re

from sqlalchemy.orm import Session

from .config import Config
from .dados import N, guardar, ler
from .fontes.google import ClienteGoogle, GoogleErro

log = logging.getLogger("escritorio")

ABA = "CRÉDITOS FIXADOS"
INTERVALO = f"'{ABA}'!A:L"
PLACA = re.compile(r"^[A-Z]{3}[0-9][A-Z0-9][0-9]{2}$")


def _pl(s) -> str:
    return re.sub(r"[^A-Z0-9]", "", N(s))


def creditos_da_planilha(linhas: list[list]) -> list[dict]:
    """Linhas da aba (a 1ª com os títulos) -> itens {placa, nome, resp, comp, cv}, como o creditos_fixados.json."""
    if not linhas:
        return []
    titulos = [N(t) for t in linhas[0]]

    def col(linha, *nomes):
        for nome in nomes:
            if nome in titulos and titulos.index(nome) < len(linha):
                return str(linha[titulos.index(nome)] or "").strip()
        return ""

    saida = []
    for linha in linhas[1:]:
        resp = N(col(linha, "RESPONSAVEL PELA META", "RESPONSAVEL"))
        placa = _pl(col(linha, "PLACA"))
        cv = col(linha, "CODIGO SGA")
        comp = col(linha, "COMPETENCIA")
        item = {"placa": placa if PLACA.match(placa) else "", "nome": col(linha, "NOME PRESERVADO", "NOME"),
                "resp": resp, "comp": comp if re.fullmatch(r"\d{4}-\d{2}", comp) else "",
                "cv": cv if cv.isdigit() else ""}
        if resp and (item["placa"] or item["cv"] or item["nome"]):
            saida.append(item)
    return saida


def atualizar_creditos(db: Session, cfg: Config, http=None) -> list[dict]:
    """Lê a aba e guarda no banco. Sem Google configurado ou com erro: devolve a última lista guardada."""
    if cfg.google_service_account_json and cfg.planilha_inside_sales:
        cliente = None
        try:
            cliente = ClienteGoogle(cfg.google_service_account_json, http=http)
            itens = creditos_da_planilha(cliente.valores(cfg.planilha_inside_sales, INTERVALO))
            guardar(db, "creditos_fixados", itens, "planilha")
            db.commit()
            log.info("busca: créditos fixados lidos da planilha: %d", len(itens))
            return itens
        except GoogleErro as e:
            log.warning("Créditos fixados: planilha não lida (%s); vale a última lista guardada.", e)
        finally:
            if cliente is not None and http is None:
                cliente.fechar()
    return ler(db, "creditos_fixados") or []
