"""Regras da etapa 1: login, links de cadastro, aprovação e registro de acessos.

Fica separado das rotas para poder ser testado sem navegador e sem Google.
"""
from __future__ import annotations

import ipaddress
import re
import unicodedata
from collections import defaultdict
from datetime import date

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .config import EQUIPES, SITUACOES, TIPOS, Config
from .db import Acesso, Pessoa
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


def chave(texto: str | None) -> str:
    """'Pé no Chão' -> 'pe no chao': compara sem acento, sem maiúscula e sem pontuação."""
    sem_acento = unicodedata.normalize("NFKD", texto or "").encode("ascii", "ignore").decode()
    return " ".join("".join(c if c.isalnum() else " " for c in sem_acento.lower()).split())


EQUIPE_POR_NOME = {chave(e): e for e in EQUIPES}


def limpar_equipes(valor) -> str | None:
    """Uma ou mais equipes ("ELITE, LUA", "Elite;Lua" ou uma lista) -> "Elite, Lua" (nomes oficiais, sem repetir)."""
    partes = valor if isinstance(valor, (list, tuple)) else re.split(r"[,;/]", valor or "")
    equipes: list[str] = []
    for parte in partes:
        if not limpar_espacos(parte):
            continue
        equipe = EQUIPE_POR_NOME.get(chave(parte))
        if equipe is None:
            raise ErroRegra(f"Equipe “{limpar_espacos(parte)}” desconhecida.")
        if equipe not in equipes:
            equipes.append(equipe)
    return ", ".join(equipes) or None


def lista_de_equipes(texto: str | None) -> list[str]:
    return [e.strip() for e in (texto or "").split(",") if e.strip()]


EMAIL_VALIDO = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def limpar_email(valor: str | None) -> str | None:
    email = (valor or "").strip().lower()
    if not email:
        return None
    if not EMAIL_VALIDO.match(email) or len(email) > 254:
        raise ErroRegra("E-mail inválido.")
    return email


def so_numeros(valor: str | None) -> str:
    return re.sub(r"\D", "", valor or "")


def cpf_valido(cpf: str) -> bool:
    if len(cpf) != 11 or cpf == cpf[0] * 11:
        return False
    for tamanho in (9, 10):
        soma = sum(int(d) * (tamanho + 1 - i) for i, d in enumerate(cpf[:tamanho]))
        if (soma * 10 % 11) % 10 != int(cpf[tamanho]):
            return False
    return True


def limpar_cpf(valor: str | None) -> str:
    cpf = so_numeros(valor).zfill(11) if so_numeros(valor) else ""
    if not cpf_valido(cpf):
        raise ErroRegra("CPF inválido. Confira os 11 números.")
    return cpf


def formatar_cpf(cpf: str | None) -> str:
    return f"{cpf[:3]}.{cpf[3:6]}.{cpf[6:9]}-{cpf[9:]}" if cpf and len(cpf) == 11 else ""


def limpar_whatsapp(valor: str | None) -> str:
    """WhatsApp com DDD, guardado só com números (ex.: 21987654321). Aceita +55 na frente."""
    numero = so_numeros(valor)
    if len(numero) in (12, 13) and numero.startswith("55"):
        numero = numero[2:]
    if len(numero) not in (10, 11) or numero[0] == "0":
        raise ErroRegra("WhatsApp inválido. Escreva com DDD, por exemplo (21) 98765-4321.")
    return numero


