"""Teste da tela no navegador (Playwright): login, primeiro acesso pelo CPF, menu e painel.

Sobe o servidor de verdade (uvicorn) num banco SQLite temporário e usa a rota de login de teste.
Se o Playwright não estiver instalado, o teste é pulado; no GitHub Actions ele é obrigatório
(EXIGE_NAVEGADOR=1). Para usar um Chromium já instalado: NAVEGADOR_CHROMIUM=/caminho/do/chrome.
"""
from __future__ import annotations

import json
import os
import re
import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn

from app.dados import guardar
from app.db import Documento, Pessoa
from app.fontes.google import ClienteGoogle
from app.main import criar_app

from .conftest import ADMIN, cfg_teste, cpf_inventado
from .test_google import CHAVE
from .test_prints import DriveFalso as DriveFalsoDosPrints

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@contextmanager
def _subir_servidor(banco, preparar, **estado):
    # Google "configurado" com valores inventados: o teste vê o redirecionamento, mas nada sai da máquina.
    app = criar_app(cfg_teste(database_url=f"sqlite:///{banco}", google_client_id="id-inventado",
                              google_client_secret="segredo-inventado"))
    for nome, valor in estado.items():  # ex.: google_prints (o Drive simulado da rota /api/print)
        setattr(app.state, nome, valor)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        porta = s.getsockname()[1]
    srv = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=porta, log_level="warning"))
    t = threading.Thread(target=srv.run, daemon=True)
    t.start()
    for _ in range(100):
        if srv.started:
            break
        time.sleep(0.05)
    with app.state.Sessao() as s:
        preparar(s)
        s.commit()
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t.join(timeout=5)


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    def preparar(s):  # um líder já aprovado, para ligar o especialista novo
        s.add(Pessoa(nome="Lider Inventado", email="lider.inventado@exemplo.com.br", tipo="lider", equipe="Elite",
                     situacao="ativo"))
    with _subir_servidor(tmp_path_factory.mktemp("banco") / "teste.db", preparar) as url:
        yield url


@pytest.fixture(scope="module")
def navegador():
    if sync_playwright is None:
        if os.environ.get("EXIGE_NAVEGADOR"):
            pytest.fail("Playwright não instalado")
        pytest.skip("Playwright não instalado")
    with sync_playwright() as p:
        caminho = os.environ.get("NAVEGADOR_CHROMIUM")
        try:
            b = p.chromium.launch(executable_path=caminho) if caminho else p.chromium.launch()
        except Exception as e:  # pragma: no cover
            if os.environ.get("EXIGE_NAVEGADOR"):
                raise
            pytest.skip(f"Chromium indisponível: {e}")
        yield b
        b.close()


def _pagina(navegador, largura=1300):
    ctx = navegador.new_context(viewport={"width": largura, "height": 900})
    pg = ctx.new_page()
    erros: list[str] = []
    pg.on("pageerror", lambda e: erros.append(str(e)))
    # 400 = recusa esperada de uma regra (o teste digita um CPF que não tem cadastro)
    # ignorados: 400 (recusa esperada de uma regra) e ERR_FAILED (o teste corta a internet: fontes do Google)
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "status of 400" not in m.text
          and "net::ERR_FAILED" not in m.text else None)
    pg.route("https://**/*", lambda r: r.abort())  # nada sai da máquina durante o teste
    return ctx, pg, erros


def _sem_rolagem_lateral(pg):
    return pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_tela_de_login(servidor, navegador):
    for largura in (1300, 390):
        ctx, pg, erros = _pagina(navegador, largura)
        pg.goto(servidor + "/")
        botao = pg.locator("#paEnviar")  # o único botão do Google, travado até preencher CPF e WhatsApp
        expect(botao).to_have_text("Entrar com Google")
        expect(botao).to_be_disabled()
        pg.fill("#paCpf", "123.456.789-09")
        expect(botao).to_be_disabled()
        pg.fill("#paWhats", "(21) 98765-4321")
        expect(botao).to_be_enabled()
        assert pg.locator("#go").count() == 0
        expect(pg.locator(".login-head h1")).to_have_text("Escritório do Especialista")
        expect(pg.locator(".brand")).to_have_text("EXODUS BENEFÍCIOS")
        assert pg.locator("#app").is_hidden()
        assert _sem_rolagem_lateral(pg), largura
        assert not erros, erros
        ctx.close()


