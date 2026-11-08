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

import pytest
import uvicorn

from app.db import Pessoa
from app.main import criar_app

from .conftest import ADMIN, cfg_teste, cpf_inventado

try:
    from playwright.sync_api import expect, sync_playwright
except ImportError:  # pragma: no cover
    sync_playwright = None


@pytest.fixture(scope="module")
def servidor(tmp_path_factory):
    banco = tmp_path_factory.mktemp("banco") / "teste.db"
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
    with app.state.Sessao() as s:  # um líder já aprovado, para ligar o especialista novo
        s.add(Pessoa(nome="Lider Inventado", email="lider.inventado@exemplo.com.br", tipo="lider", equipe="Elite",
                     situacao="ativo"))
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
    # 400 = recusa esperada de uma regra (o teste digita um CPF que não tem cadastro)
    pg.on("console", lambda m: erros.append(m.text) if m.type == "error" and "status of 400" not in m.text else None)
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
    expect(adm.locator("#hName")).to_have_text("Admin Teste")
    expect(adm.locator('#home [data-go="adm"] h3')).to_have_text("Painel do administrador")
    expect(adm.locator("#btnAtualizar")).to_be_disabled()
    expect(adm.locator("#updTexto")).to_contain_text("Pode usar 1 vez a cada 15 minutos")
    expect(adm.locator("#pfs-adm")).to_have_text("1 pessoa aguardando 1º acesso")  # o líder do teste nunca entrou

    # o admin importa a planilha (colada do Excel) e faz um cadastro avulso
    adm.click('#home [data-go="adm"]')
    expect(adm.locator("#adminView")).to_be_visible()
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
    expect(pg.locator("#hWho")).to_have_text("Especialista · Equipe Elite")
    expect(pg.locator("#homeVazio")).to_be_visible()
    assert pg.locator('#home [data-go="adm"]').count() == 0
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
    expect(adm.locator("#acsEventos")).to_contain_text("Painel: Cadastros")
    adm.select_option("#acsEquipe", "Elite")
    adm.click("#acsForm button[type=submit]")
    expect(adm.locator("#acsResumo tbody tr")).to_have_count(1)

    adm.click("#btnHome")
    expect(adm.locator("#home")).to_be_visible()
    assert not erros_adm, erros_adm
    adm_ctx.close()
