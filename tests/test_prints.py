"""Prints de reativação lidos do Drive e mostrados pela rota /api/print (Google simulado; nomes e ids inventados)."""
from __future__ import annotations

import io
import json
import re
import struct
import zipfile
import zlib
from datetime import datetime, timedelta, timezone

import httpx2
from sqlalchemy import select

import app.prints as pr
from app.atualizacoes import travar
from app.busca.completa import TRAVA_BUSCA
from app.dados import guardar, ler
from app.db import Atualizacao, Documento, Imagem, Pacote
from app.fontes.google import ClienteGoogle

from .conftest import cfg_teste, criar_pessoa, entrar
from .test_google import CHAVE

RAIZ, SUB = "pasta-prints-inventada", "pasta-antigas-inventada"
CFG = cfg_teste(google_service_account_json=CHAVE, drive_pasta_reativacao=RAIZ)


def _png() -> bytes:
    """Uma imagem PNG de 2x2 pixels (válida, para o navegador mostrar)."""
    def bloco(tipo: bytes, dados: bytes) -> bytes:
        return struct.pack(">I", len(dados)) + tipo + dados + struct.pack(">I", zlib.crc32(tipo + dados))
    linhas = b"".join(b"\x00" + b"\x7a\x5b\xe0" * 2 for _ in range(2))
    return (b"\x89PNG\r\n\x1a\n" + bloco(b"IHDR", struct.pack(">IIBBBBB", 2, 2, 8, 2, 0, 0, 0))
            + bloco(b"IDAT", zlib.compress(linhas)) + bloco(b"IEND", b""))


PNG = _png()


def ms(texto: str) -> int:
    return int(datetime.fromisoformat(texto).timestamp() * 1000)


def img(aid: str, nome: str, pasta: str = RAIZ, desc=None, mime: str = "image/jpeg",
        criado: str = "2026-11-10T12:00:00.000Z") -> dict:
    a = {"id": aid, "name": nome, "mimeType": mime, "createdTime": criado, "parents": [pasta]}
    if desc is not None:
        a["description"] = desc if isinstance(desc, str) else json.dumps(desc)
    return a


def desc(**campos) -> dict:
    base = {"lider": "Especialista Inventado", "mes": "2026-11", "enviado": "2026-11-10T12:00:00.000Z",
            "original": "IMG-inventada.jpg"}
    base.update(campos)
    return {k: v for k, v in base.items() if v is not None}


NOVO = "arquivo-print-novo-01"
ANTIGA = "arquivo-antigo-01"
ARQUIVOS = {
    RAIZ: [{"id": SUB, "name": "Antigas", "mimeType": "application/vnd.google-apps.folder", "parents": [RAIZ]},
           img(NOVO, "nov · Especialista · 10-11 09h.jpg", desc=desc()),
           # enviado antes do último registro do sistema atual: ele já copiou para os assets
           img("arquivo-print-velho-01", "out · Lider · 24-10.jpg",
               desc=desc(lider="Lider Inventado", mes="2026-10", enviado="2026-10-24T10:00:00.000Z")),
           img("arquivo-sem-descricao-01", "foto.jpg"),
           img("arquivo-sem-lider-0001", "foto2.jpg", desc=desc(lider=None)),
           img("arquivo-descricao-texto", "foto3.jpg", desc="print do WhatsApp"),
           img("arquivo-pdf-inventado1", "doc.pdf", desc=desc(), mime="application/pdf")],
    SUB: [img(ANTIGA, "assetinventado01.jpg", pasta=SUB),
          img("arquivo-antigo-sem-registro", "assetquenaoexiste.png", pasta=SUB, mime="image/png")],
}


def antigo() -> dict:
    """O documento do sistema atual (reativ/<dono>), já importado, com as url dos assets."""
    return {"p": {"pa": {"id": "assetinventado01", "url": "/_blob/assetinventado01", "esp": "Lider Inventado",
                         "mes": "2026-10", "at": ms("2026-10-20T10:00:00+00:00"), "assoc": "Associado Inventado",
                         "res": "Validada", "conf": True, "nota": "nota inventada"},
                  "pb": {"id": "assetinventado02", "url": "/_blob/assetinventado02", "esp": "Lider Elite Inventado",
                         "mes": "2026-10", "at": ms("2026-10-25T10:00:00+00:00")}},
            "outro": 1}


