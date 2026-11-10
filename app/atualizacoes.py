"""Buscas nas fontes externas: registro (tabela atualizacoes), travas e teste de conexão.

A trava do SGA fica no banco: quando o SGA bloqueia, nenhuma busca (nem o teste, nem o botão das pessoas) chama o SGA
até o próximo horário agendado. Ver a regra completa no AGENTS.md.
"""
from __future__ import annotations

import logging
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import FUSO, Config
from .db import Atualizacao, Trava
from .fontes.powercrm import ClientePowerCRM, PowerCRMErro
from .fontes.sga import ClienteSGA, SGABloqueado, SGAErro
from .tempo import agora, formatar, iso, utc

log = logging.getLogger("escritorio")

TRAVA_SGA = "sga_bloqueado"
# Horários da busca completa do SGA (Brasília): 06:00 e 16:00 (decisão do Rafael, 10/11).
HORARIOS_SGA = (time(6, 0), time(16, 0))
FONTES = {"sga": "SGA", "powercrm": "Power CRM", "bi": "BI Brasil Atuarial", "drive": "Google Drive"}
INTERVALO_DO_TESTE_DE_PARTIDA = timedelta(hours=12)


# ---------------------------------------------------------------- travas

def trava_ativa(db: Session, nome: str) -> Trava | None:
    trava = db.get(Trava, nome)
    return trava if trava is not None and utc(trava.ate) > agora() else None


def travar(db: Session, nome: str, ate: datetime, motivo: str) -> None:
    trava = db.get(Trava, nome) or Trava(nome=nome)
    trava.ate, trava.motivo, trava.criado_em = ate, motivo[:300], agora()
    db.merge(trava)
    db.commit()


def retirar_pausa_do_sga(db: Session, nome: str) -> dict:
    """O administrador tira a pausa (ex.: alarme falso, com o sistema atual funcionando). Fica registrado."""
    trava = trava_ativa(db, TRAVA_SGA)
    if trava is None:
        return {"ok": False, "mensagem": "O SGA não está pausado."}
    motivo = trava.motivo
    db.execute(delete(Trava).where(Trava.nome == TRAVA_SGA))
    db.commit()
    return concluir(db, iniciar(db, "sga", "pausa retirada"), True, f"Pausa do SGA retirada por {nome} (era: {motivo}).")


def proximo_horario_sga(depois_de: datetime | None = None) -> datetime:
    """O próximo horário agendado da busca completa do SGA, em UTC."""
    base = (depois_de or agora()).astimezone(FUSO)
    for dias in range(0, 3):
        dia = (base + timedelta(days=dias)).date()
        for h in HORARIOS_SGA:
            candidato = datetime.combine(dia, h, tzinfo=FUSO)
            if candidato > base:
                return candidato.astimezone(timezone.utc)
    raise RuntimeError("sem horário do SGA")  # pragma: no cover


# ---------------------------------------------------------------- registro

def iniciar(db: Session, fonte: str, tipo: str, pessoa_id: int | None = None) -> Atualizacao:
    a = Atualizacao(fonte=fonte, tipo=tipo, pessoa_id=pessoa_id)
    db.add(a)
    db.commit()
    return a


def concluir(db: Session, a: Atualizacao, ok: bool, mensagem: str) -> dict:
    a.fim, a.ok, a.mensagem = agora(), ok, mensagem[:500]
    db.commit()
    log.warning("Atualização %s/%s: %s — %s", a.fonte, a.tipo, "ok" if ok else "ERRO", mensagem)
    return {"ok": ok, "mensagem": mensagem}


# ---------------------------------------------------------------- teste de conexão

def testar_sga(db: Session, cfg: Config, http=None) -> dict:
    """Só o login (1 chamada): confirma que o token, o usuário e a senha do Render funcionam."""
    if not cfg.sga_configurado:
        return {"ok": False, "mensagem": "Os acessos do SGA (SGA_TOKEN, SGA_USUARIO, SGA_SENHA) não estão no Render."}
    trava = trava_ativa(db, TRAVA_SGA)
    if trava is not None:
        return {"ok": False, "mensagem": f"SGA pausado até {formatar(trava.ate)}: {trava.motivo}. Nada foi consultado."}
    a = iniciar(db, "sga", "teste")
    cliente = ClienteSGA(cfg.sga_token, cfg.sga_usuario, cfg.sga_senha, http=http, limite_chamadas=1)
    try:
        cliente.autenticar()
        return concluir(db, a, True, "Conectou no SGA: o login foi aceito.")
    except SGABloqueado as e:
        ate = proximo_horario_sga()
        travar(db, TRAVA_SGA, ate, str(e))
        return concluir(db, a, False, f"{e}. O SGA fica pausado até {formatar(ate)}.")
    except SGAErro as e:
        return concluir(db, a, False, str(e))
    finally:
        if http is None:
            cliente.fechar()


