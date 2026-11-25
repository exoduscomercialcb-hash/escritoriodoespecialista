"""Conta de serviço do Google (Drive e Planilhas): login, teste de conexão e mensagens de erro (respostas simuladas).

A chave usada aqui é gerada na hora e não vale em lugar nenhum.
"""
import json

import httpx2
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from sqlalchemy import select

import app.atualizacoes as atu
from app.db import Atualizacao
from app.fontes.google import ClienteGoogle, GoogleErro, ler_credencial

from .conftest import cfg_teste

EMAIL = "conta-inventada@projeto-inventado.iam.gserviceaccount.com"


def _chave() -> str:
    k = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    pem = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                          serialization.NoEncryption()).decode()
    return json.dumps({"type": "service_account", "client_email": EMAIL, "private_key": pem,
                       "private_key_id": "inventado", "project_id": "projeto-inventado"})


CHAVE = _chave()
CFG = cfg_teste(google_service_account_json=CHAVE, drive_pasta_comprovantes="pasta-comp-inventada",
                drive_pasta_reativacao="pasta-prints-inventada", planilha_inside_sales="planilha-inventada")


class GoogleFalso:
    def __init__(self, **respostas):
        self.respostas = respostas  # trecho do endereço -> Response
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(pedido)
        if pedido.url.host == "oauth2.googleapis.com":
            return self.respostas.get("token") or httpx2.Response(200, json={"access_token": "acesso-inventado",
                                                                             "expires_in": 3600})
        for trecho, resposta in self.respostas.items():
            if trecho != "token" and trecho in str(pedido.url):
                return resposta
        return httpx2.Response(404)

    def cliente(self):
        return httpx2.Client(transport=httpx2.MockTransport(self))


def _tudo_ok():
    return GoogleFalso(**{
        "pasta-comp-inventada": httpx2.Response(200, json={"id": "x", "name": "Comprovantes de adesões"}),
        "pasta-prints-inventada": httpx2.Response(200, json={"id": "y", "name": "Prints de reativação"}),
        "planilha-inventada": httpx2.Response(200, json={"properties": {"title": "Ativação Inside Sales"},
                                                         "sheets": [{"properties": {"title": "CRÉDITOS FIXADOS"}}]}),
    })


def test_teste_do_drive_ok(db):
    falso = _tudo_ok()
    r = atu.testar_drive(db, CFG, http=falso.cliente())
    assert r["ok"] is True, r
    assert EMAIL in r["mensagem"] and "Comprovantes de adesões" in r["mensagem"] and "CRÉDITOS FIXADOS" in r["mensagem"]
    # o login é uma assinatura (JWT), e as consultas levam o token de acesso
    login = falso.pedidos[0]
    assert b"grant_type=urn" in login.content and b"assertion=" in login.content
    assert all(p.headers.get("authorization") == "Bearer acesso-inventado" for p in falso.pedidos[1:])
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("drive", "teste", True)


def test_teste_do_drive_explica_o_que_falta(db):
    r = atu.testar_drive(db, cfg_teste(), http=_tudo_ok().cliente())
    assert r["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["mensagem"]
    r = atu.testar_drive(db, cfg_teste(google_service_account_json=CHAVE), http=_tudo_ok().cliente())
    assert r["ok"] is False and "DRIVE_PASTA_COMPROVANTES" in r["mensagem"] and "PLANILHA_INSIDE_SALES" in r["mensagem"]
    # pasta não compartilhada: diz com qual e-mail compartilhar
    falso = _tudo_ok()
    falso.respostas["pasta-prints-inventada"] = httpx2.Response(404)
    r = atu.testar_drive(db, CFG, http=falso.cliente())
    assert r["ok"] is False and "compartilhado com " + EMAIL in r["mensagem"]
    # API desligada no projeto
    falso = _tudo_ok()
    falso.respostas["planilha-inventada"] = httpx2.Response(403, json={"error": {"status": "PERMISSION_DENIED",
                                                                                 "message": "Sheets API has not been used"}})
    r = atu.testar_drive(db, CFG, http=falso.cliente())
    assert r["ok"] is False and "não está ativada" in r["mensagem"]
    # planilha sem a aba
    falso = _tudo_ok()
    falso.respostas["planilha-inventada"] = httpx2.Response(200, json={"sheets": [{"properties": {"title": "Outra"}}]})
    r = atu.testar_drive(db, CFG, http=falso.cliente())
    assert r["ok"] is False and "não tem a aba" in r["mensagem"]


def test_chave_errada_nunca_aparece_na_mensagem(db):
    for ruim in ("{nao e json", json.dumps({"type": "authorized_user", "segredo": "nao-mostrar"})):
        r = atu.testar_drive(db, cfg_teste(google_service_account_json=ruim, drive_pasta_comprovantes="p"),
                             http=_tudo_ok().cliente())
        assert r["ok"] is False and "nao-mostrar" not in r["mensagem"] and "nao e json" not in r["mensagem"]
    falso = _tudo_ok()
    falso.respostas["token"] = httpx2.Response(400, json={"error": "invalid_grant"})
    r = atu.testar_drive(db, CFG, http=falso.cliente())
    assert r["ok"] is False and "recusou a chave" in r["mensagem"]
    assert "BEGIN PRIVATE KEY" not in json.dumps([a.mensagem for a in db.scalars(select(Atualizacao))])


def test_token_reaproveitado_e_lista_paginada():
    falso = GoogleFalso()
    paginas = iter([httpx2.Response(200, json={"files": [{"id": "1"}], "nextPageToken": "p2"}),
                    httpx2.Response(200, json={"files": [{"id": "2"}]})])

    def responder(pedido):
        falso.pedidos.append(pedido)
        if pedido.url.host == "oauth2.googleapis.com":
            return httpx2.Response(200, json={"access_token": "t", "expires_in": 3600})
        return next(paginas)

    c = ClienteGoogle(CHAVE, http=httpx2.Client(transport=httpx2.MockTransport(responder)))
    assert [f["id"] for f in c.arquivos("'pasta' in parents")] == ["1", "2"]
    assert sum(1 for p in falso.pedidos if p.url.host == "oauth2.googleapis.com") == 1  # um login só
    assert falso.pedidos[2].url.params["pageToken"] == "p2"


def test_ler_credencial():
    assert ler_credencial(CHAVE)["client_email"] == EMAIL
    with pytest.raises(GoogleErro, match="não é um JSON"):
        ler_credencial("")


def test_botao_testar_conexoes_inclui_o_google(admin):
    r = admin.post("/api/admin/atualizacoes/testar", json={}).json()
    assert r["drive"]["ok"] is False and "GOOGLE_SERVICE_ACCOUNT_JSON" in r["drive"]["mensagem"]