def test_fluxo_completo_planilha_primeiro_acesso_e_acessos(servidor, navegador):
    adm_ctx, adm, erros_adm = _pagina(navegador)
    adm.goto(servidor + f"/teste/entrar?email={ADMIN}&nome=Admin%20Teste")

    # menu principal com o card do painel e o lugar do botão "Atualizar meus dados"
    # quem entra cai nos cards (a página atual); sem dados importados, aparece o aviso
    expect(adm).to_have_url(servidor + "/escritorio")
    expect(adm.locator("#hName")).to_have_text("Admin Teste")
    expect(adm.locator(".aviso-dados")).to_contain_text("ainda não foram carregados")
    painel = adm.locator('#home a[data-painel="1"]')
    expect(painel.locator("h3")).to_have_text("Painel do administrador")

    # o admin importa a planilha (colada do Excel) e faz um cadastro avulso
    painel.click()
    expect(adm.locator("#adminView")).to_be_visible()
    expect(adm.locator("#btnAtualizar")).to_be_disabled()
    expect(adm.locator("#updTexto")).to_contain_text("Pode usar 1 vez a cada 15 minutos")
    cpf_esp, cpf_cad = cpf_inventado(501), cpf_inventado(502)
    adm.click("#boxImportar summary")
    adm.fill("#impTexto", "Nome\tTipo de conta\tCPF\tEquipe\tNome no SGA\tLíder\n"
                          f"Especialista Novo Inventado\tEspecialista\t{cpf_esp}\tElite\tespecialista novo inventado\tLider Inventado\n")
    adm.click("#impEnviar")
    expect(adm.locator("#impResultado")).to_contain_text("1 cadastro(s) novo(s)")
    adm.click("#boxNovo summary")
    adm.fill("#novoNome", "Cadastro Avulso Inventado")
    adm.select_option("#novoTipo", "cadastro")
    adm.fill("#novoCpf", cpf_cad)
    adm.click("#novoForm button[type=submit]")
    adm.click('#cadFiltro [data-sit="aguardando"]')
    expect(adm.locator("#cadTabela tr.pessoa")).to_have_count(3)
    expect(adm.locator("#cadTabela tr.pessoa", has_text="Especialista Novo Inventado")).to_contain_text("Aguardando 1º acesso")

    # a pessoa abre o endereço do escritório no celular: primeiro acesso com CPF e WhatsApp, depois o Google
    ctx, pg, erros = _pagina(navegador, 390)
    pg.goto(servidor + "/")
    pg.fill("#paCpf", cpf_inventado(999))
    pg.fill("#paWhats", "(21) 98765-4321")
    pg.click("#paEnviar")
    expect(pg.locator("#paErro")).to_have_text("Não encontramos um cadastro com esse CPF. Fale com a coordenação.")
    pg.fill("#paCpf", cpf_esp)
    assert _sem_rolagem_lateral(pg)
    with pg.expect_request(lambda r: r.url.endswith("/auth/login")):
        pg.click("#paEnviar")
    # volta do Google (aqui, login de teste) já com acesso
    pg.goto(servidor + "/teste/entrar?email=especialista.novo@exemplo.com.br&nome=Nome%20Google")
    expect(pg.locator("#hName")).to_have_text("Especialista Novo Inventado")
    expect(pg.locator("#hWho")).to_contain_text("Equipe Elite")
    expect(pg).to_have_url(servidor + "/escritorio")
    expect(pg.locator(".aviso-dados")).to_contain_text("Fale com a coordenação")
    assert pg.locator('#home a[data-painel="1"]').count() == 0  # especialista não vê o painel
    assert _sem_rolagem_lateral(pg)
    assert not erros, erros
    ctx.close()

    # quem clica direto em "Entrar com Google" no primeiro acesso informa o CPF depois
    ctx, pg, erros = _pagina(navegador, 390)
    pg.goto(servidor + "/teste/entrar?email=cadastro.avulso@exemplo.com.br")
    expect(pg.locator("#semCadastro")).to_be_visible()
    pg.fill("#paCpf", cpf_cad)
    pg.fill("#paWhats", "21 99999-0000")
    pg.click("#paEnviar")
    expect(pg.locator("#hName")).to_have_text("Cadastro Avulso Inventado")
    assert not erros, erros
    ctx.close()

    # o admin vê o WhatsApp e o 1º acesso no cadastro
    adm.click('[data-adm="cad"]')
    # filtro "Já acessou" (26/11): quem entrou aparece; quem só foi cadastrado, não
    adm.click('#cadFiltro [data-sit="acessou"]')
    expect(adm.locator("#cadTabela tr.pessoa", has_text="Especialista Novo Inventado")).to_have_count(1)
    expect(adm.locator("#cadTabela tr.pessoa", has_text="Aguardando 1º acesso")).to_have_count(0)
    adm.click('#cadFiltro [data-sit="ativo"]')
    ativo = adm.locator("#cadTabela tr.pessoa", has_text="Especialista Novo Inventado")
    expect(ativo).to_contain_text("(21) 98765-4321")  # WhatsApp e e-mail Google preenchidos no primeiro acesso
    expect(ativo).to_contain_text("especialista.novo@exemplo.com.br")
    expect(ativo).to_contain_text("1º acesso:")
    expect(ativo).to_contain_text("Lider Inventado")
    # editar abre o cadastro na própria tabela
    ativo.locator('[data-acao="editar"]').click()
    expect(adm.locator(f'[data-editor="{ativo.get_attribute("data-pessoa")}"]')).to_be_visible()

    # os acessos mostram quem entrou
    adm.click('[data-adm="acs"]')
    linha = adm.locator("#acsResumo tbody tr", has_text="Especialista Novo Inventado")
    expect(linha.locator("td.r")).to_have_text("1")
    assert adm.locator("#acsEventos").count() == 0  # só o registro "Quem entrou" (pedido de 08/11)
    adm.select_option("#acsEquipe", "Elite")
    adm.click("#acsForm button[type=submit]")
    expect(adm.locator("#acsResumo tbody tr")).to_have_count(1)

    adm.click("#btnHome")  # "Menu principal" do painel volta para os cards
    expect(adm).to_have_url(servidor + "/escritorio")
    expect(adm.locator('#home a[data-painel="1"]')).to_be_visible()
    assert not erros_adm, erros_adm
    adm_ctx.close()


