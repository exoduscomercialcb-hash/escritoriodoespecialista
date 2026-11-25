"""Prints de reativação lidos do Drive e mostrados pela rota /api/print (Google simulado; nomes e ids inventados)."""
from __future__ import annotations

import json
import re
import struct
import zlib
from datetime import datetime, timedelta, timezone

import httpx2
from sqlalchemy import select

import app.prints as pr
from app.atualizacoes import travar
from app.busca.completa import TRAVA_BUSCA
from app.dados import guardar, ler
from app.db import Atualizacao, Documento, Pacote
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
    def __init__(self, arquivos=None, erro: httpx2.Response | None = None):
        self.arquivos = ARQUIVOS if arquivos is None else arquivos
        self.erro = erro
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(pedido)
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "acesso-inventado", "expires_in": 3600})
        if self.erro is not None:
            return self.erro
        if pedido.url.params.get("alt") == "media":
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
                             "sistema atual; 4 sem descrição válida (ignorada(s)).")
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
