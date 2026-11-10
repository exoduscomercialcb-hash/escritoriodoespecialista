"""Rotas públicas: páginas, login com Google, cadastro pelo link e API da pessoa logada."""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import quote

from authlib.integrations.starlette_client import OAuthError
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

from . import banco_pagina as bp
from .dados import ler as ler_pacote
from .dados import pacote_da_pessoa
from .db import Pessoa
from .dependencias import banco, config, exige_json, exige_pessoa, ip_do_cliente, pessoa_logada
from .servicos import (MSG_NAO_LIBERADO, achar_pessoa, concluir_login, lista_de_equipes, pessoa_para_json,
                       pode_ver_painel, primeiro_acesso, registrar_acesso)

ESTATICOS = Path(__file__).parent / "static"
PAGINA = ESTATICOS / "escritorio.html"
PAGINA_CARDS = Path(__file__).parent / "paginas" / "cards.html"  # gerada da página atual (ver AGENTS.md)
RTCFG_PADRAO = (Path(__file__).parent / "paginas" / "rtcfg_padrao.json").read_text(encoding="utf-8")
# A página dos cards carrega a biblioteca de PDF (jsdelivr), as fontes do Google e envia prints e comprovantes pelo
# Apps Script do Google; desenha com estilos dentro do HTML. Só esses endereços ficam liberados.
CSP_CARDS = ("default-src 'self'; script-src 'self' https://cdn.jsdelivr.net; "
             "style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; font-src 'self' https://fonts.gstatic.com; "
             "img-src 'self' data: blob: https:; connect-src 'self' https://script.google.com "
             "https://script.googleusercontent.com; frame-ancestors 'none'; base-uri 'none'; "
             "form-action 'self' https://script.google.com; object-src 'none'")

# Texto obrigatório perto do botão "Atualizar meus dados" (seção 3 da especificação).
TEXTO_ATUALIZAR = ("Puxa do SGA os seus contratos e boletos mais recentes. Pode usar 1 vez a cada 15 minutos. "
                   "O sistema também atualiza sozinho de hora em hora.")

rotas = APIRouter()
rotas_teste = APIRouter()


@rotas.get("/saude", include_in_schema=False)
def saude():
    return {"ok": True}


@rotas.get("/", include_in_schema=False)
def pagina():
    return FileResponse(PAGINA, media_type="text/html; charset=utf-8")


# ---------------------------------------------------------------- links curtos de campanha
# Pedido do Rafael (10/11): link de uma linha no fim da mensagem da Black Friday. O lead toca e abre o WhatsApp do
# especialista com a mensagem dele já escrita. Sem login e sem dados de ninguém: só o número comercial e o texto.
LINKS_CURTOS = {
    "bf": ("5521967950692", "Recebi uma mensagem do Miguelzinho sobre condições especiais para proteger meu veículo "
                            "e gostaria de saber mais sobre essa oportunidade!"),
}


def _destino_whatsapp(numero: str, texto: str) -> str:
    return "https://api.whatsapp.com/send?phone=" + numero + "&text=" + quote(texto, safe="")


def _rota_link_curto(codigo: str):
    numero, texto = LINKS_CURTOS[codigo]

    def abrir():
        return RedirectResponse(_destino_whatsapp(numero, texto), status_code=302)
    rotas.add_api_route("/" + codigo, abrir, methods=["GET"], include_in_schema=False, name="link_" + codigo)


for _codigo in LINKS_CURTOS:
    _rota_link_curto(_codigo)


# ---------------------------------------------------------------- login com Google

def _bloco_json(valor) -> str:
    """JSON dentro de <script type="application/json">: sem "</" para não fechar o bloco antes da hora."""
    return json.dumps(valor, ensure_ascii=False).replace("</", "<\\/")


@rotas.get("/escritorio", include_in_schema=False)
def escritorio(db: Session = Depends(banco), p: Pessoa | None = Depends(pessoa_logada)):
    """Os cards (a página atual, lendo /api/dados e /api/banco)."""
    if p is None:
        return RedirectResponse("/", status_code=303)
    rtcfg = ler_pacote(db, "rtcfg")
    html = (PAGINA_CARDS.read_text(encoding="utf-8")
            .replace("__RTCFG__", _bloco_json(rtcfg) if rtcfg is not None else RTCFG_PADRAO)
            .replace("__MOTIVOS__", _bloco_json(ler_pacote(db, "motivos"))))
    return HTMLResponse(html, headers={"Content-Security-Policy": CSP_CARDS})