def formatar_whatsapp(numero: str | None) -> str:
    if not numero:
        return ""
    meio = 7 if len(numero) == 11 else 6
    return f"({numero[:2]}) {numero[2:meio]}-{numero[meio:]}"


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
        "equipe": p.equipe, "equipes": lista_de_equipes(p.equipe), "lider_id": p.lider_id,
        "lider_nome": p.lider.nome if p.lider else None, "situacao": p.situacao,
        "cpf": formatar_cpf(p.cpf), "whatsapp": formatar_whatsapp(p.whatsapp),
        "aguardando_primeiro_acesso": p.vinculado_em is None,
        "faltando": requisitos_para_aprovar(p.tipo, p.equipe, p.lider_id),
        "criado_em": iso(p.criado_em), "criado_em_txt": formatar(p.criado_em),
        "aprovado_em_txt": formatar(p.aprovado_em), "aprovado_por": p.aprovado_por,
        "vinculado_em_txt": formatar(p.vinculado_em),
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
    pre = sessao.get("pre")
    p = achar_pessoa(db, email, sub)
    # Informou um CPF que já entra com outra conta Google: a tela diz qual (com parte do e-mail escondida).
    alvo_do_cpf = db.get(Pessoa, pre.get("id") or 0) if pre else None
    conta_do_cpf = (mascarar_email(alvo_do_cpf.email)
                    if alvo_do_cpf is not None and alvo_do_cpf.email and alvo_do_cpf.email != email else None)
    if p is None and pre:
        p = vincular_pre_cadastro(db, pre, email, sub)
    elif p is not None and pre and pre.get("id") == p.id and pre.get("whatsapp"):
        p.whatsapp = pre["whatsapp"]  # quem já tinha acesso e informou um WhatsApp novo na entrada

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

    destino = abrir_sessao(db, sessao, p, ip, email=email, sub=sub, nome=nome)
    if conta_do_cpf and "google" in sessao:
        sessao["google"] = {**sessao["google"], "conta_do_cpf": conta_do_cpf}
    return destino


def mascarar_email(email: str) -> str:
    """'exoduscomercialcb@gmail.com' -> 'exo•••@gmail.com'."""
    nome, _, dominio = email.partition("@")
    return nome[:3] + "•••@" + dominio


def abrir_sessao(db: Session, sessao: dict, p: Pessoa | None, ip: str | None, *, email: str, sub: str | None,
                 nome: str | None) -> str:
    """Ativo: entra e registra a entrada. Senão, guarda só quem o Google confirmou (para o primeiro acesso)."""
    sessao.clear()
    if p is not None and p.situacao == "ativo":
        if p.vinculado_em is None:  # e-mail cadastrado pela coordenação: o 1º acesso é esta entrada
            p.vinculado_em = agora()
        db.flush()
        sessao["pid"] = p.id
        db.add(Acesso(pessoa_id=p.id, aba="entrada", ip=ip_resumido(ip)))
        db.commit()
        return "/"
    db.commit()
    sessao["google"] = {"email": email, "sub": sub, "nome": limpar_espacos(nome)}
    return "/"


def ligar_conta_google(p: Pessoa, email: str, sub: str | None, whatsapp: str | None) -> None:
    p.email, p.google_sub, p.vinculado_em = email, sub, agora()
    if whatsapp:
        p.whatsapp = whatsapp


def vincular_pre_cadastro(db: Session, pre: dict, email: str, sub: str | None) -> Pessoa | None:
    """Depois do Google: liga a conta ao cadastro achado pelo CPF no primeiro acesso e grava o WhatsApp."""
    alvo = db.get(Pessoa, pre.get("id") or 0)
    if alvo is None or alvo.email is not None or alvo.situacao == "bloqueado":
        return None
    ligar_conta_google(alvo, email, sub, pre.get("whatsapp"))
    return alvo


def primeiro_acesso(db: Session, sessao: dict, cpf: str, whatsapp: str, ip: str | None) -> str:
    """Entrada (decisão de 08/11: CPF e WhatsApp antes do Google, sempre). Devolve para onde seguir.

    O CPF acha o cadastro feito pela coordenação. No primeiro acesso, a conta Google com que a pessoa entrar fica
    ligada a ele; depois, só entra com essa mesma conta. O WhatsApp informado atualiza o cadastro.
    Se a pessoa já entrou com o Google (e a conta ainda não estava ligada), liga na hora.
    """
    cpf, whatsapp = limpar_cpf(cpf), limpar_whatsapp(whatsapp)
    p = db.scalars(select(Pessoa).where(Pessoa.cpf == cpf)).first()
    if p is None:
        raise ErroRegra("Não encontramos um cadastro com esse CPF. Fale com a coordenação.")
    if p.situacao == "bloqueado":
        raise ErroRegra(MSG_NAO_LIBERADO)
    google = sessao.get("google")
    if google and google.get("email"):
        if p.email is not None and p.email != google["email"].lower():
            raise ErroRegra("Esse CPF está ligado a outra conta Google. Entre com a conta que você usou no primeiro "
                            "acesso. Se trocou de conta, fale com a coordenação.")
        if p.email is not None:  # a coordenação já tinha cadastrado este e-mail
            p.whatsapp = whatsapp
            return abrir_sessao(db, sessao, p, ip, email=p.email, sub=google.get("sub"), nome=google.get("nome"))
        if achar_pessoa(db, google["email"], google.get("sub")) is not None:
            raise ErroRegra("Esta conta Google já está ligada a outro cadastro. Fale com a coordenação.")
        ligar_conta_google(p, google["email"], google.get("sub"), whatsapp)
        return abrir_sessao(db, sessao, p, ip, email=google["email"], sub=google.get("sub"), nome=google.get("nome"))
    sessao["pre"] = {"id": p.id, "whatsapp": whatsapp}
    return "/auth/login"


