"""Pré-cadastro (decisão do Rafael em 08/11): só entra quem a coordenação cadastrou antes.

- A coordenação cadastra nome, tipo de conta e CPF (e, se tiver, equipe, líder, WhatsApp e e-mail),
  um por um no painel ou colando a planilha.
- Um endereço só para todo mundo. No primeiro acesso, a pessoa informa CPF e WhatsApp e entra com o Google;
  o CPF liga a conta Google ao cadastro (servicos.primeiro_acesso). Depois, só "Entrar com Google".
"""
from __future__ import annotations

import csv
import io

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .config import TIPOS
from .db import Pessoa
from .servicos import (ErroRegra, chave, formatar_cpf, formatar_whatsapp, limpar_cpf, limpar_email, limpar_equipes,
                       limpar_espacos, limpar_nome, limpar_whatsapp,
                       lista_de_equipes, so_numeros)
from .tempo import agora, formatar

MODELO_PLANILHA = "﻿Nome;Tipo de conta;CPF;Equipe;Líder;WhatsApp;E-mail\r\n"
LIMITE_DE_LINHAS = 2000


COLUNAS = {
    "nome": {"nome", "nome completo"},
    "tipo": {"tipo", "tipo de conta", "tipo de acesso", "conta", "acesso"},
    "cpf": {"cpf"},
    "equipe": {"equipe", "equipes", "equipe s"},
    "lider": {"lider", "lider da equipe"},
    "whatsapp": {"whatsapp", "whats", "telefone", "celular"},
    "email": {"email", "e mail", "email google", "e mail google"},
}
TIPO_POR_NOME = {chave(k): k for k in TIPOS} | {chave(v): k for k, v in TIPOS.items()} | {
    "administrador": "admin", "coordenador": "coordenacao", "coordenadora": "coordenacao", "lideranca": "lider",
    "liderado": "especialista", "vendedora": "vendedora_interna", "vendedor interno": "vendedora_interna",
    "vendedora interna": "vendedora_interna", "inside sales": "vendedora_interna",
    # nomes usados na planilha de senhas do sistema atual
    "senha master": "admin", "senha financeiro": "financeiro", "senha coordenacao": "coordenacao",
    "senha cadastro": "cadastro"}


# ---------------------------------------------------------------- cadastro um por um

def _tipo(valor: str | None, quem: Pessoa) -> str:
    tipo = valor if valor in TIPOS else TIPO_POR_NOME.get(chave(valor))
    if tipo is None:
        raise ErroRegra(f"Tipo de conta “{limpar_espacos(valor)}” desconhecido.")
    if tipo == "admin" and quem.tipo != "admin":
        raise ErroRegra("Só o administrador cadastra administrador.")
    return tipo


def criar_pre_cadastro(db: Session, dados: dict, quem: Pessoa) -> Pessoa:
    cpf = limpar_cpf(dados.get("cpf"))
    if db.scalars(select(Pessoa).where(Pessoa.cpf == cpf)).first():
        raise ErroRegra("Já existe um cadastro com esse CPF.")
    email = limpar_email(dados.get("email"))
    if email and db.scalars(select(Pessoa).where(func.lower(Pessoa.email) == email)).first():
        raise ErroRegra("Já existe um cadastro com esse e-mail.")
    lider_id = dados.get("lider_id") or None
    if lider_id is not None:
        lider = db.get(Pessoa, int(lider_id))
        if lider is None or lider.tipo != "lider":
            raise ErroRegra("Escolha um líder da lista.")
    p = Pessoa(nome=limpar_nome(dados.get("nome")), tipo=_tipo(dados.get("tipo"), quem), cpf=cpf,
               equipe=limpar_equipes(dados.get("equipe")), lider_id=lider_id,
               whatsapp=limpar_whatsapp(dados["whatsapp"]) if so_numeros(dados.get("whatsapp")) else None,
               email=email, situacao="ativo", aprovado_em=agora(), aprovado_por=quem.email)
    db.add(p)
    db.commit()
    db.refresh(p)
    return p


# ---------------------------------------------------------------- planilha

