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
3. zips (25/11: o Rafael subiu os prints antigos num .zip, sem descompactar): cada .zip da pasta (e subpastas) ainda
   não lido é baixado uma vez (estado "prints_zip": ids e md5 dos zips já lidos; cópia igual não é baixada de novo) e
   aberto com cuidado (abrir_zip: nada de caminho com ".." ou absoluto, só JPEG/PNG/WebP/GIF pela extensão e pelos
   bytes, limite por imagem e no total). Imagem com nome = id de um registro da reativ vai para a tabela "imagens" (com
   quem pode ver, tirado dos registros na primeira ligação) e o registro passa a ter url /api/print/banco/<id do
   asset> e zip = id do zip no Drive. As demais são contadas e ignoradas;
4. guarda os documentos que mudaram e o índice "prints_drive" (pacote do servidor, nunca vai para a página):
   {id do Drive: {mime, esp: [nomes N() de quem enviou]}}. A rota /api/print só mostra imagem que está no índice
   (arquivo de verdade da pasta dos prints) e num registro da reativ, para quem pode ver (pode_ver); a rota
   /api/print/banco/<id> faz o mesmo com as imagens do banco (quem pode ver vem da tabela "imagens").
Não roda com a busca completa rodando (trava "busca_rodando"). Erro do Google: registra a mensagem e não grava nada.
"""
from __future__ import annotations

import io
import json
import logging
import re
import threading
import zipfile
import zlib
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import banco_pagina as bp
from .atualizacoes import concluir, iniciar, trava_ativa
from .busca.completa import TRAVA_BUSCA
from .comprovantes import _mes
from .config import FUSO, Config
from .dados import N, _especialista_da_pessoa, chaves, guardar, ler
from .db import Documento, Imagem, Pessoa
from .fontes.google import LIMITE_ZIP, ArquivoGrande, ClienteGoogle, GoogleErro
from .servicos import lista_de_equipes
from .tempo import agora

log = logging.getLogger("escritorio")

PASTA = "application/vnd.google-apps.folder"
CAMPOS = "id,name,description,createdTime,mimeType,parents,size,md5Checksum"
# Só imagens que o navegador mostra e que não rodam código (SVG fica de fora: aberto direto, rodaria no site).
TIPOS_DE_IMAGEM = {"image/jpeg", "image/png", "image/webp", "image/gif"}
PROFUNDIDADE = 5  # subpastas dentro de subpastas
LIMITE_ARQUIVOS = 20000
DOC_NOVOS = "drive-"  # reativ/drive-<mês>: um documento por mês (o limite é 1 MB por documento)
INDICE = "prints_drive"
ID_DRIVE = re.compile(r"^[A-Za-z0-9_-]{10,200}$")
# zip dos prints antigos (cada imagem com nome = id do asset do sistema atual + extensão)
TIPOS_DE_ZIP = {"application/zip", "application/x-zip-compressed", "application/x-zip"}
ESTADO_ZIP = "prints_zip"  # pacote do servidor: {"zips": {id do zip no Drive: {md5, em, contagens}}}
ID_ASSET = re.compile(r"^[A-Za-z0-9_-]{1,200}$")
EXTENSOES_DE_IMAGEM = {".jpg", ".jpeg", ".png", ".webp", ".gif"}
LIMITE_IMAGEM_ZIP = 20 * 1024 * 1024  # por imagem, descompactada
LIMITE_TOTAL_ZIP = 300 * 1024 * 1024  # soma das imagens descompactadas: acima disso o zip inteiro é recusado
LIMITE_ENTRADAS_ZIP = 50000

_uma_de_cada_vez = threading.Lock()
_cliente_da_rota = threading.Lock()


def url_do_print(drive_id: str) -> str:
    return "/api/print/" + drive_id


def url_do_banco(asset_id: str) -> str:
    """Imagem guardada no banco (tabela imagens). Id do Drive nunca tem "/": os dois endereços não se confundem."""
    return "/api/print/banco/" + asset_id


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

def _e_zip(a: dict) -> bool:
    return a.get("mimeType") in TIPOS_DE_ZIP or str(a.get("name") or "").strip().lower().endswith(".zip")


def ler_pasta(cliente: ClienteGoogle, raiz: str) -> tuple[list[dict], list[dict]]:
    """As imagens e os .zip da pasta dos prints e das subpastas (uma consulta por pasta). Cada imagem ganha "_sub"
    (em subpasta)."""
    imagens, zips, fila, vistas = [], [], [(raiz, 0)], {raiz}
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
            elif _e_zip(a):
                zips.append(a)

    def ordem(a):
        return str(a.get("createdTime") or ""), a["id"]
    return sorted(imagens, key=ordem), sorted(zips, key=ordem)


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
                if r.get("url") == url_do_banco(str(r["id"])):
                    continue  # já tem a imagem guardada no banco (veio do zip): vale ela
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


# ---------------------------------------------------------------- 3. zip dos prints antigos

class ZipRecusado(Exception):
    """O zip inteiro fica de fora (danificado, grande demais ou com imagens demais descompactadas): nada é gravado."""


def tipo_pelos_bytes(dados: bytes) -> str | None:
    """O tipo pelos bytes iniciais (não pela extensão, que qualquer um troca)."""
    if dados.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if dados.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if dados[:6] in (b"GIF87a", b"GIF89a"):
        return "image/gif"
    if dados[:4] == b"RIFF" and dados[8:12] == b"WEBP":
        return "image/webp"
    return None


def asset_da_entrada(nome: str) -> str | None:
    """O id do asset pelo nome da entrada do zip ("pasta/3f2a….jpg" -> "3f2a…"), ou None se a entrada não serve:
    caminho absoluto ou com "..", pasta, arquivo oculto (inclusive os "._" do Mac), extensão que não é de imagem."""
    n = str(nome or "").replace("\\", "/")
    if not n or n.startswith("/") or re.match(r"^[A-Za-z]:", n) or n.endswith("/") or "\x00" in n:
        return None
    partes = n.split("/")
    if ".." in partes or "__MACOSX" in partes:
        return None
    base = partes[-1].strip()
    if base.startswith(".") or "." not in base:
        return None
    raiz, ext = base.rsplit(".", 1)
    if "." + ext.lower() not in EXTENSOES_DE_IMAGEM or not ID_ASSET.match(raiz):
        return None
    return raiz


def abrir_zip(conteudo: bytes, contagem: dict):
    """Confere o zip inteiro antes de descompactar qualquer coisa e devolve um gerador de (asset, mime, bytes).

    Contra zip-bomba: só entram entradas de imagem (pelo nome) de até LIMITE_IMAGEM_ZIP; se a soma delas passar de
    LIMITE_TOTAL_ZIP (ou o zip tiver entradas demais), o zip inteiro é recusado (ZipRecusado) antes de ler qualquer
    imagem. O tamanho de cada entrada é o declarado no zip, e a leitura nunca passa dele (o zipfile para no tamanho
    declarado e confere o CRC); mesmo assim cada leitura é limitada. contagem["ignoradas"] soma o que fica de fora."""
    try:
        zf = zipfile.ZipFile(io.BytesIO(conteudo))
        entradas = zf.infolist()
    except (zipfile.BadZipFile, zipfile.LargeZipFile, ValueError, OSError, EOFError):
        raise ZipRecusado("zip danificado") from None
    if len(entradas) > LIMITE_ENTRADAS_ZIP:
        raise ZipRecusado("entradas demais")
    boas, total = [], 0
    for info in entradas:
        if info.is_dir():
            continue
        asset = asset_da_entrada(info.filename)
        if asset is None or info.flag_bits & 0x1 or info.file_size > LIMITE_IMAGEM_ZIP:  # 0x1: com senha
            contagem["ignoradas"] += 1
            continue
        total += info.file_size
        if total > LIMITE_TOTAL_ZIP:
            raise ZipRecusado("descompactado grande demais")
        boas.append((asset, info))

    def ler():
        for asset, info in boas:
            try:
                with zf.open(info) as f:
                    dados = f.read(LIMITE_IMAGEM_ZIP + 1)
            except (zipfile.BadZipFile, zlib.error, NotImplementedError, RuntimeError, EOFError, OSError):
                contagem["ignoradas"] += 1  # entrada danificada (CRC), compressão desconhecida...
                continue
            mime = tipo_pelos_bytes(dados)
            if len(dados) > LIMITE_IMAGEM_ZIP or mime not in TIPOS_DE_IMAGEM:
                contagem["ignoradas"] += 1  # nome de imagem, mas o conteúdo não é
                continue
            yield asset, mime, dados
    return ler()


def _registros_do_sistema_atual(docs: dict) -> dict[str, list[tuple[str, dict]]]:
    """{id do asset: [(documento, registro)]}, só dos documentos do sistema atual (os drive-* são prints novos)."""
    por_asset: dict[str, list[tuple[str, dict]]] = {}
    for doc_id, _chave, r in _registros(docs):
        if not doc_id.startswith(DOC_NOVOS) and r.get("id") not in (None, ""):
            por_asset.setdefault(str(r["id"]), []).append((doc_id, r))
    return por_asset


def ler_zips(db: Session, cliente: ClienteGoogle, zips: list[dict], docs: dict, estado: dict) -> dict:
    """Baixa e abre os zips ainda não lidos e guarda na tabela imagens as que têm registro. Muda `estado` no lugar
    (os zips lidos, para não baixar de novo). Não faz commit: quem chama grava tudo junto (ou nada, se der erro)."""
    n = {"zips_lidos": 0, "zips_iguais": 0, "zips_recusados": 0, "ligadas": 0, "repetidas": 0, "sem_registro": 0,
         "ignoradas": 0}
    lidos = estado.setdefault("zips", {})
    md5_lidos = {str(v.get("md5")) for v in lidos.values() if isinstance(v, dict) and v.get("md5")}
    por_asset = _registros_do_sistema_atual(docs)
    no_banco = set(db.scalars(select(Imagem.id)))
    for z in zips:
        zid = str(z["id"])
        if zid in lidos:
            continue
        md5 = str(z.get("md5Checksum") or "") or None
        if md5 and md5 in md5_lidos:  # cópia igual a um zip já lido: nem baixa
            lidos[zid] = {"md5": md5, "em": agora().isoformat(), "igual": True}
            n["zips_iguais"] += 1
            continue
        c = {"ligadas": 0, "repetidas": 0, "sem_registro": 0, "ignoradas": 0}
        try:
            try:
                tamanho = int(z.get("size") or 0)
            except (TypeError, ValueError):
                tamanho = 0
            if tamanho > LIMITE_ZIP:
                raise ZipRecusado("zip grande demais")
            try:
                conteudo = cliente.baixar(zid, LIMITE_ZIP)
            except ArquivoGrande:
                raise ZipRecusado("zip grande demais") from None
            imagens = abrir_zip(conteudo, c)
            for asset, mime, dados in imagens:
                if asset not in por_asset:
                    c["sem_registro"] += 1
                    continue
                if asset in no_banco:
                    c["repetidas"] += 1  # a mesma imagem em outro zip (ou duas vezes no mesmo): não duplica
                    continue
                esp = sorted({N(r.get("esp")) for _d, r in por_asset[asset]} - {""})
                img = Imagem(id=asset, mime=mime, dados=dados, esp=json.dumps(esp, ensure_ascii=False),
                             origem="zip:" + zid, criado_em=agora())
                db.add(img)
                db.flush()
                db.expunge(img)  # os bytes não ficam presos na sessão até o fim da leitura
                no_banco.add(asset)
                c["ligadas"] += 1
            del conteudo
            lidos[zid] = dict(c, md5=md5, em=agora().isoformat())
            n["zips_lidos"] += 1
        except ZipRecusado as e:
            lidos[zid] = {"md5": md5, "em": agora().isoformat(), "recusado": str(e)}
            n["zips_recusados"] += 1
            c = dict.fromkeys(c, 0)  # nada deste zip entra nas contagens de imagens
        if md5:
            md5_lidos.add(md5)
        for k, v in c.items():
            n[k] += v
    return n


def ligar_imagens_do_banco(db: Session, docs: dict) -> set:
    """Todo registro do sistema atual cujo id tem imagem no banco passa a apontar para ela (url /api/print/banco/<id>
    e zip = id do zip de onde veio). Roda a cada leitura, sem baixar nada: vale também para registro importado de
    novo depois do zip. Muda `docs` no lugar; devolve os documentos que mudaram."""
    origem = {i: o for i, o in db.execute(select(Imagem.id, Imagem.origem))}
    mudaram = set()
    for asset, registros in _registros_do_sistema_atual(docs).items():
        if asset not in origem:
            continue
        url = url_do_banco(asset)
        zid = str(origem[asset] or "").removeprefix("zip:") or None
        for doc_id, r in registros:
            if r.get("url") != url or r.get("zip") != zid:
                r["url"], r["zip"] = url, zid
                mudaram.add(doc_id)
    return mudaram


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
                imagens, zips = ler_pasta(cliente, cfg.drive_pasta_reativacao)
                # os documentos são lidos depois do Drive (a parte demorada): menos chance de pegar uma versão velha
                docs = _docs_da_reativ(db)
                estado = ler(db, ESTADO_ZIP)
                estado = estado if isinstance(estado, dict) else {}
                estado_anterior = json.dumps(estado, sort_keys=True)
                nz = ler_zips(db, cliente, zips, docs, estado)
                indice_anterior = ler(db, INDICE) or {}
                mudaram, indice, n = montar(docs, imagens, indice_anterior)
                mudaram_banco = ligar_imagens_do_banco(db, docs)
                _gravar(db, docs, mudaram | mudaram_banco)
                if indice != indice_anterior:
                    guardar(db, INDICE, indice, "drive")
                if json.dumps(estado, sort_keys=True) != estado_anterior:
                    guardar(db, ESTADO_ZIP, estado, "drive")
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
                     f"{n['ignoradas']} sem descrição válida (ignorada(s)). Zip: {nz['zips_lidos']} lido(s) agora, "
                     f"{nz['zips_iguais']} cópia(s) de zip já lido, {nz['zips_recusados']} recusado(s); "
                     f"{nz['ligadas']} imagem(ns) do zip ligada(s) ao registro, {nz['repetidas']} repetida(s), "
                     f"{nz['sem_registro']} sem registro, {nz['ignoradas']} ignorada(s).")
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


def _em_registro(db: Session, drive_id: str, confere=None) -> bool:
    """O id está no campo drive de algum registro da reativ (ou o registro passa em `confere`); procura só nos
    documentos que citam o id."""
    confere = confere or (lambda r: r.get("drive") == drive_id)
    padrao = "%" + drive_id.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_") + "%"
    for texto in db.scalars(select(Documento.dados).where(Documento.colecao == "reativ",
                                                          Documento.dados.like(padrao, escape="\\"))):
        try:
            dados = json.loads(texto)
        except ValueError:
            continue
        if isinstance(dados, dict) and any(confere(r) for _d, _c, r in _registros({"x": dados})):
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


def imagem_do_banco_que_pode_ver(db: Session, p: Pessoa, asset_id: str) -> tuple[str, bytes] | None:
    """(tipo, bytes) da imagem guardada no banco, se a pessoa pode ver; senão None (a rota responde 404).

    A mesma regra das imagens do Drive: quem pode ver vem da tabela imagens (gravado na primeira ligação, a partir do
    esp dos registros), não do registro, que a pessoa pode regravar; e só vale id que ainda está num registro da
    reativ apontando para a imagem do banco."""
    if not ID_ASSET.match(asset_id or ""):
        return None
    linha = db.execute(select(Imagem.mime, Imagem.esp).where(Imagem.id == asset_id)).first()
    if linha is None or linha.mime not in TIPOS_DE_IMAGEM:
        return None
    try:
        esp = json.loads(linha.esp or "[]")
    except ValueError:
        return None
    url = url_do_banco(asset_id)
    if not isinstance(esp, list) or not pode_ver(nomes_visiveis(db, p), esp) or \
            not _em_registro(db, asset_id, lambda r: str(r.get("id")) == asset_id and r.get("url") == url):
        return None
    return linha.mime, db.scalar(select(Imagem.dados).where(Imagem.id == asset_id))


def baixar(app_state, cfg: Config, drive_id: str) -> bytes:
    """A imagem pela conta de serviço. O cliente fica guardado no servidor (o login do Google vale 1 hora)."""
    with _cliente_da_rota:
        cliente = getattr(app_state, "google_prints", None)
        if cliente is None:
            if not cfg.google_service_account_json:
                raise GoogleErro("a chave do Google não está no Render")
            cliente = app_state.google_prints = ClienteGoogle(cfg.google_service_account_json)
    return cliente.baixar(drive_id)
