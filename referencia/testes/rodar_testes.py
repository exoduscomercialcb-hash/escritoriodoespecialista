# Testes de regressão do Escritório do Especialista (Retorno Exodus).
# Regra: todo erro corrigido ganha um teste aqui; nada é publicado sem TODOS passarem.
# Uso: python3 -I rodar_testes.py <pagina.html> <senhas_teste.json>
#   senhas_teste.json = {"COORDENACAO": "...", "RODRIGO MORAES": "...", "CADASTRO": "...", "NALVA MEIRELES": "...", "GILMAR GOMES": "..."}
#   (logins que faltarem no arquivo são pulados, com aviso). Saída: uma linha por teste (OK/FALHOU) e código 1 se algo falhar.
import sys, json, asyncio
from playwright.async_api import async_playwright

PAGE, PWF = sys.argv[1], sys.argv[2]
PW = json.load(open(PWF, encoding="utf-8"))
RES = []
def ok(nome, cond, det=""): RES.append((bool(cond), nome, det)); print(("OK      " if cond else "FALHOU  ") + nome + (" · " + str(det) if det else ""), flush=True)

async def abre(pg, v):                                      # navega como a pessoa: menu principal -> card da aba
    if not await pg.is_visible("#home"): await pg.click("#btnHome"); await pg.wait_for_timeout(300)
    await pg.click(f'[data-go="{v}"]'); await pg.wait_for_timeout(900)

async def entra(b, user):
    pg = await b.new_page(viewport={"width": 1300, "height": 900}); errs = []
    pg.on("pageerror", lambda e: errs.append(str(e)))
    await pg.route("https://**/*", lambda r: r.abort())          # nada sai da máquina durante o teste
    await pg.goto("file://" + PAGE)
    await pg.fill("#u", user); await pg.fill("#p", str(PW[user])); await pg.click("#go"); await pg.wait_for_timeout(7000)
    return pg, errs