class DriveFalso:
    def __init__(self, arquivos=None, erro: httpx2.Response | None = None, conteudos: dict | None = None):
        self.arquivos = ARQUIVOS if arquivos is None else arquivos
        self.erro = erro
        self.conteudos = conteudos or {}  # id do arquivo -> bytes (o resto baixa o PNG)
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(pedido)
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "acesso-inventado", "expires_in": 3600})
        if self.erro is not None:
            return self.erro
        if pedido.url.params.get("alt") == "media":
            aid = pedido.url.path.rsplit("/", 1)[1]
            if aid in self.conteudos:
                return httpx2.Response(200, content=self.conteudos[aid], headers={"Content-Type": "application/zip"})
            return httpx2.Response(200, content=PNG, headers={"Content-Type": "image/jpeg"})
        pasta = re.match(r"^'([^']+)' in parents", pedido.url.params.get("q", ""))
        return httpx2.Response(200, json={"files": self.arquivos.get(pasta.group(1), []) if pasta else []})

    def cliente(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))

    def baixados(self) -> list[str]:
        return [p.url.path.rsplit("/", 1)[1] for p in self.pedidos if p.url.params.get("alt") == "media"]


def _preparar(db):
    db.add(Documento(colecao="reativ", doc_id="dono-inventado", dados=json.dumps(antigo())))
    for nome, eq in (("Especialista Inventado", "Lua"), ("Lider Inventado", "Lua"),
                     ("Especialista Dois Inventado", "Lua"), ("Lider Elite Inventado", "Elite")):
        guardar(db, "esp:" + nome.upper(), {"id": None, "nome": nome, "sga": [], "eqs": [eq]}, "importacao")
    db.commit()


def _reativ(db) -> dict:
    db.expire_all()
    return {d.doc_id: json.loads(d.dados) for d in db.scalars(select(Documento).where(Documento.colecao == "reativ"))}


def test_imagem_antiga_liga_ao_registro_e_print_novo_vira_registro_uma_vez(app, db):
    _preparar(db)
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())
    assert r["ok"] is True, r
    assert r["mensagem"] == ("Prints do Drive: 7 imagem(ns) lida(s); 1 imagem(ns) antiga(s) ligada(s) ao registro "
                             "(1 agora); 1 print(s) novo(s) no registro; 0 já registrado(s); 1 já copiado(s) pelo "
                             "sistema atual; 4 sem descrição válida (ignorada(s)). Zip: 0 lido(s) agora, 0 cópia(s) de "
                             "zip já lido, 0 recusado(s); 0 imagem(ns) do zip ligada(s) ao registro, 0 repetida(s), "
                             "0 sem registro, 0 ignorada(s).")
    docs = _reativ(db)
    # imagem antiga: só a url e o drive mudam
    esperado = antigo()
    esperado["p"]["pa"].update(url="/api/print/" + ANTIGA, drive=ANTIGA)
    assert docs["dono-inventado"] == esperado
    # print novo: um registro no documento do mês, pronto para a conferência
    assert docs["drive-2026-11"] == {"p": {"d" + NOVO: {
        "id": NOVO, "drive": NOVO, "url": "/api/print/" + NOVO, "esp": "Especialista Inventado", "mes": "2026-11",
        "at": ms("2026-11-10T12:00:00+00:00"), "assoc": "", "res": "", "conf": "", "nota": ""}}}
    assert set(docs) == {"dono-inventado", "drive-2026-11"}  # o print de outubro (já copiado) não virou registro
    assert ler(db, pr.INDICE) == {ANTIGA: {"mime": "image/jpeg", "esp": ["LIDER INVENTADO"]},
                                  NOVO: {"mime": "image/jpeg", "esp": ["ESPECIALISTA INVENTADO"]}}
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("drive", "prints", True) and "Inventad" not in a.mensagem  # sem nomes
    # de novo: nada duplica e nada é regravado
    antes = {d.doc_id: d.atualizado_em for d in db.scalars(select(Documento))}
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())
    assert "(0 agora); 0 print(s) novo(s) no registro; 1 já registrado(s)" in r["mensagem"], r
    assert _reativ(db) == docs
    assert {d.doc_id: d.atualizado_em for d in db.scalars(select(Documento))} == antes