# ---------------------------------------------------------------- cards com dados (mudanças da página atual até 24/11)

def _cancelado(n, pl, mat, dc, **extra):
    """Uma linha de E.data.canc inventada (nomes, placas, matrículas e telefones de mentira)."""
    linha = {"n": n, "mod": "Carro Inventado", "ano": "2020", "pl": pl, "mat": mat, "dc": dc,
             "esp": "Especialista Inventado", "t": "LUA", "wa": "55219000000" + mat[-2:], "mp": 0.8, "b": 5}
    linha.update(extra)
    return linha


PACOTE_ALL = {
    "atualizado": "2026-11-24T06:00-03:00", "meses_base": ["2026-09", "2026-10", "2026-11"],
    "meses_ad": ["2026-10", "2026-11"], "val_ate": 0, "teams": ["LUA"], "nomes": {"LUA": "Lua"},
    "leaders": {"LUA": "Lider Inventado"},
    "series": {"ALL|equipe": {"base": [3, 4, 4], "ad": [1, 1], "va": [1, 0]},
               "LUA|equipe": {"base": [3, 4, 4], "ad": [1, 1], "va": [1, 0]}},
    "pend": None, "det": {}, "desc": {"d": {}, "tk": {}},
    "ades": [{"m": "2026-11", "t": "LUA", "esp": "Especialista Inventado", "n": "Associado Adesao Inventado",
              "pl": "TST2B01", "dc": "05/11/2026"}],
    # Inside Sales (20/11): a coordenação vê o bônus de cada vendedora interna
    "vib": [{"t": "EXODUS", "key": "VENDEDORA INVENTADA", "nome": "Vendedora Inventada", "first": "Vendedora",
             "meta": 15}],
    "vesp": {"EXODUS": {"VENDEDORA INVENTADA": {"va": [16, 3]}}},
    "canc": [
        _cancelado("Associado Cancelado Inventado", "TST1A01", "9001", "2026-11-10", mot="Financeiro"),
        _cancelado("Associado Inadimplente Inventado", "TST1A02", "9002", "2026-11-11", st="inad"),
        _cancelado("Associado Inativo Inventado", "TST1A03", "9003", "2026-11-12", st="inat", wa="", mp=None, b=None),
        _cancelado("Associado Retirada Ok Inventado", "TST1A04", "9004", "2026-11-13", st="ret", moto=True,
                   rr={"ok": True, "st": "Concluído", "d": "20/11/2026"}),
        _cancelado("Associado Retirada Pendente Inventado", "TST1A05", "9005", "2026-11-14", st="ret",
                   rr={"ok": False, "st": "Aberto", "d": ""}),
        _cancelado("Associado Voltou Inventado", "TST1A06", "9006", "2026-10-20", st="inad",
                   rs={"dc": "2026-11-20", "sit": "ATIVO"}),
    ],
}