def ler_planilha(texto: str) -> list[dict]:
    """Aceita o que se copia do Excel (separado por tabulação) ou um CSV com ; ou ,. A 1ª linha é a dos títulos."""
    linhas = [linha for linha in (texto or "").lstrip("﻿").splitlines() if linha.strip()]
    if not linhas:
        raise ErroRegra("Cole a planilha, com a linha dos títulos (Nome, Tipo de conta, CPF...).")
    cabecalho = linhas[0]
    separador = "\t" if "\t" in cabecalho else (";" if ";" in cabecalho else ",")
    leitor = csv.reader(linhas, delimiter=separador)
    titulos = next(leitor)
    posicao = {}
    for i, titulo in enumerate(titulos):
        for campo, nomes in COLUNAS.items():
            if chave(titulo) in nomes and campo not in posicao:
                posicao[campo] = i
    faltando = [nome for campo, nome in (("nome", "Nome"), ("tipo", "Tipo de conta"), ("cpf", "CPF"))
                if campo not in posicao]
    if faltando:
        raise ErroRegra("A planilha precisa das colunas Nome, Tipo de conta e CPF. Faltando: " + ", ".join(faltando) + ".")
    registros = []
    for numero, colunas in enumerate(leitor, start=2):
        if not any(c.strip() for c in colunas):
            continue
        registro = {campo: (colunas[i].strip() if i < len(colunas) else "") for campo, i in posicao.items()}
        registro["linha"] = numero
        registros.append(registro)
    if len(registros) > LIMITE_DE_LINHAS:
        raise ErroRegra(f"A planilha tem mais de {LIMITE_DE_LINHAS} linhas. Divida em partes.")
    return registros


