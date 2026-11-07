"""Regras da etapa 1: login, links de cadastro, aprovação e registro de acessos.

Fica separado das rotas para poder ser testado sem navegador e sem Google.
"""
from __future__ import annotations

import ipaddress
import re
import secrets
from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import EQUIPES, SITUACOES, TIPOS, Config
from .db import Acesso, LinkCadastro, Pessoa
from .tempo import agora, fim_do_dia, formatar, inicio_do_dia, iso, utc

MSG_NAO_LIBERADO = "Seu acesso ainda não foi liberado. Fale com a coordenação."


class ErroRegra(ValueError):
    """Pedido recusado por uma regra; a mensagem vai para a tela como está."""


# ---------------------------------------------------------------- textos

def limpar_espacos(valor: str | None) -> str:
    return re.sub(r"\s+", " ", (valor or "")).strip()


def limpar_nome(valor: str | None) -> str:
    nome = limpar_espacos(valor)
    if not 3 <= len(nome) <= 120:
        raise ErroRegra("Escreva o nome completo (de 3 a 120 letras).")
    return nome


def limpar_nome_sga(valor: str | None) -> str | None:
    """Nome exatamente como está no SGA, em maiúsculas. É por ele que o especialista é ligado aos dados."""
    nome = limpar_espacos(valor).upper()
    return nome or None


def ip_resumido(ip: str | None) -> str | None:
    """Guarda só o começo do IP: '201.17.33.x' ou '2804:14c:5b::x'."""
    try:
        end = ipaddress.ip_address((ip or "").strip())
    except ValueError:
        return None
    if end.version == 4:
        return ".".join(str(end).split(".")[:3]) + ".x"
    return ":".join(format(int(g, 16), "x") for g in end.exploded.split(":")[:3]) + "::x"


# ---------------------------------------------------------------- pessoas

def pode_ver_painel(p: Pessoa | None, cfg: Config) -> bool:
    return bool(p and p.situacao == "ativo" and
                (p.tipo == "admin" or (p.tipo == "coordenacao" and cfg.painel_coordenacao)))


def pessoa_para_json(p: Pessoa) -> dict:
    return {
        "id": p.id, "nome": p.nome, "email": p.email, "tipo": p.tipo, "tipo_nome": TIPOS.get(p.tipo, p.tipo),
        "equipe": p.equipe, "nome_sga": p.nome_sga, "lider_id": p.lider_id,
        "lider_nome": p.lider.nome if p.lider else None, "situacao": p.situacao,
        "criado_em": iso(p.criado_em), "criado_em_txt": formatar(p.criado_em),
        "aprovado_em_txt": formatar(p.aprovado_em), "aprovado_por": p.aprovado_por,
    }


def achar_pessoa(db: Session, email: str, sub: str | None) -> Pessoa | None:
    condicoes = [func.lower(Pessoa.email) == email]
    if sub:
        condicoes.append(Pessoa.google_sub == sub)
    return db.scalars(select(Pessoa).where(or_(*condicoes)).order_by(Pessoa.id)).first()


def concluir_login(db: Session, sessao: dict, cfg: Config, *, email: str, sub: str | None, nome: str | None,
                   ip: str | None) -> str:
    """Depois que o Google confirmou o e-mail. Devolve o endereço para onde mandar a pessoa."""
    email = (email or "").strip().lower()
    if not email:
        raise ErroRegra("O Google não informou o e-mail.")
    codigo_link = sessao.get("link")
    p = achar_pessoa(db, email, sub)

    if email in cfg.admin_emails:  # ADMIN_EMAILS manda: sempre admin e sempre ativo
        if p is None:
            p = Pessoa(nome=limpar_espacos(nome) or email, email=email, tipo="admin")
            db.add(p)
        if p.situacao != "ativo":
            p.aprovado_em, p.aprovado_por = agora(), "ADMIN_EMAILS"
        p.tipo, p.situacao = "admin", "ativo"

    if p is not None:
        if sub and not p.google_sub:
            p.google_sub = sub
        if p.email != email:
            p.email = email

    sessao.clear()
    if p is not None and p.situacao == "ativo":
        db.flush()
        sessao["pid"] = p.id
        db.add(Acesso(pessoa_id=p.id, aba="entrada", ip=ip_resumido(ip)))
        db.commit()
        return "/"

    db.commit()
    sessao["google"] = {"email": email, "sub": sub, "nome": limpar_espacos(nome)}
    if p is None and codigo_link and link_valido(db, codigo_link):
        sessao["link"] = codigo_link
        return f"/cadastro/{codigo_link}"
    return "/"


def requisitos_para_aprovar(tipo: str, equipe: str | None, nome_sga: str | None, lider_id: int | None) -> list[str]:
    faltando = []
    if tipo in {"especialista", "lider"} and not equipe:
        faltando.append("equipe")
    if tipo in {"especialista", "lider", "vendedora_interna"} and not nome_sga:
        faltando.append("nome no SGA")
    if tipo == "especialista" and not lider_id:
        faltando.append("líder")
    return faltando


