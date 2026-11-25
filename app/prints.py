"""Prints de reativação lidos do Google Drive (pela conta de serviço, só leitura) para o card "Reativação".

No sistema atual, o botão "Enviar prints pela página da Exodus" (Apps Script) grava cada imagem na pasta
"Retorno Exodus – Prints de reativação" (sem subpastas), com nome "<mês> · <líder> · <data hora>.jpg" e descrição
JSON {lider, mes, enviado, original}; a atualização copiava a imagem para os assets da página (/_blob/<id>) e criava o
registro em reativ/<dono> (campo p: {chave: {id, url, esp, mes, at, assoc, res, conf, nota, rm?}}).

No sistema novo (atualizar_prints), a cada leitura:
1. ler_pasta: as imagens da pasta dos prints e das subpastas dela;
2. montar: imagem antiga (o Rafael coloca numa subpasta, com o nome = id do asset + extensão) liga ao registro que
   tem esse id: só a url (/api/print/<id do Drive>) e o campo drive mudam. Print novo (descrição com mes e lider) vira
   um registro em reativ/drive-<mês>, uma vez só (chave "d" + id do Drive). Print enviado até o último registro do
   sistema atual (maior "at" dos registros que não são drive-*) já foi copiado por ele: não vira registro de novo;
3. guarda os documentos que mudaram e o índice "prints_drive" (pacote do servidor, nunca vai para a página):
   {id do Drive: {mime, esp: [nomes N() de quem enviou]}}. A rota /api/print só mostra imagem que está no índice
   (arquivo de verdade da pasta dos prints) e num registro da reativ, para quem pode ver (pode_ver).
Não roda com a busca completa rodando (trava "busca_rodando"). Erro do Google: registra a mensagem e não grava nada.
"""
from __future__ import annotations

import json
import logging
import re
import threading
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import banco_pagina as bp
from .atualizacoes import concluir, iniciar, trava_ativa
from .busca.completa import TRAVA_BUSCA
from .comprovantes import _mes
from .config import FUSO, Config
from .dados import N, _especialista_da_pessoa, chaves, guardar, ler
from .db import Documento, Pessoa
from .fontes.google import ClienteGoogle, GoogleErro
from .servicos import lista_de_equipes
from .tempo import agora

log = logging.getLogger("escritorio")

PASTA = "application/vnd.google-apps.folder"
CAMPOS = "id,name,description,createdTime,mimeType,parents"
# Só imagens que o navegador mostra e que não rodam código (SVG fica de fora: aberto direto, rodaria no site).
TIPOS_DE_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PROFUNDIDADE = 5  # subpastas dentro de subpastas
LIMITE_ARQUIVOS = 20000
DOC_NOVOS = "drive-"  # reativ/drive-<mês>: um documento por mês (o limite é 1 MB por documento)
INDICE = "prints_drive"
ID_DRIVE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")

_uma_de_cada_vez = threading.Lock()
_cliente_da_rota = threading.Lock()


def url_do_print(drive_id: str) -> str:
    return "/api/print/" + drive_id


def _ms(valor) -> int | None:
    """Data do envio em milissegundos (o "at" da página): número, ISO ("2026-11-10T12:00:00.000Z") ou
    "10/11/2026 09:00[:00]" (Brasília)."""
    if isinstance(valor, bool) or valor in (None, ""):
        return None
    if isinstance(valor, (int, float)):
        return int(valor)
    t = str(valor).strip()
    try:
        d = datetime.fromisoformat(t)
    except ValueError:
        m = re.match(r"^(\d{1,2})/(\d{1,2})/(\d{4})(?:[ ,]+(\d{1,2}):(\d{2})(?::(\d{2}))?)?$", t)
        if not m:
            return None
        try:
            d = datetime(int(m.group(3)), int(m.group(2)), int(m.group(1)), int(m.group(4) or 0),
                         int(m.group(5) or 0), int(m.group(6) or 0), tzinfo=FUSO)
        except ValueError:
            return None
    if d.tzinfo is None:
        d = d.replace(tzinfo=FUSO)
    return int(d.timestamp() * 1000)


# ---------------------------------------------------------------- 1. leitura do Drive