def importar_planilha(db: Session, texto: str, quem: Pessoa) -> dict:
    """Confere a planilha inteira; se alguma linha tiver erro, não grava nada e devolve a lista de erros.

    Quem já tem cadastro (mesmo CPF) é atualizado (nome, tipo, equipe, líder, WhatsApp e e-mail);
    e-mail Google, situação e acessos não mudam.
    """
    erros: list[dict] = []
    prontos: list[dict] = []
    linha_do_cpf: dict[str, int] = {}
    for r in ler_planilha(texto):
        try:
            cpf = limpar_cpf(r.get("cpf"))
            if cpf in linha_do_cpf:
                raise ErroRegra(f"CPF repetido (também na linha {linha_do_cpf[cpf]}).")
            linha_do_cpf[cpf] = r["linha"]
            prontos.append({
                "linha": r["linha"], "cpf": cpf, "nome": limpar_nome(r.get("nome")),
                "tipo": _tipo(r.get("tipo"), quem), "equipe": limpar_equipes(r.get("equipe")),
                "whatsapp": limpar_whatsapp(r["whatsapp"]) if so_numeros(r.get("whatsapp")) else None,
                "lider": limpar_espacos(r.get("lider")) or None,
                "email": limpar_email(r.get("email")),
            })
        except ErroRegra as e:
            erros.append({"linha": r["linha"], "mensagem": str(e)})

    existentes = {p.cpf: p for p in db.scalars(select(Pessoa).where(Pessoa.cpf.in_(list(linha_do_cpf))))}
    linha_do_email: dict[str, int] = {}
    for r in prontos:
        if not r["email"]:
            continue
        if r["email"] in linha_do_email:
            erros.append({"linha": r["linha"], "mensagem": f"E-mail repetido (também na linha {linha_do_email[r['email']]})."})
        linha_do_email[r["email"]] = r["linha"]
        dono = db.scalars(select(Pessoa).where(func.lower(Pessoa.email) == r["email"])).first()
        atual = existentes.get(r["cpf"])
        if dono is not None and (atual is None or dono.id != atual.id):
            erros.append({"linha": r["linha"], "mensagem": "Esse e-mail já está em outro cadastro."})
        elif atual is not None and atual.email and atual.email != r["email"]:
            erros.append({"linha": r["linha"], "mensagem": "Essa pessoa já entra com outro e-mail. Para trocar, use "
                                                           "Editar no painel."})
    # A linha de administrador da planilha ("SENHA MASTER") é o próprio administrador que está importando:
    # o CPF é ligado ao cadastro dele, em vez de criar uma segunda pessoa.
    linhas_admin_novas = [r for r in prontos if r["tipo"] == "admin" and r["cpf"] not in existentes]
    ligado_ao_admin = False
    if quem.tipo == "admin" and quem.cpf is None and len(linhas_admin_novas) == 1:
        existentes[linhas_admin_novas[0]["cpf"]] = quem
        ligado_ao_admin = True
    for r in prontos:
        atual = existentes.get(r["cpf"])
        if atual is not None and quem.tipo != "admin" and "admin" in {atual.tipo, r["tipo"]}:
            erros.append({"linha": r["linha"], "mensagem": "Só o administrador mexe em cadastro de administrador."})

    # líderes: os já cadastrados no sistema e os que estão na própria planilha
    lideres_conhecidos = set()
    for p in db.scalars(select(Pessoa).where(Pessoa.tipo == "lider")):
        lideres_conhecidos.add(chave(p.nome))
    for r in prontos:
        if r["tipo"] == "lider":
            lideres_conhecidos.add(chave(r["nome"]))
    lideres_conhecidos.discard("")
    for r in prontos:
        if r["lider"] and chave(r["lider"]) not in lideres_conhecidos:
            erros.append({"linha": r["linha"], "mensagem": f"Líder “{r['lider']}” não encontrado. Ele precisa estar "
                                                           "cadastrado como Líder (na planilha ou no sistema)."})
    if erros:
        return {"importado": False, "criados": 0, "atualizados": 0, "erros": sorted(erros, key=lambda e: e["linha"])}

    criados = atualizados = 0
    gravados: dict[str, Pessoa] = {}
    for r in sorted(prontos, key=lambda x: x["tipo"] != "lider"):  # líderes primeiro, para os liderados acharem
        p = existentes.get(r["cpf"])
        if p is None:
            p = Pessoa(cpf=r["cpf"], situacao="ativo", aprovado_em=agora(), aprovado_por=f"{quem.email} (planilha)")
            db.add(p)
            criados += 1
        else:
            atualizados += 1
        if p is quem:
            p.cpf = r["cpf"]  # o tipo e a situação do administrador não mudam
        else:
            p.tipo = r["tipo"]
        p.nome, p.equipe = r["nome"], r["equipe"] or p.equipe
        p.whatsapp = r["whatsapp"] or p.whatsapp
        if r["email"] and p is not quem:
            p.email = r["email"]
        gravados[r["cpf"]] = p
    db.flush()

    id_do_lider = {}
    for p in db.scalars(select(Pessoa).where(Pessoa.tipo == "lider")):
        id_do_lider.setdefault(chave(p.nome), p.id)
    for r in prontos:
        if r["lider"]:
            lider_id = id_do_lider[chave(r["lider"])]
            if lider_id != gravados[r["cpf"]].id:
                gravados[r["cpf"]].lider_id = lider_id

    # Sem a coluna Líder: o liderado fica com o líder da equipe dele, quando só um líder cuida dessa(s) equipe(s).
    lideres = [p for p in db.scalars(select(Pessoa).where(Pessoa.tipo == "lider", Pessoa.situacao != "bloqueado"))]
    pela_equipe = 0
    for r in prontos:
        p = gravados[r["cpf"]]
        if r["tipo"] != "especialista" or r["lider"] or p.lider_id:
            continue
        equipes = set(lista_de_equipes(p.equipe))
        candidatos = [lid for lid in lideres if equipes & set(lista_de_equipes(lid.equipe))]
        if len(candidatos) == 1:
            p.lider_id = candidatos[0].id
            pela_equipe += 1
    db.commit()
    return {"importado": True, "criados": criados, "atualizados": atualizados, "erros": [],
            "lideres_pela_equipe": pela_equipe, "ligado_ao_admin": ligado_ao_admin}


# ---------------------------------------------------------------- planilha para baixar

def _celula(valor) -> str:
    """Evita que o Excel trate um texto começando com = + - @ como fórmula."""
    texto = "" if valor is None else str(valor)
    return "'" + texto if texto[:1] in ("=", "+", "-", "@") else texto


def planilha_de_cadastros(db: Session) -> str:
    saida = io.StringIO()
    escritor = csv.writer(saida, delimiter=";", lineterminator="\r\n")
    escritor.writerow(["Nome", "CPF", "Telefone (WhatsApp)", "E-mail Google", "Tipo de conta", "Equipe(s)", "Líder",
                       "Situação", "1º acesso"])
    for p in db.scalars(select(Pessoa).order_by(Pessoa.nome)):
        escritor.writerow([_celula(v) for v in (
            p.nome, formatar_cpf(p.cpf), formatar_whatsapp(p.whatsapp), p.email, TIPOS.get(p.tipo, p.tipo), p.equipe,
            p.lider.nome if p.lider else "",
            "aguardando 1º acesso" if p.vinculado_em is None and p.situacao == "ativo" else p.situacao,
            formatar(p.vinculado_em))])
    return "\ufeff" + saida.getvalue()
