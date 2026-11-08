"""API do painel do administrador: Cadastros, Links de cadastro e Acessos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from .cadastro import MODELO_PLANILHA, criar_pre_cadastro, importar_planilha
from .config import EQUIPES, SITUACOES, TIPOS
from .db import Pessoa
from .dependencias import banco, config, exige_json, exige_painel
from .servicos import (atualizar_pessoa, data_do_filtro, lideres, limpar_espacos, pessoa_para_json, relatorio_acessos,
                       so_numeros)

rotas_admin = APIRouter(prefix="/api/admin", dependencies=[Depends(exige_painel)])


class CorpoPessoa(BaseModel):
    nome: str | None = None
    tipo: str | None = None
    equipe: str | None = None
    nome_sga: str | None = None
    lider_id: int | None = None
    situacao: str | None = None
    cpf: str | None = None
    whatsapp: str | None = None


class CorpoPessoaNova(BaseModel):
    nome: str
    tipo: str
    cpf: str
    equipe: str | None = None
    nome_sga: str | None = None
    lider_id: int | None = None
    whatsapp: str | None = None


class CorpoPlanilha(BaseModel):
    texto: str


@rotas_admin.get("/opcoes")
def opcoes(db: Session = Depends(banco)):
    return {"tipos": [{"id": k, "nome": v} for k, v in TIPOS.items()], "equipes": list(EQUIPES),
            "situacoes": list(SITUACOES), "lideres": lideres(db)}


@rotas_admin.get("/pessoas")
def listar_pessoas(situacao: str | None = None, q: str | None = None, db: Session = Depends(banco)):
    consulta = select(Pessoa)
    if situacao in SITUACOES:
        consulta = consulta.where(Pessoa.situacao == situacao)
    elif situacao == "aguardando":  # cadastrado pela coordenação e ainda não entrou com o Google
        consulta = consulta.where(Pessoa.email.is_(None), Pessoa.situacao != "bloqueado")
    ordem = case((Pessoa.situacao == "pendente", 0), (Pessoa.situacao == "ativo", 1), else_=2)
    pessoas = db.scalars(consulta.order_by(ordem, Pessoa.nome)).all()
    termo = limpar_espacos(q).lower()
    if termo:
        numeros = so_numeros(termo)
        pessoas = [p for p in pessoas
                   if termo in " ".join(filter(None, [p.nome, p.email, p.nome_sga, p.equipe, TIPOS.get(p.tipo)])).lower()
                   or (len(numeros) >= 4 and numeros in (p.cpf or "") + " " + (p.whatsapp or ""))]
    return {"pessoas": [pessoa_para_json(p) for p in pessoas]}


@rotas_admin.post("/pessoas", dependencies=[Depends(exige_json)])
def nova_pessoa(corpo: CorpoPessoaNova, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    """Cadastro feito pela coordenação. A pessoa só ganha acesso quando abrir o link do tipo dela."""
    p = criar_pre_cadastro(db, corpo.model_dump(), db.get(Pessoa, quem.id))
    return {"pessoa": pessoa_para_json(p)}


@rotas_admin.post("/importar", dependencies=[Depends(exige_json)])
def importar(corpo: CorpoPlanilha, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    return importar_planilha(db, corpo.texto, db.get(Pessoa, quem.id))


@rotas_admin.get("/modelo-planilha.csv")
def modelo_planilha():
    return Response(MODELO_PLANILHA, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="modelo-cadastro-escritorio.csv"'})


@rotas_admin.patch("/pessoas/{pessoa_id}", dependencies=[Depends(exige_json)])
def editar_pessoa(pessoa_id: int, corpo: CorpoPessoa, request: Request, db: Session = Depends(banco),
                  quem: Pessoa = Depends(exige_painel)):
    alvo = db.get(Pessoa, pessoa_id)
    if alvo is None:
        raise HTTPException(404, "Cadastro não encontrado.")
    quem = db.get(Pessoa, quem.id)
    alvo = atualizar_pessoa(db, alvo, corpo.model_dump(exclude_unset=True), quem, config(request))
    return {"pessoa": pessoa_para_json(alvo)}


@rotas_admin.get("/acessos")
def acessos(pessoa_id: int | None = None, equipe: str | None = None, de: str | None = None,
            ate: str | None = None, db: Session = Depends(banco)):
    return relatorio_acessos(db, pessoa_id=pessoa_id, equipe=equipe or None, de=data_do_filtro(de),
                             ate=data_do_filtro(ate))
