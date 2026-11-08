"""Banco de dados: Postgres do Supabase em produção, SQLite nos testes e no computador.

Tabelas da etapa 1 (seção 6 da especificação): pessoas, links_cadastro e acessos.
As tabelas são criadas sozinhas quando o servidor liga (create_all só cria o que ainda não existe).
No Postgres, a segurança por linha (RLS) é ligada em todas elas sem nenhuma regra de leitura:
assim a API pública do Supabase (chave anon) não enxerga nada, e só o servidor, que entra
direto pelo DATABASE_URL, lê e grava.
"""
from __future__ import annotations

from datetime import datetime

from sqlalchemy import (Boolean, DateTime, ForeignKey, Integer, String, create_engine, event, inspect,
                        text)
from sqlalchemy.engine import Engine, make_url
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship, sessionmaker

from .tempo import agora


class Base(DeclarativeBase):
    pass


class LinkCadastro(Base):
    __tablename__ = "links_cadastro"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tipo: Mapped[str] = mapped_column(String(30))
    codigo: Mapped[str] = mapped_column(String(64), unique=True, index=True)
    validade: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ativo: Mapped[bool] = mapped_column(Boolean, default=True)
    usos: Mapped[int] = mapped_column(Integer, default=0)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    criado_por: Mapped[str | None] = mapped_column(String(254), nullable=True)


class Pessoa(Base):
    __tablename__ = "pessoas"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    nome: Mapped[str] = mapped_column(String(120))
    # E-mail da conta Google (sempre em minúsculas). Pode ficar vazio para quem veio da migração
    # do sistema atual e ainda não entrou nenhuma vez.
    email: Mapped[str | None] = mapped_column(String(254), unique=True, index=True, nullable=True)
    google_sub: Mapped[str | None] = mapped_column(String(64), unique=True, nullable=True)
    tipo: Mapped[str] = mapped_column(String(30))
    # Uma ou mais equipes, separadas por vírgula ("Elite, Lua"): há liderados e líderes em mais de uma equipe.
    equipe: Mapped[str | None] = mapped_column(String(200), nullable=True)
    lider_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True)
    # CPF (só números): é por ele que a pessoa, ao abrir o link, é ligada ao cadastro feito antes pela coordenação.
    cpf: Mapped[str | None] = mapped_column(String(11), unique=True, index=True, nullable=True)
    whatsapp: Mapped[str | None] = mapped_column(String(20), nullable=True)  # só números, com DDD
    vinculado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)  # 1º acesso
    situacao: Mapped[str] = mapped_column(String(12), default="pendente", index=True)
    link_id: Mapped[int | None] = mapped_column(ForeignKey("links_cadastro.id", ondelete="SET NULL"), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)
    aprovado_em: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    aprovado_por: Mapped[str | None] = mapped_column(String(254), nullable=True)

    lider: Mapped["Pessoa | None"] = relationship(remote_side="Pessoa.id", foreign_keys=[lider_id])


class Acesso(Base):
    __tablename__ = "acessos"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    pessoa_id: Mapped[int] = mapped_column(ForeignKey("pessoas.id", ondelete="CASCADE"), index=True)
    data_hora: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    aba: Mapped[str] = mapped_column(String(40))  # "entrada" = login; o resto = aba aberta
    ip: Mapped[str | None] = mapped_column(String(48), nullable=True)  # IP resumido (sem o final)

    pessoa: Mapped[Pessoa] = relationship()


def criar_engine(url: str) -> Engine:
    if url.startswith("sqlite"):
        extra = {"poolclass": StaticPool} if url in {"sqlite://", "sqlite:///:memory:"} else {}  # memória: 1 conexão só
        engine = create_engine(url, connect_args={"check_same_thread": False}, **extra)

        @event.listens_for(engine, "connect")
        def _fk(conn, _):  # o SQLite só respeita chaves estrangeiras com isto ligado
            conn.execute("PRAGMA foreign_keys=ON")

        return engine
    connect_args = {} if "sslmode=" in url else {"sslmode": "require"}
    # Poucas conexões: o pooler do Supabase no plano gratuito tem limite baixo.
    return create_engine(url, pool_pre_ping=True, pool_size=3, max_overflow=2, pool_recycle=1800,
                         connect_args=connect_args)


class Atualizacao(Base):
    """Registro de cada busca nas fontes (SGA, Power CRM, BI, Drive): aparece no painel, aba Atualizações."""
    __tablename__ = "atualizacoes"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    fonte: Mapped[str] = mapped_column(String(20), index=True)  # sga, powercrm, bi, drive
    tipo: Mapped[str] = mapped_column(String(30))  # teste, completa, leve, pessoa
    inicio: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora, index=True)
    fim: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ok: Mapped[bool | None] = mapped_column(Boolean, nullable=True)  # None = ainda rodando
    mensagem: Mapped[str | None] = mapped_column(String(500), nullable=True)
    pessoa_id: Mapped[int | None] = mapped_column(ForeignKey("pessoas.id", ondelete="SET NULL"), nullable=True)