def atualizar_pessoa(db: Session, alvo: Pessoa, dados: dict, quem: Pessoa, cfg: Config) -> Pessoa:
    """Aprovar, editar ou bloquear um cadastro (painel do administrador)."""
    novo = {
        "nome": alvo.nome, "tipo": alvo.tipo, "equipe": alvo.equipe, "nome_sga": alvo.nome_sga,
        "lider_id": alvo.lider_id, "situacao": alvo.situacao,
    }
    if "nome" in dados:
        novo["nome"] = limpar_nome(dados["nome"])
    if "tipo" in dados:
        if dados["tipo"] not in TIPOS:
            raise ErroRegra("Tipo de acesso desconhecido.")
        novo["tipo"] = dados["tipo"]
    if "equipe" in dados:
        equipe = limpar_espacos(dados["equipe"]) or None
        if equipe is not None and equipe not in EQUIPES:
            raise ErroRegra("Equipe desconhecida.")
        novo["equipe"] = equipe
    if "nome_sga" in dados:
        novo["nome_sga"] = limpar_nome_sga(dados["nome_sga"])
    if "lider_id" in dados:
        lider_id = dados["lider_id"] or None
        if lider_id is not None:
            lider = db.get(Pessoa, int(lider_id))
            if lider is None or lider.tipo != "lider" or lider.id == alvo.id:
                raise ErroRegra("Escolha um líder da lista.")
            lider_id = lider.id
        novo["lider_id"] = lider_id
    if "situacao" in dados:
        if dados["situacao"] not in SITUACOES:
            raise ErroRegra("Situação desconhecida.")
        novo["situacao"] = dados["situacao"]

    if quem.id == alvo.id and (novo["situacao"] != alvo.situacao or novo["tipo"] != alvo.tipo):
        raise ErroRegra("Você não pode bloquear nem trocar o seu próprio tipo de acesso.")
    if quem.tipo != "admin" and "admin" in {alvo.tipo, novo["tipo"]}:
        raise ErroRegra("Só o administrador mexe em acessos de administrador.")
    if alvo.email and alvo.email in cfg.admin_emails and (novo["tipo"] != "admin" or novo["situacao"] != "ativo"):
        raise ErroRegra("Este e-mail está em ADMIN_EMAILS no Render: continua administrador e ativo.")
    if novo["situacao"] == "ativo":
        faltando = requisitos_para_aprovar(novo["tipo"], novo["equipe"], novo["nome_sga"], novo["lider_id"])
        if faltando:
            raise ErroRegra(f"Para aprovar como {TIPOS[novo['tipo']].lower()}, preencha: " + ", ".join(faltando) + ".")

    if novo["situacao"] == "ativo" and alvo.situacao != "ativo":
        alvo.aprovado_em, alvo.aprovado_por = agora(), quem.email
    for campo, valor in novo.items():
        setattr(alvo, campo, valor)
    db.commit()
    db.refresh(alvo)
    return alvo


# ---------------------------------------------------------------- links de cadastro

def situacao_do_link(link: LinkCadastro) -> str:
    if not link.ativo:
        return "desativado"
    if link.validade is not None and agora() >= utc(link.validade):
        return "vencido"
    return "ativo"


def link_valido(db: Session, codigo: str) -> LinkCadastro | None:
    link = db.scalars(select(LinkCadastro).where(LinkCadastro.codigo == (codigo or ""))).first()
    return link if link is not None and situacao_do_link(link) == "ativo" else None


def criar_link(db: Session, tipo: str, validade: str | None, quem: Pessoa) -> LinkCadastro:
    if tipo not in TIPOS:
        raise ErroRegra("Tipo de acesso desconhecido.")
    if tipo == "admin" and quem.tipo != "admin":
        raise ErroRegra("Só o administrador gera link de administrador.")
    vence = None
    if validade:
        try:
            dia = date.fromisoformat(validade)
        except ValueError:
            raise ErroRegra("Data de validade inválida.") from None
        if fim_do_dia(dia) <= agora():
            raise ErroRegra("A validade precisa ser hoje ou depois.")
        vence = fim_do_dia(dia)
    link = LinkCadastro(tipo=tipo, codigo=secrets.token_urlsafe(12), validade=vence, criado_por=quem.email)
    db.add(link)
    db.commit()
    return link


def link_para_json(link: LinkCadastro, base_url: str) -> dict:
    vence = utc(link.validade)
    return {
        "id": link.id, "tipo": link.tipo, "tipo_nome": TIPOS.get(link.tipo, link.tipo), "codigo": link.codigo,
        "url": base_url.rstrip("/") + "/cadastro/" + link.codigo, "ativo": link.ativo, "usos": link.usos,
        "situacao": situacao_do_link(link),
        # validade é guardada como 00:00 do dia seguinte; na tela aparece o último dia que vale
        "validade_txt": formatar(vence - timedelta(minutes=1))[:10] if vence else "",
        "criado_em_txt": formatar(link.criado_em), "criado_por": link.criado_por,
    }