def ler_pasta(cliente: ClienteGoogle, raiz: str) -> list[dict]:
    """As imagens da pasta dos prints e das subpastas (uma consulta por pasta). Cada uma ganha "_sub" (em subpasta)."""
    imagens, fila, vistas = [], [(raiz, 0)], {raiz}
    while fila:
        pasta, nivel = fila.pop(0)
        for a in cliente.arquivos(f"'{pasta}' in parents and trashed = false", CAMPOS, limite=LIMITE_ARQUIVOS):
            aid = str(a.get("id") or "")
            if not ID_DRIVE.match(aid):
                continue
            if a.get("mimeType") == PASTA:
                if nivel < PROFUNDIDADE and aid not in vistas:
                    vistas.add(aid)
                    fila.append((aid, nivel + 1))
            elif a.get("mimeType") in TIPOS_DE_IMAGEM:
                imagens.append(dict(a, _sub=nivel > 0))
    return sorted(imagens, key=lambda a: (str(a.get("createdTime") or ""), a["id"]))


def print_da_descricao(arq: dict) -> dict | None:
    """A descrição do Apps Script ({lider, mes, enviado, original}) vira {esp, mes, at}; o resto devolve None."""
    try:
        d = json.loads(arq.get("description") or "")
    except ValueError:
        return None
    if not isinstance(d, dict):
        return None
    mes, lider = _mes(d.get("mes")), " ".join(str(d.get("lider") or "").split())
    if not mes or not lider:
        return None
    return {"esp": lider, "mes": mes, "at": _ms(d.get("enviado")) or _ms(arq.get("createdTime"))}


def _nome_sem_extensao(nome) -> str:
    nome = str(nome or "").strip()
    return nome.rsplit(".", 1)[0].strip() if "." in nome else nome


# ---------------------------------------------------------------- 2. registros

def _registros(docs: dict) -> list[tuple[str, str, dict]]:
    saida = []
    for doc_id, dados in docs.items():
        p = dados.get("p") if isinstance(dados, dict) else None
        if isinstance(p, dict):
            saida += [(doc_id, chave, r) for chave, r in p.items() if isinstance(r, dict)]
    return saida


def montar(docs: dict, imagens: list[dict], indice_anterior: dict) -> tuple[set, dict, dict]:
    """Muda `docs` ({id do documento: dados}) no lugar. Devolve (documentos que mudaram, índice novo, contagens)."""
    registros = _registros(docs)
    por_asset: dict[str, list[tuple[str, dict]]] = {}
    for doc_id, _chave, r in registros:
        if r.get("id") not in (None, ""):
            por_asset.setdefault(str(r["id"]), []).append((doc_id, r))
    ja_tem_registro = {str(r.get("drive")) for _d, _c, r in registros if r.get("drive")}
    do_atual = [_ms(r.get("at")) for d, _c, r in registros if not d.startswith(DOC_NOVOS)]
    ultimo_do_atual = max((x for x in do_atual if x is not None), default=None)

    mudaram, indice = set(), {}
    n = {"imagens": len(imagens), "antigas": 0, "antigas_novas": 0, "novos": 0, "ja": 0, "copiados": 0,
         "ignoradas": 0}
    for img in imagens:
        did, url = img["id"], url_do_print(img["id"])
        antigos = por_asset.get(_nome_sem_extensao(img.get("name")))
        if antigos:  # imagem antiga (nome = id do asset): só a url e o drive do registro mudam
            n["antigas"] += 1
            for doc_id, r in antigos:
                if r.get("drive") != did or r.get("url") != url:
                    r["drive"], r["url"] = did, url
                    mudaram.add(doc_id)
                    n["antigas_novas"] += 1
            # quem enviou fica como na primeira ligação (o registro pode ser regravado pela página)
            esp = (indice_anterior.get(did) or {}).get("esp") or sorted({N(r.get("esp")) for _d, r in antigos} - {""})
            indice[did] = {"mime": img["mimeType"], "esp": esp}
            continue
        pr = print_da_descricao(img)
        if pr is None:
            n["ignoradas"] += 1
            continue
        if did in ja_tem_registro:
            n["ja"] += 1
        elif ultimo_do_atual is not None and pr["at"] is not None and pr["at"] <= ultimo_do_atual:
            n["copiados"] += 1  # o sistema atual já copiou este print para os assets: o registro dele já existe
            continue
        else:
            doc_id = DOC_NOVOS + pr["mes"]
            doc = docs.setdefault(doc_id, {})
            if not isinstance(doc.get("p"), dict):
                doc["p"] = {}
            doc["p"]["d" + did] = {"id": did, "drive": did, "url": url, "esp": pr["esp"], "mes": pr["mes"],
                                   "at": pr["at"], "assoc": "", "res": "", "conf": "", "nota": ""}
            mudaram.add(doc_id)
            ja_tem_registro.add(did)
            n["novos"] += 1
        indice[did] = {"mime": img["mimeType"], "esp": [N(pr["esp"])]}
    return mudaram, indice, n


