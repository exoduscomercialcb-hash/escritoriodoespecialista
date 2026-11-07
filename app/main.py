"""Servidor do Escritório do Especialista.

No Render:  uvicorn --factory app.main:criar_app --host 0.0.0.0 --port $PORT --proxy-headers --forwarded-allow-ips '*'
No computador:  MODO_TESTE=1 uvicorn --factory app.main:criar_app --reload
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from authlib.integrations.starlette_client import OAuth
from fastapi import FastAPI, HTTPException, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

from .config import Config, carregar
from .db import criar_engine, fabrica_de_sessoes, iniciar_banco
from .hosts import NEUTRA, pagina_do_host
from .rotas import ESTATICOS, rotas, rotas_teste
from .rotas_admin import rotas_admin
from .servicos import ErroRegra

PAGINA_NEUTRA = (Path(__file__).parent / "static" / "neutra.html").read_text(encoding="utf-8")

CSP = ("default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; "
       "frame-ancestors 'none'; base-uri 'none'; form-action 'self'; object-src 'none'")


def _cabecalhos(resposta, producao: bool, csp: str = CSP):
    resposta.headers.setdefault("Content-Security-Policy", csp)
    resposta.headers.setdefault("X-Content-Type-Options", "nosniff")
    resposta.headers.setdefault("Referrer-Policy", "same-origin")
    resposta.headers.setdefault("X-Frame-Options", "DENY")
    resposta.headers.setdefault("Cache-Control", "no-cache")
    if producao:
        resposta.headers.setdefault("Strict-Transport-Security", "max-age=31536000")
    return resposta


class EscolhaPorHost(BaseHTTPMiddleware):
    """Olha o endereço de entrada antes de tudo. Endereço desconhecido: página neutra, sem login e sem dados."""

    def __init__(self, app, cfg: Config):
        super().__init__(app)
        self.cfg = cfg

    async def dispatch(self, request: Request, call_next):
        if request.url.path == "/saude":  # o Render confere a saúde do serviço por dentro, com outro host
            return await call_next(request)
        if pagina_do_host(request.headers.get("host"), self.cfg) == NEUTRA:
            resposta = HTMLResponse(PAGINA_NEUTRA, status_code=200 if request.url.path == "/" else 404)
            return _cabecalhos(resposta, self.cfg.em_producao, CSP.replace("style-src 'self'",
                                                                            "style-src 'unsafe-inline'"))
        resposta = await call_next(request)
        return _cabecalhos(resposta, self.cfg.em_producao)


def criar_app(cfg: Config | None = None) -> FastAPI:
    cfg = cfg or carregar()
    engine = criar_engine(cfg.database_url)

    @asynccontextmanager
    async def ciclo(_app: FastAPI):
        iniciar_banco(engine)
        yield
        engine.dispose()

    app = FastAPI(title="Escritório do Especialista", docs_url=None, redoc_url=None, openapi_url=None,
                  lifespan=ciclo)
    app.state.cfg = cfg
    app.state.engine = engine
    app.state.Sessao = fabrica_de_sessoes(engine)

    oauth = OAuth()
    oauth.register(
        "google",
        client_id=cfg.google_client_id,
        client_secret=cfg.google_client_secret,
        authorize_url="https://accounts.google.com/o/oauth2/v2/auth",
        access_token_url="https://oauth2.googleapis.com/token",
        jwks_uri="https://www.googleapis.com/oauth2/v3/certs",
        userinfo_endpoint="https://openidconnect.googleapis.com/v1/userinfo",
        client_kwargs={"scope": "openid email profile", "prompt": "select_account"},
    )
    app.state.oauth = oauth

    # A ordem importa: o último adicionado roda primeiro. O host é conferido antes da sessão.
    app.add_middleware(SessionMiddleware, secret_key=cfg.session_secret, session_cookie="escritorio_sessao",
                       max_age=14 * 24 * 3600, same_site="lax", https_only=cfg.cookie_seguro)
    app.add_middleware(EscolhaPorHost, cfg=cfg)

    @app.exception_handler(ErroRegra)
    async def _erro_regra(_req: Request, exc: ErroRegra):
        return JSONResponse({"erro": str(exc)}, status_code=400)

    @app.exception_handler(HTTPException)
    async def _erro_http(_req: Request, exc: HTTPException):
        return JSONResponse({"erro": exc.detail}, status_code=exc.status_code)

    @app.exception_handler(RequestValidationError)
    async def _erro_validacao(_req: Request, _exc: RequestValidationError):
        return JSONResponse({"erro": "Dados incompletos ou inválidos."}, status_code=422)

    app.mount("/static", StaticFiles(directory=ESTATICOS), name="static")
    app.include_router(rotas)
    app.include_router(rotas_admin)
    if cfg.modo_teste:
        app.include_router(rotas_teste)
    return app
