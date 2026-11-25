"""Teste da tela no navegador (Playwright): login, primeiro acesso pelo CPF, menu e painel.

Sobe o servidor de verdade (uvicorn) num banco SQLite temporário e usa a rota de login de teste.
Se o Playwright não estiver instalado, o teste é pulado; no GitHub Actions ele é obrigatório
(EXIGE_NAVEGADOR=1). Para usar um Chromium já instalado: NAVEGADOR_CHROMIUM=/caminho/do/chrome.
"""
from __future__ import annotations

import os
import socket
import threading
import time
from contextlib import contextmanager

import pytest
import uvicorn

from app.dados import guardar
from app.db import Pessoa
from app.main import criar_app

from .conftest import ADMIN, cfg_teste, cpf_inventado

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@contextmanager
def _subir_servidor(banco, preparar):
    # Google "configurado" com valores inventados: o teste vê o redirecionamento, mas nada sai da máquina.
    app = criar_app(cfg_teste(database_url=f"sqlite:///{banco}", google_client_id="id-inventado",
                              google_client_secret="segredo-inventado"))
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
    with _subir_servidor(tmp_path_factory.mktemp("banco_dados") / "teste.db", preparar) as url:
        yield url


def test_cards_do_admin_com_cancelados_de_cada_tipo(servidor_com_dados, navegador):
    ctx, pg, erros = _pagina(navegador)
    pg.goto(servidor_com_dados + f"/teste/entrar?email={ADMIN}&nome=Admin%20Teste")
    expect(pg).to_have_url(servidor_com_dados + "/escritorio")
    assert pg.locator(".aviso-dados").count() == 0
    expect(pg.locator('#home [data-go="evo"] p')).to_contain_text("1 cancelados recentes")  # só os cancelados (sem st)

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