@pytest.fixture(scope="module")
def servidor_com_dados(tmp_path_factory):
    def preparar(s):
        guardar(s, "all", PACOTE_ALL, "importacao")
        # lista do remarketing (estático) de um especialista: um ex-associado que também está nos cancelados recentes
        guardar(s, "esp:ESPECIALISTA INVENTADO", {"id": 1, "nome": "Especialista Inventado", "sga": [], "eqs": ["LUA"]},
                "importacao")
        guardar(s, "rm:ESPECIALISTA INVENTADO", [
            {"mat": "9002", "n": "Associado Inadimplente Inventado", "pl": "TST1A02", "wa": "5521900000002",
             "eq": "Lua", "mod": "Carro Inventado", "ano": "2019"},
            {"mat": "8001", "n": "Associado Antigo Inventado", "pl": "TST3C01", "wa": "5521900000081", "eq": "Lua",
             "mod": "Carro Inventado", "ano": "2015"}], "importacao")
        s.add(Pessoa(nome="Cadastro Inventado", email="cadastro.inventado@exemplo.com.br", tipo="cadastro",
                     situacao="ativo"))
    with _subir_servidor(tmp_path_factory.mktemp("banco_dados") / "teste.db", preparar) as url:
        yield url


def test_cards_do_admin_com_cancelados_de_cada_tipo(servidor_com_dados, navegador):
    ctx, pg, erros = _pagina(navegador)
    pg.goto(servidor_com_dados + f"/teste/entrar?email={ADMIN}&nome=Admin%20Teste")
    expect(pg).to_have_url(servidor_com_dados + "/escritorio")
    assert pg.locator(".aviso-dados").count() == 0
    expect(pg.locator('#home [data-go="evo"] .pfs')).to_have_text("1 cancelados recentes")  # só os cancelados (sem st)

    # cancelados recentes: um card de cada tipo, com a cor do tipo
    pg.click('#home [data-go="evo"]')
    lista = pg.locator("#cancList")
    expect(lista.locator("article.cx")).to_have_count(6)
    expect(lista.locator("article.cx.inad")).to_contain_text("INADIMPLENTE")
    expect(lista.locator("article.cx.inat")).to_contain_text("Sem celular válido")
    expect(lista.locator("article.cx.ret")).to_have_count(2)
    expect(lista.locator("article.cx.ret .rrbox.ok")).to_contain_text("já pode fazer nova adesão")
    expect(lista.locator("article.cx.ret .rrbox.no")).to_contain_text("não pode fazer nova adesão")
    expect(lista.locator("article.cx.ret", has_text="Retirada Pendente").locator("a.btn.wa")).to_have_attribute(
        "href", "https://wa.me/5521900000005")
    expect(lista.locator("article.cx.resg", has_text="Voltou")).to_contain_text("Voltou a ficar ativo!")
    soma = pg.locator("#cancSum")
    for texto in ("1 cancelados", "1 inadimplentes", "1 inativos", "2 em retirada", "1 voltaram a ficar ativos"):
        expect(soma).to_contain_text(texto)
    # filtros novos
    for filtro, rotulo, n in (("inad", "Inadimplentes (1)", 1), ("inat", "Inativos (1)", 1), ("ret", "Retirada (2)", 2),
                              ("resg", "Reativados (1)", 1)):
        botao = pg.locator(f'#cancSit [data-cs="{filtro}"]')
        expect(botao).to_have_text(rotulo)
        botao.click()
        expect(lista.locator("article.cx")).to_have_count(n)
    pg.click('#cancSit [data-cs="all"]')
    expect(lista.locator("article.cx")).to_have_count(6)

    # adesões validadas: bônus do Inside Sales na visão da coordenação
    pg.click("#btnHome")
    pg.click('#home [data-go="va"]')
    expect(pg.locator("#vaBonus")).to_contain_text("Bônus do Inside Sales")
    expect(pg.locator("#vaBonus")).to_contain_text("Vendedora Inventada")
    expect(pg.locator("#vaBonus .pill.ok")).to_have_text("Meta batida")

    # comprovante de adesões: o valor pago grava sozinho 0,9 s depois da última tecla e cria o documento do mês
    pg.click("#btnHome")
    pg.click('#home [data-go="cp"]')
    ler = "m => fetch('/api/banco/comp/' + m).then(r => r.json())"
    assert pg.evaluate(ler, "2026-11") == {"exists": False, "data": None}
    campo = pg.locator('#cpList input[data-pg="TST2B01"]')
    campo.click()
    campo.press_sequentially("150,00")
    expect(pg.locator("#toast")).to_have_text("Pagamento salvo: R$\xa0150,00 ✓")
    doc = pg.evaluate(ler, "2026-11")
    assert doc["exists"] and doc["data"]["TST2B01"]["pg"] == 150 and doc["data"]["TST2B01"]["pgl"] == "avulso"
    # outra pessoa marca outra adesão no mesmo mês; a próxima gravação daqui não apaga a marcação dela
    pg.evaluate("""() => fetch('/api/banco/comp/2026-11', {method: 'PATCH', headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({OUTRA: {ok: true}})})""")
    campo = pg.locator('#cpList input[data-pg="TST2B01"]')
    campo.fill("")
    campo.press_sequentially("200")
    expect(pg.locator("#toast")).to_have_text("Pagamento salvo: R$\xa0200,00 ✓")
    doc = pg.evaluate(ler, "2026-11")["data"]
    assert doc["TST2B01"]["pg"] == 200 and doc["OUTRA"] == {"ok": True}
    assert _sem_rolagem_lateral(pg)
    assert not erros, erros
    ctx.close()