def test_sem_registro_do_sistema_atual_todo_print_valido_entra(app, db):
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())
    assert "2 print(s) novo(s)" in r["mensagem"] and "0 já copiado(s)" in r["mensagem"], r
    docs = _reativ(db)
    assert set(docs) == {"drive-2026-10", "drive-2026-11"}
    assert docs["drive-2026-10"]["p"]["darquivo-print-velho-01"]["esp"] == "Lider Inventado"


def test_data_do_envio():
    assert pr._ms("2026-11-10T12:00:00.000Z") == ms("2026-11-10T12:00:00+00:00")
    assert pr._ms("10/11/2026 09:00") == ms("2026-11-10T12:00:00+00:00")  # Brasília
    assert pr._ms(1794312000000) == 1794312000000
    assert [pr._ms(x) for x in ("", None, "ontem", "31/02/2026")] == [None] * 4
    # sem "enviado" na descrição vale a criação do arquivo
    assert pr.print_da_descricao(img("x" * 12, "a.jpg", desc=desc(enviado=None)))["at"] == \
        ms("2026-11-10T12:00:00+00:00")
    assert pr.print_da_descricao(img("x" * 12, "a.jpg", desc=desc(mes="Novembro/2026")))["mes"] == "2026-11"


def test_erro_do_google_nao_mexe_em_nada(app, db):
    _preparar(db)
    guardar(db, pr.INDICE, {"arquivo-qualquer-01": {"mime": "image/png", "esp": []}}, "drive")
    db.commit()
    antes_docs, antes_pac = _reativ(db), {p.chave: p.dados for p in db.scalars(select(Pacote))}
    falso = DriveFalso(erro=httpx2.Response(500, text="detalhe-cru-inventado"))
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is False and r["mensagem"].startswith("Google:") and "Nada foi gravado" in r["mensagem"]
    assert "detalhe-cru-inventado" not in r["mensagem"]
    assert _reativ(db) == antes_docs and {p.chave: p.dados for p in db.scalars(select(Pacote))} == antes_pac
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("drive", "prints", False)


def test_nao_roda_com_a_busca_rodando_nem_sem_configuracao(app, db):
    travar(db, TRAVA_BUSCA, datetime.now(timezone.utc) + timedelta(hours=1), "busca completa em andamento")
    falso = DriveFalso()
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is False and "busca completa está rodando" in r["mensagem"]
    assert falso.pedidos == [] and db.scalars(select(Atualizacao)).first() is None
    assert "GOOGLE_SERVICE_ACCOUNT_JSON" in pr.atualizar_prints(app.state.Sessao, cfg_teste())["mensagem"]
    r = pr.atualizar_prints(app.state.Sessao, cfg_teste(google_service_account_json=CHAVE))
    assert "DRIVE_PASTA_REATIVACAO" in r["mensagem"]
    r = pr.atualizar_prints(app.state.Sessao, cfg_teste(google_service_account_json=CHAVE,
                                                        drive_pasta_reativacao="' or name contains 'x"))
    assert "não parece um id" in r["mensagem"]


def test_agendador_le_os_prints_nos_horarios_dos_comprovantes(db):
    from app.comprovantes import leitura_devida
    sp = timezone(timedelta(hours=-3))
    db.add(Atualizacao(fonte="drive", tipo="comprovantes", inicio=datetime(2026, 11, 9, 10, 26, tzinfo=timezone.utc)))
    db.commit()
    assert leitura_devida(db, datetime(2026, 11, 9, 7, 40, tzinfo=sp)) is False
    assert leitura_devida(db, datetime(2026, 11, 9, 7, 40, tzinfo=sp), tipo="prints") is True  # cada um conta o seu
    assert leitura_devida(db, datetime(2026, 11, 9, 7, 20, tzinfo=sp), tipo="prints") is False


