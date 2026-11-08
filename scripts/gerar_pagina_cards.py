"""Gera a página dos cards (app/paginas/cards.html, app/static/cards.css, app/static/cards.js) a partir de
referencia/pagina_atual.html, trocando só a entrada (login antigo -> /api/dados) e o banco (claude.use -> /api/banco)."""
import re, sys
RAIZ = sys.argv[1]
L = open(RAIZ + "/referencia/pagina_atual.html", encoding="utf-8").read().split("\n")

def trecho(a, b):  # linhas a..b (1-based, inclusive)
    return "\n".join(L[a - 1:b])

# ---- CSS (bloco <style> da página, linhas 8..377)
assert L[6] == "<style>" and L[377] == "</style>", (L[6], L[377])
css = trecho(8, 377) + """

/* ===== Sistema novo (Render) ===== */
/* regra que ficava no esqueleto da página publicada no Claude: escondido é escondido, mesmo com display definido */
[hidden]:not([hidden=until-found i]) { display: none !important; }
*, *::before, *::after { box-sizing: border-box; }
html, body { margin: 0; }
#carregando { min-height: 60vh; display: grid; place-items: center; color: var(--muted); font-family: var(--body); }
.cover-art { display: none; }
.cover-logo { display: none; }
.aviso-dados { max-width: 1208px; margin: 16px auto 0; padding: 10px 14px; border-radius: 10px; background: #FFF4CC; color: #4A3A00; font-size: 14px; position: relative; z-index: 2; }
@media (max-width: 1240px) { .aviso-dados { margin-left: 16px; margin-right: 16px; } }
a.pcard { text-decoration: none; }
"""
open(RAIZ + "/app/static/cards.css", "w", encoding="utf-8").write(css)

# ---- HTML (marcação 379..706; blocos de dados trocados pelo servidor)
marc = trecho(379, 706)
for a, b in [
    ('<section id="login">', '<section id="login" hidden>'),
    ('<div class="cover-art"><img src="/_blob/f69b7d717b5665e4e297a1cb592eb4cd" alt="Exodus Benefícios — Rumo aos 5.100 associados. Nossa meta, nosso compromisso. 31/12 é todo dia."></div>', '<div class="cover-art"></div>'),
    ('<img class="cover-logo" src="/_blob/2c628580ba72587aab8ad7fb4e3968cf" alt="Exodus Benefícios">', ''),
]:
    assert a in marc, a[:60]
    marc = marc.replace(a, b)
assert "/_blob/" not in marc
html = """<!doctype html>
<html lang="pt-BR">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="robots" content="noindex">
<title>Escritório do Especialista</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Archivo:wdth,wght@75..125,500..800&family=Manrope:wght@400;500;600;700;800&family=Public+Sans:wght@400;500;600;700&display=swap">
<link rel="stylesheet" href="/static/cards.css">
<script src="/static/claude_banco.js"></script>
<script src="/static/cards.js" defer></script>
</head>
<body>
<p id="carregando">Carregando o escritório…</p>
""" + marc + """
<script id="vault" type="application/json">{}</script>
<script id="evo" type="application/json">{}</script>
<script id="rtcfg" type="application/json">__RTCFG__</script>
<script id="motivos" type="application/json">__MOTIVOS__</script>
</body>
</html>
"""
open(RAIZ + "/app/paginas/cards.html", "w", encoding="utf-8").write(html)

# rtcfg padrão (da página atual), usado se a importação não trouxer outro
m = re.search(r'<script id="rtcfg" type="application/json">(.*?)</script>', "\n".join(L), re.S)
open(RAIZ + "/app/paginas/rtcfg_padrao.json", "w", encoding="utf-8").write(m.group(1))