def test_acesso_cadastro_ve_remarketing_estatico_e_dinamico(servidor_com_dados, navegador):
    ctx, pg, erros = _pagina(navegador)
    pg.goto(servidor_com_dados + "/teste/entrar?email=cadastro.inventado@exemplo.com.br")
    expect(pg).to_have_url(servidor_com_dados + "/escritorio")
    expect(pg.locator('#home [data-go="list"] h3')).to_have_text("Remarketing estático")
    expect(pg.locator('#home [data-go="evo"] h3')).to_have_text("Remarketing dinâmico")
    pg.click('#home [data-go="list"]')
    no_dinamico = pg.locator("#list article.card", has_text="Associado Inadimplente Inventado")
    expect(no_dinamico.locator(".chip.warnc")).to_have_text("NO REMARKETING DINÂMICO")
    expect(no_dinamico.locator(".dynbox")).to_contain_text("como inadimplente · TST1A02")
    expect(pg.locator("#list article.card", has_text="Associado Antigo Inventado").locator(".chip.warnc")).to_have_count(0)
    # o botão leva aos cancelados recentes já filtrados pela placa, com o filtro de situação limpo
    no_dinamico.locator("[data-goc]").click()
    expect(pg.locator("#evoTitle")).to_contain_text("Remarketing dinâmico · ")
    expect(pg.locator("#cancQ")).to_have_value("TST1A02")
    expect(pg.locator('#cancSit [data-cs="all"]')).to_have_attribute("aria-pressed", "true")
    expect(pg.locator("#cancList article.cx")).to_have_count(1)
    assert not erros, erros
    ctx.close()


