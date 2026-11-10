"""API do painel do administrador: Cadastros, Links de cadastro e Acessos."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel
from sqlalchemy import case, select
from sqlalchemy.orm import Session

from .atualizacoes import painel as painel_de_atualizacoes
from .atualizacoes import retirar_pausa_do_sga, testar_powercrm, testar_sga
from .busca.completa import motivo_para_nao_rodar, rodar_em_segundo_plano
from .cadastro import MODELO_PLANILHA, criar_pre_cadastro, importar_planilha, planilha_de_cadastros
from .config import EQUIPES, SITUACOES, TIPOS
from .dados import importar_sistema_atual, resumo_da_importacao
from .db import Pessoa
from .dependencias import banco, config, exige_json, exige_painel
from .servicos import (atualizar_pessoa, data_do_filtro, excluir_pessoa, lideres, limpar_espacos, pessoa_para_json,
                       relatorio_acessos, so_numeros)

rotas_admin = APIRouter(prefix="/api/admin", dependencies=[Depends(exige_painel)])


class CorpoPessoa(BaseModel):
    nome: str | None = None
    tipo: str | None = None
    equipe: str | None = None
    lider_id: int | None = None
    situacao: str | None = None
    cpf: str | None = None
    whatsapp: str | None = None
    email: str | None = None


class CorpoPessoaNova(BaseModel):
    nome: str
    tipo: str
    cpf: str
    equipe: str | None = None
    lider_id: int | None = None
    whatsapp: str | None = None
    email: str | None = None


class CorpoPlanilha(BaseModel):
    texto: str


@rotas_admin.get("/opcoes")
def opcoes(db: Session = Depends(banco)):
    return {"tipos": [{"id": k, "nome": v} for k, v in TIPOS.items()], "equipes": list(EQUIPES),
            "situacoes": list(SITUACOES), "lideres": lideres(db)}


@rotas_admin.get("/pessoas")
def listar_pessoas(situacao: str | None = None, q: str | None = None, db: Session = Depends(banco)):
    consulta = select(Pessoa)
    if situacao in SITUACOES:
        consulta = consulta.where(Pessoa.situacao == situacao)
    elif situacao == "aguardando":  # cadastrado pela coordenação e ainda não entrou com o Google
        consulta = consulta.where(Pessoa.vinculado_em.is_(None), Pessoa.situacao != "bloqueado")
    ordem = case((Pessoa.situacao == "pendente", 0), (Pessoa.situacao == "ativo", 1), else_=2)
    pessoas = db.scalars(consulta.order_by(ordem, Pessoa.nome)).all()
    termo = limpar_espacos(q).lower()
    if termo:
        numeros = so_numeros(termo)
        pessoas = [p for p in pessoas
                   if termo in " ".join(filter(None, [p.nome, p.email, p.equipe,
                                                      TIPOS.get(p.tipo)])).lower()
                   or (len(numeros) >= 4 and numeros in (p.cpf or "") + " " + (p.whatsapp or ""))]
    return {"pessoas": [pessoa_para_json(p) for p in pessoas]}


@rotas_admin.post("/pessoas", dependencies=[Depends(exige_json)])
def nova_pessoa(corpo: CorpoPessoaNova, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    """Cadastro feito pela coordenação. A pessoa só ganha acesso quando abrir o link do tipo dela."""
    p = criar_pre_cadastro(db, corpo.model_dump(), db.get(Pessoa, quem.id))
    return {"pessoa": pessoa_para_json(p)}


@rotas_admin.post("/importar", dependencies=[Depends(exige_json)])
def importar(corpo: CorpoPlanilha, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    return importar_planilha(db, corpo.texto, db.get(Pessoa, quem.id))


@rotas_admin.get("/cadastros.csv")
def baixar_cadastros(db: Session = Depends(banco)):
    """Todos os cadastros numa planilha (abre no Excel), com o telefone e o e-mail do primeiro acesso."""
    return Response(planilha_de_cadastros(db), media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="cadastros-escritorio.csv"'})


@rotas_admin.get("/modelo-planilha.csv")
def modelo_planilha():
    return Response(MODELO_PLANILHA, media_type="text/csv; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="modelo-cadastro-escritorio.csv"'})


@rotas_admin.patch("/pessoas/{pessoa_id}", dependencies=[Depends(exige_json)])
def editar_pessoa(pessoa_id: int, corpo: CorpoPessoa, request: Request, db: Session = Depends(banco),
                  quem: Pessoa = Depends(exige_painel)):
    alvo = db.get(Pessoa, pessoa_id)
    if alvo is None:
        raise HTTPException(404, "Cadastro não encontrado.")
    quem = db.get(Pessoa, quem.id)
    alvo = atualizar_pessoa(db, alvo, corpo.model_dump(exclude_unset=True), quem, config(request))
    return {"pessoa": pessoa_para_json(alvo)}


@rotas_admin.post("/pessoas/{pessoa_id}/excluir", dependencies=[Depends(exige_json)])
def excluir(pessoa_id: int, request: Request, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    alvo = db.get(Pessoa, pessoa_id)
    if alvo is None:
        raise HTTPException(404, "Cadastro não encontrado.")
    excluir_pessoa(db, alvo, db.get(Pessoa, quem.id), config(request))
    return {"ok": True}


@rotas_admin.get("/importacao")
def ver_importacao(db: Session = Depends(banco)):
    return resumo_da_importacao(db)


@rotas_admin.post("/importar-sistema-atual", dependencies=[Depends(exige_json)])
async def importar_do_sistema_atual(request: Request, db: Session = Depends(banco),
                                    quem: Pessoa = Depends(exige_painel)):
    """Recebe o arquivo exportacao_escritorio.json (gerado pelo Claude que tem o Kit) e guarda no banco."""
    if quem.tipo != "admin":
        raise HTTPException(403, "Só o administrador importa os dados do sistema atual.")
    try:
        exp = await request.json()
    except ValueError:
        raise HTTPException(400, "O arquivo não é um JSON válido.") from None
    return importar_sistema_atual(db, exp)


@rotas_admin.get("/atualizacoes")
def ver_atualizacoes(request: Request, db: Session = Depends(banco)):
    r = painel_de_atualizacoes(db)
    r["busca_automatica"] = config(request).busca_automatica
    return r


@rotas_admin.post("/atualizacoes/retirar-pausa", dependencies=[Depends(exige_json)])
def retirar_pausa(db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    """Tira a pausa do SGA (só o administrador; ex.: alarme falso com o sistema atual funcionando)."""
    if quem.tipo != "admin":
        raise HTTPException(403, "Só o administrador tira a pausa do SGA.")
    return retirar_pausa_do_sga(db, quem.nome)


@rotas_admin.post("/atualizacoes/busca", dependencies=[Depends(exige_json)])
def rodar_busca_agora(request: Request, db: Session = Depends(banco), quem: Pessoa = Depends(exige_painel)):
    """Busca completa fora do horário (só o administrador). Roda em segundo plano; o resultado vai para o histórico."""
    if quem.tipo != "admin":
        raise HTTPException(403, "Só o administrador roda a busca completa.")
    cfg = config(request)
    motivo = motivo_para_nao_rodar(db, cfg)
    if motivo is not None:
        return {"ok": False, "mensagem": motivo}
    rodar_em_segundo_plano(request.app.state.Sessao, cfg, tipo="manual", pessoa_id=quem.id)
    return {"ok": True, "mensagem": "Busca iniciada. Leva alguns minutos; o resultado aparece no histórico abaixo."}


@rotas_admin.post("/atualizacoes/testar", dependencies=[Depends(exige_json)])
def testar_conexoes(request: Request, db: Session = Depends(banco)):
    """Testa SGA (só o login) e Power CRM (1 página). Respeita a trava do SGA."""
    cfg = config(request)
    return {"sga": testar_sga(db, cfg), "powercrm": testar_powercrm(db, cfg)}


@rotas_admin.get("/acessos")
def acessos(pessoa_id: int | None = None, equipe: str | None = None, de: str | None = None,
            ate: str | None = None, db: Session = Depends(banco)):
    return relatorio_acessos(db, pessoa_id=pessoa_id, equipe=equipe or None, de=data_do_filtro(de),
                             ate=data_do_filtro(ate))
