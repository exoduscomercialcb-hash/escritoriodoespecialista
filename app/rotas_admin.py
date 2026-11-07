"""API do painel do administrador: Cadastros, Links de cadastro e Acessos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from .config import EQUIPES, SITUACOES, TIPOS
from .db import LinkCadastro, Pessoa
from .dependencias import banco, config, exige_json, exige_painel
from .servicos import (atualizar_pessoa, criar_link, data_do_filtro, lideres, limpar_espacos, link_para_json,
                       pessoa_para_json, relatorio_acessos)

rotas_admin = APIRouter(prefix="/api/admin", dependencies=[Depends(exige_painel)])


class CorpoPessoa(BaseModel):
    nome: str | None = None
    tipo: str | None = None
    equipe: str | None = None
    nome_sga: str | None = None
    lider_id: int | None = None
    situacao: str | None = None


class CorpoLinkNovo(BaseModel):
    tipo: str
    validade: str | None = None  # AAAA-MM-DD; vazio = sem validade


class CorpoLink(BaseModel):
    ativo: bool


@rotas_admin.get("/opcoes")
def opcoes(db: Session = Depends(banco)):
    return {"tipos": [{"id": k, "nome": v} for k, v in TIPOS.items()], "equipes": list(EQUIPES),
            "situacoes": list(SITUACOES), "lideres": lideres(db)}


@rotas_admin.get("/pessoas")
def listar_pessoas(situacao: str | None = None, q: str | None = None, db: Session = Depends(banco)):
    consulta = select(Pessoa)
    if situacao in SITUACOES:
        consulta = consulta.where(Pessoa.situacao == situacao)
    ordem = case((Pessoa.situacao == "pendente", 0), (Pessoa.situacao == "ativo", 1), else_=2)
    pessoas = db.scalars(consulta.order_by(ordem, Pessoa.nome)).all()
    termo = limpar_espacos(q).lower()
    if termo:
        pessoas = [p for p in pessoas if termo in " ".join(filter(None, [p.nome, p.email, p.nome_sga, p.equipe,
                                                                         TIPOS.get(p.tipo)])).lower()]
    return {"pessoas": [pessoa_para_json(p) for p in pessoas]}


@rotas_admin.patch("/pessoas/{pessoa_id}", dependencies=[Depends(exige_json)])
def editar_pessoa(pessoa_id: int, corpo: CorpoPessoa, request: Request, db: Session = Depends(banco),
                  quem: Pessoa = Depends(exige_painel)):
    alvo = db.get(Pessoa, pessoa_id)
    if alvo is None:
        raise HTTPException(404, "Cadastro não encontrado.")
    quem = db.get(Pessoa, quem.id)
    alvo = atualizar_pessoa(db, alvo, corpo.model_dump(exclude_unset=True), quem, config(request))
    return {"pessoa": pessoa_para_json(alvo)}


@rotas_admin.get("/links")
def listar_links(request: Request, db: Session = Depends(banco)):
    links = db.scalars(select(LinkCadastro).order_by(LinkCadastro.criado_em.desc(), LinkCadastro.id.desc()))
    return {"links": [link_para_json(link, str(request.base_url)) for link in links]}


@rotas_admin.post("/links", dependencies=[Depends(exige_json)])
def novo_link(corpo: CorpoLinkNovo, request: Request, db: Session = Depends(banco),
              quem: Pessoa = Depends(exige_painel)):
    link = criar_link(db, corpo.tipo, corpo.validade, quem)
    return {"link": link_para_json(link, str(request.base_url))}


@rotas_admin.patch("/links/{link_id}", dependencies=[Depends(exige_json)])
def mudar_link(link_id: int, corpo: CorpoLink, request: Request, db: Session = Depends(banco),
               quem: Pessoa = Depends(exige_painel)):
    link = db.get(LinkCadastro, link_id)
    if link is None:
        raise HTTPException(404, "Link não encontrado.")
    if link.tipo == "admin" and quem.tipo != "admin":
        raise HTTPException(403, "Só o administrador mexe em link de administrador.")
    link.ativo = corpo.ativo
    db.commit()
    return {"link": link_para_json(link, str(request.base_url))}


@rotas_admin.get("/acessos")
def acessos(pessoa_id: int | None = None, equipe: str | None = None, de: str | None = None,
            ate: str | None = None, db: Session = Depends(banco)):
    return relatorio_acessos(db, pessoa_id=pessoa_id, equipe=equipe or None, de=data_do_filtro(de),
                             ate=data_do_filtro(ate))
