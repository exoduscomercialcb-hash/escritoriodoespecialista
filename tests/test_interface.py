"""Teste da tela no navegador (Playwright): login, menu, painel e cadastro pelo link.

Sobe o servidor de verdade (uvicorn) num banco SQLite temporário e usa a rota de login de teste.
Se o Playwright não estiver instalado, o teste é pulado; no GitHub Actions ele é obrigatório
(EXIGE_NAVEGADOR=1). Para usar um Chromium já instalado: NAVEGADOR_CHROMIUM=/caminho/do/chrome.
"""
from __future__ import annotations

import os
import socket
import threading
import time

import pytest
import uvicorn

from app.db import Pessoa
from app.main import criar_app

from .conftest import ADMIN, cfg_teste

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    banco = tmp_path_factory.mktemp("banco") / "teste.db"
    app = criar_app(cfg_teste(database_url=f"sqlite:///{banco}"))
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
    with app.state.Sessao() as s:  # um líder já aprovado, para ligar o especialista novo
        s.add(Pessoa(nome="Lider Inventado", email="lider.inventado@exemplo.com.br", tipo="lider", equipe="Elite",
                     nome_sga="LIDER INVENTADO", situacao="ativo"))
        s.commit()
    yield f"http://127.0.0.1:{porta}"
    srv.should_exit = True
    t.join(timeout=5)


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
    # 400 = recusa esperada de uma regra (o teste tenta aprovar sem os campos obrigatórios)
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "status of 400" not in m.text else None)
    pg.route("https://**/*", lambda r: r.abort())  # nada sai da máquina durante o teste
    return ctx, pg, erros


def _sem_rolagem_lateral(pg):
    return pg.evaluate("document.documentElement.scrollWidth <= document.documentElement.clientWidth")


def test_tela_de_login(servidor, navegador):
    for largura in (1300, 390):
        ctx, pg, erros = _pagina(navegador, largura)
        pg.goto(servidor + "/")
        botao = pg.locator("#go")
        expect(botao).to_have_text("Entrar com Google")
        assert botao.get_attribute("href") == "/auth/login"
        expect(pg.locator(".login-head h1")).to_have_text("Escritório do Especialista")
        expect(pg.locator(".brand")).to_have_text("EXODUS BENEFÍCIOS")
        assert pg.locator("#app").is_hidden()
        assert _sem_rolagem_lateral(pg), largura
        assert not erros, erros
        ctx.close()


def test_fluxo_completo_admin_link_cadastro_aprovacao_acessos(servidor, navegador):
    adm_ctx, adm, erros_adm = _pagina(navegador)
    adm.goto(servidor + f"/teste/entrar?email={ADMIN}&nome=Admin%20Teste")

    # menu principal com o card do painel e o lugar do botão "Atualizar meus dados"
    expect(adm.locator("#hName")).to_have_text("Admin Teste")
    expect(adm.locator('#home [data-go="adm"] h3')).to_have_text("Painel do administrador")
    expect(adm.locator("#btnAtualizar")).to_be_disabled()
    expect(adm.locator("#updTexto")).to_contain_text("Pode usar 1 vez a cada 15 minutos")
    expect(adm.locator("#pfs-adm")).to_have_text("Nenhum cadastro pendente")

    # gera um link de especialista
    adm.click('#home [data-go="adm"]')
    expect(adm.locator("#adminView")).to_be_visible()
    adm.click('[data-adm="lnk"]')
    adm.select_option("#lnkTipo", "especialista")
    adm.click("#lnkForm button[type=submit]")
    campo = adm.locator("#lnkTabela tbody tr").first.locator("input")
    expect(campo).to_have_value(servidor + "/cadastro/" + campo.input_value().rsplit("/", 1)[-1])
    url_link = campo.input_value()
    codigo = url_link.rsplit("/", 1)[-1]

    # a pessoa abre o link, vê o tipo, entra (login de teste) e preenche o nome
    ctx, pg, erros = _pagina(navegador, 390)
    pg.goto(url_link)
    expect(pg.locator("#loginSub")).to_have_text("Cadastro de acesso: Especialista.")
    assert pg.locator("#go").get_attribute("href") == f"/auth/login?link={codigo}"
    pg.goto(servidor + f"/teste/entrar?email=especialista.novo@exemplo.com.br&nome=Nome%20Google&link={codigo}")
    expect(pg.locator("#cadNome")).to_have_value("Nome Google")
    pg.fill("#cadNome", "Especialista Novo Inventado")
    pg.click("#cadEnviar")
    expect(pg.locator("#naoLiberado")).to_have_text("Seu acesso ainda não foi liberado. Fale com a coordenação.")
    assert _sem_rolagem_lateral(pg)
    assert not erros, erros

    # o admin aprova, ligando ao nome do SGA, à equipe e ao líder
    adm.click('[data-adm="cad"]')
    cartao = adm.locator("#cadLista article", has_text="Especialista Novo Inventado")
    cartao.locator("button", has_text="Aprovar").click()
    expect(cartao.locator(".err")).to_contain_text("preencha: equipe, nome no SGA, líder")
    cartao.locator("select").nth(1).select_option("Elite")
    cartao.locator("input").nth(1).fill("especialista novo inventado")
    cartao.locator("select").nth(2).select_option(label="Lider Inventado (Elite)")
    cartao.locator("button", has_text="Aprovar").click()
    expect(adm.locator("#cadLista")).to_contain_text("Nenhum cadastro pendente.")
    adm.click('#cadFiltro [data-sit="ativo"]')
    ativo = adm.locator("#cadLista article", has_text="Especialista Novo Inventado")
    expect(ativo).to_contain_text("SGA: ESPECIALISTA NOVO INVENTADO")
    expect(ativo).to_contain_text("Líder: Lider Inventado")

    # agora a pessoa entra e vê a tela dela, sem o painel
    pg.goto(servidor + "/teste/entrar?email=especialista.novo@exemplo.com.br")
    expect(pg.locator("#hName")).to_have_text("Especialista Novo Inventado")
    expect(pg.locator("#hWho")).to_have_text("Especialista · Equipe Elite")
    expect(pg.locator("#homeVazio")).to_be_visible()
    assert pg.locator('#home [data-go="adm"]').count() == 0
    assert _sem_rolagem_lateral(pg)
    assert not erros, erros
    ctx.close()

    # o link mostra 1 pessoa cadastrada, e os acessos mostram quem entrou
    adm.click('[data-adm="lnk"]')
    expect(adm.locator(f'#lnkTabela tr[data-codigo="{codigo}"] td.r')).to_have_text("1")
    adm.click('[data-adm="acs"]')
    linha = adm.locator("#acsResumo tbody tr", has_text="Especialista Novo Inventado")
    expect(linha.locator("td.r")).to_have_text("1")
    expect(adm.locator("#acsEventos")).to_contain_text("Painel: Links")
    adm.select_option("#acsEquipe", "Elite")
    adm.click("#acsForm button[type=submit]")
    expect(adm.locator("#acsResumo tbody tr")).to_have_count(1)

    adm.click("#btnHome")
    expect(adm.locator("#home")).to_be_visible()
    assert not erros_adm, erros_adm
    adm_ctx.close()
