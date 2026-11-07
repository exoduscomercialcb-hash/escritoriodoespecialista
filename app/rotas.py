"""Rotas públicas: páginas, login com Google, cadastro pelo link e API da pessoa logada."""
from __future__ import annotations

from pathlib import Path

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from .config import TIPOS
from .db import Pessoa
from .dependencias import banco, config, exige_json, exige_pessoa, ip_do_cliente, pessoa_logada
from .servicos import (MSG_NAO_LIBERADO, achar_pessoa, cadastrar, concluir_login, link_valido, pessoa_para_json,
                       pode_ver_painel, registrar_acesso)

ESTATICOS = Path(__file__).parent / "static"
PAGINA = ESTATICOS / "escritorio.html"

# Texto obrigatório perto do botão "Atualizar meus dados" (seção 3 da especificação).
TEXTO_ATUALIZAR = ("Puxa do SGA os seus contratos e boletos mais recentes. Pode usar 1 vez a cada 15 minutos. "
                   "O sistema também atualiza sozinho de hora em hora.")

rotas = APIRouter()
rotas_teste = APIRouter()


@rotas.get("/saude", include_in_schema=False)
def saude():
    return {"ok": True}


@rotas.get("/", include_in_schema=False)
@rotas.get("/cadastro/{codigo}", include_in_schema=False)
def pagina():
    return FileResponse(PAGINA, media_type="text/html; charset=utf-8")


# ---------------------------------------------------------------- login com Google

@rotas.get("/auth/login", include_in_schema=False)
async def auth_login(request: Request, link: str | None = None, db: Session = Depends(banco)):
    if not config(request).google_configurado:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Escritório do Especialista</title>"
                            "<p>O login com Google ainda não foi configurado no servidor.</p>", status_code=503)
    request.session.pop("google", None)
    if link and link_valido(db, link):
        request.session["link"] = link
    destino = str(request.url_for("auth_callback"))
    return await request.app.state.oauth.google.authorize_redirect(request, destino)


@rotas.get("/auth/callback", name="auth_callback", include_in_schema=False)
async def auth_callback(request: Request, db: Session = Depends(banco)):
    try:
        token = await request.app.state.oauth.google.authorize_access_token(request)
    except OAuthError:
        return RedirectResponse("/?erro=google", status_code=303)
    info = token.get("userinfo") or {}
    if not info.get("email") or not info.get("email_verified"):
        return RedirectResponse("/?erro=email", status_code=303)
    destino = concluir_login(db, request.session, config(request), email=info["email"], sub=info.get("sub"),
                             nome=info.get("name"), ip=ip_do_cliente(request))
    return RedirectResponse(destino, status_code=303)


@rotas.get("/auth/sair", include_in_schema=False)
def auth_sair(request: Request):
    request.session.clear()
    return RedirectResponse("/", status_code=303)


@rotas_teste.get("/teste/entrar", include_in_schema=False)
def teste_entrar(request: Request, email: str, nome: str = "Pessoa de Teste", link: str | None = None,
                 db: Session = Depends(banco)):
    """Login sem Google, só para os testes automáticos. Não existe no Render (ver config.modo_teste)."""
    if link:
        request.session["link"] = link
    destino = concluir_login(db, request.session, config(request), email=email, sub="teste-" + email.lower(),
                             nome=nome, ip=ip_do_cliente(request))
    return RedirectResponse(destino, status_code=303)


# ---------------------------------------------------------------- API

class CorpoCadastro(BaseModel):
    nome: str


class CorpoAcesso(BaseModel):
    aba: str


@rotas.get("/api/eu")
def eu(request: Request, db: Session = Depends(banco), p: Pessoa | None = Depends(pessoa_logada)):
    cfg = config(request)
    if p is not None:
        return {"estado": "ativo", "pessoa": pessoa_para_json(p), "painel": pode_ver_painel(p, cfg)}
    google = request.session.get("google")
    if not google:
        return {"estado": "anonimo", "google_configurado": cfg.google_configurado}
    existente = achar_pessoa(db, google["email"], google.get("sub"))
    if existente is not None and existente.situacao == "ativo":  # aprovado depois que entrou: só entrar de novo
        return {"estado": "anonimo", "google_configurado": cfg.google_configurado,
                "aviso": "Seu acesso foi liberado. Entre com o Google."}
    return {"estado": existente.situacao if existente else "sem_cadastro", "email": google["email"],
            "nome": google.get("nome"), "link": request.session.get("link"), "mensagem": MSG_NAO_LIBERADO}


@rotas.get("/api/cadastro/{codigo}")
def info_do_link(codigo: str, db: Session = Depends(banco)):
    link = link_valido(db, codigo)
    if link is None:
        return {"valido": False, "mensagem": "Este link de cadastro não vale mais. Peça um novo à coordenação."}
    return {"valido": True, "tipo": link.tipo, "tipo_nome": TIPOS[link.tipo]}


@rotas.post("/api/cadastro/{codigo}", dependencies=[Depends(exige_json)])
def enviar_cadastro(codigo: str, corpo: CorpoCadastro, request: Request, db: Session = Depends(banco)):
    cadastrar(db, request.session, codigo, corpo.nome)
    return {"estado": "pendente", "mensagem": MSG_NAO_LIBERADO}


@rotas.post("/api/acesso", dependencies=[Depends(exige_json)])
def acesso(corpo: CorpoAcesso, request: Request, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    registrar_acesso(db, p, corpo.aba, ip_do_cliente(request))
    return {"ok": True}


@rotas.get("/api/meus-dados/situacao")
def situacao_meus_dados(p: Pessoa = Depends(exige_pessoa)):
    """Botão "Atualizar meus dados": o lugar já existe; a busca no SGA entra na etapa 2."""
    return {"disponivel": False, "motivo": "em_breve", "texto": TEXTO_ATUALIZAR, "ultima_atualizacao_txt": None}
