"""Dados das telas (os cards): importação do sistema atual e o pacote de cada pessoa.

O formato dos pacotes é o mesmo que a página atual já sabe desenhar (`E.data` e `specs[].rows` em
referencia/pagina_atual.html). Ver docs/PLANO_ETAPAS_2_E_3.md.
"""
from __future__ import annotations

import json
import unicodedata
from datetime import datetime

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .banco_pagina import importar_colecoes
from .db import Pacote, Pessoa
from .servicos import ErroRegra, lista_de_equipes
from .tempo import agora, formatar

PERFIS_GERAIS = {"admin", "coordenacao", "financeiro", "cadastro"}


def N(texto) -> str:
    """Igual ao script atual: sem acento, maiúsculas e espaços simples ("Pé no Chão" -> "PE NO CHAO")."""
    return " ".join(unicodedata.normalize("NFKD", str(texto or "")).encode("ascii", "ignore").decode().upper().split())


# ---------------------------------------------------------------- guardar e ler

def guardar(db: Session, chave: str, dados, origem: str) -> None:
    db.merge(Pacote(chave=chave, dados=json.dumps(dados, ensure_ascii=False, separators=(",", ":")), origem=origem,
                    atualizado_em=agora()))


def ler(db: Session, chave: str):
    p = db.get(Pacote, chave)
    return json.loads(p.dados) if p is not None else None


def chaves(db: Session, prefixo: str) -> list[str]:
    return list(db.scalars(select(Pacote.chave).where(Pacote.chave.like(prefixo + "%")).order_by(Pacote.chave)))


# ---------------------------------------------------------------- importação do sistema atual

def importar_sistema_atual(db: Session, exp) -> dict:
    """Substitui tudo o que veio de importação anterior. Confere o formato antes de gravar."""
    if not isinstance(exp, dict) or not isinstance(exp.get("evo"), dict) or not isinstance(exp["evo"].get("all"), dict):
        raise ErroRegra("Arquivo fora do formato: falta o bloco evo.all (veja docs/PLANO_ETAPAS_2_E_3.md).")
    evo = exp["evo"]
    if not isinstance(evo["all"].get("meses_base"), list) or not evo["all"]["meses_base"]:
        raise ErroRegra("Arquivo fora do formato: evo.all.meses_base vazio.")
    especialistas = exp.get("especialistas") or []
    if not isinstance(especialistas, list) or not all(isinstance(x, dict) and x.get("nome") for x in especialistas):
        raise ErroRegra("Arquivo fora do formato: especialistas precisa ser uma lista com nome.")

    db.execute(delete(Pacote).where(Pacote.origem == "importacao"))
    guardar(db, "all", evo["all"], "importacao")
    for equipe, obj in (evo.get("t") or {}).items():
        guardar(db, "t:" + N(equipe), obj, "importacao")
    for nome, obj in (evo.get("e") or {}).items():
        guardar(db, "e:" + N(nome), obj, "importacao")
    linhas = 0
    for x in especialistas:
        nome = N(x["nome"])
        rows = x.get("rows") or []
        linhas += len(rows)
        # como o especialista está no spec_keys.json do Kit (sem a chave "k"): a busca automática usa id, ld e rot
        guardar(db, "esp:" + nome, {"id": x.get("id"), "nome": x["nome"], "sga": [N(s) for s in (x.get("sga") or [])],
                                    "eqs": x.get("eqs") or [], "carteira": x.get("carteira"), "rot": x.get("rot") or "",
                                    "ld": x.get("ld")}, "importacao")
        guardar(db, "rm:" + nome, rows, "importacao")
    for bloco in ("motivos", "rtcfg", "comp_registro"):
        if exp.get(bloco) is not None:
            guardar(db, bloco, exp[bloco], "importacao")
    marcacoes = importar_colecoes(db, exp.get("banco") or {})
    guardar(db, "importacao", {"gerado_em": exp.get("gerado_em"), "importado_em": agora().isoformat(),
                               "marcacoes": marcacoes}, "importacao")
    db.commit()
    return resumo_da_importacao(db)