async def main():
    async with async_playwright() as p:
        b = await p.chromium.launch()
        # T1 — cada perfil entra, vê as abas certas e nenhuma aba dá erro de JavaScript
        esperado = {"COORDENACAO": {"list", "evo", "va", "ds", "cp", "rt"}, "RODRIGO MORAES": {"list", "evo", "cp"}, "CADASTRO": {"list", "evo"}}
        for u, abas in esperado.items():
            if u not in PW: print("PULADO  T1 " + u + " (sem senha de teste)"); continue
            pg, errs = await entra(b, u)
            tabs = set(await pg.evaluate("[...document.querySelectorAll('.view-tab')].filter(b=>!b.hidden).map(b=>b.dataset.view)"))
            cards = set(await pg.evaluate("[...document.querySelectorAll('#home [data-go]')].map(b=>b.dataset.go)"))
            ok("T10 menu principal com um card por aba · " + u, cards == tabs, sorted(cards))
            for t in tabs: await abre(pg, t)
            await pg.click("#btnHome"); await pg.wait_for_timeout(300)
            ok("T10 botão Menu principal volta para os cards · " + u, await pg.is_visible("#home") and not await pg.is_visible("#listView"))
            ok("T1 abas de " + u, abas <= tabs, sorted(tabs)); ok("T1 sem erro de JavaScript · " + u, not errs, errs[:2]); await pg.close()
        if "COORDENACAO" in PW:
            pg, errs = await entra(b, "COORDENACAO")
            # T2 — cancelados recentes: lista com cards e legenda das 3 cores
            await abre(pg, "evo")
            n = await pg.evaluate("document.querySelectorAll('#cancList .cx').length")
            ok("T2 cancelados recentes listados", n > 0, n)
            ok("T2 legenda das cores dos cancelados", await pg.evaluate("!!document.getElementById('cancLeg') && document.getElementById('cancLeg').innerText.includes('coordenador')"))
            # T3 — comprovantes: seletor de mês com o mês anterior e só as 4 cores previstas
            await abre(pg, "cp")
            meses = await pg.evaluate("[...document.getElementById('cpMes').options].map(o=>o.value)")
            ok("T3 seletor de mês dos comprovantes tem mais de um mês", len(meses) >= 2, meses)
            await pg.select_option("#cpMes", meses[1] if len(meses) > 1 else meses[0]); await pg.wait_for_timeout(2000)
            cls = await pg.evaluate("[...document.querySelectorAll('#cpList tbody tr')].map(t=>t.className)")
            ok("T3 adesões do mês anterior aparecem", len(cls) > 0, len(cls))
            ok("T3 só cores previstas (branco/amarelo/azul/verde)", all(c in ("", "okv", "cpc", "cpe") for c in cls), sorted(set(cls)))
            ok("T3 legenda e regra de valor visíveis", await pg.evaluate("!!document.getElementById('cpLeg') && /vale o valor encontrado no comprovante/.test(document.getElementById('cpRegra').innerText)"))
            # T4 — regra da meta: liberação do rastreador só vale no mês do contrato (bug 31/10)
            r = await pg.evaluate("""(()=>{ const T = window.__teste, CP = T.CP; const bk = CP.marks; CP.marks = {regras: {ZZZ9Z99: {mes: '2026-10', nc: true, obs: 'META TESTE'}}};
                 const a = T.cpMark({m: '2026-10', pl: 'ZZZ9Z99', n: 'Teste'}), b = T.cpMark({m: '2026-11', pl: 'ZZZ9Z99', n: 'Teste'}); CP.marks = bk; return [!!a.nc, !!b.nc]; })()""")
            ok("T4 meta vale no mês do contrato e não em outro mês", r == [True, False], r)
            # T5 — regra de valor: divergência = vale o valor lido no comprovante (01/11)
            r = await pg.evaluate("""(()=>{ const c = window.__teste.cpCalc({m: '2026-10', pl: 'ZZZ9Z99', n: 'Teste', t: 'LUA', cp: {v: 223, vi: 233, vc: false, url: '#'}}); return c.v; })()""")
            ok("T5 valor do comprovante prevalece sobre o informado", r == 223, r)
            # T15 — Região dos Lagos (04/11): rastreador desconta R$ 50 (mesmo na residência); fora dela, residência R$ 100; meta (nc) não desconta
            r = await pg.evaluate("""(()=>{ const f = window.__teste.cpCalc, b = {m: '2026-10', n: 'Teste', t: 'LUA', inst: 'R'};
                 return [f(Object.assign({pl: 'ZZZ1A11', cid: 'Cabo Frio'}, b)).desc, f(Object.assign({pl: 'ZZZ1A12', cid: 'Rio Das Ostras'}, b)).desc, f(Object.assign({pl: 'ZZZ1A13', cid: 'Nova Iguaçu'}, b)).desc]; })()""")
            ok("T15 Região dos Lagos desconta R$ 50 do rastreador", r == [50, 50, 100], r)
            # T6 — chave por chassi quando a adesão não tem placa (bug do Luis Paes, 27/10)
            r = await pg.evaluate("window.__teste.cpKey({pl: '', ch: 'HL5TCAH37S9W51071', n: 'Teste'})")
            ok("T6 adesão sem placa usa o chassi como chave", r == "HL5TCAH37S9W51071", r)
            # T12 — remarketing realizado (01/11): verde-escuro, parabéns e mensagem travada, na lista e nos cancelados
            r = await pg.evaluate("""(()=>{ const c = [...document.querySelectorAll('#cancList .cx.resg')];
                 return [c.length, c.filter(x => x.querySelector('.btn.wa, [data-cx="copy"], [data-cxs]')).length, c.filter(x => /Parabéns/.test(x.innerText)).length]; })()""")
            ok("T12 cancelados resgatados em verde, travados e com parabéns", r[0] > 0 and r[1] == 0 and r[2] == r[0], r)
            await abre(pg, "evo")
            await pg.click('#cancSit [data-cs="resg"]'); await pg.wait_for_timeout(500)
            r = await pg.evaluate("[document.querySelectorAll('#cancList .cx').length, document.querySelectorAll('#cancList .cx:not(.resg)').length]")
            ok("T13 filtro Reativados nos cancelados recentes", r[0] > 0 and r[1] == 0, r)
            await pg.click('#cancSit [data-cs="all"]'); await pg.wait_for_timeout(400)
            await abre(pg, "list")
            r = await pg.evaluate("""(()=>{ const c = [...document.querySelectorAll('#list .card.resg')];
                 return [c.length, c.filter(x => x.querySelector('.btn.wa, [data-act="copy"], [data-act="mark"]')).length, c.filter(x => /Parabéns/.test(x.innerText)).length]; })()""")
            ok("T12 lista do remarketing: resgatados travados (os que aparecem na página atual)", r[1] == 0 and r[2] == r[0], r)
            # T13 — contador e filtro "Reativados" (01/11): card verde-escuro com o total e filtro que mostra só os reativados
            n_ = await pg.evaluate("+document.getElementById('sResg').textContent.replace(/\\D/g,'')")
            bg = await pg.evaluate("getComputedStyle(document.getElementById('stResg')).backgroundColor")
            await pg.click("#stResg"); await pg.wait_for_timeout(600)
            r = await pg.evaluate("[document.querySelectorAll('#list .card').length, document.querySelectorAll('#list .card:not(.resg)').length]")
            ok("T13 contador de reativados verde-escuro e filtro só com reativados", n_ > 0 and bg not in ("rgba(0, 0, 0, 0)", "rgb(255, 255, 255)") and r[0] > 0 and r[1] == 0, [n_, bg, r])
            await pg.click('[data-s="all"]'); await pg.wait_for_timeout(400)
            # T16 — adesões = data de contrato no SGA, sem reativações (05/11): ALL|equipe do mês = adesões da lista; bônus soma as reativações validadas
            r = await pg.evaluate("""(()=>{ const d = window.__teste.E.data, s = d.series['ALL|equipe'], out = [];
                 for (const i of [d.val_ate, d.val_ate + 1]) { const m = d.meses_ad[i]; if (!m) continue; out.push([m, s.ad[i], d.ades.filter(a => a.m === m).length, (s.vb || s.va)[i] - s.va[i] === ((s.rv || [])[i] || 0)]); }
                 return out; })()""")
            ok("T16 adesões do mês sem reativações (bate com a lista do SGA) e bônus com reativações", len(r) > 0 and all(x[1] == x[2] and x[3] for x in r), r)
            # T17 — adesão no nome do líder no SGA e vendida por liderado (afiliado no Power CRM) conta para o liderado (09/11).
            # (No Kit, o teste confere um liderado e duas placas reais; aqui, sem dados pessoais: a regra vale para todas as equipes.)
            r = await pg.evaluate("""(()=>{ const d = window.__teste.E.data, s = d.series, out = [];
                 const mv = d.ades.filter(a => a.esp_sga);
                 for (const t of Object.keys(d.leaders || {})) { const z = s[t + '|propria'], l = s[t + '|liderados'], e = s[t + '|equipe'];
                   if (z && l && e) d.meses_ad.forEach((m, i) => out.push(z.ad[i] + l.ad[i] === e.ad[i])); }
                 return [mv.length, mv.every(a => a.esp !== a.esp_sga), out.every(x => x)]; })()""")
            ok("T17 adesão do liderado cadastrada no nome do líder conta para o liderado (Minha base + Liderados = equipe)", r[1] and r[2], r)
            # T7 — adesões validadas: legenda e linhas azuis
            await abre(pg, "va")
            ok("T7 legenda das adesões validadas", await pg.evaluate("!!document.getElementById('vaLeg')"))
            ok("T2-T7 sem erro de JavaScript · COORDENACAO", not errs, errs[:2]); await pg.close()
        # T8 — vendedora interna: abas próprias e reativação
        if "NALVA MEIRELES" in PW:
            pg, errs = await entra(b, "NALVA MEIRELES")
            tabs = set(await pg.evaluate("[...document.querySelectorAll('.view-tab')].filter(b=>!b.hidden).map(b=>b.dataset.view)"))
            ok("T8 vendedora interna vê validadas e comprovantes", {"va", "cp"} <= tabs, sorted(tabs)); ok("T8 sem erro de JavaScript · vendedora interna", not errs, errs[:2]); await pg.close()
        # T9 — especialista: só os dados dele (login do Gilmar, criado em 27/10)
        if "GILMAR GOMES" in PW:
            pg, errs = await entra(b, "GILMAR GOMES")
            nome = await pg.evaluate("document.getElementById('hName').textContent")
            ok("T9 especialista entra com o próprio nome", "Gilmar" in nome, nome); ok("T9 sem erro de JavaScript · especialista", not errs, errs[:2]); await pg.close()
        # T14 — liderado com o mesmo início de nome (03/11): "Rodrigo Venâncio" entra no painel dele, não no do Rodrigo Moraes Luiz
        if "RODRIGO VENANCIO" in PW:
            pg, errs = await entra(b, "RODRIGO VENANCIO")
            nome = await pg.evaluate("document.getElementById('hName').textContent")
            ok("T14 Rodrigo Venâncio entra com o próprio nome", "Ven" in nome and "Luiz" not in nome, nome); ok("T14 sem erro de JavaScript · Rodrigo Venâncio", not errs, errs[:2]); await pg.close()
        # T18 — painel de cada líder abre sem erro e com dados (09/11: série de liderado sem base[] travou o painel de vários líderes).
        # No Kit, a lista são os logins dos líderes; aqui, todo login do arquivo de senhas que não seja de coordenação, cadastro ou especialista dos testes acima.
        for lu in [u for u in PW if u not in ("COORDENACAO", "CADASTRO", "NALVA MEIRELES", "GILMAR GOMES", "RODRIGO VENANCIO", "RODRIGO MORAES")]:
            pg, errs = await entra(b, lu)
            await abre(pg, "cp")
            n = await pg.evaluate("(()=>{ const d = window.__teste.E.data; return [Object.values(d.series).every(s => Array.isArray(s.base)), d.ades.length]; })()")
            ok("T18 painel do líder abre sem erro e com adesões · " + lu, not errs and n[0] and n[1] > 0, [n, errs[:1]]); await pg.close()
        # T11 — o visual do menu precisa sobreviver à publicação (bug 01/11: CSS ficou no <head> do esqueleto e a publicação apagou)
        if "COORDENACAO" in PW:
            import tempfile, re as _re
            src = open(PAGE, encoding="utf-8").read(); i = src.find("<title>")
            pub = "<!doctype html><html><head><meta charset=utf8><style>body{margin:0}</style></head><body>\n" + src[i:]
            tf = tempfile.NamedTemporaryFile("w", suffix=".html", delete=False, encoding="utf-8"); tf.write(pub); tf.close()
            pg = await b.new_page(viewport={"width": 1300, "height": 900}); errs = []
            pg.on("pageerror", lambda e: errs.append(str(e))); await pg.route("https://**/*", lambda r: r.abort())
            await pg.goto("file://" + tf.name)
            await pg.fill("#u", "COORDENACAO"); await pg.fill("#p", str(PW["COORDENACAO"])); await pg.click("#go"); await pg.wait_for_timeout(7000)
            r = await pg.evaluate("[getComputedStyle(document.querySelector('#home .pcard')).borderTopLeftRadius, getComputedStyle(document.getElementById('views')).display, getComputedStyle(document.getElementById('home')).display]")
            ok("T11 estilo do menu continua depois de publicar (cards arredondados, abas antigas escondidas)", r[0] == "24px" and r[1] == "none" and r[2] == "grid", r)
            await pg.close()
        await b.close()
    falhas = [n for c, n, _ in RES if not c]
    print(json.dumps({"testes": len(RES), "falhas": len(falhas), "quais": falhas}, ensure_ascii=False))
    sys.exit(1 if falhas else 0)
asyncio.run(main())