def cadastrar(db: Session, sessao: dict, codigo: str, nome: str) -> Pessoa:
    """A pessoa abriu o link, entrou com o Google e preencheu o nome: fica pendente."""
    google = sessao.get("google")
    if not google or not google.get("email"):
        raise ErroRegra("Entre com o Google antes de preencher o cadastro.")
    link = link_valido(db, codigo)
    if link is None:
        raise ErroRegra("Este link de cadastro não vale mais. Peça um novo à coordenação.")
    if achar_pessoa(db, google["email"], google.get("sub")) is not None:
        raise ErroRegra("Este e-mail já tem cadastro. " + MSG_NAO_LIBERADO)
    p = Pessoa(nome=limpar_nome(nome), email=google["email"], google_sub=google.get("sub"), tipo=link.tipo,
               situacao="pendente", link_id=link.id)
    link.usos = (link.usos or 0) + 1
    db.add(p)
    db.commit()
    sessao.pop("link", None)
    return p


# ---------------------------------------------------------------- acessos

ABA_VALIDA = re.compile(r"^[a-z0-9_]{1,40}$")


def registrar_acesso(db: Session, pessoa: Pessoa, aba: str, ip: str | None) -> None:
    if not ABA_VALIDA.match(aba or "") or aba == "entrada":
        raise ErroRegra("Aba inválida.")
    db.add(Acesso(pessoa_id=pessoa.id, aba=aba, ip=ip_resumido(ip)))
    db.commit()


def relatorio_acessos(db: Session, *, pessoa_id: int | None = None, equipe: str | None = None,
                      de: date | None = None, ate: date | None = None, limite_eventos: int = 300) -> dict:
    filtros = []
    if pessoa_id:
        filtros.append(Acesso.pessoa_id == pessoa_id)
    if equipe:
        filtros.append(Pessoa.equipe == equipe)
    if de:
        filtros.append(Acesso.data_hora >= inicio_do_dia(de))
    if ate:
        filtros.append(Acesso.data_hora < fim_do_dia(ate))

    base = select(Acesso.pessoa_id, Acesso.aba, func.count(), func.min(Acesso.data_hora),
                  func.max(Acesso.data_hora)).join(Pessoa, Pessoa.id == Acesso.pessoa_id).where(*filtros)
    linhas = db.execute(base.group_by(Acesso.pessoa_id, Acesso.aba)).all()

    por_pessoa: dict[int, dict] = defaultdict(lambda: {"entradas": 0, "primeiro": None, "ultimo": None, "abas": {}})
    for pid, aba, qtd, primeiro, ultimo in linhas:
        r = por_pessoa[pid]
        primeiro, ultimo = utc(primeiro), utc(ultimo)
        r["primeiro"] = min(filter(None, [r["primeiro"], primeiro]))
        r["ultimo"] = max(filter(None, [r["ultimo"], ultimo]))
        if aba == "entrada":
            r["entradas"] = qtd
        else:
            r["abas"][aba] = qtd

    pessoas = {p.id: p for p in db.scalars(select(Pessoa).where(Pessoa.id.in_(por_pessoa)))} if por_pessoa else {}
    resumo = []
    for pid, r in por_pessoa.items():
        p = pessoas[pid]
        resumo.append({"pessoa_id": pid, "nome": p.nome, "tipo_nome": TIPOS.get(p.tipo, p.tipo), "equipe": p.equipe,
                       "entradas": r["entradas"], "primeiro_txt": formatar(r["primeiro"]),
                       "ultimo": iso(r["ultimo"]), "ultimo_txt": formatar(r["ultimo"]),
                       "abas": dict(sorted(r["abas"].items(), key=lambda kv: -kv[1]))})
    resumo.sort(key=lambda r: r["ultimo"] or "", reverse=True)

    eventos = db.execute(select(Acesso, Pessoa).join(Pessoa, Pessoa.id == Acesso.pessoa_id).where(*filtros)
                         .order_by(Acesso.data_hora.desc(), Acesso.id.desc()).limit(limite_eventos)).all()
    return {
        "resumo": resumo,
        "eventos": [{"data_hora_txt": formatar(a.data_hora), "pessoa_id": p.id, "nome": p.nome, "equipe": p.equipe,
                     "aba": a.aba, "ip": a.ip} for a, p in eventos],
    }


def data_do_filtro(valor: str | None) -> date | None:
    if not valor:
        return None
    try:
        return date.fromisoformat(valor)
    except ValueError:
        raise ErroRegra("Data inválida no filtro.") from None


def lideres(db: Session) -> list[dict]:
    rows = db.scalars(select(Pessoa).where(Pessoa.tipo == "lider").order_by(Pessoa.nome))
    return [{"id": p.id, "nome": p.nome, "equipe": p.equipe, "situacao": p.situacao} for p in rows]