def testar_powercrm(db: Session, cfg: Config, http=None) -> dict:
    """Uma página das cotações de hoje (1 chamada)."""
    if not cfg.powercrm_token:
        return {"ok": False, "mensagem": "O acesso do Power CRM (POWERCRM_TOKEN) não está no Render."}
    a = iniciar(db, "powercrm", "teste")
    cliente = ClientePowerCRM(cfg.powercrm_token, http=http, espera=lambda _s: None)
    hoje = agora().astimezone(FUSO).date().isoformat()
    try:
        itens = cliente.pagina(hoje, hoje, 0)
        return concluir(db, a, True, f"Conectou no Power CRM: {len(itens)} cotação(ões) de hoje na 1ª página.")
    except PowerCRMErro as e:
        return concluir(db, a, False, str(e))
    finally:
        if http is None:
            cliente.fechar()


def teste_devido(db: Session, fonte: str) -> bool:
    ultimo = db.scalars(select(Atualizacao).where(Atualizacao.fonte == fonte, Atualizacao.tipo == "teste",
                                                  Atualizacao.ok.is_(True))
                        .order_by(Atualizacao.inicio.desc())).first()
    return ultimo is None or agora() - utc(ultimo.inicio) > INTERVALO_DO_TESTE_DE_PARTIDA


def teste_de_partida(Sessao, cfg: Config) -> None:
    """Quando o servidor liga no Render: testa as conexões, se não houve teste bom nas últimas 12 horas."""
    try:
        with Sessao() as db:
            if cfg.sga_configurado and teste_devido(db, "sga"):
                testar_sga(db, cfg)
            if cfg.powercrm_token and teste_devido(db, "powercrm"):
                testar_powercrm(db, cfg)
    except Exception as e:  # noqa: BLE001 - o teste nunca pode derrubar o servidor
        log.warning("Teste de conexão na partida falhou: %s", type(e).__name__)


# ---------------------------------------------------------------- painel

def _registro_json(a: Atualizacao) -> dict:
    return {"id": a.id, "fonte": a.fonte, "fonte_nome": FONTES.get(a.fonte, a.fonte), "tipo": a.tipo,
            "inicio_txt": formatar(a.inicio), "fim_txt": formatar(a.fim), "ok": a.ok, "mensagem": a.mensagem}


def painel(db: Session) -> dict:
    fontes = []
    for fonte, nome in FONTES.items():
        ultimos = db.scalars(select(Atualizacao).where(Atualizacao.fonte == fonte)
                             .order_by(Atualizacao.inicio.desc()).limit(50)).all()
        ok = next((a for a in ultimos if a.ok is True), None)
        erro = next((a for a in ultimos if a.ok is False), None)
        fontes.append({"fonte": fonte, "nome": nome,
                       "ultimo_ok_txt": formatar(ok.fim) if ok else "", "ultimo_ok_tipo": ok.tipo if ok else None,
                       "ultimo_erro_txt": formatar(erro.fim) if erro else "",
                       "ultimo_erro": erro.mensagem if erro else None,
                       "rodando": any(a.ok is None for a in ultimos[:3])})
    trava = trava_ativa(db, TRAVA_SGA)
    historico = db.scalars(select(Atualizacao).order_by(Atualizacao.inicio.desc(), Atualizacao.id.desc()).limit(40))
    return {
        "fontes": fontes,
        "sga_pausado": {"ate_txt": formatar(trava.ate), "ate": iso(trava.ate), "motivo": trava.motivo} if trava else None,
        "proxima_busca_sga_txt": formatar(proximo_horario_sga()),
        "historico": [_registro_json(a) for a in historico],
    }
