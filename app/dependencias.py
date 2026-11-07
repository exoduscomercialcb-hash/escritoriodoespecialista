"""Peças usadas pelas rotas: banco, pessoa logada e proteções."""
from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from .config import Config
from .db import Pessoa
from .hosts import nome_do_host
from .servicos import pode_ver_painel


def config(request: Request) -> Config:
    return request.app.state.cfg


def banco(request: Request):
    db: Session = request.app.state.Sessao()
    try:
        yield db
    finally:
        db.close()


def pessoa_logada(request: Request, db: Session = Depends(banco)) -> Pessoa | None:
    """Confere no banco a cada pedido: quem for bloqueado sai na hora."""
    pid = request.session.get("pid")
    if not pid:
        return None
    p = db.get(Pessoa, pid)
    if p is None or p.situacao != "ativo":
        request.session.clear()
        return None
    return p


def exige_pessoa(p: Pessoa | None = Depends(pessoa_logada)) -> Pessoa:
    if p is None:
        raise HTTPException(401, "Entre com o Google para continuar.")
    return p


def exige_painel(request: Request, p: Pessoa = Depends(exige_pessoa)) -> Pessoa:
    if not pode_ver_painel(p, config(request)):
        raise HTTPException(403, "Só o administrador abre o painel.")
    return p


def exige_json(request: Request) -> None:
    """Proteção contra envio de outro site: o pedido tem de ser JSON e vir do mesmo endereço."""
    if not request.headers.get("content-type", "").startswith("application/json"):
        raise HTTPException(415, "Envie os dados em JSON.")
    origem = request.headers.get("origin")
    if origem and nome_do_host(urlsplit(origem).netloc) != nome_do_host(request.headers.get("host")):
        raise HTTPException(403, "Pedido de outro endereço recusado.")


def ip_do_cliente(request: Request) -> str | None:
    return request.client.host if request.client else None