# ---------------------------------------------------------------- a leitura completa

def motivo_para_nao_ler(db: Session, cfg: Config) -> str | None:
    if not cfg.google_service_account_json:
        return "A chave do Google (GOOGLE_SERVICE_ACCOUNT_JSON) não está no Render."
    if not cfg.drive_pasta_reativacao:
        return "O id da pasta dos prints (DRIVE_PASTA_REATIVACAO) não está no Render."
    if not ID_DRIVE.match(cfg.drive_pasta_reativacao):
        return "O id da pasta dos prints (DRIVE_PASTA_REATIVACAO) no Render não parece um id do Drive."
    if trava_ativa(db, TRAVA_BUSCA) is not None:
        return "A busca completa está rodando: os prints são lidos depois que ela terminar."
    return None


def _docs_da_reativ(db: Session) -> dict:
    return {d["id"]: d["data"] for d in bp.listar(db, "reativ", limite=1_000_000) if isinstance(d["data"], dict)}


def _gravar(db: Session, docs: dict, mudaram: set) -> None:
    for doc_id in sorted(mudaram):
        texto = json.dumps(docs[doc_id], ensure_ascii=False, separators=(",", ":"))
        if len(texto) > bp.TAMANHO_MAXIMO:
            raise ValueError("documento da reativ grande demais")
        db.merge(Documento(colecao="reativ", doc_id=doc_id, dados=texto, atualizado_em=agora(), atualizado_por=None))


def atualizar_prints(Sessao, cfg: Config, http=None, *, pessoa_id: int | None = None) -> dict:
    """Lê os prints do Drive e liga/cria os registros da reativ. `http` só muda nos testes."""
    if not _uma_de_cada_vez.acquire(blocking=False):
        return {"ok": False, "mensagem": "Já tem uma leitura dos prints rodando."}
    try:
        with Sessao() as db:
            motivo = motivo_para_nao_ler(db, cfg)
            if motivo is not None:
                return {"ok": False, "mensagem": motivo}
            a = iniciar(db, "drive", "prints", pessoa_id)
            cliente = None
            try:
                cliente = ClienteGoogle(cfg.google_service_account_json, http=http)
                imagens = ler_pasta(cliente, cfg.drive_pasta_reativacao)
                # os documentos são lidos depois do Drive (a parte demorada): menos chance de pegar uma versão velha
                docs = _docs_da_reativ(db)
                indice_anterior = ler(db, INDICE) or {}
                mudaram, indice, n = montar(docs, imagens, indice_anterior)
                _gravar(db, docs, mudaram)
                if indice != indice_anterior:
                    guardar(db, INDICE, indice, "drive")
                db.commit()
            except GoogleErro as e:
                db.rollback()
                return concluir(db, a, False, f"Google: {e}. Nada foi gravado.")
            except Exception as e:  # noqa: BLE001 - erro inesperado: registra só o tipo (o texto pode ter dados)
                db.rollback()
                log.warning("Prints: erro inesperado (%s)", type(e).__name__)
                return concluir(db, a, False, f"Leitura dos prints parada por um erro inesperado "
                                              f"({type(e).__name__}). Nada foi gravado.")
            finally:
                if http is None and cliente is not None:
                    cliente.fechar()
            texto = (f"Prints do Drive: {n['imagens']} imagem(ns) lida(s); {n['antigas']} imagem(ns) antiga(s) "
                     f"ligada(s) ao registro ({n['antigas_novas']} agora); {n['novos']} print(s) novo(s) no registro; "
                     f"{n['ja']} já registrado(s); {n['copiados']} já copiado(s) pelo sistema atual; "
                     f"{n['ignoradas']} sem descrição válida (ignorada(s)).")
            return concluir(db, a, True, texto)
    finally:
        _uma_de_cada_vez.release()