def test_banco_da_pagina_so_avisa_quando_o_documento_muda(servidor_com_dados, navegador):
    """A busca de 20 em 20 s não chama a página à toa (redesenhar a lista apagaria o foco de quem está digitando)."""
    ctx, pg, erros = _pagina(navegador)
    pg.clock.install()
    pg.goto(servidor_com_dados + f"/teste/entrar?email={ADMIN}&nome=Admin%20Teste")
    expect(pg).to_have_url(servidor_com_dados + "/escritorio")
    pg.evaluate("""async () => { window._avisos = [];
        const db = await window.claude.use('db');
        db.collection('enviados').doc('teste-foco').onSnapshot(d => window._avisos.push(d.exists ? d.data().n : null)); }""")
    pg.wait_for_function("() => window._avisos.length === 1")
    pg.clock.run_for(65_000)  # três buscas sem mudança
    pg.wait_for_timeout(200)
    assert pg.evaluate("window._avisos") == [None]
    pg.evaluate("""() => fetch('/api/banco/enviados/teste-foco', {method: 'PUT',
                  headers: {'Content-Type': 'application/json'}, body: JSON.stringify({n: 1})})""")  # outra pessoa grava
    pg.clock.run_for(21_000)
    pg.wait_for_function("() => window._avisos.length === 2")
    assert pg.evaluate("window._avisos") == [None, 1]
    assert not erros, erros
    ctx.close()


# ---------------------------------------------------------------- botões do Apps Script (anexar comprovante e prints)

GAS_INVENTADO = "https://script.google.com/macros/s/INVENTADO/exec"
TOK_LUA, TOK_ESP, TOK_LIDER = "0a0a0a0a0a0a0a0a", "1b1b1b1b1b1b1b1b", "2c2c2c2c2c2c2c2c"  # inventados
PRINT_ID = "arquivo-print-novo-01"