def test_botao_so_para_o_administrador(admin, novo_cliente, db):
    criar_pessoa(db, nome="Coordenacao Inventada", email="coord@exemplo.com.br", tipo="coordenacao")
    c = novo_cliente()
    entrar(c, "coord@exemplo.com.br")
    assert c.post("/api/admin/atualizacoes/prints", json={}).status_code == 403
    assert admin.post("/api/admin/atualizacoes/prints", content="x").status_code == 415
    r = admin.post("/api/admin/atualizacoes/prints", json={}).json()
    assert r["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["mensagem"]  # app de teste: sem a chave
    assert admin.get("/api/admin/atualizacoes").json()["prints_automatico"] is False
    assert "Ler prints agora" in admin.get("/static/escritorio.html").text


# ---------------------------------------------------------------- quem vê cada imagem

def _pessoas(db, novo_cliente):
    clientes = {}
    for nome, tipo, equipe in (("Coordenacao Inventada", "coordenacao", None), ("Financeiro Inventado", "financeiro", None),
                               ("Cadastro Inventado", "cadastro", None), ("Lider Inventado", "lider", "Lua"),
                               ("Lider Elite Inventado", "lider", "Elite"),
                               ("Especialista Inventado", "especialista", "Lua"),
                               ("Especialista Dois Inventado", "especialista", "Lua")):
        email = nome.lower().replace(" ", ".") + "@exemplo.com.br"
        criar_pessoa(db, nome=nome, email=email, tipo=tipo, equipe=equipe)
        clientes[nome] = c = novo_cliente()
        entrar(c, email, nome)
    return clientes


def test_rota_do_print_so_para_quem_pode_ver(app, admin, novo_cliente, db):
    _preparar(db)
    assert pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())["ok"] is True
    falso = DriveFalso()
    app.state.google_prints = ClienteGoogle(CHAVE, http=falso.cliente())
    c = _pessoas(db, novo_cliente)

    r = admin.get("/api/print/" + NOVO)
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/jpeg"
    assert r.headers["cache-control"] == "private, max-age=86400"
    vistos = {nome: (cl.get("/api/print/" + ANTIGA).status_code, cl.get("/api/print/" + NOVO).status_code)
              for nome, cl in c.items()}
    assert vistos == {
        "Coordenacao Inventada": (200, 200), "Financeiro Inventado": (200, 200),
        "Cadastro Inventado": (404, 404),
        "Lider Inventado": (200, 200),          # o dele e o do especialista da equipe dele
        "Lider Elite Inventado": (404, 404),    # outra equipe
        "Especialista Inventado": (404, 200),   # só o dele
        "Especialista Dois Inventado": (404, 404),
    }
    baixados = len(falso.baixados())
    # id fora da reativ (mesmo da pasta dos prints, ou de qualquer outro arquivo do Drive): 404, sem ir ao Drive
    for aid in ("arquivo-sem-descricao-01", "arquivo-antigo-sem-registro", "arquivo-print-velho-01",
                "qualquer-arquivo-do-drive", "../files", "a"):
        assert admin.get("/api/print/" + aid).status_code == 404, aid
    assert len(falso.baixados()) == baixados
    assert novo_cliente().get("/api/print/" + NOVO).status_code == 401
    # registro forjado no próprio documento não abre o print de outra pessoa (quem enviou vem do Drive)
    dois = c["Especialista Dois Inventado"]
    eu = dois.get("/api/eu").json()["pessoa"]["id"]
    assert dois.put(f"/api/banco/reativ/{eu}", json={"p": {"x": {"id": NOVO, "drive": NOVO,
                                                                 "esp": "Especialista Dois Inventado"}}}).status_code == 200
    assert dois.get("/api/print/" + NOVO).status_code == 404
    # registro apagado: a imagem deixa de abrir, mesmo antes da próxima leitura
    db.query(Documento).filter(Documento.doc_id.in_(["drive-2026-11", str(eu)])).delete(synchronize_session=False)
    db.commit()
    assert admin.get("/api/print/" + NOVO).status_code == 404


def test_erro_do_google_na_imagem(app, admin, db):
    _preparar(db)
    pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())
    app.state.google_prints = ClienteGoogle(CHAVE, http=DriveFalso(erro=httpx2.Response(500, text="cru")).cliente())
    r = admin.get("/api/print/" + NOVO)
    assert r.status_code == 502 and "cru" not in r.text