class Trava(Base):
    """Travas guardadas no banco: SGA bloqueado (até o próximo horário) e "só uma instância roda a busca"."""
    __tablename__ = "travas"

    nome: Mapped[str] = mapped_column(String(40), primary_key=True)
    ate: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    motivo: Mapped[str | None] = mapped_column(String(300), nullable=True)
    criado_em: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=agora)


def descrever_banco(url: str) -> str:
    """Para o registro do Render: a quem o servidor tentou conectar, sem nunca mostrar a senha."""
    try:
        u = make_url(url)
    except Exception:  # noqa: BLE001 - endereço ilegível: não repetir nada dele
        return "endereço do banco ilegível"
    return (f"usuário {u.username or '(vazio)'}, servidor {u.host or '(vazio)'}, porta {u.port or 5432}, "
            f"senha recebida com {len(u.password or '')} caracteres")


def motivo_da_falha(erro: BaseException) -> str:
    """Traduz o erro de conexão do Postgres/Supabase para uma frase curta, sem copiar o texto original."""
    texto = str(getattr(erro, "orig", None) or erro).lower()
    if "password authentication failed" in texto:
        return ("o Supabase recusou a senha. Confira a DATABASE_PASSWORD no Render e a senha do banco no Supabase "
                "(Project Settings > Database)")
    if "tenant or user not found" in texto:
        return ("o Supabase não achou o projeto nesse servidor. Copie de novo o endereço do Session pooler "
                "do projeto certo")
    if "resolve host" in texto or "name or service not known" in texto or "translate host" in texto:
        return "o servidor do banco não foi encontrado. Confira o endereço na DATABASE_URL"
    if "timeout" in texto or "timed out" in texto or "unreachable" in texto:
        return "o banco não respondeu. Use o endereço do Session pooler, não o da conexão direta"
    return "erro de conexão com o banco"


# Colunas acrescentadas depois que as tabelas já existiam no Supabase (create_all não mexe em tabela existente).
COLUNAS_NOVAS = {
    "pessoas": {"cpf": "VARCHAR(11)", "whatsapp": "VARCHAR(20)", "vinculado_em": "TIMESTAMP WITH TIME ZONE"},
}
# Colunas tiradas do sistema (matrícula e nome no SGA saíram por decisão do Rafael em 08/11; os dados são apagados).
COLUNAS_REMOVIDAS = {"pessoas": ["matricula_sga", "nome_sga"]}
# Só no Postgres (o SQLite não limita tamanho de texto): colunas que ficaram maiores.
AJUSTES_POSTGRES = ['ALTER TABLE "pessoas" ALTER COLUMN "equipe" TYPE VARCHAR(200)']
INDICES_NOVOS = ['CREATE UNIQUE INDEX IF NOT EXISTS "ix_pessoas_cpf" ON "pessoas" ("cpf")']


def migrar(engine: Engine) -> None:
    with engine.begin() as conn:
        tabelas = set(inspect(conn).get_table_names())
        for tabela, colunas in COLUNAS_NOVAS.items():
            if tabela not in tabelas:
                continue
            existentes = {c["name"] for c in inspect(conn).get_columns(tabela)}
            for coluna, tipo in colunas.items():
                if coluna not in existentes:
                    conn.execute(text(f'ALTER TABLE "{tabela}" ADD COLUMN "{coluna}" {tipo}'))
        for tabela, colunas in COLUNAS_REMOVIDAS.items():
            if tabela not in tabelas:
                continue
            existentes = {c["name"] for c in inspect(conn).get_columns(tabela)}
            for coluna in colunas:
                if coluna in existentes:
                    conn.execute(text(f'ALTER TABLE "{tabela}" DROP COLUMN "{coluna}"'))
        for indice in INDICES_NOVOS:
            conn.execute(text(indice))
        if engine.dialect.name == "postgresql" and "pessoas" in tabelas:
            for ajuste in AJUSTES_POSTGRES:
                conn.execute(text(ajuste))


def iniciar_banco(engine: Engine) -> None:
    Base.metadata.create_all(engine)
    migrar(engine)
    if engine.dialect.name == "postgresql":
        with engine.begin() as conn:
            for tabela in inspect(conn).get_table_names():
                if tabela in Base.metadata.tables:
                    conn.execute(text(f'ALTER TABLE "{tabela}" ENABLE ROW LEVEL SECURITY'))


def fabrica_de_sessoes(engine: Engine) -> sessionmaker:
    return sessionmaker(bind=engine, expire_on_commit=False)
