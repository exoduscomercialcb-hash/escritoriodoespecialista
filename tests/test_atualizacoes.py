"""SGA e Power CRM: teste de conexão, trava do BLOQUEADO e registro das buscas (sem rede: respostas simuladas)."""
from datetime import datetime, timedelta, timezone

import httpx2
import pytest
from sqlalchemy import select

import app.atualizacoes as atu  # importado como módulo: o pytest não confunde atu.testar_sga com um teste
from app.db import Atualizacao
from app.fontes.sga import BASE, ClienteSGA, SGABloqueado, SGAErro

from .conftest import cfg_teste, criar_pessoa, entrar

CFG = cfg_teste(sga_token="token-inventado", sga_usuario="usuario-inventado", sga_senha="senha-inventada",
                powercrm_token="pc-inventado")


class SGAFalso:
    """Responde em sequência às chamadas e guarda o que recebeu."""

    def __init__(self, *respostas):
        self.respostas = list(respostas)
        self.pedidos: list[httpx2.Request] = []

    def __call__(self, pedido: httpx2.Request) -> httpx2.Response:
        self.pedidos.append(pedido)
        r = self.respostas.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def cliente(self, base=BASE):
        return httpx2.Client(transport=httpx2.MockTransport(self), base_url=base)


LOGIN_OK = httpx2.Response(200, json={"token_usuario": "acesso-inventado"})


def test_teste_do_sga_faz_so_o_login(db):
    falso = SGAFalso(LOGIN_OK)
    r = atu.testar_sga(db, CFG, http=falso.cliente())
    assert r == {"ok": True, "mensagem": "Conectou no SGA: o login foi aceito."}
    assert len(falso.pedidos) == 1
    p = falso.pedidos[0]
    assert p.url.path.endswith("/usuario/autenticar") and p.headers["authorization"] == "Bearer token-inventado"
    assert b"usuario-inventado" in p.content and b"senha-inventada" in p.content
    a = db.scalars(select(Atualizacao)).one()
    assert (a.fonte, a.tipo, a.ok) == ("sga", "teste", True)


@pytest.mark.parametrize("resposta,trecho", [
    (httpx2.Response(403, text="Token BLOQUEADO por excesso de requisições"), "BLOQUEADO"),
    (httpx2.Response(401, text="Login ou senha inválido"), "recusou o login"),
])
def test_bloqueio_do_sga_pausa_ate_o_proximo_horario(db, resposta, trecho):
    falso = SGAFalso(resposta)
    r = atu.testar_sga(db, CFG, http=falso.cliente())
    assert r["ok"] is False and trecho in r["mensagem"] and "pausado até" in r["mensagem"]
    assert "requisições" not in r["mensagem"] and "inválido" not in r["mensagem"]  # não repete o texto do SGA
    trava = atu.trava_ativa(db, atu.TRAVA_SGA)
    assert trava is not None
    # enquanto estiver pausado, nem o teste chama o SGA
    outro = SGAFalso()
    r2 = atu.testar_sga(db, CFG, http=outro.cliente())
    assert r2["ok"] is False and "Nada foi consultado" in r2["mensagem"] and outro.pedidos == []


def test_sga_fora_do_ar_nao_trava(db):
    falso = SGAFalso(httpx2.ConnectTimeout("tempo esgotado"))
    r = atu.testar_sga(db, CFG, http=falso.cliente())
    assert r["ok"] is False and "não respondeu" in r["mensagem"]
    assert atu.trava_ativa(db, atu.TRAVA_SGA) is None


def test_sem_acessos_no_render(db):
    r = atu.testar_sga(db, cfg_teste(), http=SGAFalso().cliente())
    assert r["ok"] is False and "não estão no Render" in r["mensagem"]
    r = atu.testar_powercrm(db, cfg_teste(), http=SGAFalso().cliente())
    assert r["ok"] is False and "POWERCRM_TOKEN" in r["mensagem"]
    assert db.scalars(select(Atualizacao)).all() == []