def test_lista_da_reativ_so_com_os_prints_que_cada_um_pode_ver(app, admin, novo_cliente, db):
    _preparar(db)
    pr.atualizar_prints(app.state.Sessao, CFG, http=DriveFalso().cliente())
    c = _pessoas(db, novo_cliente)

    def chaves(cl):
        return sorted(k for d in cl.get("/api/banco/reativ").json()["docs"] for k in d["data"].get("p", {}))
    assert chaves(admin) == chaves(c["Coordenacao Inventada"]) == chaves(c["Financeiro Inventado"]) == \
        ["d" + NOVO, "pa", "pb"]
    assert chaves(c["Lider Inventado"]) == ["d" + NOVO, "pa"]
    assert chaves(c["Lider Elite Inventado"]) == ["pb"]
    assert chaves(c["Especialista Inventado"]) == ["d" + NOVO]
    assert chaves(c["Especialista Dois Inventado"]) == [] and chaves(c["Cadastro Inventado"]) == []
    # um documento lido direto também vem filtrado (e sem os outros campos)
    assert c["Lider Elite Inventado"].get("/api/banco/reativ/dono-inventado").json()["data"] == \
        {"p": {"pb": antigo()["p"]["pb"]}}
    assert admin.get("/api/banco/reativ/dono-inventado").json()["data"]["outro"] == 1


# ---------------------------------------------------------------- zip dos prints antigos (25/11)

JPEG = b"\xff\xd8\xff\xe0\x00\x10JFIF\x00\x01\x01\x00\x00\x01\x00\x01\x00\x00\xff\xd9"  # só o começo e o fim
ZIP_A, ZIP_B = "arquivo-zip-inventado-01", "arquivo-zip-inventado-02"


def _zip(entradas: dict) -> bytes:
    """Um zip montado na hora: {nome da entrada: bytes} (nome terminado em "/" vira pasta)."""
    saida = io.BytesIO()
    with zipfile.ZipFile(saida, "w", zipfile.ZIP_DEFLATED) as z:
        for nome, dados in entradas.items():
            info = zipfile.ZipInfo(nome)  # ZipInfo guarda o nome como veio (inclusive "../" e "/")
            info.compress_type = zipfile.ZIP_DEFLATED
            z.writestr(info, dados if dados is not None else b"")
    return saida.getvalue()


ZIP_PRINTS = _zip({
    "pasta/": None,
    "pasta/assetinventado02.png": PNG,       # registro pb (Lider Elite Inventado)
    "assetinventado03.jpg": JPEG,            # registro pc (Especialista Inventado)
    "assetsemregistro01.jpg": JPEG,          # nenhum registro com esse id
    "../assetinventado04.png": PNG,          # caminho para fora: ignorado (registro pd fica como está)
    "/tmp/assetinventado04.png": PNG,        # caminho absoluto: ignorado
    "assetinventado05.png": b"nao sou uma imagem",  # nome de imagem, conteúdo não: ignorado
    "assetinventado06.txt": PNG,             # extensão que não é de imagem: ignorado
    "__MACOSX/pasta/._assetinventado02.png": b"\x00\x05\x16\x07",  # lixo do Mac: ignorado
})


def zipdesc(aid: str, nome: str = "prints_reativacao_completo.zip", pasta: str = RAIZ, md5="md5-inventado-01",
            tamanho=None) -> dict:
    a = {"id": aid, "name": nome, "mimeType": "application/zip", "createdTime": "2026-11-25T12:00:00.000Z",
         "parents": [pasta]}
    if md5:
        a["md5Checksum"] = md5
    if tamanho is not None:
        a["size"] = str(tamanho)
    return a


def _registros_zip() -> dict:
    d = antigo()
    for chave, aid, esp in (("pc", "assetinventado03", "Especialista Inventado"),
                            ("pd", "assetinventado04", "Especialista Inventado"),
                            ("pe", "assetinventado05", "Especialista Inventado")):
        d["p"][chave] = {"id": aid, "url": "/_blob/" + aid, "esp": esp, "mes": "2026-10",
                         "at": ms("2026-10-21T10:00:00+00:00")}
    return d


