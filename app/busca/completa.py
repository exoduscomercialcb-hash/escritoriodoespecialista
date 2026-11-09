"""A busca completa: monta a entrada a partir do banco, roda o script adaptado e grava os pacotes.

Quem chama: o agendador (1 vez por dia, às 03:52 de Brasília, enquanto o sistema atual estiver no ar) e o botão
"Rodar a busca agora" do painel do administrador. As duas portas respeitam as mesmas travas:
- SGA pausado (BLOQUEADO ou login recusado duas vezes): não chama o SGA até o próximo horário agendado;
- uma busca de cada vez (trava "busca_rodando" no banco, que vence sozinha depois de 2 horas);
- sem os dados do sistema atual importados (pacote "all"), não roda: o script precisa do estado anterior.
Se qualquer passo falhar, nada é gravado e os cards continuam com os dados anteriores.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone

import httpx2
from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .. import banco_pagina as bp
from ..atualizacoes import (HORARIOS_SGA, TRAVA_SGA, concluir, iniciar, proximo_horario_sga, trava_ativa, travar)
from ..config import FUSO, Config
from ..dados import N, chaves, guardar, ler
from ..db import Atualizacao, Pacote, Trava
from ..fontes.powercrm import ClientePowerCRM, PowerCRMErro
from ..fontes.sga import ClienteSGA, SGABloqueado, SGAErro
from ..tempo import agora, formatar, utc
from .entrada import Entrada, ErroBusca, Saida

log = logging.getLogger("escritorio")

TRAVA_BUSCA = "busca_rodando"
DURACAO_MAXIMA = timedelta(hours=2)  # se o servidor cair no meio, a trava vence sozinha
# A busca completa do sistema atual faz alguns milhares de chamadas (base ativa, histórico, boletos, detalhes novos).
# O limite só existe para uma busca com defeito não martelar o SGA sem fim.
LIMITE_CHAMADAS_SGA = 20000
JANELA_DO_AGENDADOR = timedelta(hours=3)  # servidor reiniciado às 04:30 ainda roda a busca das 03:52; às 10h, não
INTERVALO_DO_AGENDADOR = 300  # segundos entre uma conferência e outra

_uma_de_cada_vez = threading.Lock()  # dentro do mesmo servidor; a trava no banco cobre o resto


# ---------------------------------------------------------------- conferências

def motivo_para_nao_rodar(db: Session, cfg: Config) -> str | None:
    if not cfg.sga_configurado:
        return "Os acessos do SGA (SGA_TOKEN, SGA_USUARIO, SGA_SENHA) não estão no Render."
    trava = trava_ativa(db, TRAVA_SGA)
    if trava is not None:
        return f"SGA pausado até {formatar(trava.ate)}: {trava.motivo}. Nada foi consultado."
    rodando = trava_ativa(db, TRAVA_BUSCA)
    if rodando is not None:
        return "Já tem uma busca rodando. Espere ela terminar."
    if ler(db, "all") is None:
        return ("Os dados do sistema atual ainda não foram importados (Painel > Atualizações > Dados do sistema "
                "atual). A busca precisa deles como ponto de partida.")
    return None


def ultimo_horario_sga(ate: datetime | None = None) -> datetime:
    """O horário agendado mais recente que já passou (UTC)."""
    base = (ate or agora()).astimezone(FUSO)
    for dias in range(0, 3):
        dia = (base - timedelta(days=dias)).date()
        for h in sorted(HORARIOS_SGA, reverse=True):
            candidato = datetime.combine(dia, h, tzinfo=FUSO)
            if candidato <= base:
                return candidato.astimezone(timezone.utc)
    raise RuntimeError("sem horário do SGA")  # pragma: no cover


def busca_devida(db: Session, momento: datetime | None = None) -> bool:
    """O agendador roda se passou um horário há menos de 3 horas e nenhuma busca agendada começou depois dele."""
    momento = momento or agora()
    horario = ultimo_horario_sga(momento)
    if momento - horario > JANELA_DO_AGENDADOR:
        return False
    feita = db.scalars(select(Atualizacao).where(Atualizacao.fonte == "sga", Atualizacao.tipo == "agendada")
                       .order_by(Atualizacao.inicio.desc())).first()
    return feita is None or utc(feita.inicio) < horario


# ---------------------------------------------------------------- entrada e saída

def montar_entrada(db: Session, *, sga, powercrm, http_bi, momento: datetime | None = None, log_=None) -> Entrada:
    especialistas = [ler(db, c) for c in chaves(db, "esp:")]
    especialistas = [e for e in especialistas if isinstance(e, dict) and e.get("nome")]
    return Entrada(
        agora=(momento or agora()).astimezone(FUSO),
        old=ler(db, "all"),
        especialistas=especialistas,
        listas={e["nome"]: ler(db, "rm:" + N(e["nome"])) or [] for e in especialistas},
        comp_marks={d["id"]: d["data"] for d in bp.listar(db, "comp")},
        comp_registro=ler(db, "comp_registro") or [],
        sga=sga, powercrm=powercrm, http_bi=http_bi,
        log=log_ or (lambda *a: log.info("busca: %s", " ".join(str(x) for x in a))),
    )


def gravar_saida(db: Session, saida: Saida, inicio: datetime) -> int:
    """Troca os pacotes da busca anterior pelos novos, de uma vez só (no mesmo commit)."""
    pacotes = saida.pacotes or {}
    if not isinstance(pacotes.get("all"), dict):
        raise ErroBusca("a busca terminou sem o pacote geral (all)")
    # pacotes de equipe/especialista que sumiram (gerados por uma busca anterior) não ficam para trás
    db.execute(delete(Pacote).where(Pacote.origem == "busca", Pacote.chave.notin_(list(pacotes))))
    for chave, dados in pacotes.items():
        guardar(db, chave, dados, "busca")
    guardar(db, "novos_cancelados", saida.novos_cancelados or {}, "busca")
    guardar(db, "busca", {"feita_em": agora().isoformat(), "inicio": inicio.isoformat(), "resumo": saida.resumo},
            "busca")
    db.commit()
    return len(pacotes)


def _resumo_txt(saida: Saida, gravados: int) -> str:
    r = saida.resumo or {}
    partes = [f"Busca completa gravada: {gravados} pacote(s)"]
    if r.get("base_hoje") is not None:
        partes.append(f"base ativa hoje {r['base_hoje']}")
    if r.get("cancelados_recentes") is not None:
        partes.append(f"{r['cancelados_recentes']} cancelado(s) recente(s)")
    if r.get("bi"):
        partes.append(f"BI: {r['bi']}")
    return "; ".join(partes) + "."


# ---------------------------------------------------------------- a busca

def _liberar(db: Session) -> None:
    db.execute(delete(Trava).where(Trava.nome == TRAVA_BUSCA))
    db.commit()


def busca_completa(Sessao, cfg: Config, *, tipo: str = "agendada", pessoa_id: int | None = None, rodar=None,
                   clientes=None) -> dict:
    """Roda a busca inteira. `rodar` e `clientes` só mudam nos testes (script e fontes falsos)."""
    if not _uma_de_cada_vez.acquire(blocking=False):
        return {"ok": False, "mensagem": "Já tem uma busca rodando. Espere ela terminar."}
    try:
        with Sessao() as db:
            motivo = motivo_para_nao_rodar(db, cfg)
            if motivo is not None:
                return {"ok": False, "mensagem": motivo}
            travar(db, TRAVA_BUSCA, agora() + DURACAO_MAXIMA, "busca completa em andamento")
            a = iniciar(db, "sga", tipo, pessoa_id)
            inicio = agora()
            if clientes is None:
                sga = ClienteSGA(cfg.sga_token, cfg.sga_usuario, cfg.sga_senha, limite_chamadas=LIMITE_CHAMADAS_SGA)
                powercrm = ClientePowerCRM(cfg.powercrm_token) if cfg.powercrm_token else None
                http_bi = httpx2.Client(timeout=300)
            else:
                sga, powercrm, http_bi = clientes
            try:
                if rodar is None:
                    from .retorno import rodar  # o script adaptado (pesado): só carrega quando a busca roda
                saida = rodar(montar_entrada(db, sga=sga, powercrm=powercrm, http_bi=http_bi))
                gravados = gravar_saida(db, saida, inicio)
                return concluir(db, a, True, _resumo_txt(saida, gravados))
            except SGABloqueado as e:
                db.rollback()
                ate = proximo_horario_sga()
                travar(db, TRAVA_SGA, ate, str(e))
                return concluir(db, a, False, f"{e}. Nada foi gravado. O SGA fica pausado até {formatar(ate)}.")
            except (SGAErro, PowerCRMErro, ErroBusca) as e:
                db.rollback()
                return concluir(db, a, False, f"Busca parada, nada foi gravado: {e}.")
            except Exception as e:  # noqa: BLE001 - erro inesperado: registra só o tipo (o texto pode ter dados)
                db.rollback()
                log.exception("Busca completa: erro inesperado")
                return concluir(db, a, False, f"Busca parada por um erro inesperado ({type(e).__name__}). "
                                              "Nada foi gravado. Veja o registro do Render.")
            finally:
                _liberar(db)
                if clientes is None:
                    for c in (sga, powercrm, http_bi):
                        if c is not None:
                            (getattr(c, "fechar", None) or c.close)()
    finally:
        _uma_de_cada_vez.release()


def rodar_em_segundo_plano(Sessao, cfg: Config, *, tipo: str, pessoa_id: int | None = None) -> None:
    threading.Thread(target=busca_completa, args=(Sessao, cfg), kwargs={"tipo": tipo, "pessoa_id": pessoa_id},
                     daemon=True, name="busca-completa").start()


# ---------------------------------------------------------------- agendador

def agendador(Sessao, cfg: Config, parar: threading.Event) -> None:
    """Confere a cada 5 minutos se chegou a hora da busca do dia. Nunca derruba o servidor."""
    while not parar.wait(INTERVALO_DO_AGENDADOR):
        try:
            with Sessao() as db:
                devida = busca_devida(db)
            if devida:
                r = busca_completa(Sessao, cfg, tipo="agendada")
                if not r["ok"]:  # sem dados importados, SGA pausado...: registra uma vez por horário
                    with Sessao() as db:
                        if busca_devida(db):
                            concluir(db, iniciar(db, "sga", "agendada"), False, r["mensagem"])
        except Exception as e:  # noqa: BLE001
            log.warning("Agendador da busca: %s", type(e).__name__)