def test_consultas_do_sga_renovam_o_login_e_param_no_segundo_recusado():
    falso = SGAFalso(LOGIN_OK, httpx2.Response(401), LOGIN_OK, httpx2.Response(200, json={"veiculos": [1]}))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    assert c.post("/listar/veiculo", {"codigo_situacao": "1"}) == {"veiculos": [1]}
    falso = SGAFalso(LOGIN_OK, httpx2.Response(401), LOGIN_OK, httpx2.Response(403))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    with pytest.raises(SGABloqueado, match="duas vezes seguidas"):
        c.post("/listar/veiculo", {})
    falso = SGAFalso(LOGIN_OK, httpx2.Response(406, text="Nenhum veículo encontrado"))
    assert ClienteSGA("t", "u", "s", http=falso.cliente()).post("/listar/veiculo", {}) == {}
    falso = SGAFalso(LOGIN_OK, httpx2.Response(404, text="Nenhum boleto para o filtro"))  # sem repetir a consulta
    assert ClienteSGA("t", "u", "s", http=falso.cliente()).post("/listar/boleto-associado-veiculo", {}) == {}
    assert len(falso.pedidos) == 2


def test_limite_de_chamadas_e_tentativas():
    falso = SGAFalso(LOGIN_OK, httpx2.Response(500), httpx2.Response(502), httpx2.Response(503))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    with pytest.raises(SGAErro, match="3 tentativas"):
        c.post("/listar/veiculo", {})
    falso = SGAFalso(LOGIN_OK, httpx2.Response(200, json={}))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), limite_chamadas=1)
    with pytest.raises(SGAErro, match="limite"):
        c.post("/listar/veiculo", {})


def test_teste_do_powercrm(db):
    falso = SGAFalso(httpx2.Response(200, json={"items": [{"id": 1}, {"id": 2}]}))
    r = atu.testar_powercrm(db, CFG, http=falso.cliente(base="https://api.powercrm.com.br"))
    assert r["ok"] is True and "2 cotação" in r["mensagem"]
    assert falso.pedidos[0].headers["authorization"] == "Bearer pc-inventado"
    falso = SGAFalso(httpx2.Response(200, json={"total": 0}))  # sem "items": fim das páginas
    assert atu.testar_powercrm(db, CFG, http=falso.cliente(base="https://api.powercrm.com.br"))["ok"] is True
    falso = SGAFalso(httpx2.Response(401))
    r = atu.testar_powercrm(db, CFG, http=falso.cliente(base="https://api.powercrm.com.br"))
    assert r["ok"] is False and "recusou o token" in r["mensagem"]


def test_proximo_horario_do_sga():
    sp = timezone(timedelta(hours=-3))
    # 06:00 e 16:00 de Brasília = 09:00 e 19:00 UTC
    assert atu.proximo_horario_sga(datetime(2026, 11, 8, 2, 0, tzinfo=sp)) == datetime(2026, 11, 8, 9, 0, tzinfo=timezone.utc)
    assert atu.proximo_horario_sga(datetime(2026, 11, 8, 7, 0, tzinfo=sp)) == datetime(2026, 11, 8, 19, 0, tzinfo=timezone.utc)
    assert atu.proximo_horario_sga(datetime(2026, 11, 8, 17, 0, tzinfo=sp)) == datetime(2026, 11, 9, 9, 0, tzinfo=timezone.utc)


def test_teste_de_partida_so_quando_devido(app, db):
    assert atu.teste_devido(db, "sga") is True
    atu.testar_sga(db, CFG, http=SGAFalso(LOGIN_OK).cliente())
    assert atu.teste_devido(db, "sga") is False  # teve teste bom há menos de 12 horas
    atu.teste_de_partida(app.state.Sessao, cfg_teste())  # sem acessos: não faz nada e não quebra


def test_painel_de_atualizacoes(admin, novo_cliente, db):
    atu.testar_sga(db, CFG, http=SGAFalso(httpx2.Response(403, text="BLOQUEADO")).cliente())
    r = admin.get("/api/admin/atualizacoes").json()
    sga = next(f for f in r["fontes"] if f["fonte"] == "sga")
    assert "BLOQUEADO" in sga["ultimo_erro"] and r["sga_pausado"]["ate_txt"]
    assert r["historico"][0]["fonte_nome"] == "SGA" and r["historico"][0]["ok"] is False
    testes = admin.post("/api/admin/atualizacoes/testar", json={}).json()  # app de teste: sem acessos no Render
    assert testes["sga"]["ok"] is False and testes["powercrm"]["ok"] is False
    criar_pessoa(db, nome="Sem Painel", email="sem@exemplo.com.br", tipo="cadastro")
    c = novo_cliente()
    entrar(c, "sem@exemplo.com.br")
    assert c.get("/api/admin/atualizacoes").status_code == 403
    assert c.post("/api/admin/atualizacoes/testar", json={}).status_code == 403