# ---------------------------------------------------------------- quem vê cada print

def nomes_visiveis(db: Session, p: Pessoa) -> set[str] | None:
    """None = todos (administrador, coordenação e financeiro). Líder: ele e os especialistas das equipes dele.
    Os demais (especialista, vendedora interna, cadastro): só os dele. Nomes em N()."""
    if p.tipo in bp.GESTAO:
        return None
    nomes = {N(p.nome)}
    proprio = _especialista_da_pessoa(db, p)
    if proprio:
        nomes.add(proprio)
    if p.tipo == "lider":
        equipes = {N(e) for e in lista_de_equipes(p.equipe)} - {""}
        for chave in chaves(db, "esp:"):
            esp = ler(db, chave) or {}
            if {N(e) for e in esp.get("eqs") or []} & equipes:
                nomes |= {chave[4:], N(esp.get("nome"))}
    return nomes - {""}


def pode_ver(nomes: set[str] | None, esps) -> bool:
    return nomes is None or bool({N(e) for e in esps or []} & nomes)


def filtrar_documento(nomes: set[str] | None, dados):
    """O documento da reativ só com os prints que a pessoa pode ver (os demais campos ficam de fora)."""
    if nomes is None or not isinstance(dados, dict):
        return dados
    p = dados.get("p") if isinstance(dados.get("p"), dict) else {}
    return {"p": {k: r for k, r in p.items() if isinstance(r, dict) and pode_ver(nomes, [r.get("esp")])}}


def filtrar_reativ(db: Session, p: Pessoa, docs: list[dict]) -> list[dict]:
    """A listagem da reativ para a página: cada um só recebe os prints que pode ver."""
    nomes = nomes_visiveis(db, p)
    if nomes is None:
        return docs
    saida = []
    for d in docs:
        filtrado = filtrar_documento(nomes, d["data"])
        if filtrado.get("p"):
            saida.append({"id": d["id"], "data": filtrado})
    return saida


def _em_registro(db: Session, drive_id: str) -> bool:
    """O id está no campo drive de algum registro da reativ (procura só nos documentos que citam o id)."""
    padrao = "%" + drive_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    for texto in db.scalars(select(Documento.dados).where(Documento.colecao == "reativ",
                                                          Documento.dados.like(padrao, escape="\\"))):
        try:
            dados = json.loads(texto)
        except ValueError:
            continue
        if isinstance(dados, dict) and any(r.get("drive") == drive_id for _d, _c, r in _registros({"x": dados})):
            return True
    return False


def imagem_que_pode_ver(db: Session, p: Pessoa, drive_id: str) -> str | None:
    """O tipo da imagem, se a pessoa pode ver; senão None (a rota responde 404, sem dizer por quê).

    Só vale id que a leitura achou na pasta dos prints (índice do servidor) e que está num registro da reativ: a rota
    nunca vira um caminho para outros arquivos do Drive. Quem enviou vem do índice (do Drive), não do registro."""
    if not ID_DRIVE.match(drive_id or ""):
        return None
    item = (ler(db, INDICE) or {}).get(drive_id)
    if not isinstance(item, dict) or item.get("mime") not in TIPOS_DE_IMAGEM:
        return None
    if not pode_ver(nomes_visiveis(db, p), item.get("esp")) or not _em_registro(db, drive_id):
        return None
    return item["mime"]


def baixar(app_state, cfg: Config, drive_id: str) -> bytes:
    """A imagem pela conta de serviço. O cliente fica guardado no servidor (o login do Google vale 1 hora)."""
    with _cliente_da_rota:
        cliente = getattr(app_state, "google_prints", None)
        if cliente is None:
            if not cfg.google_service_account_json:
                raise GoogleErro("a chave do Google não está no Render")
            cliente = app_state.google_prints = ClienteGoogle(cfg.google_service_account_json)
    return cliente.baixar(drive_id)