def resumo_da_importacao(db: Session) -> dict:
    info = ler(db, "importacao")
    if info is None:
        return {"importado": False}
    geral = ler(db, "all") or {}
    meses = geral.get("meses_base") or []
    sem_ligacao = []
    for p in db.scalars(select(Pessoa).where(Pessoa.situacao != "bloqueado").order_by(Pessoa.nome)):
        if p.tipo in PERFIS_GERAIS:
            continue
        if _chave_do_pacote(db, p) is None:
            sem_ligacao.append({"id": p.id, "nome": p.nome, "tipo": p.tipo})
    return {
        "importado": True, "gerado_em": info.get("gerado_em"), "importado_em_txt": formatar(_data(info)),
        "meses": [meses[0], meses[-1]] if meses else [], "equipes": [c[2:] for c in chaves(db, "t:")],
        "especialistas": len(chaves(db, "esp:")), "linhas_remarketing": sum(len(ler(db, c) or []) for c in chaves(db, "rm:")),
        "marcacoes": info.get("marcacoes", 0),
        "sem_ligacao": sem_ligacao,
    }


def _data(info: dict):
    try:
        return datetime.fromisoformat(info["importado_em"])
    except (KeyError, TypeError, ValueError):
        return None


# ---------------------------------------------------------------- o pacote de cada pessoa

def _especialista_da_pessoa(db: Session, p: Pessoa) -> str | None:
    """Acha o especialista do sistema atual pelo nome completo do cadastro (igual ao nome no SGA)."""
    alvo = N(p.nome)
    for chave in chaves(db, "esp:"):
        esp = ler(db, chave) or {}
        if alvo == chave[4:] or alvo in (esp.get("sga") or []):
            return chave[4:]
    return None


def _chave_do_pacote(db: Session, p: Pessoa) -> str | None:
    if p.tipo in PERFIS_GERAIS:
        return "all"
    if p.tipo == "lider":
        for equipe in lista_de_equipes(p.equipe):
            if db.get(Pacote, "t:" + N(equipe)) is not None:
                return "t:" + N(equipe)
        return None
    nome = _especialista_da_pessoa(db, p)
    return "e:" + nome if nome and db.get(Pacote, "e:" + nome) is not None else None


def _lista(db: Session, nome: str) -> dict:
    esp = ler(db, "esp:" + nome) or {}
    return {"nome": esp.get("nome") or nome, "equipes": esp.get("eqs") or [], "rows": ler(db, "rm:" + nome) or []}


def pacote_da_pessoa(db: Session, p: Pessoa) -> dict:
    """O que a página precisa para desenhar os cards desta pessoa (cada um só vê o que é seu)."""
    chave = _chave_do_pacote(db, p)
    perfil = {"tipo": p.tipo, "admin": p.tipo in {"admin", "coordenacao", "cadastro"}, "fin": p.tipo == "financeiro",
              "cad": p.tipo == "cadastro"}
    if p.tipo in {"admin", "coordenacao", "cadastro"}:
        specs = [_lista(db, c[3:]) for c in chaves(db, "rm:")]
    elif p.tipo == "lider":
        equipes = {N(e) for e in lista_de_equipes(p.equipe)}
        specs = [_lista(db, c[4:]) for c in chaves(db, "esp:")
                 if {N(e) for e in (ler(db, c) or {}).get("eqs") or []} & equipes]
    elif p.tipo == "financeiro":
        specs = []
    else:
        nome = _especialista_da_pessoa(db, p)
        specs = [_lista(db, nome)] if nome else []
    info = ler(db, "importacao") or {}
    return {"perfil": perfil, "pacote": ler(db, chave) if chave else None, "specs": specs,
            "motivos": ler(db, "motivos"), "rtcfg": ler(db, "rtcfg"), "dados_de": info.get("gerado_em")}