@rotas.get("/auth/login", include_in_schema=False)
async def auth_login(request: Request):
    if not config(request).google_configurado:
        return HTMLResponse("<!doctype html><meta charset=utf-8><title>Escritório do Especialista</title>"
                            "<p>O login com Google ainda não foi configurado no servidor.</p>", status_code=503)
    request.session.pop("google", None)
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
def teste_entrar(request: Request, email: str, nome: str = "Pessoa de Teste", db: Session = Depends(banco)):
    """Login sem Google, só para os testes automáticos. Não existe no Render (ver config.modo_teste)."""
    destino = concluir_login(db, request.session, config(request), email=email, sub="teste-" + email.lower(),
                             nome=nome, ip=ip_do_cliente(request))
    return RedirectResponse(destino, status_code=303)


# ---------------------------------------------------------------- API

class CorpoCadastro(BaseModel):
    cpf: str
    whatsapp: str


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
    resposta = {"estado": existente.situacao if existente else "sem_cadastro", "email": google["email"],
                "nome": google.get("nome"), "mensagem": MSG_NAO_LIBERADO}
    if google.get("conta_do_cpf"):
        resposta["dica"] = (f"O CPF que você informou entra com a conta Google {google['conta_do_cpf']}. "
                            "Clique em Entrar com outra conta e use essa.")
    return resposta


@rotas.post("/api/primeiro-acesso", dependencies=[Depends(exige_json)])
def api_primeiro_acesso(corpo: CorpoCadastro, request: Request, db: Session = Depends(banco)):
    """Primeiro acesso: CPF e WhatsApp. Responde para onde seguir (login do Google ou já para dentro)."""
    return {"ok": True, "proximo": primeiro_acesso(db, request.session, corpo.cpf, corpo.whatsapp,
                                                   ip_do_cliente(request))}


@rotas.post("/api/acesso", dependencies=[Depends(exige_json)])
def acesso(corpo: CorpoAcesso, request: Request, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    registrar_acesso(db, p, corpo.aba, ip_do_cliente(request))
    return {"ok": True}


@rotas.get("/api/dados")
def dados(request: Request, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    """O pacote da pessoa logada para os cards (o mesmo formato da página atual)."""
    resposta = pacote_da_pessoa(db, p)
    resposta["painel"] = pode_ver_painel(p, config(request))
    resposta["perfil"]["nome"] = p.nome
    resposta["perfil"]["equipes"] = lista_de_equipes(p.equipe)
    return resposta


# ---------------------------------------------------------------- banco de marcações da página dos cards

@rotas.get("/api/banco/{colecao}")
def banco_listar(colecao: str, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    return {"docs": bp.listar(db, colecao)}


@rotas.post("/api/banco/{colecao}", dependencies=[Depends(exige_json)])
async def banco_adicionar(colecao: str, request: Request, db: Session = Depends(banco),
                          p: Pessoa = Depends(exige_pessoa)):
    return {"id": bp.adicionar(db, colecao, await request.json(), p)}


@rotas.get("/api/banco/{colecao}/{doc_id}")
def banco_ler(colecao: str, doc_id: str, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    dados = bp.ler(db, colecao, doc_id)
    return {"exists": dados is not None, "data": dados}


@rotas.put("/api/banco/{colecao}/{doc_id}", dependencies=[Depends(exige_json)])
async def banco_definir(colecao: str, doc_id: str, request: Request, db: Session = Depends(banco),
                        p: Pessoa = Depends(exige_pessoa)):
    bp.definir(db, colecao, doc_id, await request.json(), p)
    return {"ok": True}


@rotas.patch("/api/banco/{colecao}/{doc_id}", dependencies=[Depends(exige_json)])
async def banco_atualizar(colecao: str, doc_id: str, request: Request, db: Session = Depends(banco),
                          p: Pessoa = Depends(exige_pessoa)):
    if not bp.atualizar(db, colecao, doc_id, await request.json(), p):
        raise HTTPException(404, "Documento não existe.")
    return {"ok": True}


@rotas.delete("/api/banco/{colecao}/{doc_id}", dependencies=[Depends(exige_json)])
def banco_apagar(colecao: str, doc_id: str, db: Session = Depends(banco), p: Pessoa = Depends(exige_pessoa)):
    bp.apagar(db, colecao, doc_id, p)
    return {"ok": True}


@rotas.get("/api/meus-dados/situacao")
def situacao_meus_dados(p: Pessoa = Depends(exige_pessoa)):
    """Botão "Atualizar meus dados": o lugar já existe; a busca no SGA entra na etapa 2."""
    return {"disponivel": False, "motivo": "em_breve", "texto": TEXTO_ATUALIZAR, "ultima_atualizacao_txt": None}
