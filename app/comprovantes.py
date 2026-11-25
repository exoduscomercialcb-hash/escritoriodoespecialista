"""Comprovantes de adesão lidos do Google Drive (pela conta de serviço, só leitura), como a tarefa de hora em hora do
sistema atual ("Pix": só o Drive, sem SGA, sem Power CRM e sem BI).

Cada comprovante é um arquivo em "Comprovantes de adesões / <Mês> / Equipes / <Equipe> / <Especialista>", gravado pelo
Apps Script. A descrição do arquivo é um JSON {placa (ou chassi), mes, equipe, especialista, associado, valor, lider,
enviado}. Arquivo sem placa/chassi e mês na descrição não é comprovante (ex.: print de WhatsApp, erro de 31/10).

Passos (atualizar_comprovantes):
1. ler_do_drive: uma consulta no Drive (só arquivos dentro da pasta dos comprovantes) vira itens do registro;
2. montar_registro: valor lido e conferência vêm da coleção compconf (ou do registro anterior); o registro anterior
   (importação do sistema atual) é mantido, e o que veio do Drive entra ou substitui;
3. guarda o pacote "comp_registro" (a busca completa também lê ele) e aplica nas adesões dos pacotes, como o pix.py
   (campos cp e mk, a partir de out/26).
Não roda com a busca completa rodando (trava "busca_rodando"): a busca grava os pacotes por cima (erro de 24/11 no
sistema atual). Erro do Google: registra a mensagem (nunca o texto da resposta) e não grava nada.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime, time, timedelta, timezone

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import banco_pagina as bp
from .atualizacoes import concluir, iniciar, trava_ativa
from .busca.completa import TRAVA_BUSCA
from .config import FUSO, Config
from .dados import N, chaves, guardar, ler
from .db import Atualizacao, Pacote
from .fontes.google import ClienteGoogle, GoogleErro
from .tempo import agora, utc

log = logging.getLogger("escritorio")

COMP_DESDE = "2026-10"  # como no pix.py e no script: a aba de comprovantes começa em out/26
CRIADOS_DEPOIS_DE = "2026-09-30T00:00:00"
PASTA = "application/vnd.google-apps.folder"
CONSULTA = (f"fullText contains 'placa' and mimeType != '{PASTA}' and trashed = false "
            f"and createdTime > '{CRIADOS_DEPOIS_DE}'")
CAMPOS = "id,name,description,createdTime,webViewLink,parents"
LIMITE_ARQUIVOS = 50000  # o cliente lê 1.000 por página
# Horários da tarefa de hora em hora do sistema atual (Brasília): :25, das 7h às 15h e das 17h às 22h.
HORARIOS_COMPROVANTES = tuple(time(h, 25) for h in (*range(7, 16), *range(17, 23)))
JANELA_DO_AGENDADOR = timedelta(minutes=50)  # servidor reiniciado ou busca rodando: tenta até perto do próximo horário
INTERVALO_DO_AGENDADOR = 60  # segundos entre uma conferência e outra

MESES = {"JAN": 1, "FEV": 2, "MAR": 3, "ABR": 4, "MAI": 5, "JUN": 6, "JUL": 7, "AGO": 8, "SET": 9, "OUT": 10,
         "NOV": 11, "DEZ": 12}

_uma_de_cada_vez = threading.Lock()


def pl_(s) -> str:
    """Igual ao pix.py: placa ou chassi só com letras maiúsculas e números."""
    return re.sub(r"[^A-Z0-9]", "", N(s))


def _mes(texto) -> str | None:
    """"2026-11", "11/2026", "Novembro/2026" ou "nov 26" -> "2026-11" (o formato do campo m das adesões)."""
    t = N(texto)
    m = re.match(r"^(\d{4})-(\d{1,2})\b", t)
    if m:
        ano, mes = int(m.group(1)), int(m.group(2))
    elif (m := re.match(r"^(\d{1,2})[/ -](\d{4})$", t)):
        mes, ano = int(m.group(1)), int(m.group(2))
    elif (m := re.match(r"^([A-Z]{3})[A-Z]*\W*(?:DE\W+)?(\d{4}|\d{2})$", t)) and m.group(1) in MESES:
        mes, ano = MESES[m.group(1)], int(m.group(2))
        ano += 2000 if ano < 100 else 0
    else:
        return None
    return f"{ano:04d}-{mes:02d}" if 1 <= mes <= 12 and 2000 <= ano <= 2100 else None


def _valor(v):
    """Número, "150", "150.5", "R$ 1.234,56" -> float; o que não for valor -> None (a página faz +cp.v)."""
    if isinstance(v, bool) or v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    t = re.sub(r"[^\d,.\-]", "", str(v))
    if "," in t:
        t = t.replace(".", "").replace(",", ".")
    try:
        return float(t)
    except ValueError:
        return None


def _id_do_arquivo(url) -> str:
    m = re.search(r"/d/([A-Za-z0-9_-]{10,})", str(url or "")) or re.search(r"[?&]id=([A-Za-z0-9_-]{10,})",
                                                                            str(url or ""))
    return m.group(1) if m else ""


def _chave(c: dict) -> tuple:
    return (c.get("mes") or "", pl_(c.get("pl")) or pl_(c.get("ch")), str(c.get("enviado") or ""))


# ---------------------------------------------------------------- 1. leitura do Drive

def item_do_arquivo(arq: dict) -> dict | None:
    """A descrição do arquivo vira item do registro; o que não for comprovante devolve None."""
    try:
        d = json.loads(arq.get("description") or "")
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    pl, ch, mes = pl_(d.get("placa")), pl_(d.get("chassi")), _mes(d.get("mes"))
    if not (pl or ch) or not mes:
        return None
    vi = _valor(d.get("valor"))
    return {"mes": mes, "pl": pl, "ch": "" if pl else ch, "eq": str(d.get("equipe") or ""),
            "esp": str(d.get("especialista") or ""), "vi": vi, "valor": vi, "url": arq.get("webViewLink") or "",
            "enviado": str(d.get("enviado") or arq.get("createdTime") or ""), "conferido": None,
            "arquivo": arq.get("name") or ""}


def _pastas_dentro(cliente: ClienteGoogle, raiz: str) -> set[str]:
    """A pasta dos comprovantes e todas as subpastas (mês, equipe, especialista), numa consulta só."""
    pastas = cliente.arquivos(f"mimeType = '{PASTA}' and trashed = false", "id,parents", limite=LIMITE_ARQUIVOS)
    dentro, mudou = {raiz}, True
    while mudou:
        mudou = False
        for p in pastas:
            if p.get("id") not in dentro and set(p.get("parents") or []) & dentro:
                dentro.add(p["id"])
                mudou = True
    return dentro


def ler_do_drive(cliente: ClienteGoogle, pasta_raiz: str | None = None) -> list[dict]:
    """Os comprovantes que a conta de serviço enxerga, criados desde 01/10/2026, em ordem de envio.

    Com `pasta_raiz`, só os arquivos dentro da pasta dos comprovantes: a conta de serviço também enxerga a pasta dos
    prints de reativação, que não são comprovantes de adesão."""
    arquivos = cliente.arquivos(CONSULTA, CAMPOS, limite=LIMITE_ARQUIVOS)
    if pasta_raiz:
        dentro = _pastas_dentro(cliente, pasta_raiz)
        arquivos = [a for a in arquivos if set(a.get("parents") or []) & dentro]
    itens = [i for i in (item_do_arquivo(a) for a in arquivos) if i is not None]
    return sorted(itens, key=lambda i: (i["enviado"], i["url"]))


# ---------------------------------------------------------------- 2. registro

def _conferencia(compconf: dict, c: dict) -> dict | None:
    """compconf: "<mes>-<placa ou chassi>-<enviado>" -> {lido, conferido}."""
    for chave in {c.get("pl") or c.get("ch"), pl_(c.get("pl")) or pl_(c.get("ch"))}:
        doc = compconf.get(f"{c.get('mes')}-{chave}-{c.get('enviado')}")
        if isinstance(doc, dict):
            return doc
    return None


def _completar(c: dict, compconf: dict, anterior: dict | None) -> dict:
    c = dict(c)
    doc = _conferencia(compconf, c)
    if doc is not None:
        lido = _valor(doc.get("lido"))
        c["valor"] = lido if lido is not None else c.get("vi")
        c["conferido"] = doc.get("conferido")
    elif anterior is not None:
        c["valor"] = anterior.get("valor") if anterior.get("valor") is not None else c.get("vi")
        c["conferido"] = anterior.get("conferido")
    return c


def montar_registro(db: Session, itens: list[dict]) -> list:
    """O registro completo: o anterior (importação ou leitura passada) com os itens do Drive por cima.

    Valor lido e conferido: da compconf; sem ela, do item anterior do mesmo arquivo (url) ou da mesma chave
    (mês, placa ou chassi, envio). Sem leitura nenhuma, valor = informado."""
    compconf = {d["id"]: d["data"] for d in bp.listar(db, "compconf", limite=1_000_000)}
    antigos = [c for c in (ler(db, "comp_registro") or []) if isinstance(c, dict)]
    por_id = {_id_do_arquivo(c.get("url")): c for c in antigos if _id_do_arquivo(c.get("url"))}
    por_chave = {_chave(c): c for c in antigos}
    usados, saida = set(), []
    for item in itens:
        anterior = por_id.get(_id_do_arquivo(item.get("url"))) or por_chave.get(_chave(item))
        if anterior is not None:
            usados.add(id(anterior))
        saida.append(_completar(item, compconf, anterior))
    # o que já estava no registro e não veio do Drive fica (como no sistema atual, o registro só cresce)
    for c in antigos:
        if id(c) not in usados:
            saida.append(_completar(c, compconf, c))
    return sorted(saida, key=lambda c: (str(c.get("enviado") or ""), str(c.get("url") or "")))


# ---------------------------------------------------------------- 3. aplicar nas adesões (porta do pix.fix)

def _mais_recentes(registro: list) -> dict:
    cmp = {}
    for c in registro:
        if not isinstance(c, dict):
            continue
        kk = (c.get("mes") or "") + "|" + (pl_(c.get("pl")) or pl_(c.get("ch")))
        if kk.endswith("|"):
            continue
        if kk not in cmp or str(cmp[kk].get("enviado")) < str(c.get("enviado")):
            cmp[kk] = c
    return cmp


def _fix(a_: dict, cmp: dict, marcas: dict, regras: dict) -> bool:
    """O pix.fix: grava cp (comprovante mais recente do mês) e mk (marcas do coordenador). True se mudou."""
    k = a_.get("m") or ""
    if k < COMP_DESDE:
        return False
    antes = json.dumps([a_.get("cp"), a_.get("mk")], sort_keys=True)
    plx = pl_(a_.get("pl"))
    chx = a_.get("ch") or ""
    ck = plx or chx or ("SP" + re.sub(r"[^A-Z]", "", N(a_.get("n")))[:10] + re.sub(r"\D", "", a_.get("dc") or "")[:4])
    c0 = cmp.get(k + "|" + ck)
    if c0:
        a_["cp"] = {"v": c0.get("valor"), "url": c0.get("url") or "", "at": c0.get("enviado") or "",
                    "vc": c0.get("conferido"), "vi": c0.get("vi")}
    rg_ = regras.get(ck) or (regras.get("NOME:" + N(a_.get("n"))) if not plx else None) or {}
    if not isinstance(rg_, dict) or (rg_.get("mes") and rg_["mes"] != k):
        rg_ = {}
    do_mes = marcas.get(k) if isinstance(marcas.get(k), dict) else {}
    marca = do_mes.get(ck) if isinstance(do_mes.get(ck), dict) else {}
    mk = dict({x_: v_ for x_, v_ in rg_.items() if x_ in ("nc", "obs")}, **marca)
    mk = {x_: mk.get(x_) for x_ in ("ok", "nc", "obs", "okby", "okat", "pg", "pgby", "pgat", "pgl")
          if mk.get(x_) not in (None, "")}
    if mk:
        a_["mk"] = mk
    else:
        a_.pop("mk", None)
    return json.dumps([a_.get("cp"), a_.get("mk")], sort_keys=True) != antes


def aplicar_nos_pacotes(db: Session, registro: list) -> int:
    """Aplica o registro e as marcas (comp/regras e comp/<mês>) nas adesões de "all", "t:*" e "e:*".

    Só regrava o pacote que mudou e mantém a origem dele (importação ou busca). Devolve quantas adesões mudaram
    (somando os pacotes, como o pix.py)."""
    cmp = _mais_recentes(registro)
    marcas = {d["id"]: d["data"] for d in bp.listar(db, "comp", limite=1_000_000)}
    regras = marcas.get("regras") if isinstance(marcas.get("regras"), dict) else {}
    total = 0
    for chave in ["all", *chaves(db, "t:"), *chaves(db, "e:")]:
        p = db.get(Pacote, chave)
        if p is None:
            continue
        dados = json.loads(p.dados)
        if not isinstance(dados, dict):
            continue
        mudaram = sum(_fix(a, cmp, marcas, regras) for a in dados.get("ades") or [] if isinstance(a, dict))
        if mudaram:
            p.dados = json.dumps(dados, ensure_ascii=False, separators=(",", ":"))
            p.atualizado_em = agora()
            total += mudaram
    return total


# ---------------------------------------------------------------- a leitura completa

def motivo_para_nao_ler(db: Session, cfg: Config) -> str | None:
    if not cfg.google_service_account_json:
        return "A chave do Google (GOOGLE_SERVICE_ACCOUNT_JSON) não está no Render."
    if not cfg.drive_pasta_comprovantes:
        return "O id da pasta dos comprovantes (DRIVE_PASTA_COMPROVANTES) não está no Render."
    if trava_ativa(db, TRAVA_BUSCA) is not None:
        return "A busca completa está rodando: os comprovantes são lidos depois que ela terminar."
    return None


def atualizar_comprovantes(Sessao, cfg: Config, http=None, *, pessoa_id: int | None = None) -> dict:
    """Lê os comprovantes do Drive, guarda o registro e aplica nos pacotes. `http` só muda nos testes."""
    if not _uma_de_cada_vez.acquire(blocking=False):
        return {"ok": False, "mensagem": "Já tem uma leitura dos comprovantes rodando."}
    try:
        with Sessao() as db:
            motivo = motivo_para_nao_ler(db, cfg)
            if motivo is not None:
                return {"ok": False, "mensagem": motivo}
            a = iniciar(db, "drive", "comprovantes", pessoa_id)
            cliente = None
            try:
                cliente = ClienteGoogle(cfg.google_service_account_json, http=http)
                itens = ler_do_drive(cliente, cfg.drive_pasta_comprovantes)
                registro = montar_registro(db, itens)
                if trava_ativa(db, TRAVA_BUSCA) is not None:  # a busca começou durante a leitura: ela grava por cima
                    db.rollback()
                    return concluir(db, a, False, "A busca completa começou durante a leitura dos comprovantes. Nada "
                                                  "foi gravado; a próxima leitura traz os comprovantes.")
                mudou_registro = registro != (ler(db, "comp_registro") or [])
                if mudou_registro:
                    guardar(db, "comp_registro", registro, "drive")
                mudaram = aplicar_nos_pacotes(db, registro)
                db.commit()
            except GoogleErro as e:
                db.rollback()
                return concluir(db, a, False, f"Google: {e}. Nada foi gravado.")
            except Exception as e:  # noqa: BLE001 - erro inesperado: registra só o tipo (o texto pode ter dados)
                db.rollback()
                log.warning("Comprovantes: erro inesperado (%s)", type(e).__name__)
                return concluir(db, a, False, f"Leitura dos comprovantes parada por um erro inesperado "
                                              f"({type(e).__name__}). Nada foi gravado.")
            finally:
                if http is None and cliente is not None:
                    cliente.fechar()
            texto = (f"Comprovantes do Drive: {len(itens)} lido(s); registro com {len(registro)} item(ns)"
                     f"{' (atualizado)' if mudou_registro else ' (sem mudança)'}; "
                     f"{mudaram} adesão(ões) mudaram nos cards.")
            return concluir(db, a, True, texto)
    finally:
        _uma_de_cada_vez.release()


# ---------------------------------------------------------------- agendador (de hora em hora, aos :25)

def ultimo_horario_comprovantes(ate: datetime | None = None) -> datetime:
    """O horário da tarefa de hora em hora mais recente que já passou (UTC)."""
    base = (ate or agora()).astimezone(FUSO)
    for dias in range(0, 3):
        dia = (base - timedelta(days=dias)).date()
        for h in sorted(HORARIOS_COMPROVANTES, reverse=True):
            candidato = datetime.combine(dia, h, tzinfo=FUSO)
            if candidato <= base:
                return candidato.astimezone(timezone.utc)
    raise RuntimeError("sem horário dos comprovantes")  # pragma: no cover


def leitura_devida(db: Session, momento: datetime | None = None) -> bool:
    """Roda se passou um horário há menos de 50 minutos e nenhuma leitura começou depois dele."""
    momento = momento or agora()
    horario = ultimo_horario_comprovantes(momento)
    if momento - horario > JANELA_DO_AGENDADOR:
        return False
    feita = db.scalars(select(Atualizacao).where(Atualizacao.fonte == "drive", Atualizacao.tipo == "comprovantes")
                       .order_by(Atualizacao.inicio.desc())).first()
    return feita is None or utc(feita.inicio) < horario


def agendador_comprovantes(Sessao, cfg: Config, parar: threading.Event) -> None:
    """Confere a cada minuto se chegou um horário da leitura. Com a busca rodando, tenta de novo no minuto seguinte.
    Nunca derruba o servidor."""
    while not parar.wait(INTERVALO_DO_AGENDADOR):
        try:
            with Sessao() as db:
                devida = leitura_devida(db)
            if devida:
                atualizar_comprovantes(Sessao, cfg)
        except Exception as e:  # noqa: BLE001
            log.warning("Agendador dos comprovantes: %s", type(e).__name__)
