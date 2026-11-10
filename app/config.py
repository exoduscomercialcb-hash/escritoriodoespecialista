"""Configuração lida das variáveis de ambiente (nunca do código).

No Render, a variável RENDER existe sempre. Ela liga as proteções de produção:
- banco, segredo da sessão e login com Google passam a ser obrigatórios;
- o cookie da sessão só anda por HTTPS;
- a rota de login de teste fica desligada, mesmo se MODO_TESTE estiver ligado.
"""
from __future__ import annotations

import os
import secrets
from dataclasses import dataclass, field
from urllib.parse import quote
from zoneinfo import ZoneInfo

FUSO = ZoneInfo("America/Sao_Paulo")

# Tipos de acesso (os mesmos do sistema atual) e o nome que aparece na tela.
TIPOS = {
    "admin": "Administrador",
    "coordenacao": "Coordenação",
    "financeiro": "Financeiro",
    "cadastro": "Cadastro",
    "lider": "Líder",
    "vendedora_interna": "Vendedora interna",
    "especialista": "Especialista",
}

EQUIPES = ("Recreio", "Lua", "Elite", "Águias", "Pé no Chão", "Tubarões", "Magnatas", "Elim", "Exodus Benefícios")

SITUACOES = ("pendente", "ativo", "bloqueado")

HOST_ESCRITORIO_PADRAO = "escritorio.exodusbeneficios.com.br"


def _lista(valor: str | None) -> list[str]:
    return [p.strip().lower() for p in (valor or "").split(",") if p.strip()]


def _sim(valor: str | None) -> bool:
    return (valor or "").strip().lower() in {"1", "sim", "true", "yes", "on"}


MARCA_DA_SENHA = "[YOUR-PASSWORD]"


def montar_url_do_banco(url: str | None, senha: str | None) -> str:
    """Junta o endereço do Supabase (copiado como vem, com [YOUR-PASSWORD]) com a senha da DATABASE_PASSWORD.

    Assim ninguém precisa editar a senha no meio do endereço, e símbolos na senha (@, #, /) não quebram nada.
    Se DATABASE_PASSWORD estiver vazia, vale a senha que já estiver escrita no endereço.
    """
    url = (url or "").strip()
    if any(c.isspace() for c in url):
        raise ConfigInvalida("DATABASE_URL tem espaço ou quebra de linha no meio. "
                             "Copie de novo o endereço do Supabase e cole em uma linha só.")
    senha = (senha or "").strip("\r\n")
    if not url or not senha:
        if MARCA_DA_SENHA in url:
            raise ConfigInvalida("DATABASE_URL ainda tem [YOUR-PASSWORD]. "
                                 "Cadastre a senha do banco na variável DATABASE_PASSWORD.")
        return url
    esquema, separador, resto = url.partition("://")
    credenciais, arroba, servidor = resto.rpartition("@")
    if not separador or not arroba or not credenciais:
        raise ConfigInvalida("DATABASE_URL não está no formato do Supabase. "
                             "Copie o endereço do Session pooler (começa com postgresql://postgres.).")
    usuario = credenciais.split(":", 1)[0]
    return f"{esquema}://{usuario}:{quote(senha, safe='')}@{servidor}"


def url_do_banco(url: str) -> str:
    """O Supabase entrega 'postgresql://...'; o SQLAlchemy com psycopg 3 quer 'postgresql+psycopg://...'."""
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    if url.startswith("postgresql://"):
        url = "postgresql+psycopg://" + url[len("postgresql://"):]
    return url


@dataclass
class Config:
    database_url: str
    session_secret: str
    google_client_id: str = ""
    google_client_secret: str = ""
    admin_emails: frozenset[str] = frozenset()
    hosts_escritorio: frozenset[str] = frozenset({HOST_ESCRITORIO_PADRAO})
    modo_teste: bool = False
    cookie_seguro: bool = True
    painel_coordenacao: bool = False
    em_producao: bool = False
    sga_token: str = ""
    sga_usuario: str = ""
    sga_senha: str = ""
    powercrm_token: str = ""
    testar_na_partida: bool = False  # testa SGA e Power CRM quando o servidor liga (só no Render)
    busca_automatica: bool = False  # busca completa diária às 06:00 e às 16:00 (só no Render; BUSCA_AUTOMATICA=0 desliga)
    extras: dict = field(default_factory=dict)

    @property
    def sga_configurado(self) -> bool:
        return bool(self.sga_token and self.sga_usuario and self.sga_senha)

    @property
    def google_configurado(self) -> bool:
        return bool(self.google_client_id and self.google_client_secret)


class ConfigInvalida(RuntimeError):
    pass


def carregar(env: dict | None = None) -> Config:
    env = os.environ if env is None else env
    em_producao = bool(env.get("RENDER"))

    hosts = set(_lista(env.get("HOSTS_ESCRITORIO")) or [HOST_ESCRITORIO_PADRAO])
    if env.get("RENDER_EXTERNAL_HOSTNAME"):  # o Render preenche com o endereço .onrender.com do serviço
        hosts.add(env["RENDER_EXTERNAL_HOSTNAME"].strip().lower())
    if not em_producao:
        hosts.update({"localhost", "127.0.0.1"})

    database_url = montar_url_do_banco(env.get("DATABASE_URL"), env.get("DATABASE_PASSWORD"))
    session_secret = env.get("SESSION_SECRET", "").strip()
    if em_producao:
        faltando = [n for n, v in (("DATABASE_URL", database_url), ("SESSION_SECRET", session_secret),
                                   ("GOOGLE_OAUTH_CLIENT_ID", env.get("GOOGLE_OAUTH_CLIENT_ID")),
                                   ("GOOGLE_OAUTH_CLIENT_SECRET", env.get("GOOGLE_OAUTH_CLIENT_SECRET")),
                                   ("ADMIN_EMAILS", env.get("ADMIN_EMAILS"))) if not v]
        if faltando:
            raise ConfigInvalida("Variáveis de ambiente faltando no Render: " + ", ".join(faltando))
        if len(session_secret) < 32:
            raise ConfigInvalida("SESSION_SECRET precisa ter pelo menos 32 caracteres.")
    database_url = url_do_banco(database_url or "sqlite:///./escritorio_local.db")
    session_secret = session_secret or secrets.token_urlsafe(48)  # só fora do Render: muda a cada reinício

    return Config(
        database_url=database_url,
        session_secret=session_secret,
        google_client_id=env.get("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        google_client_secret=env.get("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        admin_emails=frozenset(_lista(env.get("ADMIN_EMAILS"))),
        hosts_escritorio=frozenset(hosts),
        modo_teste=_sim(env.get("MODO_TESTE")) and not em_producao,
        cookie_seguro=em_producao,
        painel_coordenacao=_sim(env.get("PAINEL_COORDENACAO")),
        em_producao=em_producao,
        sga_token=env.get("SGA_TOKEN", "").strip(),
        sga_usuario=env.get("SGA_USUARIO", "").strip(),
        sga_senha=env.get("SGA_SENHA", "").strip(),
        powercrm_token=env.get("POWERCRM_TOKEN", "").strip(),
        testar_na_partida=em_producao,
        busca_automatica=em_producao and (env.get("BUSCA_AUTOMATICA") or "1").strip().lower() not in {
            "0", "nao", "não", "false", "off"},
    )