def requisitos_para_aprovar(tipo: str, equipe: str | None, lider_id: int | None) -> list[str]:
    faltando = []
    if tipo in {"especialista", "lider"} and not equipe:
        faltando.append("equipe")
    if tipo == "especialista" and not lider_id:
        faltando.append("líder")
    return faltando


def atualizar_pessoa(db: Session, alvo: Pessoa, dados: dict, quem: Pessoa, cfg: Config) -> Pessoa:
    """Aprovar, editar ou bloquear um cadastro (painel do administrador)."""
    novo = {
        "nome": alvo.nome, "tipo": alvo.tipo, "equipe": alvo.equipe,
        "lider_id": alvo.lider_id, "situacao": alvo.situacao, "cpf": alvo.cpf, "whatsapp": alvo.whatsapp,
    }
    troca_de_email = False
    if "email" in dados:
        email = limpar_email(dados["email"])
        if email != alvo.email:
            if quem.id == alvo.id or (alvo.email and alvo.email in cfg.admin_emails):
                raise ErroRegra("Este e-mail de administrador não pode ser trocado por aqui.")
            if email and db.scalars(select(Pessoa).where(func.lower(Pessoa.email) == email, Pessoa.id != alvo.id)).first():
                raise ErroRegra("Já existe outro cadastro com esse e-mail.")
            troca_de_email = True
    if "cpf" in dados:
        novo["cpf"] = limpar_cpf(dados["cpf"]) if so_numeros(dados["cpf"]) else None
        if novo["cpf"] and db.scalars(select(Pessoa).where(Pessoa.cpf == novo["cpf"], Pessoa.id != alvo.id)).first():
            raise ErroRegra("Já existe outro cadastro com esse CPF.")
    if "whatsapp" in dados:
        novo["whatsapp"] = limpar_whatsapp(dados["whatsapp"]) if so_numeros(dados["whatsapp"]) else None
    if "nome" in dados:
        novo["nome"] = limpar_nome(dados["nome"])
    if "tipo" in dados:
        if dados["tipo"] not in TIPOS:
            raise ErroRegra("Tipo de acesso desconhecido.")
        novo["tipo"] = dados["tipo"]
    if "equipe" in dados:
        novo["equipe"] = limpar_equipes(dados["equipe"])
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
    if novo["situacao"] == "ativo" and alvo.situacao != "ativo":  # aprovar um pendente ou liberar um bloqueado
        faltando = requisitos_para_aprovar(novo["tipo"], novo["equipe"], novo["lider_id"])
        if faltando:
            raise ErroRegra(f"Para aprovar como {TIPOS[novo['tipo']].lower()}, preencha: " + ", ".join(faltando) + ".")

    if novo["situacao"] == "ativo" and alvo.situacao != "ativo":
        alvo.aprovado_em, alvo.aprovado_por = agora(), quem.email
    for campo, valor in novo.items():
        setattr(alvo, campo, valor)
    if troca_de_email:  # a conta Google antiga deixa de entrar; o próximo acesso liga a nova
        alvo.email, alvo.google_sub, alvo.vinculado_em = email, None, None
    db.commit()
    db.refresh(alvo)
    return alvo


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
    if equipe:  # a pessoa pode ter mais de uma equipe ("Elite, Lua")
        filtros.append(or_(Pessoa.equipe == equipe, Pessoa.equipe.like(f"{equipe}, %"),
                           Pessoa.equipe.like(f"%, {equipe}"), Pessoa.equipe.like(f"%, {equipe}, %")))
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