# ---- JS (linhas 712..2299: o conteúdo do <script>)
assert L[710] == "<script>" and L[2299] == "</script>", (L[710], L[2299])
js = trecho(712, 2299)
trocas = [
    # 1) os dados chegam prontos do servidor (no lugar de descriptografar o bloco evo)
    ("""  let EV; try { EV = JSON.parse(document.getElementById('evo').textContent); } catch (e) { return; }
  try {
    if (ring.fin && ring.evk) {""", """  // Sistema novo: o pacote da pessoa vem pronto de /api/dados (ver o fim deste arquivo).
  if (ring.__novo) {
    E.data = ring.__pacote || null;
    if (E.data) {
      if (ring.admin || ring.fin) E.admin = true;
      else if (E.data.esp !== undefined) { E.team = E.data.ld ? E.data.team : ''; E.esp = E.data.esp || ''; if (E.data.ld) E.seg = 'propria'; }
      else E.team = E.data.team;
    }
  } else try {
    let EV; try { EV = JSON.parse(document.getElementById('evo').textContent); } catch (e) { return; }
    if (ring.fin && ring.evk) {"""),
    # 2) sair = sair da conta Google
    ("""$('logout').addEventListener('click', () => { sset('sessionStorage', 'retorno_exodus_sess', null); location.reload(); });""",
     """$('logout').addEventListener('click', () => { location.href = '/auth/sair'; });"""),
    # 3) início: pede os dados ao servidor (login pelo Google) no lugar da sessão antiga
    ("""(async () => {
  const saved = sget('sessionStorage', 'retorno_exodus_sess');
  if (!saved) return;
  try { const ring = JSON.parse(saved); startApp(await openRing(ring), !!ring.admin, ring); } catch (e) { sset('sessionStorage', 'retorno_exodus_sess', null); }
})();""", """// ---------- Sistema novo (Render): login pelo Google e dados de /api/dados ----------
(async () => {
  let d;
  try {
    const r = await fetch('/api/dados', { credentials: 'same-origin' });
    if (r.status === 401) { location.replace('/'); return; }
    d = await r.json();
  } catch (e) { $('carregando').textContent = 'Não foi possível carregar o escritório. Aperte F5 para tentar de novo.'; return; }
  $('carregando').hidden = true;
  PAINEL = !!d.painel;
  const ring = { __novo: true, __pacote: d.pacote, admin: !!d.perfil.admin, fin: !!d.perfil.fin, cad: !!d.perfil.cad, ids: [], keys: [] };
  let specs = d.specs.map(s => ({ nome: s.nome, equipes: s.equipes || [], rows: s.rows || [] }));
  // sem lista do remarketing ainda: a tela de quem não é da coordenação precisa de pelo menos o próprio nome
  if (!specs.length && !d.perfil.admin) specs = [{ nome: d.perfil.nome || '', equipes: d.perfil.equipes || [], rows: [] }];
  startApp(specs, !!d.perfil.admin, ring);
  if (d.perfil.nome) $('hName').textContent = d.perfil.nome;
  if (!d.pacote) {
    const av = document.createElement('p'); av.className = 'aviso-dados';
    av.textContent = d.perfil.admin || d.perfil.fin ? 'Os dados do escritório ainda não foram carregados no sistema novo (Painel do administrador > Atualizações > Dados do sistema atual).' : 'Os seus dados ainda não foram carregados no sistema novo. Fale com a coordenação.';
    document.querySelector('.cover').appendChild(av);
  }
})();"""),
    # 4) card do painel do administrador no menu principal
    ("""function goHome() {""", """let PAINEL = false;
const _renderHomeOriginal = renderHome;
renderHome = function () {
  _renderHomeOriginal();
  if (!PAINEL) return;
  const n = $('home').querySelectorAll('.pcard').length + 1;
  const ic = '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6l8-3Z"/><path d="M9 12l2 2 4-4"/>';
  $('home').insertAdjacentHTML('beforeend', `<a class="pcard" href="/#painel" data-painel="1" style="--g:linear-gradient(135deg,#1a1240 0%,#33228a 55%,#5b4bd6 100%)"><span class="pv"><span class="pn">${String(n).padStart(2, '0')}</span><svg class="pbig" viewBox="0 0 24 24" aria-hidden="true">${ic}</svg></span><span class="pb"><span class="pic" aria-hidden="true"><svg viewBox="0 0 24 24">${ic}</svg></span><h3>Painel do administrador</h3><p>Cadastros, acessos e atualizações das fontes (SGA, Power CRM e BI).</p></span><span class="pf"><span class="pfs">Cadastros e acessos</span><span class="pgo">Abrir${HOME_ARROW}</span></span></a>`);
};
function goHome() {"""),
]
for a, b in trocas:
    assert js.count(a) == 1, ("troca não encontrada uma vez:", a[:80], js.count(a))
    js = js.replace(a, b)
open(RAIZ + "/app/static/cards.js", "w", encoding="utf-8").write(js + "\n")
print("ok", len(css), len(html), len(js))