@pytest.fixture(scope="module")
def servidor_com_tokens(tmp_path_factory):
    def preparar(s):
        guardar(s, "rtcfg", {"meses": [], "prazos": {}, "comp": True, "gas": GAS_INVENTADO}, "importacao")
        guardar(s, "t:LUA", dict(PACOTE_ALL, team="LUA"), "importacao")
        pessoal = dict(PACOTE_ALL, team="", teams=[], leaders={}, series={"ALL|equipe": PACOTE_ALL["series"]["ALL|equipe"]})
        guardar(s, "e:ESPECIALISTA INVENTADO", dict(pessoal, esp="Especialista Inventado", eq="LUA"), "importacao")
        guardar(s, "e:SEM TOKEN INVENTADA", dict(pessoal, esp="Sem Token Inventada", eq="ELITE",
                                                 ades=[dict(PACOTE_ALL["ades"][0], t="ELITE", esp="Sem Token Inventada")]),
                "importacao")
        for nome, eq in (("Especialista Inventado", "LUA"), ("Outro Especialista Inventado", "LUA"),
                         ("Lider Inventado", "LUA"), ("Sem Token Inventada", "ELITE")):
            guardar(s, "esp:" + nome.upper(), {"id": None, "nome": nome, "sga": [], "eqs": [eq]}, "importacao")
            guardar(s, "rm:" + nome.upper(), [], "importacao")
        # como a importação guarda: chaves normalizadas. Sem token para o "Outro" e para a equipe ELITE.
        guardar(s, "tokens_gas", {"comp": {"LUA": TOK_LUA},
                                  "rt": {"ESPECIALISTA INVENTADO": TOK_ESP, "LIDER INVENTADO": TOK_LIDER}}, "importacao")
        for nome, tipo, equipe in (("Especialista Inventado", "especialista", "Lua"), ("Lider Inventado", "lider", "Lua"),
                                   ("Sem Token Inventada", "especialista", "Elite")):
            s.add(Pessoa(nome=nome, email=nome.split()[0].lower() + ".tok@exemplo.com.br", tipo=tipo, equipe=equipe,
                         situacao="ativo"))
        # prints de reativação: um do especialista da equipe (já no Drive), um do líder ainda nos assets do sistema
        # atual e um de outra equipe (o líder não recebe)
        s.add(Documento(colecao="reativ", doc_id="dono-inventado", dados=json.dumps({"p": {
            "pa": {"id": "assetinventado01", "url": "/_blob/assetinventado01", "esp": "Lider Inventado",
                   "mes": "2026-10", "at": 1792497600000},
            "pb": {"id": "assetinventado02", "url": "/_blob/assetinventado02", "esp": "Sem Token Inventada",
                   "mes": "2026-10", "at": 1792497600000}}})))
        s.add(Documento(colecao="reativ", doc_id="drive-2026-11", dados=json.dumps({"p": {"d" + PRINT_ID: {
            "id": PRINT_ID, "drive": PRINT_ID, "url": "/api/print/" + PRINT_ID, "esp": "Especialista Inventado",
            "mes": "2026-11", "at": 1794312000000, "assoc": "", "res": "", "conf": "", "nota": ""}}})))
        guardar(s, "prints_drive", {PRINT_ID: {"mime": "image/png", "esp": ["ESPECIALISTA INVENTADO"]}}, "drive")
    drive = ClienteGoogle(CHAVE, http=DriveFalsoDosPrints().cliente())
    with _subir_servidor(tmp_path_factory.mktemp("banco_tokens") / "teste.db", preparar, google_prints=drive) as url:
        yield url


def _entrar_com_tokens(navegador, servidor, email):
    ctx, pg, erros = _pagina(navegador)
    ao_google: list[str] = []
    pg.on("request", lambda r: ao_google.append(r.url) if "script.google.com" in r.url else None)
    pg.goto(servidor + "/teste/entrar?email=" + email)
    expect(pg).to_have_url(servidor + "/escritorio")
    return ctx, pg, erros, ao_google


def test_especialista_anexa_comprovante_com_o_token_da_equipe(servidor_com_tokens, navegador):
    ctx, pg, erros, ao_google = _entrar_com_tokens(navegador, servidor_com_tokens, "especialista.tok@exemplo.com.br")
    pg.click('#home [data-go="cp"]')
    botao = pg.locator("#cpList a[data-cpsent]")
    expect(botao).to_have_text("Anexar comprovante (foto ou PDF)")
    expect(botao).to_have_attribute("href", GAS_INVENTADO + "?tipo=comp&k=" + TOK_LUA + "&m=2026-11&pl=TST2B01"
                                    "&n=Associado%20Adesao%20Inventado&esp=Especialista%20Inventado&eq=Lua")
    assert pg.locator('[data-view="rt"]').is_hidden()  # especialista não envia print de reativação
    assert not ao_google and not erros, (ao_google, erros)
    ctx.close()