def _preparar_zip(db):
    _preparar(db)
    db.query(Documento).filter(Documento.doc_id == "dono-inventado").update({"dados": json.dumps(_registros_zip())})
    db.commit()


def _imagens(db) -> dict:
    db.expire_all()
    return {i.id: (i.mime, i.dados, json.loads(i.esp), i.origem) for i in db.scalars(select(Imagem))}


def _drive_zip(**kw) -> DriveFalso:
    arquivos = kw.pop("arquivos", {RAIZ: [zipdesc(ZIP_A), zipdesc(ZIP_B, nome="prints_reativacao_completo (1).zip")]})
    return DriveFalso(arquivos=arquivos, conteudos=kw.pop("conteudos", {ZIP_A: ZIP_PRINTS, ZIP_B: ZIP_PRINTS}), **kw)


def test_zip_liga_as_imagens_aos_registros_uma_vez_so(app, db):
    _preparar_zip(db)
    falso = _drive_zip()
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is True, r
    assert r["mensagem"].endswith("Zip: 1 lido(s) agora, 1 cópia(s) de zip já lido, 0 recusado(s); 2 imagem(ns) do "
                                  "zip ligada(s) ao registro, 0 repetida(s), 1 sem registro, 5 ignorada(s)."), r
    assert len(r["mensagem"]) < 500 and "Inventad" not in r["mensagem"]
    assert falso.baixados() == [ZIP_A]  # a cópia igual (mesmo md5) nem é baixada
    assert _imagens(db) == {
        "assetinventado02": ("image/png", PNG, ["LIDER ELITE INVENTADO"], "zip:" + ZIP_A),
        "assetinventado03": ("image/jpeg", JPEG, ["ESPECIALISTA INVENTADO"], "zip:" + ZIP_A)}
    esperado = _registros_zip()
    esperado["p"]["pb"].update(url="/api/print/banco/assetinventado02", zip=ZIP_A)
    esperado["p"]["pc"].update(url="/api/print/banco/assetinventado03", zip=ZIP_A)
    docs = _reativ(db)
    assert docs == {"dono-inventado": esperado}  # pa, pd e pe ficam como estavam
    estado = ler(db, pr.ESTADO_ZIP)["zips"]
    assert set(estado) == {ZIP_A, ZIP_B} and estado[ZIP_B]["igual"] is True and estado[ZIP_A]["ligadas"] == 2

    # de novo: nada é baixado, nada duplica e nada é regravado
    antes = {d.doc_id: d.atualizado_em for d in db.scalars(select(Documento))}
    falso = _drive_zip()
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert "Zip: 0 lido(s) agora, 0 cópia(s) de zip já lido, 0 recusado(s); 0 imagem(ns)" in r["mensagem"], r
    assert falso.baixados() == [] and len(_imagens(db)) == 2 and _reativ(db) == docs
    assert {d.doc_id: d.atualizado_em for d in db.scalars(select(Documento))} == antes

    # registro importado de novo (url /_blob/ outra vez): volta a apontar para o banco, sem baixar o zip
    db.query(Documento).filter(Documento.doc_id == "dono-inventado").update({"dados": json.dumps(_registros_zip())})
    db.commit()
    falso = _drive_zip()
    assert pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())["ok"] is True
    assert falso.baixados() == [] and _reativ(db) == docs


def test_zip_sem_md5_baixado_duas_vezes_nao_duplica(app, db):
    _preparar_zip(db)
    arquivos = {RAIZ: [{"id": SUB, "name": "Antigas", "mimeType": "application/vnd.google-apps.folder"}],
                SUB: [zipdesc(ZIP_A, pasta=SUB, md5=None), zipdesc(ZIP_B, pasta=SUB, md5=None)]}  # em subpasta
    falso = _drive_zip(arquivos=arquivos)
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert "Zip: 2 lido(s) agora, 0 cópia(s) de zip já lido, 0 recusado(s); 2 imagem(ns) do zip ligada(s) ao " \
           "registro, 2 repetida(s), 2 sem registro, 10 ignorada(s)." in r["mensagem"], r
    assert sorted(falso.baixados()) == [ZIP_A, ZIP_B]
    assert {i: v[3] for i, v in _imagens(db).items()} == {"assetinventado02": "zip:" + ZIP_A,
                                                          "assetinventado03": "zip:" + ZIP_A}
    falso = _drive_zip(arquivos=arquivos)
    pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert falso.baixados() == [] and len(_imagens(db)) == 2