def test_consulta_get_do_sga():
    falso = SGAFalso(LOGIN_OK, httpx2.Response(200, json=[{"codigo": "1", "descricao": "Inadimplência"}]),
                     httpx2.Response(404), httpx2.Response(403, text="BLOQUEADO"),
                     httpx2.Response(403, text="BLOQUEADO"))  # o login de conferência também: bloqueio de verdade
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    assert c.get("/listar/situacaomotivo/ativo") == [{"codigo": "1", "descricao": "Inadimplência"}]
    assert c.get("/veiculo/buscar/123/codigo") is None
    with pytest.raises(SGABloqueado):
        c.get("/veiculo/buscar/456/codigo")
    assert falso.pedidos[1].method == "GET"


def test_bloqueio_para_a_consulta_que_esperava_nova_tentativa():
    """Busca em paralelo: a consulta A falha na rede e espera; nesse meio tempo a B recebe BLOQUEADO.
    A A não pode tentar de novo (revisão do PR #5)."""
    falso = SGAFalso(LOGIN_OK, httpx2.ConnectTimeout("rede"), httpx2.Response(403, text="BLOQUEADO"),
                     httpx2.Response(403, text="BLOQUEADO"))  # login de conferência da B: bloqueio de verdade
    c = ClienteSGA("t", "u", "s", http=falso.cliente())

    def enquanto_a_espera(_segundos):
        with pytest.raises(SGABloqueado):
            c.post("/listar/veiculo", {"b": 1})

    c.espera = enquanto_a_espera
    with pytest.raises(SGABloqueado, match="BLOQUEADO"):
        c.post("/listar/veiculo", {"a": 1})
    assert len(falso.pedidos) == 4  # login, 1ª tentativa da A, a B e o login de conferência; nada depois
    with pytest.raises(SGABloqueado):  # nem login novo nem GET saem depois disso
        c.autenticar()
    with pytest.raises(SGABloqueado):
        c.get("/veiculo/buscar/1/codigo")
    assert len(falso.pedidos) == 4


def test_palavra_bloqueado_nos_dados_nao_e_bloqueio():
    """Alarme falso de 10/11: a lista de status de atendimento do SGA tem um status chamado "Bloqueado"."""
    lista = [{"codigo_statusatendimentoassociado": "7", "descricao": "BLOQUEADO"}]
    falso = SGAFalso(LOGIN_OK, httpx2.Response(200, json=lista),
                     httpx2.Response(200, json={"veiculos": [{"situacao": "Bloqueado"}]}),
                     httpx2.Response(403, text="Token BLOQUEADO"), httpx2.Response(403, text="Token BLOQUEADO"))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    assert c.get("/listar/status-atendimento/todos") == lista
    assert c.post("/listar/veiculo", {}) == {"veiculos": [{"situacao": "Bloqueado"}]}
    assert c.bloqueio is None
    with pytest.raises(SGABloqueado):  # o aviso de verdade (resposta de erro) continua parando
        c.post("/listar/veiculo", {})
    falso = SGAFalso(httpx2.Response(200, json={"mensagem": "Usuário bloqueado"}))  # login sem token, com o aviso
    with pytest.raises(SGABloqueado):
        ClienteSGA("t", "u", "s", http=falso.cliente()).autenticar()


def test_consulta_recusada_com_login_aceito_nao_pausa():
    """Caso de 10/11 (2ª vez): o SGA recusa só /listar/status-atendimento/todos com erro dizendo "bloqueado".
    O login de conferência é aceito: o acesso está bom, a busca segue (o script original ignora essa consulta)."""
    falso = SGAFalso(LOGIN_OK, httpx2.Response(403, text="Acesso bloqueado para esta rota"), LOGIN_OK,
                     httpx2.Response(200, json={"veiculos": []}))
    c = ClienteSGA("t", "u", "s", http=falso.cliente(), espera=lambda _s: None)
    with pytest.raises(SGAErro, match="recusou a consulta listar/status-atendimento") as erro:
        c.get("/listar/status-atendimento/todos")
    assert "rota" not in str(erro.value)  # não repete o texto do SGA
    assert c.bloqueio is None
    assert c.post("/listar/veiculo", {}) == {"veiculos": []}  # as outras consultas continuam
    assert [p.url.path.rsplit("/", 1)[-1] for p in falso.pedidos] == ["autenticar", "todos", "autenticar", "veiculo"]