def test_sem_token_nao_aparece_o_botao(servidor_com_tokens, navegador):
    ctx, pg, erros, ao_google = _entrar_com_tokens(navegador, servidor_com_tokens, "sem.tok@exemplo.com.br")
    pg.click('#home [data-go="cp"]')
    expect(pg.locator("#cpList .pill.bad")).to_have_text("Sem comprovante")
    assert pg.locator("#cpList a[data-cpsent]").count() == 0
    assert "k=" not in pg.locator("#cpList").inner_html()
    assert not ao_google and not erros, (ao_google, erros)
    ctx.close()


def test_lider_envia_print_com_o_token_do_especialista_escolhido(servidor_com_tokens, navegador):
    ctx, pg, erros, ao_google = _entrar_com_tokens(navegador, servidor_com_tokens, "lider.tok@exemplo.com.br")
    # comprovante: o token do líder da equipe da adesão
    pg.click('#home [data-go="cp"]')
    expect(pg.locator("#cpList a[data-cpsent]")).to_have_attribute("href", re.compile(r"\?tipo=comp&k=" + TOK_LUA + "&"))
    # print de reativação: começa no próprio líder e troca pelo especialista escolhido
    pg.click("#btnHome")
    pg.click('#home [data-go="rt"]')
    expect(pg.locator("#rtEspL")).to_be_visible()
    expect(pg.locator("#rtEsp")).to_have_value("Lider Inventado")
    mes = pg.input_value("#rtMes")
    expect(pg.locator("#rtGas")).to_have_attribute("href", GAS_INVENTADO + "?k=" + TOK_LIDER + "&m=" + mes)
    pg.select_option("#rtEsp", "Especialista Inventado")
    expect(pg.locator("#rtGas")).to_have_attribute("href", GAS_INVENTADO + "?k=" + TOK_ESP + "&m=" + mes)
    expect(pg.locator("#rtGasBox")).to_be_visible()
    pg.select_option("#rtEsp", "Outro Especialista Inventado")  # sem token: o botão some
    expect(pg.locator("#rtGasBox")).to_be_hidden()
    assert pg.locator("#rtGas").get_attribute("href") is None
    assert not ao_google and not erros, (ao_google, erros)
    ctx.close()


def test_lider_ve_os_prints_da_equipe_vindos_do_drive(servidor_com_tokens, navegador):
    ctx, pg, erros, ao_google = _entrar_com_tokens(navegador, servidor_com_tokens, "lider.tok@exemplo.com.br")
    pg.click('#home [data-go="rt"]')
    expect(pg.locator("#rtList .rt-item")).to_have_count(2)  # o de outra equipe não vem do servidor
    expect(pg.locator("#rtListT")).to_have_text("Seus prints enviados (2)")
    imagem = pg.locator("#rtList img")
    expect(imagem).to_have_attribute("src", "/api/print/" + PRINT_ID)
    expect(pg.locator("#rtList a", has=pg.locator("img"))).to_have_attribute("href", "/api/print/" + PRINT_ID)  # abrir
    imagem.scroll_into_view_if_needed()
    pg.wait_for_function("() => { const i = document.querySelector('#rtList img'); return i && i.complete && i.naturalWidth === 2; }")
    expect(pg.locator("#rtList .rt-rm")).to_have_text("Imagem ainda não copiada para o sistema novo. O registro continua valendo.")
    assert "Sem Token" not in pg.locator("#rtList").inner_html()
    assert not ao_google and not erros, (ao_google, erros)
    ctx.close()