def test_entrada_do_zip_que_nao_serve():
    assert pr.asset_da_entrada("pasta/sub/assetinventado01.JPG") == "assetinventado01"
    assert pr.asset_da_entrada("assetinventado01.webp") == "assetinventado01"
    for nome in ("../assetinventado01.jpg", "pasta/../../assetinventado01.jpg", "..\\assetinventado01.jpg",
                 "/assetinventado01.jpg", "C:/assetinventado01.jpg", "C:assetinventado01.jpg", "pasta/",
                 "assetinventado01.svg", "assetinventado01.jpg.exe", "assetinventado01", ".assetinventado01.jpg",
                 "__MACOSX/assetinventado01.jpg", "nome com espaço.jpg", ""):
        assert pr.asset_da_entrada(nome) is None, nome
    assert [pr.tipo_pelos_bytes(b) for b in (PNG, JPEG, b"GIF89a....", b"RIFF\x00\x00\x00\x00WEBPVP8 ",
                                             b"<svg></svg>", b"")] == \
        ["image/png", "image/jpeg", "image/gif", "image/webp", None, None]


def test_zip_bomba_e_zip_grande_sao_recusados_sem_gravar(app, db, monkeypatch):
    _preparar_zip(db)
    monkeypatch.setattr(pr, "LIMITE_TOTAL_ZIP", 50_000)
    monkeypatch.setattr(pr, "LIMITE_ZIP", 5_000_000)
    # imagens que, descompactadas, passam do total (zeros comprimem quase a nada: o zip tem poucos KB)
    bomba = _zip({"assetinventado02.png": PNG + b"\x00" * 30_000, "assetinventado03.jpg": JPEG + b"\x00" * 30_000})
    assert len(bomba) < 5_000
    grande_listado, grande_baixado = "arquivo-zip-grande-01", "arquivo-zip-grande-02"
    arquivos = {RAIZ: [zipdesc(ZIP_A, md5="md5-bomba"),
                       zipdesc(grande_listado, md5="md5-grande-1", tamanho=6_000_000),  # o Drive diz o tamanho
                       zipdesc(grande_baixado, md5="md5-grande-2"),  # sem tamanho na lista: para no download
                       zipdesc(ZIP_B, nome="estragado.zip", md5="md5-estragado")]}
    conteudos = {ZIP_A: bomba, grande_baixado: b"PK" + b"\x00" * 5_000_001, ZIP_B: b"PK\x03\x04 nao e zip"}
    falso = _drive_zip(arquivos=arquivos, conteudos=conteudos)
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is True, r
    assert "Zip: 0 lido(s) agora, 0 cópia(s) de zip já lido, 4 recusado(s); 0 imagem(ns) do zip ligada(s) ao " \
           "registro, 0 repetida(s), 0 sem registro, 0 ignorada(s)." in r["mensagem"], r
    assert sorted(falso.baixados()) == sorted([ZIP_A, grande_baixado, ZIP_B])  # o grande da lista nem é baixado
    assert _imagens(db) == {} and _reativ(db) == {"dono-inventado": _registros_zip()}
    estado = ler(db, pr.ESTADO_ZIP)["zips"]
    assert {k: v["recusado"] for k, v in estado.items()} == {
        ZIP_A: "descompactado grande demais", grande_listado: "zip grande demais",
        grande_baixado: "zip grande demais", ZIP_B: "zip danificado"}
    # recusado também conta como lido: não é baixado de hora em hora
    falso = _drive_zip(arquivos=arquivos, conteudos=conteudos)
    pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert falso.baixados() == []


def test_zip_imagem_grande_demais_fica_de_fora(app, db, monkeypatch):
    _preparar_zip(db)
    monkeypatch.setattr(pr, "LIMITE_IMAGEM_ZIP", 1_000)
    conteudos = {ZIP_A: _zip({"assetinventado02.png": PNG + b"\x00" * 2_000, "assetinventado03.jpg": JPEG})}
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=_drive_zip(conteudos=conteudos).cliente())
    assert "1 imagem(ns) do zip ligada(s) ao registro, 0 repetida(s), 0 sem registro, 1 ignorada(s)." in r["mensagem"]
    assert set(_imagens(db)) == {"assetinventado03"}


