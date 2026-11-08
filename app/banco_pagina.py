"""Banco de marcações usado pela página dos cards (coleção + documento), no lugar do banco da página do Claude.

A página chama window.claude.use('db') (app/static/claude_banco.js), que conversa com /api/banco.
Gravação: "comp" e "compconf" só administrador, coordenação e financeiro (só eles dão baixa e conferem valor);
as demais coleções, qualquer pessoa logada.
"""
from __future__ import annotations

import json
import re
import secrets

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .db import Documento, Pessoa
from .servicos import ErroRegra
from .tempo import agora

COLECOES = {"enviados", "comp", "compconf", "reativ", "cancenv"}
SO_GESTAO = {"comp", "compconf"}
GESTAO = {"admin", "coordenacao", "financeiro"}
NOME_VALIDO = re.compile(r"^[A-Za-z0-9_.:@|+-]{1,200}$")
TAMANHO_MAXIMO = 1_000_000  # 1 MB por documento


def _conferir(colecao: str, doc_id: str | None = None) -> None:
    if colecao not in COLECOES:
        raise ErroRegra("Coleção desconhecida.")
    if doc_id is not None and not NOME_VALIDO.match(doc_id):
        raise ErroRegra("Identificador de documento inválido.")


def pode_gravar(p: Pessoa, colecao: str) -> bool:
    return colecao not in SO_GESTAO or p.tipo in GESTAO


def listar(db: Session, colecao: str, limite: int = 2000) -> list[dict]:
    _conferir(colecao)
    docs = db.scalars(select(Documento).where(Documento.colecao == colecao).order_by(Documento.doc_id).limit(limite))
    return [{"id": d.doc_id, "data": json.loads(d.dados)} for d in docs]


def ler(db: Session, colecao: str, doc_id: str) -> dict | None:
    _conferir(colecao, doc_id)
    d = db.get(Documento, (colecao, doc_id))
    return json.loads(d.dados) if d is not None else None


def _gravar(db: Session, colecao: str, doc_id: str, dados: dict, quem: Pessoa | None) -> None:
    texto = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
    if len(texto) > TAMANHO_MAXIMO:
        raise ErroRegra("Documento grande demais.")
    db.merge(Documento(colecao=colecao, doc_id=doc_id, dados=texto, atualizado_em=agora(),
                       atualizado_por=quem.id if quem else None))
    db.commit()


def _exigir_gravacao(quem: Pessoa, colecao: str) -> None:
    if not pode_gravar(quem, colecao):
        raise ErroRegra("Só a coordenação e o financeiro gravam aqui.")


def definir(db: Session, colecao: str, doc_id: str, dados, quem: Pessoa) -> None:
    _conferir(colecao, doc_id)
    _exigir_gravacao(quem, colecao)
    if not isinstance(dados, dict):
        raise ErroRegra("O documento precisa ser um objeto.")
    _gravar(db, colecao, doc_id, dados, quem)


def _juntar(base: dict, novo: dict) -> dict:
    """Atualização: junta os campos; objetos dentro de objetos também são juntados (ex.: {"p": {chave: print}})."""
    saida = dict(base)
    for k, v in novo.items():
        saida[k] = _juntar(saida[k], v) if isinstance(v, dict) and isinstance(saida.get(k), dict) else v
    return saida


def atualizar(db: Session, colecao: str, doc_id: str, dados, quem: Pessoa) -> bool:
    """Devolve False se o documento não existe (a página então usa definir)."""
    _conferir(colecao, doc_id)
    _exigir_gravacao(quem, colecao)
    if not isinstance(dados, dict):
        raise ErroRegra("A atualização precisa ser um objeto.")
    atual = ler(db, colecao, doc_id)
    if atual is None:
        return False
    _gravar(db, colecao, doc_id, _juntar(atual, dados), quem)
    return True


def apagar(db: Session, colecao: str, doc_id: str, quem: Pessoa) -> None:
    _conferir(colecao, doc_id)
    _exigir_gravacao(quem, colecao)
    db.execute(delete(Documento).where(Documento.colecao == colecao, Documento.doc_id == doc_id))
    db.commit()


def adicionar(db: Session, colecao: str, dados, quem: Pessoa) -> str:
    doc_id = secrets.token_hex(10)
    definir(db, colecao, doc_id, dados, quem)
    return doc_id


def importar_colecoes(db: Session, banco: dict) -> int:
    """Da exportação do sistema atual: {coleção: {id do documento: dados}}. Substitui as coleções que vieram."""
    total = 0
    for colecao, docs in (banco or {}).items():
        if colecao not in COLECOES or not isinstance(docs, dict):
            continue
        db.execute(delete(Documento).where(Documento.colecao == colecao))
        for doc_id, dados in docs.items():
            if isinstance(dados, dict) and NOME_VALIDO.match(str(doc_id)):
                db.add(Documento(colecao=colecao, doc_id=str(doc_id), dados=json.dumps(dados, ensure_ascii=False)))
                total += 1
    return total