def test_erro_do_google_no_zip_nao_grava_nada(app, db):
    _preparar_zip(db)

    class FalhaNoSegundo(DriveFalso):
        def __call__(self, pedido):
            if pedido.url.params.get("alt") == "media" and pedido.url.path.endswith(ZIP_B):
                self.pedidos.append(pedido)
                return httpx2.Response(500, text="detalhe-cru-inventado")
            return super().__call__(pedido)
    arquivos = {RAIZ: [zipdesc(ZIP_A), zipdesc(ZIP_B, md5="md5-outro")]}
    falso = FalhaNoSegundo(arquivos=arquivos, conteudos={ZIP_A: ZIP_PRINTS})
    r = pr.atualizar_prints(app.state.Sessao, CFG, http=falso.cliente())
    assert r["ok"] is False and "Nada foi gravado" in r["mensagem"] and "cru" not in r["mensagem"]
    assert _imagens(db) == {} and ler(db, pr.ESTADO_ZIP) is None
    assert _reativ(db) == {"dono-inventado": _registros_zip()}


def test_rota_da_imagem_do_banco_so_para_quem_pode_ver(app, admin, novo_cliente, db):
    _preparar_zip(db)
    assert pr.atualizar_prints(app.state.Sessao, CFG, http=_drive_zip().cliente())["ok"] is True
    c = _pessoas(db, novo_cliente)
    r = admin.get("/api/print/banco/assetinventado02")
    assert r.status_code == 200 and r.content == PNG and r.headers["content-type"] == "image/png"
    assert r.headers["cache-control"] == "private, max-age=86400"
    r = admin.get("/api/print/banco/assetinventado03")
    assert r.status_code == 200 and r.content == JPEG and r.headers["content-type"] == "image/jpeg"
    vistos = {nome: (cl.get("/api/print/banco/assetinventado02").status_code,
                     cl.get("/api/print/banco/assetinventado03").status_code) for nome, cl in c.items()}
    assert vistos == {
        "Coordenacao Inventada": (200, 200), "Financeiro Inventado": (200, 200),
        "Cadastro Inventado": (404, 404),
        "Lider Inventado": (404, 200),          # o especialista da equipe dele
        "Lider Elite Inventado": (200, 404),    # o dele
        "Especialista Inventado": (404, 200),   # só o dele
        "Especialista Dois Inventado": (404, 404),
    }
    # id sem imagem no banco, imagem sem registro, nome estranho: 404
    for aid in ("assetsemregistro01", "assetinventado04", "assetinventado01", "..", "a%2F..%2Fb", "x" * 201):
        assert admin.get("/api/print/banco/" + aid).status_code == 404, aid
    assert novo_cliente().get("/api/print/banco/assetinventado03").status_code == 401
    # a imagem do banco não abre pela rota do Drive (e vice-versa)
    assert admin.get("/api/print/assetinventado03").status_code == 404
    # registro forjado no próprio documento não abre a imagem de outra pessoa (quem vê vem da tabela imagens)
    dois = c["Especialista Dois Inventado"]
    eu = dois.get("/api/eu").json()["pessoa"]["id"]
    forjado = {"id": "assetinventado03", "url": "/api/print/banco/assetinventado03", "esp": "Especialista Dois Inventado"}
    assert dois.put(f"/api/banco/reativ/{eu}", json={"p": {"x": forjado}}).status_code == 200
    assert dois.get("/api/print/banco/assetinventado03").status_code == 404
    # nem a próxima leitura muda quem vê
    pr.atualizar_prints(app.state.Sessao, CFG, http=_drive_zip().cliente())
    assert dois.get("/api/print/banco/assetinventado03").status_code == 404
    # registro apagado (ou que não aponta mais para o banco): a imagem deixa de abrir
    db.query(Documento).filter(Documento.doc_id.in_(["dono-inventado", str(eu)])).delete(synchronize_session=False)
    db.commit()
    assert admin.get("/api/print/banco/assetinventado03").status_code == 404
