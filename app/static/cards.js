(() => {
const V = JSON.parse(document.getElementById('vault').textContent);
const PART = new Set(['de','da','do','dos','das','e','di','du']);
const $ = id => document.getElementById(id);
const te = new TextEncoder();
const b64 = s => Uint8Array.from(atob(s), c => c.charCodeAt(0));
const toB64 = u8 => btoa(String.fromCharCode(...u8));
const brl = v => v == null ? '—' : v.toLocaleString('pt-BR', { style: 'currency', currency: 'BRL' });
const pct = v => v == null ? '—' : (v * 100).toLocaleString('pt-BR', { maximumFractionDigits: 1 }) + '%';
const norm = s => (s || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toLowerCase();
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const sget = (st, k) => { try { return window[st].getItem(k); } catch (e) { return null; } };
const sset = (st, k, v) => { try { v == null ? window[st].removeItem(k) : window[st].setItem(k, v); } catch (e) {} };

function userKey(raw) {
  const w = raw.trim().split(/\s+/).filter(x => x && !PART.has(x.toLowerCase()));
  return w.slice(0, 2).join(' ').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase();
}
async function sha(s) {
  const h = new Uint8Array(await crypto.subtle.digest('SHA-256', te.encode(s)));
  return [...h].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 24);
}
async function aesDec(keyBytes, iv, data) {
  const k = await crypto.subtle.importKey('raw', keyBytes, 'AES-GCM', false, ['decrypt']);
  return new Uint8Array(await crypto.subtle.decrypt({ name: 'AES-GCM', iv }, k, data));
}
async function gunzip(u8) {
  const s = new Blob([u8]).stream().pipeThrough(new DecompressionStream('gzip'));
  return await new Response(s).text();
}
async function unlock(user, pass) {
  const e = V.users[await sha(V.pepper + '|' + user)];
  if (!e) throw new Error('user');
  const base = await crypto.subtle.importKey('raw', te.encode(pass), 'PBKDF2', false, ['deriveBits']);
  const kek = new Uint8Array(await crypto.subtle.deriveBits({ name: 'PBKDF2', hash: 'SHA-256', salt: b64(e.s), iterations: V.iter }, base, 256));
  let ring;
  try { ring = JSON.parse(new TextDecoder().decode(await aesDec(kek, b64(e.iv), b64(e.w)))); }
  catch (x) { throw new Error('pass'); }
  return ring;
}
async function openRing(ring) {
  const out = [];
  for (let i = 0; i < ring.ids.length; i++) {
    const blob = V.specs[ring.ids[i]];
    const plain = await aesDec(b64(ring.keys[i]), b64(blob.iv), b64(blob.c));
    out.push(JSON.parse(await gunzip(plain)));
  }
  return out;
}

/* ---------- state ---------- */
let S = { specs: [], admin: false, label: '', rows: [], type: 'all', sit: 'all', esp: '', eq: '', q: '', shown: 50 };
const SENT = 'retorno_exodus_enviado_';
const sentKey = r => SENT + r.mat + '_' + r.pl;
/* Marcações: nuvem (db do artefato) quando o visitante pode gravar; senão este navegador; e sempre na memória da sessão. */
const MEM = new Map();              // chave -> true/false nesta sessão
const CLOUD = new Map();            // hash do contato -> timestamp (>0 = enviado)
let DB = null, cloudRead = false, cloudWrite = null; // cloudWrite: null = não testado, true/false
const hex = async s => [...new Uint8Array(await crypto.subtle.digest('SHA-256', te.encode(s)))].slice(0, 12).map(b => b.toString(16).padStart(2, '0')).join('');
const isSent = r => {
  const k = sentKey(r);
  if (MEM.has(k)) return MEM.get(k);
  if (r._h && (CLOUD.get(r._h) || 0) > 0) return true;
  return sget('localStorage', k) === '1';
};
const queues = new Map();
function cloudSet(r, on) {
  if (!DB || !r._h || !r._eh || cloudWrite === false) return Promise.resolve(false);
  const ref = DB.collection('enviados').doc(r._eh);
  const prev = queues.get(r._eh) || Promise.resolve();
  const p = prev.then(() => ref.update({ [r._h]: on ? Date.now() : 0 }))
    .catch(() => ref.set(Object.assign(Object.fromEntries(CLOUD_DOCS.get(r._eh) || []), { [r._h]: on ? Date.now() : 0 })))
    .then(() => { cloudWrite = true; return true; }, () => { cloudWrite = false; return false; });
  queues.set(r._eh, p.catch(() => {}));
  return p;
}
const CLOUD_DOCS = new Map();       // hash do especialista -> [[hash, ts], ...]
let _lok = null;
function localOk() {
  if (_lok !== null) return _lok;
  try { const t = '__rx_t'; window.localStorage.setItem(t, '1'); _lok = window.localStorage.getItem(t) === '1'; window.localStorage.removeItem(t); } catch (e) { _lok = false; }
  return _lok;
}
function saveNote() {
  const el = $('saveNote'); if (!el) return;
  if (cloudWrite === true || (cloudRead && cloudWrite === null && DB)) el.textContent = '✓ Marcações de "enviado" salvas na nuvem: aparecem em qualquer aparelho e para a coordenação.';
  else if (cloudRead) el.textContent = 'Você vê as marcações da equipe, mas as suas ficam salvas só neste navegador.';
  else if (localOk()) el.textContent = 'As marcações de "enviado" ficam salvas neste navegador.';
  else el.textContent = 'Atenção: neste navegador as marcações de "enviado" somem ao recarregar a página.';
}
async function setupSync() {
  try {
    const ehs = new Map();
    for (const sp of S.specs) ehs.set(sp.nome, await hex('esp1_' + sp.nome));
    await Promise.all(S.rows.map(async r => { r._h = 'c' + await hex('rx1_' + r.mat + '_' + r.pl); r._eh = ehs.get(r._esp); }));
  } catch (e) { saveNote(); return; }
  try { DB = (window.claude && typeof window.claude.use === 'function') ? await window.claude.use('db') : null; } catch (e) { DB = null; }
  if (!DB) { saveNote(); return; }
  const apply = docs => {
    docs.forEach(d => { const data = d.data() || {}; CLOUD_DOCS.set(d.id, Object.entries(data)); Object.entries(data).forEach(([h, ts]) => CLOUD.set(h, Number(ts) || 0)); });
    cloudRead = true; saveNote();
    const y = window.scrollY; render(); window.scrollTo(0, y);
  };
  const fail = () => { cloudRead = false; saveNote(); };
  try {
    if (S.admin) DB.collection('enviados').limit(1000).onSnapshot(snap => apply(snap.docs), fail);
    else [...new Set(S.rows.map(r => r._eh).filter(Boolean))].slice(0, 20)
      .forEach(eh => DB.collection('enviados').doc(eh).onSnapshot(d => apply([d]), fail));
  } catch (e) { fail(); }
}

function firstName(n) {
  const w = String(n || '').trim().split(/\s+/)[0] || '';
  if (!/[A-Za-zÀ-ÿ]/.test(w)) return '';
  return w.toLocaleLowerCase('pt-BR').replace(/(^|-)(\p{L})/gu, (m, a, b) => a + b.toLocaleUpperCase('pt-BR'));
}
function shortModel(m, moto) {
  let s = String(m || '').trim();
  if (!s) return '';
  if (s.includes('/')) s = s.split('/').pop().trim() || s;
  const t = s.split(/\s+/);
  const out = [t[0]];
  let i = 1;
  if (/^(new|novo|nova|grand)$/i.test(t[0]) && t[1]) out.push(t[i++]);
  if (moto && t[i] && /^\d{2,4}$/.test(t[i])) out.push(t[i]);
  return out.join(' ');
}
function message(r) {
  const mod = shortModel(r.mod, r.moto);
  const ano = String(r.ano || '').split('/').pop().trim();
  const veic = [mod || 'seu veículo', ano].filter(Boolean).join(' ') + (r.pl ? ' – ' + r.pl : '');
  const pn = firstName(r.n);
  const linhas = r.moto
    ? '• *50% OFF* no 1º boleto\n\n• *10% OFF* nos demais'
    : '• *50% OFF* no 1º boleto\n\n• *10% OFF* nos demais (sem adesivo)\n\n• *20% OFF* nos demais (com adesivo)';
  return 'Olá' + (pn ? ', ' + pn : '') + '! Tudo bem?\n\n' +
    'Você já foi associado da Exodus Benefícios com ' + (r.moto ? 'a' : 'o') + ':\n' +
    veic + '\n\n' +
    'Temos uma promoção especial de retorno pra você:\n' + linhas + '\n\n' +
    'Quer garantir essa promoção com esse veículo ou com um novo? *É só digitar SIM aqui!*';
}
const waLink = r => 'https://wa.me/' + r.wa + '?text=' + encodeURIComponent(message(r));

/* ---------- Evolução da base (líderes e coordenação) ---------- */
const EVO_LEAD_IDS = [38, 44, 61, 70, 71, 79, 81];
const MES = ['jan','fev','mar','abr','mai','jun','jul','ago','set','out','nov','dez'];
const mlab = k => MES[+k.slice(5, 7) - 1] + '/' + k.slice(2, 4);
const nf = v => v == null ? '' : v.toLocaleString('pt-BR');
const pf = (v, d = 1) => v == null ? '' : (v * 100).toLocaleString('pt-BR', { minimumFractionDigits: d, maximumFractionDigits: d }) + '%';
const E = { data: null, admin: false, team: '', seg: 'equipe', lid: '', esp: '' };
async function deriveKey(label, parts) {
  const bytes = [te.encode(label), ...parts];
  const len = bytes.reduce((a, b) => a + b.length, 0); const all = new Uint8Array(len); let o = 0;
  bytes.forEach(b => { all.set(b, o); o += b.length; });
  return new Uint8Array(await crypto.subtle.digest('SHA-256', all));
}
async function setupEvo(ring) {
  // Sistema novo: o pacote da pessoa vem pronto de /api/dados (ver o fim deste arquivo).
  if (ring.__novo) {
    E.data = ring.__pacote || null;
    if (E.data) {
      if (ring.admin || ring.fin) E.admin = true;
      else if (E.data.esp !== undefined) { E.team = E.data.ld ? E.data.team : ''; E.esp = E.data.esp || ''; if (E.data.ld) E.seg = 'propria'; }
      else E.team = E.data.team;
    }
  } else try {
    let EV; try { EV = JSON.parse(document.getElementById('evo').textContent); } catch (e) { return; }
    if (ring.fin && ring.evk) {
      E.data = JSON.parse(await gunzip(await aesDec(b64(ring.evk), b64(EV.all.iv), b64(EV.all.c)))); E.admin = true;
    } else if (ring.admin) {
      const parts = EVO_LEAD_IDS.map(id => { const i = ring.ids.indexOf(id); return i < 0 ? null : b64(ring.keys[i]); });
      if (parts.some(p => !p)) return;
      const k = await deriveKey('evo-all|', parts);
      E.data = JSON.parse(await gunzip(await aesDec(k, b64(EV.all.iv), b64(EV.all.c)))); E.admin = true;
    } else {
      for (let i = 0; i < ring.ids.length; i++) {
        const blob = EV.t[ring.ids[i]]; if (!blob) continue;
        const k = await deriveKey('evo1|', [b64(ring.keys[i])]);
        E.data = JSON.parse(await gunzip(await aesDec(k, b64(blob.iv), b64(blob.c)))); E.team = E.data.team; break;
      }
      if (!E.data && EV.e) for (let i = 0; i < ring.ids.length; i++) {   // especialista (não líder): só a base, os cancelados e as adesões dele
        const blob = EV.e[ring.ids[i]]; if (!blob) continue;
        const k = await deriveKey('evo-esp|', [b64(ring.keys[i])]);
        E.data = JSON.parse(await gunzip(await aesDec(k, b64(blob.iv), b64(blob.c)))); E.team = E.data.ld ? E.data.team : ''; E.esp = E.data.esp || ''; if (E.data.ld) E.seg = 'propria'; break;   // vendedoras: abre na carteira (base ativa total do voluntário)
      }
    }
  } catch (e) { E.data = null; }
  if (!E.data) return;
  sepReat(E.data);
  try { if (S.rows && S.rows.length) render(); } catch (e) {}   // contador de reativados usa E.data.resg, que chega depois da lista
  $('views').hidden = false; document.querySelectorAll('.view-tab.lead').forEach(b => b.hidden = false);
  if (E.admin) {
    const t = $('evoTeam'); t.hidden = false;
    t.innerHTML = '<option value="">Todas as equipes</option>' + E.data.teams.map(n => `<option value="${esc(n)}">${esc(E.data.nomes[n] || n)}</option>`).join('');
  }
  evoControls();
  if (RING && RING.cad) {           // cadastro: só Lista do remarketing e Evolução da base (todas as equipes, sem validadas)
    E.cad = true; document.querySelectorAll('[data-view="va"],[data-view="ds"],[data-view="cp"],[data-view="rt"]').forEach(b => b.hidden = true);
    return;
  }
  if (E.esp) {                      // especialista: Lista do remarketing, Evolução da base e Comprovante de adesões
    if (E.data.vi) { setupVA(); setupDS(); setupCP(); return; }   // vendedora interna: tudo dela (validadas, descontos, comprovantes e reativação)
    document.querySelectorAll('[data-view="va"],[data-view="ds"],[data-view="rt"]').forEach(b => b.hidden = true);
    setupCP(); return;
  }
  setupVA();
  setupDS();
  setupCP();
  if (S.fin) { document.querySelectorAll('[data-view="evo"],[data-view="rt"],[data-view="list"]').forEach(b => b.hidden = true); if (!$('home').hidden) renderHome(); }
}
function evoControls() {
  const led = E.team && (E.data.leaders[E.team] || (E.data.cartl || {})[E.team]);   // carteira sem líder (Exodus Benefícios): "Base de" = voluntário da carteira
  $('evoSeg').hidden = !led;
  if (!led) E.seg = 'equipe';
  document.querySelectorAll('#evoSeg [data-g]').forEach(b => b.setAttribute('aria-pressed', b.dataset.g === E.seg));
  const lids = led ? Object.keys(E.data.series).filter(k => k.startsWith(E.team + '|lid:') && !k.endsWith('|lid:SEM ESPECIALISTA'))
    .map(k => ({ k: k.split('|lid:')[1], s: E.data.series[k] }))
    .sort((a, b) => (b.s.base[b.s.base.length - 1] - a.s.base[a.s.base.length - 1]) || a.k.localeCompare(b.k)) : [];
  const ls = $('evoLid'); ls.hidden = !(led && lids.length);
  if (!lids.some(x => x.k === E.lid)) E.lid = '';
  ls.innerHTML = '<option value="">Filtrar por liderado…</option>' + lids.map(x => `<option value="${esc(x.k)}"${x.k === E.lid ? ' selected' : ''}>${esc(nomeCurto(x.k, lids.map(y => y.k)))}</option>`).join('');
  const pr = document.querySelector('#evoSeg [data-g="propria"]');
  if (pr) pr.textContent = E.data.ld ? 'Carteira' : (E.data.cartl || {})[E.team] && !E.data.leaders[E.team] ? 'Base de ' + led : E.admin && led ? 'Base de ' + led.split(' ')[0] : 'Minha base';
}
function cancRows() {
  const all = E.data.canc || [], t = E.team, cv = (E.data.cartv || {})[t];
  if (!t) return all;
  if (E.seg === 'propria') return all.filter(r => r.lt === t || (cv && r.t === t && r.en === cv));
  if (E.seg === 'liderados') return all.filter(r => r.t === t && (E.lid ? r.en === E.lid || r.vi === E.lid : r.lt !== t && r.en !== cv));
  return all.filter(r => r.t === t);
}
function cancCoord(r) { return r.mp != null && r.mp >= 0.7 && r.b != null && r.b < 3; }
function cancMotivo(r) {
  const m = [];
  if (r.mp == null && r.b == null) return ['sem margem e boletos no BI do Brasil Atuarial (confira antes de oferecer)'];
  if (r.mp != null && r.mp < 0.7) m.push('margem abaixo de 70% (está em ' + pf(r.mp, 0) + ')');
  if (r.b == null || r.b < 3) m.push('menos de 3 boletos pagos (' + (r.b == null ? 'sem registro' : r.b === 1 ? 'pagou 1' : 'pagou ' + r.b) + ')');
  return m;
}
/* "mensagem enviada" nos cancelados recentes: fica na nuvem (db comp/cancenv), aparece para todos os acessos */
const CXE = { db: null, map: {}, mem: new Map(), sit: 'all', live: false };
const cxKey = r => 'k' + String(r.mat || '') + '_' + String(r.pl || '').replace(/[^A-Za-z0-9]/g, '');
const cxSent = r => { const k = cxKey(r); if (CXE.mem.has(k)) return CXE.mem.get(k); const v = CXE.map[k]; return !!(v && (v.t || v) > 0); };
async function cxDb() {
  if (CXE.db) return; try { CXE.db = await window.claude.use('db'); } catch (e) { CXE.db = null; return; }
  try { CXE.db.collection('comp').doc('cancenv').onSnapshot(d => { CXE.map = d.exists ? (d.data() || {}) : {}; CXE.live = true; if (!$('evoView').hidden) { const y = window.scrollY; renderCanc(); window.scrollTo(0, y); } }, () => {}); } catch (e) {}
}
function cxSet(r, on) {
  const k = cxKey(r); CXE.mem.set(k, on);
  const v = on ? { t: Date.now(), by: (S.admin ? 'Coordenação' : (S.specs[0] && S.specs[0].nome) || '') } : 0;
  CXE.map[k] = v;
  if (!CXE.db) { toast('Não foi possível salvar na nuvem agora'); return; }
  const ref = CXE.db.collection('comp').doc('cancenv');
  ref.update({ [k]: v }).catch(() => ref.set(Object.assign({}, CXE.map, { [k]: v }))).catch(() => toast('Não foi possível salvar a marcação'));
}
function renderCanc() {
  cxDb();
  const rows = cancRows().slice().sort((a, b) => b.dc.localeCompare(a.dc) || a.n.localeCompare(b.n));
  const mesAt = E.data.meses_base[E.data.meses_base.length - 1], mesAnt = E.data.meses_base[E.data.meses_base.length - 2];
  $('cancSub').textContent = 'Veículos que passaram para cancelado em ' + mlab(mesAnt) + ' e ' + mlab(mesAt) + ' e continuam cancelados. Não entra na promoção: margem abaixo de 70% ou menos de 3 boletos pagos (margem e boletos: BI Brasil Atuarial).';
  const neg = rows.filter(r => cancMotivo(r).length && !cancCoord(r)).length, coord = rows.filter(cancCoord).length;
  const nRs = rows.filter(r => r.rs).length;
  $('cancSum').innerHTML = (nRs ? `<span class="rs">${nf(nRs)} remarketing realizado</span>` : '') + `<span>${nf(rows.length)} cancelados</span><span class="ok">${nf(rows.length - neg - coord)} entram na promoção</span><span class="mid">${nf(coord)} negociar com o coordenador</span><span class="no">${nf(neg)} não entram</span>`;
  const all = rows.length, q = norm($('cancQ').value.trim()), qp = q.replace(/[^a-z0-9]/g, '');
  const nEnv = rows.filter(r => !r.rs && cxSent(r)).length;
  document.querySelectorAll('#cancSit [data-cs]').forEach(b => { b.setAttribute('aria-pressed', b.dataset.cs === CXE.sit); b.textContent = { all: 'Todos', pend: 'Pendentes (' + nf(rows.length - nEnv - nRs) + ')', sent: 'Enviados (' + nf(nEnv) + ')', resg: 'Reativados (' + nf(nRs) + ')' }[b.dataset.cs]; });
  if (CXE.sit !== 'all') rows.splice(0, rows.length, ...rows.filter(r => CXE.sit === 'resg' ? !!r.rs : !r.rs && cxSent(r) === (CXE.sit === 'sent')));
  if (q) rows.splice(0, rows.length, ...rows.filter(r => norm(r.n).includes(q) || (qp && norm(r.pl).replace(/[^a-z0-9]/g, '').includes(qp)) || (qp && String(r.mat || '').includes(qp))));
  $('cancQn').textContent = q ? 'Mostrando ' + nf(rows.length) + ' de ' + nf(all) : '';
  if (!rows.length) { $('cancList').innerHTML = '<p class="empty">' + (q ? 'Nenhum cancelado com essa placa ou nome.' : 'Nenhum cancelado nesse período para esta seleção.') + '</p>'; $('cancList')._rows = []; return; }
  $('cancList').innerHTML = rows.map((r, i) => {
    const why = cancMotivo(r), mid = cancCoord(r), bad = why.length > 0 && !mid, rs = r.rs || null;
    const veh = [r.mod, r.ano, r.pl].filter(Boolean).join(' · ');
    const env = cxSent(r), ev_ = CXE.map[cxKey(r)];
    return `<article class="cx${rs ? ' resg' : bad ? ' no' : mid ? ' mid' : ''}${env && !rs ? ' envc' : ''}" data-i="${i}">
      <div>
        <div class="who-line"><h3>${esc(r.n)}</h3>${r.moto ? '<span class="chip moto">MOTO</span>' : ''}${rs ? '<span class="chip ok">REMARKETING REALIZADO</span>' : bad ? '<span class="chip alert">NÃO ENTRA NA PROMOÇÃO</span>' : mid ? '<span class="chip warnc">NEGOCIAR COM O COORDENADOR</span>' : '<span class="chip ok">ENTRA NA PROMOÇÃO</span>'}</div>
        <p class="veh">${esc(veh)}</p>
        <p class="mot"><b>Motivo do cancelamento:</b> ${esc(r.mot || 'Sem motivo registrado')}${r.obs && norm(r.obs).replace(/[^a-z]/g, '') !== norm(r.mot).replace(/[^a-z]/g, '') ? ` <span>“${esc(r.obs)}”</span>` : ''}</p>
        <div class="meta"><span>Cancelado em ${esc(r.dc.split('-').reverse().join('/'))}</span><span>${esc(r.esp)}</span><span>Equipe ${esc(E.data.nomes[r.t] || r.t || '—')}</span>${r.wa ? `<span>${esc(r.wa.replace(/^55(\d{2})(\d{4,5})(\d{4})$/, '($1) $2-$3'))}</span>` : ''}</div>
      </div>
      <div class="facts">
        <div class="row2">Margem<b>${r.mp == null ? 'sem dado' : pf(r.mp, 0)}</b></div>
        <div class="row2">Boletos pagos<b>${r.b == null ? 'sem dado' : nf(r.b)}</b></div>
        <div class="row2">Matrícula<b>${esc(r.mat)}</b></div>
      </div>
      ${!Array.isArray(r.ov) ? '' : r.ov.length ? `<p class="basebox cont"><b>Continua associado</b> com ${nf(r.ov.length)} ${r.ov.length === 1 ? 'outro veículo ativo' : 'outros veículos ativos'} na base: ${esc(r.ov.join(', '))}</p>`
        : '<p class="basebox saiu"><b>Saiu da base:</b> esse associado cancelou e ficou sem nenhum veículo ativo na Exodus.</p>'}
      ${rs ? rsBox(rs) : mid ? `<p class="why"><svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><path d="M10 2L19 18H1Z" fill="none" stroke="currentColor" stroke-width="2" stroke-linejoin="round"/><path d="M10 8v4M10 14.5v.5" stroke="currentColor" stroke-width="2" stroke-linecap="round"/></svg><span>Não participa da promoção: ${esc(why.join(' e '))}. Porém, pode retornar para a base com condições negociadas com o coordenador.</span></p>`
        : bad ? `<p class="why"><svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true"><circle cx="10" cy="10" r="8.5" fill="none" stroke="currentColor" stroke-width="2"/><path d="M5 15L15 5" stroke="currentColor" stroke-width="2"/></svg><span>Não entra na promoção: ${esc(why.join(' e '))}.</span></p>`
        : `<div class="actions">${r.wa ? `<a class="btn wa" href="${waLink(r)}" target="_blank" rel="noopener">Abrir WhatsApp</a>` : '<span class="btn wa off">Sem celular válido</span>'}<button class="btn" type="button" data-cx="copy">Copiar mensagem</button></div>`}
      ${rs ? '' : `<div class="cxenv"><label class="chk"><input type="checkbox" data-cxs${env ? ' checked' : ''}> Mensagem enviada</label>${env ? `<b>✓ Enviada${ev_ && ev_.t ? ' em ' + new Date(ev_.t).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) + (ev_.by ? ' · ' + esc(ev_.by) : '') : ''}</b>` : '<span class="legend" style="margin:0">Marque depois de chamar no WhatsApp</span>'}</div>`}
    </article>`;
  }).join('');
  $('cancList')._rows = rows;
}
$('list').addEventListener('click', e => { const b = e.target.closest('[data-goc]'); if (!b) return; showView('evo'); $('cancQ').value = b.dataset.goc; renderCanc(); setTimeout(() => $('cancTitle').scrollIntoView({ behavior: 'smooth', block: 'start' }), 60); });
document.querySelectorAll('#cancSit [data-cs]').forEach(b => b.addEventListener('click', () => { CXE.sit = b.dataset.cs; renderCanc(); }));
$('cancList').addEventListener('change', ev => {
  const c = ev.target.closest('[data-cxs]'); if (!c) return;
  const i = +c.closest('.cx').dataset.i, r = ($('cancList')._rows || [])[i]; if (!r) return;
  cxSet(r, c.checked); const y = window.scrollY; renderCanc(); window.scrollTo(0, y);
});
$('cancQ').addEventListener('input', () => { clearTimeout($('cancQ')._t); $('cancQ')._t = setTimeout(renderCanc, 200); });
$('cancList').addEventListener('click', async ev => {
  const b = ev.target.closest('[data-cx="copy"]'); if (!b) return;
  const r = $('cancList')._rows[+b.closest('.cx').dataset.i]; if (!r) return;
  try { await navigator.clipboard.writeText(message(r)); toast('Mensagem copiada'); } catch (e) { toast('Não foi possível copiar neste navegador'); }
});
function nomeCurto(full, all) {
  const cap = w => w.charAt(0) + w.slice(1).toLowerCase();
  const ws = full.split(' ').filter(w => !PART.has(w.toLowerCase()));
  const short = ws.slice(0, 2).map(cap).join(' ');
  const clash = all.filter(o => o !== full && o.split(' ').filter(w => !PART.has(w.toLowerCase())).slice(0, 2).join(' ') === ws.slice(0, 2).join(' ')).length;
  return clash ? full.split(' ').map(w => PART.has(w.toLowerCase()) ? w.toLowerCase() : cap(w)).join(' ') : short;
}
function evoSeries() {
  const key = (E.team || 'ALL') + '|' + (E.seg === 'liderados' && E.lid ? 'lid:' + E.lid : E.seg);
  const s = E.data.series[key] || { base: [], ad: [], va: [] };
  if (E.seg === 'liderados') return s;
  // Evolução da base: só as adesões (ativações do SGA); as reativações contam apenas na aba Adesões validadas
  const ad = s.ad.slice(), va = s.va.slice(), ms = E.data.meses_ad || [];
  ((E.data.pend || {}).rows || []).filter(r => r.tipo === 'reat' && (!E.team || r.t === E.team)).forEach(r => {
    const i = ms.indexOf(r.mes); if (i < 0) return;
    ad[i] = Math.max(0, (ad[i] || 0) - 1);
    if (r.val && i <= E.data.val_ate) va[i] = Math.max(0, (va[i] || 0) - 1);
  });
  return Object.assign({}, s, { ad, va });
}

/* ---------- Menu principal: um card por aba (as abas continuam existindo, escondidas, e decidem quem vê o quê) ---------- */
const HOME_CARDS = {
  list: { t: 'Lista do remarketing', d: 'Ex-associados para chamar no WhatsApp com a mensagem da promoção de retorno já pronta.', g: 'linear-gradient(135deg,#0b1338 0%,#1b2d86 55%,#2f6fd6 100%)', ic: '<path d="M21 11.5a8.4 8.4 0 0 1-12.4 7.4L3 21l2.1-5.4A8.4 8.4 0 1 1 21 11.5Z"/><path d="M8.5 10h7M8.5 13.5h4.5"/>' },
  evo: { t: 'Evolução da base', d: 'Base ativa, adesões e cancelamentos mês a mês, e os cancelados recentes da campanha de resgate.', g: 'linear-gradient(135deg,#0c2f5c 0%,#1f62c4 55%,#46a1ff 100%)', ic: '<path d="M3 17l6-6 4 4 8-8"/><path d="M15 7h6v6"/>' },
  va: { t: 'Adesões validadas', d: 'Adesões com o 1º boleto pago e reativações validadas, com o bônus de cada mês.', g: 'linear-gradient(135deg,#08311f 0%,#0d6a3f 55%,#2fa36b 100%)', ic: '<path d="M20 6L9 17l-5-5"/>' },
  ds: { t: 'Descontos', d: 'Ativações com desconto na mensalidade, comparando o 1º boleto do SGA com a cotação do Power CRM.', g: 'linear-gradient(135deg,#1a2141 0%,#36406a 55%,#5d6a9c 100%)', ic: '<path d="M19 5L5 19"/><circle cx="6.5" cy="6.5" r="2.5"/><circle cx="17.5" cy="17.5" r="2.5"/>' },
  cp: { t: 'Comprovante de adesões', d: 'Anexe o comprovante de cada adesão e acompanhe a conferência do valor e a baixa do financeiro.', g: 'linear-gradient(135deg,#0a2a4a 0%,#145c8f 55%,#22a3c9 100%)', ic: '<path d="M6 2h12v20l-3-2-3 2-3-2-3 2Z"/><path d="M9.5 8h5M9.5 12h5"/>' },
  rt: { t: 'Reativação', d: 'Prints das conversas com associados em atraso para a lista de reativação do mês.', g: 'linear-gradient(135deg,#2a1450 0%,#4b2a96 55%,#7a5be0 100%)', ic: '<path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/>' }
};
const HOME_ARROW = '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M5 12h14M13 6l6 6-6 6"/></svg>';
function homeStatus(v) {
  try {
    if (v === 'list') return nf(S.rows.length) + ' ex-associados na lista';
    if (v === 'evo') return E.data && E.data.canc ? nf(E.data.canc.length) + ' cancelados recentes' : 'Base ativa e cancelados';
    if (v === 'rt') return 'Envio de prints e conferência';
  } catch (e) {}
  return E.data && E.data.atualizado ? 'Atualizado em ' + new Date(E.data.atualizado).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) : 'Abrir';
}
function renderHome() {
  const tabs = [...document.querySelectorAll('.view-tab')].filter(b => !b.hidden && HOME_CARDS[b.dataset.view]);
  $('home').innerHTML = tabs.map((b, i) => { const c = HOME_CARDS[b.dataset.view];
    return `<button type="button" class="pcard" data-go="${b.dataset.view}" style="--g:${c.g}"><span class="pv"><span class="pn">${String(i + 1).padStart(2, '0')}</span><svg class="pbig" viewBox="0 0 24 24" aria-hidden="true">${c.ic}</svg></span><span class="pb"><span class="pic" aria-hidden="true"><svg viewBox="0 0 24 24">${c.ic}</svg></span><h3>${c.t}</h3><p>${c.d}</p></span><span class="pf"><span class="pfs">${esc(homeStatus(b.dataset.view))}</span><span class="pgo">Abrir${HOME_ARROW}</span></span></button>`; }).join('');
}
let PAINEL = false;
const _renderHomeOriginal = renderHome;
renderHome = function () {
  _renderHomeOriginal();
  if (!PAINEL) return;
  const n = $('home').querySelectorAll('.pcard').length + 1;
  const ic = '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6l8-3Z"/><path d="M9 12l2 2 4-4"/>';
  $('home').insertAdjacentHTML('beforeend', `<a class="pcard" href="/#painel" data-painel="1" style="--g:linear-gradient(135deg,#1a1240 0%,#33228a 55%,#5b4bd6 100%)"><span class="pv"><span class="pn">${String(n).padStart(2, '0')}</span><svg class="pbig" viewBox="0 0 24 24" aria-hidden="true">${ic}</svg></span><span class="pb"><span class="pic" aria-hidden="true"><svg viewBox="0 0 24 24">${ic}</svg></span><h3>Painel do administrador</h3><p>Cadastros, acessos e atualizações das fontes (SGA, Power CRM e BI).</p></span><span class="pf"><span class="pfs">Cadastros e acessos</span><span class="pgo">Abrir${HOME_ARROW}</span></span></a>`);
};
function goHome() {
  ['listView', 'evoView', 'vaView', 'dsView', 'cpView', 'rtView'].forEach(id => { $(id).hidden = true; });
  $('app').classList.add('mhome'); $('home').hidden = false; $('btnHome').hidden = true;
  $('coverEyebrow').textContent = 'Menu principal'; $('coverTitle').textContent = 'Escritório do Especialista';
  renderHome(); window.scrollTo(0, 0);
}
$('home').addEventListener('click', e => { const b = e.target.closest('[data-go]'); if (b) showView(b.dataset.go); });
$('btnHome').addEventListener('click', goHome);
new MutationObserver(() => { if (!$('home').hidden) renderHome(); }).observe($('views'), { subtree: true, attributes: true, attributeFilter: ['hidden'] });
function showView(v) {
  $('app').classList.remove('mhome'); $('home').hidden = true; $('btnHome').hidden = false;
  { const c = HOME_CARDS[v]; $('coverEyebrow').textContent = 'Escritório do Especialista'; $('coverTitle').textContent = c ? c.t : 'Escritório do Especialista'; }
  window.scrollTo(0, 0);
  document.querySelectorAll('.view-tab').forEach(b => b.setAttribute('aria-pressed', b.dataset.view === v));
  $('listView').hidden = v !== 'list'; $('evoView').hidden = v !== 'evo'; $('vaView').hidden = v !== 'va'; $('dsView').hidden = v !== 'ds'; $('cpView').hidden = v !== 'cp'; $('rtView').hidden = v !== 'rt';
  if (v === 'evo') renderEvo();
  if (v === 'va') renderVA();
  if (v === 'ds') renderDS();
  if (v === 'rt') renderRT();
  if (v === 'cp') renderCP();
}
const meanOf = a => { const v = a.filter(x => x != null && isFinite(x)); return v.length ? v.reduce((p, c) => p + c, 0) / v.length : null; };
const n1 = v => v.toLocaleString('pt-BR', { maximumFractionDigits: 1 });
function avgBadge(el, ano, items) {          // média do ano em destaque ao lado do título do gráfico
  const card = el.closest('.chart-card'); if (!card) return;
  let b = card.querySelector(':scope > .avgb');
  if (!b) { b = document.createElement('div'); b.className = 'avgb'; card.insertBefore(b, card.firstChild); }
  const ok = items.filter(x => x.v != null && isFinite(x.v));
  b.hidden = !ok.length;
  b.innerHTML = '<small>Média de ' + ano + '</small>' + ok.map(x => `<span>${x.l ? esc(x.l) : ''}<b>${esc(x.f(x.v))}</b></span>`).join('<i>·</i>');
}
function renderEvo() {
  if (!E.data) return;
  const d = E.data, s = evoSeries();
  const teamName = E.esp && !d.ld ? E.esp : E.team ? (d.nomes[E.team] || E.team) : 'Todas as equipes';
  const lider = E.team && (d.leaders[E.team] || (d.cartl || {})[E.team]), cartOnly = !!(E.team && !d.leaders[E.team] && (d.cartl || {})[E.team]);
  const segName = E.seg === 'liderados' && E.lid ? 'liderado ' + nomeCurto(E.lid, []) : { equipe: 'equipe toda', propria: d.ld ? 'carteira' : E.admin ? 'base de ' + (lider || '') : 'minha base', liderados: 'todos os liderados' }[E.seg];
  $('evoTitle').textContent = 'Evolução da base · ' + teamName;
  $('evoSub').textContent = E.esp && !d.ld ? d.rot ? d.rot : (d.cart ? 'Carteira ' + (d.nomes[d.eq] || d.eq) + ': todos os veículos da carteira' : 'Sua base: veículos em que você é o especialista' + (d.eq && d.nomes[d.eq] ? ' · equipe ' + d.nomes[d.eq] : '')) : (lider ? cartOnly ? 'Voluntário da carteira: ' + lider + ' · ' : (d.ld ? lider + ' + liderados da equipe' + (d.ldx ? ' (sem ' + d.ldx + ')' : '') + ' · ' : 'Líder: ' + lider + ' · ') : '') + 'Mostrando: ' + segName +
    (E.seg === 'propria' ? (d.ld || cartOnly ? ' (veículos da carteira)' : ' (veículos em que o líder é o especialista)') : E.seg === 'liderados' && !E.lid ? (d.ld || cartOnly ? ' (equipe sem os veículos da carteira)' : ' (equipe sem os veículos do líder)') : E.lid ? ((d.vin || []).includes(E.lid) ? ' (vendas dela na carteira, cruzando SGA e Power CRM)' : ' (veículos da equipe em que ele é o especialista)') : '');
  const VA = d.val_ate;
  const ad = s.ad.slice(), va = s.va.map((v, i) => i <= VA ? v : null);
  const tx = s.ad.map((v, i) => i <= VA && v ? s.va[i] / v : null);
  const LA = d.meses_ad.map(mlab);
  const ESPV = (!!E.esp && !d.ld) || !!E.cad || E.seg === 'liderados';         // liderados (visão do especialista ou filtro Liderados do líder): sem nada de validadas
  $('chAdT').textContent = ESPV ? 'Adesões por mês' : 'Adesões e adesões validadas por mês';
  $('chAdS').textContent = ESPV ? 'SGA · adesões = ativações do mês' : 'SGA · adesões = ativações do mês · validadas = 1º boleto pago · o mês atual ainda está em validação';
  $('chAdLv').hidden = ESPV; $('cardTx').hidden = ESPV;
  $('chChurnS').textContent = ESPV ? 'Churn = base ativa do mês anterior + adesões do mês − base ativa do mês' : 'Churn = base ativa do mês anterior + adesões validadas do mês − base ativa do mês · meses ainda em validação usam as adesões';
  lineChart($('chAd'), LA, ESPV ? [{ name: 'Adesões', cls: 's1', vals: ad, fmt: nf }] : [{ name: 'Adesões', cls: 's1', vals: ad, fmt: nf }, { name: 'Adesões validadas', cls: 's2', vals: va, fmt: nf }]);
  if (!ESPV) lineChart($('chTx'), LA, [{ name: 'Taxa de validação', cls: 's2', vals: tx, fmt: v => pf(v, 1) }]);
  const mb = d.meses_base, base = s.base;
  const LB = mb.slice(1).map((k, i) => mlab(k) + (i === mb.length - 2 ? '*' : ''));
  lineChart($('chBase'), LB, [{ name: 'Base ativa', cls: 's1', vals: base.slice(1), fmt: nf }]);
  { const vi = d.vi, z = vi && d.series[vi.t + '|equipe'];
    $('cardVi').hidden = $('cardViB').hidden = !z;
    if (z) {
      const i0 = Math.max(0, z.ad.findIndex(v => v > 0)), L2 = d.meses_ad.slice(i0).map(mlab);
      $('viAdT').textContent = 'Suas ativações por mês · ' + vi.nome;
      $('viAdS').textContent = 'SGA × Power CRM · ativações da carteira Exodus Benefícios em que você é a vendedora da cotação · validadas = 1º boleto pago · meta: ' + vi.meta + ' validadas por mês (reativações validadas também contam)';
      lineChart($('viAd'), L2, [{ name: 'Adesões', cls: 's1', vals: z.ad.slice(i0), fmt: nf }, { name: 'Adesões validadas', cls: 's2', vals: z.va.slice(i0).map((v, j) => j + i0 <= d.val_ate ? v : null), fmt: nf }]);
      const bk = z.bk || [], bm = d.meses_base.map((k, j) => ({ k, v: z.base[j] })).filter(o => bk.includes(o.k));
      $('viBS').textContent = 'SGA × Power CRM · veículos ativos da carteira Exodus Benefícios em que a cotação é sua' + (!bm.length ? ' · começa na próxima atualização geral' : bm.length < 2 ? ' · o histórico começa em ' + mlab(bm[0].k) + ' e cresce mês a mês' : '');
      if (bm.length) lineChart($('viB'), bm.map(o => mlab(o.k)), [{ name: 'Sua base', cls: 's1', vals: bm.map(o => o.v), fmt: nf }]); else $('viB').innerHTML = '<p class="empty">Aparece na próxima atualização geral.</p>';
    } }
  const pc = base.slice(1).map((v, i) => base[i] ? (v - base[i]) / base[i] : null);
  barChart($('chPct'), LB, pc, v => (v > 0 ? '+' : '') + pf(v, 2), base.slice(1).map((v, i) => v - base[i]));
  const up = new Date(d.atualizado);
  $('evoNow').textContent = '* ' + mlab(mb[mb.length - 1]) + ' = posição em ' + up.toLocaleDateString('pt-BR');
  const entra = s.ad.map((a, j) => j <= VA && !ESPV ? s.va[j] : a);   // validadas; mês ainda em validação (e visão do especialista) usa adesões
  const churn = entra.map((a, j) => base[j + 1] == null || base[j] == null ? null : base[j] + a - base[j + 1]);
  const txc = churn.map((c, j) => c == null || !base[j + 1] ? null : c / base[j + 1]);
  lineChart($('chChurn'), LA, [{ name: 'Churn', cls: 'down', vals: churn, fmt: nf }]);
  lineChart($('chTxChurn'), LA, [{ name: 'Taxa de churn', cls: 'down', vals: txc, fmt: v => pf(v, 2) }]);
  { /* médias do ano (meses fechados; o mês atual ainda está aberto) */
    const cur = mb[mb.length - 1], ano = cur.slice(0, 4), selA = j => d.meses_ad[j].startsWith(ano) && d.meses_ad[j] !== cur;
    const iA = d.meses_ad.map((k, j) => j).filter(selA), iV = iA.filter(j => j <= VA);
    const sA = iA.reduce((a, j) => a + (s.ad[j] || 0), 0), sAv = iV.reduce((a, j) => a + (s.ad[j] || 0), 0), sV = iV.reduce((a, j) => a + (s.va[j] || 0), 0);
    avgBadge($('chAd'), ano, ESPV ? [{ v: iA.length ? sA / iA.length : null, f: n1 }] : [{ l: 'Adesões', v: iA.length ? sA / iA.length : null, f: n1 }, { l: 'Validadas', v: iV.length ? sV / iV.length : null, f: n1 }]);
    if (!ESPV) avgBadge($('chTx'), ano, [{ v: sAv ? sV / sAv : null, f: v => pf(v, 1) }]);
    const iB = mb.map((k, j) => j).filter(j => j > 0 && mb[j].startsWith(ano) && mb[j] !== cur);
    avgBadge($('chBase'), ano, [{ v: meanOf(iB.map(j => base[j])), f: n1 }]);
    avgBadge($('chPct'), ano, [{ v: meanOf(iB.map(j => pc[j - 1])), f: v => (v > 0 ? '+' : '') + pf(v, 2) }]);
    avgBadge($('chChurn'), ano, [{ v: meanOf(iA.map(j => churn[j])), f: n1 }]);
    avgBadge($('chTxChurn'), ano, [{ v: meanOf(iA.map(j => txc[j])), f: v => pf(v, 2) }]);
    const vi = d.vi, z = vi && d.series[vi.t + '|equipe'];
    if (z) {
      const jA = iA.filter(j => (z.ad[j] || 0) > 0 || d.meses_ad[j] >= (d.meses_ad[Math.max(0, z.ad.findIndex(v => v > 0))] || '')), jV = jA.filter(j => j <= VA);
      avgBadge($('viAd'), ano, [{ l: 'Adesões', v: jA.length ? jA.reduce((a, j) => a + (z.ad[j] || 0), 0) / jA.length : null, f: n1 }, { l: 'Validadas', v: jV.length ? jV.reduce((a, j) => a + (z.va[j] || 0), 0) / jV.length : null, f: n1 }]);
      const bk = z.bk || []; avgBadge($('viB'), ano, [{ v: meanOf(mb.map((k, j) => bk.includes(k) && k.startsWith(ano) ? z.base[j] : null)), f: n1 }]);
    }
  }
  renderCanc();
  document.querySelectorAll('#evoView .chart').forEach(c => { c.scrollLeft = c.scrollWidth; });
  $('evoUpd').textContent = 'Dados atualizados em ' + up.toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) + (ESPV ? '. Base ativa e adesões: direto do SGA.' : '. Base ativa, adesões e adesões validadas: direto do SGA.');
}
const svgNS = 'http://www.w3.org/2000/svg';
function mk(tag, attrs, parent, text) { const e = document.createElementNS(svgNS, tag); for (const k in attrs) e.setAttribute(k, attrs[k]); if (text != null) e.textContent = text; if (parent) parent.appendChild(e); return e; }
function chartBox(el) {
  el.innerHTML = '';
  const W = Math.max(620, el.clientWidth || 620);
  return { W, H: 240, padL: 24, padR: 24, padT: 26, padB: 30, small: false };
}
function tipShow(ev, title, rows) {
  const t = $('tip'); t.innerHTML = '<b>' + esc(title) + '</b>' + rows.map(r => `<div><span><i style="background:var(--${r.cls})"></i>${esc(r.name)}</span><strong>${esc(r.val)}</strong></div>`).join('');
  t.hidden = false;
  const x = Math.min(window.innerWidth - t.offsetWidth - 8, ev.clientX + 14), y = Math.max(8, ev.clientY - t.offsetHeight - 12);
  t.style.left = x + 'px'; t.style.top = y + 'px';
}
function tipHide() { $('tip').hidden = true; }
function lineChart(el, labels, series, opt = {}) {
  const b = chartBox(el), n = labels.length;
  const all = series.flatMap(s => s.vals.filter(v => v != null));
  if (!all.length) { el.innerHTML = '<p class="empty">Sem dados para esta seleção.</p>'; return; }
  let lo = Math.min(...all), hi = Math.max(...all);
  if (opt.zeroBase) lo = 0;
  const span = (hi - lo) || Math.max(1, Math.abs(hi) * .1); lo -= span * .18; hi += span * .22;
  if (opt.zeroBase) lo = Math.max(0, lo);
  const svg = mk('svg', { viewBox: `0 0 ${b.W} ${b.H}`, width: b.W, height: b.H, role: 'img', 'aria-label': series.map(s => s.name).join(' e ') }, el);
  const step = (b.W - b.padL - b.padR) / Math.max(1, n - 1);
  const X = i => b.padL + i * step, Y = v => b.padT + (b.H - b.padT - b.padB) * (1 - (v - lo) / (hi - lo));
  mk('line', { x1: b.padL, x2: b.W - b.padR, y1: b.H - b.padB, y2: b.H - b.padB, stroke: 'var(--grid)', 'stroke-width': 1 }, svg);
  const every = b.small && n > 8 ? 2 : 1;
  labels.forEach((l, i) => { if (i % every === 0 || i === n - 1) mk('text', { x: X(i), y: b.H - 9, 'text-anchor': 'middle', class: 'ax' }, svg, l); });
  series.forEach(s => {
    let d = '', pen = false;
    s.vals.forEach((v, i) => { if (v == null) { pen = false; return; } d += (pen ? 'L' : 'M') + X(i).toFixed(1) + ' ' + Y(v).toFixed(1); pen = true; });
    mk('path', { d, fill: 'none', stroke: `var(--${s.cls})`, 'stroke-width': 2.4, 'stroke-linejoin': 'round', 'stroke-linecap': 'round' }, svg);
  });
  series.forEach((s, si) => s.vals.forEach((v, i) => {
    if (v == null) return;
    mk('circle', { cx: X(i), cy: Y(v), r: 4.5, fill: `var(--${s.cls})`, stroke: 'var(--surface)', 'stroke-width': 2 }, svg);
    if (b.small && n > 8 && i % every && i !== n - 1) return;
    const other = series.find((o, oi) => oi !== si && o.vals[i] != null);
    const below = other ? v < other.vals[i] || (v === other.vals[i] && si > 0) : false;
    mk('text', { x: X(i), y: below ? Y(v) + 18 : Y(v) - 10, 'text-anchor': 'middle', class: 'lbl' }, svg, s.fmt(v));
  }));
  const hit = mk('g', {}, svg);
  labels.forEach((l, i) => {
    const r = mk('rect', { x: X(i) - step / 2, y: 0, width: step, height: b.H, fill: 'transparent' }, hit);
    r.addEventListener('pointermove', ev => tipShow(ev, l, series.map(s => ({ cls: s.cls, name: s.name, val: s.vals[i] == null ? 'em validação' : s.fmt(s.vals[i]) }))));
    r.addEventListener('pointerleave', tipHide);
  });
}
function barChart(el, labels, vals, fmt, deltas, opt = {}) {
  const b = chartBox(el), n = labels.length;
  const ok = vals.filter(v => v != null);
  if (!ok.length) { el.innerHTML = '<p class="empty">Sem dados para esta seleção.</p>'; return; }
  const m = Math.max(...ok.map(Math.abs)) || 1;
  const svg = mk('svg', { viewBox: `0 0 ${b.W} ${b.H}`, width: b.W, height: b.H, role: 'img', 'aria-label': 'Evolução da base em %' }, el);
  const neg = ok.some(v => v < 0), pos = ok.some(v => v > 0);
  const plot = b.H - b.padT - b.padB;
  const zero = neg && pos ? b.padT + plot / 2 : neg ? b.padT + 6 : b.H - b.padB, half = (neg && pos ? plot / 2 : plot) - 22;
  const slot = (b.W - b.padL - b.padR) / n, bw = Math.min(46, slot * .58);
  const X = i => b.padL + slot * i + slot / 2;
  mk('line', { x1: b.padL, x2: b.W - b.padR, y1: zero, y2: zero, stroke: 'var(--muted)', 'stroke-width': 1, opacity: .5 }, svg);
  const every = b.small && n > 8 ? 2 : 1;
  vals.forEach((v, i) => {
    if (i % every === 0 || i === n - 1) mk('text', { x: X(i), y: b.H - 9, 'text-anchor': 'middle', class: 'ax' }, svg, labels[i]);
    if (v == null) return;
    const h = Math.max(2, Math.abs(v) / m * half), up = v >= 0;
    const y = up ? zero - h : zero;
    const r = Math.min(4, h / 2, bw / 2);
    const x0 = X(i) - bw / 2, x1 = X(i) + bw / 2;
    const d = up
      ? `M${x0} ${zero}V${y + r}Q${x0} ${y} ${x0 + r} ${y}H${x1 - r}Q${x1} ${y} ${x1} ${y + r}V${zero}Z`
      : `M${x0} ${zero}V${zero + h - r}Q${x0} ${zero + h} ${x0 + r} ${zero + h}H${x1 - r}Q${x1} ${zero + h} ${x1} ${zero + h - r}V${zero}Z`;
    mk('path', { d, fill: opt.mono ? 'var(--s1)' : up ? 'var(--up)' : 'var(--down)' }, svg);
    if (!(b.small && n > 8 && i % every && i !== n - 1))
      mk('text', { x: X(i), y: up ? y - 6 : zero + h + 14, 'text-anchor': 'middle', class: 'lbl' }, svg, fmt(v));
    const hr = mk('rect', { x: X(i) - slot / 2, y: 0, width: slot, height: b.H, fill: 'transparent' }, svg);
    hr.addEventListener('pointermove', ev => tipShow(ev, labels[i], opt.mono ? [{ cls: 's1', name: opt.name || 'Valor', val: fmt(v) }] : [{ cls: up ? 'up' : 'down', name: 'Variação', val: fmt(v) }, { cls: up ? 'up' : 'down', name: 'Veículos', val: (deltas[i] > 0 ? '+' : '') + nf(deltas[i]) }]));
    hr.addEventListener('pointerleave', tipHide);
  });
}

/* regra do Rafael (05/11): reativação não entra em adesões nem na taxa de validação; só no bônus do líder.
   Os dados trazem ad/va com a soma e rt/rv (reativações e reativações validadas): aqui desconta, e guarda vb = validadas do bônus. */
function sepReat(d) {
  const fix = z => { if (!z || !z.rt || z._sep) return; z.vb = (z.va || []).slice(); z.ad = (z.ad || []).map((v, i) => Math.max(0, v - (z.rt[i] || 0))); z.va = (z.va || []).map((v, i) => Math.max(0, v - (z.rv[i] || 0))); z._sep = true; };
  Object.values(d.series || {}).forEach(fix);
  Object.values(d.vesp || {}).forEach(o => Object.values(o || {}).forEach(fix));
}
/* ---------- Adesões validadas (mesmo painel dos Indicadores Diretoria; líderes e coordenação) ---------- */
const FAIXAS = [[100, 6000], [60, 4000], [30, 2000], [20, 500]];
const VA = { team: '', mes: '' };
function setupVA() {
  const d = E.data;
  if (E.admin) {
    const t = $('vaTeam'); t.hidden = false;
    t.innerHTML = '<option value="">Todas as equipes</option>' + d.teams.map(n => `<option value="${esc(n)}">${esc(d.nomes[n] || n)}</option>`).join('');
  } else VA.team = d.vi ? d.vi.t : E.team;
  const ms = d.meses_ad.slice(0, d.val_ate + 1), msP = d.meses_ad.slice(d.val_ate + 1);   // meses ainda em validação: aparecem como parciais
  const ano = ms.length ? ms[ms.length - 1].slice(0, 4) : '';
  VA.mes = ms.length ? ms[ms.length - 1] : 'ano';
  $('vaMes').innerHTML = msP.slice().reverse().map(k => `<option value="${k}">${mlab(k)} (parcial, em validação)</option>`).join('') + ms.slice().reverse().map(k => `<option value="${k}">${mlab(k)}</option>`).join('') + (ano ? `<option value="ano">Ano de ${ano} (até ${mlab(ms[ms.length - 1])})</option>` : '');
  $('vaMes').value = VA.mes;
}
function vaIdx() {
  const d = E.data, ms = d.meses_ad.slice(0, d.val_ate + 1);
  if (VA.mes !== 'ano') return [d.meses_ad.indexOf(VA.mes)].filter(i => i >= 0);
  const ano = ms.length ? ms[ms.length - 1].slice(0, 4) : '';
  return ms.map((k, i) => k.startsWith(ano) ? i : -1).filter(i => i >= 0);
}
const vsum = (arr, idx) => idx.reduce((a, i) => a + ((arr || [])[i] || 0), 0);
function faixa(v) { const f = FAIXAS.find(([n]) => v >= n); const prox = FAIXAS.slice().reverse().find(([n]) => n > v); return { f, prox }; }
function renderVA() {
  if (!E.data) return;
  const d = E.data, t = VA.team, idx = vaIdx(), per = VA.mes === 'ano' ? 'ano de ' + d.meses_ad[idx[0]].slice(0, 4) + ' (até ' + mlab(d.meses_ad[idx[idx.length - 1]]) + ')' : mlab(VA.mes) + (d.meses_ad.indexOf(VA.mes) > d.val_ate ? ' (parcial)' : '');
  const teamName = t ? (d.nomes[t] || t) : 'Todas as equipes';
  const lider = t && (d.lidb || {})[t];
  $('vaTitle').textContent = 'Adesões validadas · ' + teamName;
  $('vaSub').textContent = (lider ? 'Líder: ' + lider + ' · ' : '') + 'Período: ' + per + (idx.some(i => i > d.val_ate) ? ' · PARCIAL: mês ainda em validação, o 1º boleto de muitas adesões ainda vai vencer, então as validadas vão subir até o fechamento.' : ' · validadas fechadas até ' + mlab(d.meses_ad[d.val_ate]) + '; o mês atual aparece como parcial.');
  { const hj = new Date().toISOString().slice(0, 10), ms_ = idx.map(i => d.meses_ad[i]);
    const av = ((d.pend || {}).rows || []).filter(r => (!t || r.t === t) && ms_.includes((r.dc || '').split('/').reverse().join('-').slice(0, 7)) && /aberto/i.test(r.sb) && r.venc && r.venc.split('/').reverse().join('-') >= hj).length;
    if (av) $('vaSub').textContent += ' Atenção: ' + nf(av) + (av === 1 ? ' adesão do período ainda tem' : ' adesões do período ainda têm') + ' o 1º boleto a vencer, por isso as validadas desse mês ainda vão subir.'; }
  const s = d.series[(t || 'ALL') + '|equipe'] || { ad: [], va: [] };
  const A = vsum(s.ad, idx), Vv = vsum(s.va, idx);
  /* bônus: equipes (sem a Exodus Benefícios) × meses do período */
  const teams = (t ? [t] : d.teams).filter(x => !norm(x).startsWith('exodus') && (d.lidb || {})[x]);
  const bon = [];
  idx.slice().reverse().forEach(i => teams.forEach(x => {
    const z_ = d.series[x + '|equipe'] || {}, v = ((z_.vb || z_.va) || [])[i] || 0; const { f, prox } = faixa(v);   // bônus: validadas + reativações validadas
    const rv = z_.rv ? (z_.rv[i] || 0) : ((d.pend || {}).rows || []).filter(r => r.tipo === 'reat' && r.val && r.t === x && r.mes === d.meses_ad[i]).length;
    bon.push({ m: d.meses_ad[i], t: x, l: d.lidb[x], v, f, prox, rv });
  }));
  bon.sort((a, b) => b.m.localeCompare(a.m) || ((b.f ? b.f[1] : 0) - (a.f ? a.f[1] : 0)) || b.v - a.v);
  const totB = bon.reduce((a, r) => a + (r.f ? r.f[1] : 0), 0), nWin = bon.filter(r => r.f).length;
  let bonStat = t && teams.length ? [VA.mes === 'ano' ? brl(totB) : (bon[0] && bon[0].f ? brl(bon[0].f[1]) : 'Não atingiu'), VA.mes === 'ano' ? 'Bônus do líder no ano' : 'Bônus do líder']
    : t ? ['—', 'Bônus do líder (não se aplica)'] : [nf(nWin) + ' · ' + brl(totB), 'Equipes no bônus'];
  /* vendedora interna: meta própria (validadas + reativações validadas) e bônus = metade dos comprovantes anexados no mês, sem a instalação do rastreador */
  let VB = null;
  if (d.vi) {
    const meta = d.vi.meta || 15;
    VB = idx.slice().reverse().map(i => {
      const m = d.meses_ad[i], val = i <= d.val_ate, v = (s.va || [])[i] || 0;
      const rv = ((d.pend || {}).rows || []).filter(r => r.tipo === 'reat' && r.val && r.t === d.vi.t && r.mes === m).length;
      const L = (d.ades || []).filter(a => a.m === m && a.t === d.vi.t).map(r => cpCalc(r)).filter(c => c.tem);
      const anex = L.reduce((a, c) => a + c.rec, 0), hit = v >= meta;
      return { m, v, rv, val, hit, n: L.length, anex, bon: hit ? Math.max(0, anex) / 2 : 0, falta: Math.max(0, meta - v) };
    });
    const r0 = VB[0], totV = VB.reduce((a, r) => a + r.bon, 0);
    bonStat = VA.mes === 'ano' ? [brl(totV), 'Seu bônus no ano'] : [!r0 ? '—' : r0.hit ? brl(r0.bon) : 'Faltam ' + nf(r0.falta), 'Seu bônus (meta ' + nf(meta) + ' validadas)' + (r0 && !r0.val ? ' · parcial' : '')];
  }
  VA.rep = { arq: 'Adesoes validadas', titulo: 'Adesões validadas', eq: teamName, lider: lider || '', per, upd: d.atualizado, stats: [[nf(A), 'Adesões'], [nf(Vv), 'Adesões validadas'], [A ? pf(Vv / A, 1) : '—', 'Taxa de validação'], bonStat], tabs: [] };
  $('vaStats').innerHTML = [[nf(A), 'Adesões'], [nf(Vv), 'Adesões validadas'], [A ? pf(Vv / A, 1) : '—', 'Taxa de validação'], bonStat]
    .map(([v, l]) => `<div class="stat"><b class="num">${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
  /* barras: por equipe (coordenação, todas) ou por especialista (equipe escolhida) */
  let rows;
  if (!t) rows = d.teams.map(x => { const z = d.series[x + '|equipe'] || {}; return { nm: d.nomes[x] || x, a: vsum(z.ad, idx), v: vsum(z.va, idx) }; });
  else {
    const ve = (d.vesp || {})[t] || {}, names = Object.keys(ve);
    rows = names.map(n => ({ nm: n === 'SEM ESPECIALISTA' ? 'Sem especialista' : nomeCurto(n, names), lead: lider && norm(n).startsWith(norm(lider).split(' ').slice(0, 2).join(' ')), a: vsum(ve[n].ad, idx), v: vsum(ve[n].va, idx) }));
  }
  rows = rows.filter(r => r.a > 0).sort((a, b) => b.a - a.a || b.v - a.v || a.nm.localeCompare(b.nm));
  $('vaBarT').textContent = (t ? 'Adesões por especialista · ' : 'Adesões por equipe · ') + per;
  VA.rep.tabs.push({ t: (t ? 'Adesões por especialista' : 'Adesões por equipe'), head: [t ? 'Especialista' : 'Equipe', 'Adesões', 'Validadas', 'Taxa de validação'], r: [1, 2, 3],
    body: rows.map(r => [r.nm + (r.lead ? ' (líder)' : ''), nf(r.a), nf(r.v), r.a ? pf(r.v / r.a, 0) : '—']), foot: rows.length > 1 ? ['Total', nf(A), nf(Vv), A ? pf(Vv / A, 1) : '—'] : null });
  $('vaBarS').textContent = 'SGA · ativações do mês e 1º boleto pago · ' + (t ? 'especialista da adesão' : 'equipe da adesão');
  const mx = Math.max(1, ...rows.map(r => r.a));
  $('vaBars').innerHTML = rows.length ? rows.map(r => `<div class="hb"><div class="nm">${esc(r.nm)}${r.lead ? '<small>líder</small>' : ''}</div>
      <div class="bars"><div class="bar a"><i style="width:${(r.a / mx * 100).toFixed(1)}%"></i><b>${nf(r.a)}</b></div><div class="bar v"><i style="width:${(r.v / mx * 100).toFixed(1)}%"></i><b>${nf(r.v)}</b></div></div>
      <div class="tx">${r.a ? pf(r.v / r.a, 0) : '—'}<small>validadas</small></div></div>`).join('') : '<p class="empty">Sem adesões nesse período.</p>';
  /* linhas por mês */
  $('vaLineT').textContent = 'Adesões e adesões validadas por mês · ' + teamName;
  const VAt = d.val_ate, LA = d.meses_ad.map(mlab);
  lineChart($('vaAd'), LA, [{ name: 'Adesões', cls: 's1', vals: s.ad.slice(), fmt: nf }, { name: 'Adesões validadas', cls: 's2', vals: s.va.map((v, i) => i <= VAt ? v : null), fmt: nf }]);
  lineChart($('vaTx'), LA, [{ name: 'Taxa de validação', cls: 's2', vals: s.ad.map((v, i) => i <= VAt && v ? s.va[i] / v : null), fmt: v => pf(v, 1) }]);
  document.querySelectorAll('#vaView .chart').forEach(c => { c.scrollLeft = c.scrollWidth; });
  /* tabela do bônus */
  if (bon.length) VA.rep.tabs.push({ t: 'Bônus do líder', nota: 'Faixas: 20 = R$ 500,00 · 30 = R$ 2.000,00 · 60 = R$ 4.000,00 · 100 = R$ 6.000,00 (vale a maior faixa atingida)', head: ['Mês', 'Líder', 'Equipe', 'Validadas', 'Faixa atingida', 'Bônus', 'Para a próxima faixa'], r: [3, 5],
    body: bon.map(r => [mlab(r.m), r.l, d.nomes[r.t] || r.t, nf(r.v) + (r.rv ? ' (' + nf(r.rv) + ' reativ.)' : ''), r.f ? nf(r.f[0]) + ' validadas' : 'não atingiu', r.f ? brl(r.f[1]) : '—', r.prox ? 'faltaram ' + nf(r.prox[0] - r.v) + ' p/ ' + nf(r.prox[0]) + ' (' + brl(r.prox[1]) + ')' : 'faixa máxima']),
    hl: bon.map((r, i) => r.f ? i : -1).filter(i => i >= 0), foot: bon.length > 1 ? ['Total', '', '', '', nf(nWin) + (nWin === 1 ? ' ganhador' : ' ganhadores'), brl(totB), ''] : null });
  $('vaBonT').textContent = 'Bônus do líder · ' + per + (bon.length ? ' (' + nf(nWin) + (nWin === 1 ? ' ganhador · ' : ' ganhadores · ') + brl(totB) + ')' : '');
  $('vaBonus').innerHTML = !bon.length ? '<p class="empty">' + (t ? 'A Exodus Benefícios não entra no bônus do líder.' : 'Sem equipes para o bônus.') + '</p>' :
    `<table class="vtab"><thead><tr><th>Mês</th><th>Líder</th><th>Equipe</th><th>Validadas</th><th>Faixa atingida</th><th>Bônus</th><th>Para a próxima faixa</th></tr></thead><tbody>${bon.map(r => `<tr${r.f ? ' class="win"' : ''}>
      <td class="nw">${mlab(r.m)}</td><td>${esc(r.l)}</td><td>${esc(d.nomes[r.t] || r.t)}</td><td><b>${nf(r.v)}</b>${r.rv ? `<span class="sub">${nf(r.v - r.rv)} de adesão + ${nf(r.rv)} de reativação</span>` : `<span class="sub">${nf(r.v)} de adesão</span>`}</td>
      <td>${r.f ? `<span class="pill ok">${nf(r.f[0])} validadas</span>` : '<span class="pill">não atingiu</span>'}</td>
      <td class="nw"><b>${r.f ? brl(r.f[1]) : '—'}</b></td>
      <td>${r.prox ? 'faltaram ' + nf(r.prox[0] - r.v) + ' p/ ' + nf(r.prox[0]) + ' (' + brl(r.prox[1]) + ')' : 'faixa máxima'}</td></tr>`).join('')}</tbody></table>`;
  if (VB) {
    const meta = d.vi.meta || 15;
    $('vaBonT').textContent = 'Seu bônus · ' + per;
    VA.rep.tabs = VA.rep.tabs.filter(x => x.t !== 'Bônus do líder');
    VA.rep.tabs.push({ t: 'Seu bônus', nota: 'Meta: ' + meta + ' validadas no mês (adesões com o 1º boleto pago + reativações validadas). Batendo a meta, o bônus é a metade da soma dos comprovantes anexados no mês, já descontada a instalação do rastreador.',
      head: ['Mês', 'Validadas', 'Meta', 'Comprovantes anexados (sem instalação)', 'Bônus'], r: [1, 3, 4],
      body: VB.map(r => [mlab(r.m) + (r.val ? '' : ' (parcial)'), nf(r.v), r.hit ? 'bateu' : (r.val ? 'faltaram ' : 'faltam ') + nf(r.falta), nf(r.n) + ' · ' + brl(r.anex), r.hit ? brl(r.bon) : '—']), hl: VB.map((r, i) => r.hit ? i : -1).filter(i => i >= 0) });
    $('vaBonus').innerHTML = !VB.length ? '<p class="empty">Sem meses nesse período.</p>' : `<p class="legend">Meta: ${nf(meta)} validadas no mês (adesões com o 1º boleto pago + reativações validadas). Batendo a meta, o bônus é a metade da soma dos comprovantes anexados no mês, já descontada a instalação do rastreador.</p>
      <table class="vtab"><thead><tr><th>Mês</th><th>Validadas</th><th>Meta de ${nf(meta)}</th><th class="r">Comprovantes anexados (sem instalação)</th><th class="r">Bônus</th></tr></thead><tbody>${VB.map(r => `<tr${r.hit ? ' class="win"' : ''}>
        <td class="nw">${mlab(r.m)}${r.val ? '' : '<span class="sub">parcial, em validação</span>'}</td><td><b>${nf(r.v)}</b><span class="sub">${nf(r.v - r.rv)} de adesão${r.rv ? ' + ' + nf(r.rv) + ' de reativação' : ''}</span></td>
        <td>${r.hit ? '<span class="pill ok">bateu</span>' : '<span class="pill">' + (r.val ? 'faltaram ' : 'faltam ') + nf(r.falta) + '</span>'}</td>
        <td class="r nw">${nf(r.n)} · ${brl(r.anex)}</td><td class="r nw"><b>${r.hit ? brl(r.bon) : '—'}</b></td></tr>`).join('')}</tbody></table>`;
  }
  /* 1º boleto pendente */
  const P = d.pend;
  if (d.ades) vaLista(d, t, idx, per, teamName);
  else if (!P) { $('vaPendT').textContent = 'Adesões com o 1º boleto pendente'; $('vaPendS').textContent = ''; $('vaPend').innerHTML = '<p class="empty">A lista ainda não foi gerada.</p>'; }
  else {
    const mesR = r => r.tipo === 'reat' ? r.mes : (r.dc || '').split('/').reverse().join('-').slice(0, 7);
    const mSel = VA.mes === 'ano' ? null : VA.mes;
    const pr = P.rows.filter(r => (!t || r.t === t) && (!mSel || mesR(r) === mSel)).sort((a, b) => (b.dc || '').split('/').reverse().join('').slice(0, 6).localeCompare((a.dc || '').split('/').reverse().join('').slice(0, 6)) || (a.t || '').localeCompare(b.t || '') || (a.esp || '').localeCompare(b.esp || '') || (a.n || '').localeCompare(b.n || ''));
    const pm = mSel ? mlab(mSel) : (P.meses || [P.mes]).map(mlab).join(' e ');
    const nR = pr.filter(r => r.tipo === 'reat').length;
    $('vaPendT').textContent = 'Adesões de ' + pm + ' com o 1º boleto pendente (' + nf(pr.length - nR) + ')' + (nR ? ' e reativações (' + nf(nR) + ')' : '');
    $('vaPendS').textContent = 'SGA · adesões de ' + pm + ' sem o 1º boleto pago (não contam como validadas) · consultado em ' + new Date(P.at).toLocaleDateString('pt-BR') + (P.fora && !t ? ' · ' + P.fora : '') + (pr.some(r => r.tipo === 'reat') ? ' · reativação (print do líder + lista do financeiro ou SGA): conta como adesão do líder no mês da lista; letras verdes = aguardando o 2º boleto; fundo verde = validada' : '');
    const wa = tel => { const x = String(tel || '').replace(/\D/g, ''); return x.length >= 10 ? `<a href="https://wa.me/55${x}" target="_blank" rel="noopener">${esc(tel)}</a>` : esc(tel || '—'); };
    const cls = v => /aguardando 2/i.test(v) ? 'ok2' : /pago|a vencer/i.test(v) ? (/a vencer/i.test(v) ? '' : 'ok') : /cancel|retirad|vencido/i.test(v) ? 'bad' : 'mid';
    const hojeI = new Date().toISOString().slice(0, 10);
    const sitB = r => r.tipo === 'reat' && !r.val ? 'Aguardando 2º boleto' + (r.venc ? ' · vence ' + r.venc.slice(0, 5) : '') : /^pago/i.test(r.sb) ? r.sb : /aberto/i.test(r.sb) && r.venc ? (r.venc.split('/').reverse().join('-') >= hojeI ? 'Em aberto · a vencer' : 'Em aberto · vencido') : r.sb;
    $('vaPend').innerHTML = !pr.length ? '<p class="empty">Nenhuma adesão de ' + pm + ' com o 1º boleto pendente nesta seleção.</p>' :
      `<table class="vtab"><thead><tr><th>Associado</th><th>Telefone</th><th>Especialista</th>${t ? '' : '<th>Equipe</th>'}<th>Placa</th><th>Contrato</th><th>Vencimento do boleto</th><th>Boleto</th><th>Situação no SGA</th></tr></thead><tbody>${pr.map(r => `<tr${r.tipo === 'reat' ? (r.val ? ' class="reat"' : ' class="reat aguard"') : ''}>
        <td>${r.tipo === 'reat' ? '<span class="pill rt">REATIVAÇÃO' + (r.teste ? ' · TESTE' : '') + '</span><br>' : ''}${esc(r.n)}</td><td class="nw">${wa(r.tel)}</td><td>${esc(r.esp)}</td>${t ? '' : `<td>${esc(d.nomes[r.t] || r.t)}</td>`}<td class="nw">${esc(r.pl)}</td><td class="nw">${r.tipo === 'reat' ? 'Reativação ' + mlab(r.mes) : esc(r.dc)}</td><td class="nw">${esc(r.venc)}</td>
        <td><span class="pill ${cls(sitB(r))}">${esc(sitB(r))}</span></td><td><span class="pill ${cls(r.ss)}">${esc(r.ss)}</span></td></tr>`).join('')}</tbody></table>`;
  }
  $('vaUpd').textContent = 'Dados atualizados em ' + new Date(d.atualizado).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) + '. Adesões, validadas e lista do 1º boleto: direto do SGA.';
}
$('vaTeam').addEventListener('change', e => { VA.team = e.target.value; renderVA(); });
$('vaMes').addEventListener('change', e => { VA.mes = e.target.value; renderVA(); });

/* ---------- Descontos (mesmo card Descontos do Comercial nos Indicadores Diretoria; líderes e coordenação) ---------- */
const DS = { team: '', mes: '', pl: 'all' };
const plNome = { all: '', P: ' · plantão', F: ' · fora do plantão' };
function setupDS() {
  const d = E.data, D = d.desc;
  if (!D) { document.querySelector('[data-view="ds"]').hidden = true; return; }
  if (E.admin) {
    const t = $('dsTeam'); t.hidden = false;
    t.innerHTML = '<option value="">Todas as equipes</option>' + d.teams.map(n => `<option value="${esc(n)}">${esc(d.nomes[n] || n)}</option>`).join('');
  } else DS.team = d.vi ? d.vi.t : E.team;
  const ms = Object.keys(D.d).sort(); const ano = ms.length ? ms[ms.length - 1].slice(0, 4) : '';
  DS.mes = ms.length ? ms[ms.length - 1] : 'ano';
  $('dsMes').innerHTML = ms.slice().reverse().map(k => `<option value="${k}">${mlab(k)}${dsParcial(k) ? ' (parcial)' : ''}</option>`).join('') + (ano ? `<option value="ano">Ano de ${ano}</option>` : '');
  $('dsMes').value = DS.mes;
}
function dsParcial(k) { const a = (E.data.desc || {}).ate || ''; const iso = /^\d{2}\/\d{2}\/\d{4}$/.test(a) ? a.split('/').reverse().join('-') : a; return iso.slice(0, 7) === k; }
function dsMeses() {
  const ms = Object.keys(E.data.desc.d).sort();
  if (DS.mes !== 'ano') return [DS.mes];
  const ano = ms[ms.length - 1].slice(0, 4); return ms.filter(k => k.startsWith(ano));
}
function dsAgg(teams, meses) {
  const o = { n: 0, P: 0, F: 0, O: 0 };
  meses.forEach(m => teams.forEach(t => { const v = ((E.data.desc.d[m] || {})[t]); if (!v) return; o.n += v[0]; o.P += v[1]; o.F += v[2]; o.O += v[3]; }));
  o.dsc = DS.pl === 'all' ? o.P + o.F + o.O : o[DS.pl];
  return o;
}
function dsTeams() {
  const D = E.data.desc; if (DS.team) return [DS.team];
  const s = new Set(); Object.values(D.d).forEach(o => Object.keys(o).forEach(t => s.add(t))); return [...s];
}
function recorrente(t, m) {
  const D = E.data.desc, v = (D.d[m] || {})[t] || [0, 0, 0, 0], n = v[0], f = v[2];
  const p = n ? Math.round(f / n * 10000) / 10000 : 0;
  const tk = (D.tk[m] || {})[t]; const tm = tk && tk[1] ? tk[0] / tk[1] : null;
  let val, obs = '';
  if (p > 0.30) val = 16; else if (p >= 0.20) val = 16.5; else if (p >= 0.10) val = 17;
  else { const vOk = n >= 15, tOk = tm != null && tm >= 225; if (vOk && tOk) val = 18; else { val = 17; obs = tm == null ? 'ticket médio não disponível p/ conferir os R$ 18,00' : [!vOk ? 'menos de 15 vendas' : '', !tOk ? 'ticket médio abaixo de R$ 225,00' : ''].filter(Boolean).join(' e ') + ' (sem os R$ 18,00)'; } }
  return { m, t, n, f, p, tm, val, obs };
}
function renderDS() {
  if (!E.data || !E.data.desc) return;
  const d = E.data, D = d.desc, t = DS.team, meses = dsMeses();
  const per = DS.mes === 'ano' ? 'ano de ' + meses[0].slice(0, 4) : mlab(DS.mes) + (dsParcial(DS.mes) ? ' (parcial)' : '');
  const teamName = t ? (d.nomes[t] || t) : 'Todas as equipes', lider = t && (d.lidb || {})[t];
  document.querySelectorAll('#dsPl [data-pl]').forEach(b => b.setAttribute('aria-pressed', b.dataset.pl === DS.pl));
  $('dsTitle').textContent = 'Descontos · ' + teamName;
  $('dsSub').textContent = (lider ? 'Líder: ' + lider + ' · ' : '') + 'Período: ' + per + ' · base = adesões realizadas (vendas ativadas no mês); o filtro de plantão muda só as adesões com desconto.';
  const teams = dsTeams(), A = dsAgg(teams, meses), pt = plNome[DS.pl];
  DS.rep = { arq: 'Descontos', titulo: 'Descontos', eq: teamName, lider: lider || '', per: per + (DS.pl === 'all' ? '' : ' · filtro: ' + plNome[DS.pl].replace(' · ', '')), upd: d.atualizado, tabs: [],
    stats: [[nf(A.n), 'Adesões realizadas'], [nf(A.dsc), 'Com desconto' + pt], [A.n ? pf(A.dsc / A.n, 1) : '—', '% com desconto' + pt], DS.pl === 'all' ? [nf(A.F) + ' · ' + (A.n ? pf(A.F / A.n, 1) : '—'), 'Fora do plantão'] : [nf(A.P + A.F + A.O), 'Com desconto (todos)']] };
  $('dsStats').innerHTML = [[nf(A.n), 'Adesões realizadas'], [nf(A.dsc), 'Com desconto' + pt], [A.n ? pf(A.dsc / A.n, 1) : '—', '% com desconto' + pt],
    DS.pl === 'all' ? [nf(A.F) + ' · ' + (A.n ? pf(A.F / A.n, 1) : '—'), 'Fora do plantão'] : [nf(A.P + A.F + A.O), 'Com desconto (todos)']]
    .map(([v, l]) => `<div class="stat"><b class="num">${esc(v)}</b><span>${esc(l)}</span></div>`).join('');
  /* barras: por equipe (coordenação) ou por plantão (equipe escolhida / líder) */
  let rows, leg;
  if (!t) {
    rows = teams.map(x => { const o = dsAgg([x], meses); return { nm: d.nomes[x] || (x === 'INSIDE SALES' ? 'Inside Sales' : x), a: o.n, b: o.dsc }; }).filter(r => r.a > 0).sort((x, y) => y.a - x.a || y.b - x.b);
    $('dsBarT').textContent = 'Adesões e descontos por equipe · ' + per + pt;
    leg = '<span><i class="sw s1"></i>Adesões realizadas</span><span><i class="sw s3"></i>Com desconto' + esc(pt) + '</span><span>% = com desconto ÷ adesões</span>';
  } else {
    rows = [['Plantão', A.P], ['Fora do plantão', A.F], ['Sem informação', A.O]].filter(([, v]) => v > 0 || A.n).map(([nm, v]) => ({ nm, a: null, b: v, base: A.n }));
    $('dsBarT').textContent = 'Descontos por plantão · ' + per;
    leg = '<span><i class="sw s3"></i>Adesões com desconto</span><span>% = ÷ adesões realizadas da equipe (' + nf(A.n) + ')</span>';
  }
  $('dsBarL').innerHTML = leg;
  DS.rep.tabs.push(!t ? { t: 'Adesões e descontos por equipe' + pt, head: ['Equipe', 'Adesões realizadas', 'Com desconto' + pt, '% com desconto'], r: [1, 2, 3], body: rows.map(r => [r.nm, nf(r.a), nf(r.b), r.a ? pf(r.b / r.a, 0) : '—']), foot: rows.length > 1 ? ['Total', nf(A.n), nf(A.dsc), A.n ? pf(A.dsc / A.n, 1) : '—'] : null }
    : { t: 'Descontos por plantão', head: ['Plantão', 'Adesões com desconto', '% das adesões realizadas (' + nf(A.n) + ')'], r: [1, 2], body: rows.map(r => [r.nm, nf(r.b), r.base ? pf(r.b / r.base, 0) : '—']) });
  $('dsBarS').textContent = 'BD_COTAÇÕES até ' + mlab(String(D.desde).slice(0, 7).replace(/(\d{4})-(\d{2})/, (m_, y, mo) => mo === '01' ? (y - 1) + '-12' : y + '-' + String(mo - 1).padStart(2, '0'))) + ' + Power CRM/SGA desde ' + mlab(D.desde) + ' · com desconto na mensalidade';
  const mx = Math.max(1, ...rows.map(r => r.a == null ? (r.base || r.b) : r.a));
  $('dsBars').innerHTML = rows.length ? rows.map(r => `<div class="hb"><div class="nm">${esc(r.nm)}</div><div class="bars">
      ${r.a != null ? `<div class="bar a"><i style="width:${(r.a / mx * 100).toFixed(1)}%"></i><b>${nf(r.a)}</b></div>` : ''}
      <div class="bar d"><i style="width:${(r.b / mx * 100).toFixed(1)}%"></i><b>${nf(r.b)}</b></div></div>
      <div class="tx d">${(r.a != null ? r.a : r.base) ? pf(r.b / (r.a != null ? r.a : r.base), 0) : '—'}<small>${r.a != null ? 'c/ desconto' : 'das adesões'}</small></div></div>`).join('') : '<p class="empty">Sem adesões nesse período.</p>';
  /* linhas por mês (ano todo) */
  const ms = Object.keys(D.d).sort(), LA = ms.map(k => mlab(k) + (dsParcial(k) ? '*' : ''));
  const serie = ms.map(m => dsAgg(teams, [m]));
  $('dsLineT').textContent = 'Adesões realizadas e adesões com desconto por mês · ' + teamName + pt;
  lineChart($('dsAd'), LA, [{ name: 'Adesões realizadas', cls: 's1', vals: serie.map(o => o.n), fmt: nf }, { name: 'Com desconto', cls: 's3', vals: serie.map(o => o.dsc), fmt: nf }]);
  $('dsTxT').textContent = '% de adesões com desconto por mês · ' + teamName + pt;
  lineChart($('dsTx'), LA, [{ name: '% com desconto', cls: 's3', vals: serie.map(o => o.n ? o.dsc / o.n : null), fmt: v => pf(v, 1) }]);
  document.querySelectorAll('#dsView .chart').forEach(c => { c.scrollLeft = c.scrollWidth; });
  /* recorrente do líder */
  const elig = teams.filter(x => (d.lidb || {})[x] && !norm(x).startsWith('exodus'));
  let rec = [];
  if (DS.mes === 'ano' && !t) $('dsRec').innerHTML = '<p class="empty">Escolha um mês no filtro para ver o recorrente de cada líder.</p>';
  else {
    meses.slice().reverse().forEach(m => elig.forEach(x => { const r = recorrente(x, m); if (r.n) rec.push(r); }));
    rec.sort((a, b) => b.m.localeCompare(a.m) || b.val - a.val || a.p - b.p);
    $('dsRec').innerHTML = !rec.length ? '<p class="empty">' + (t && !elig.length ? 'A Exodus Benefícios não entra no recorrente do líder.' : 'Sem adesões no período.') + '</p>' :
      `<table class="vtab"><thead><tr><th>Mês</th><th>Líder</th><th>Equipe</th><th>Adesões</th><th>Descontos fora do plantão</th><th>% fora do plantão</th><th>Ticket médio</th><th>Recorrente</th><th>Observação</th></tr></thead><tbody>${rec.map(r => `<tr${r.val > 16 ? ' class="esp"' : ''}>
        <td class="nw">${mlab(r.m)}${dsParcial(r.m) ? '*' : ''}</td><td>${esc(d.lidb[r.t])}</td><td>${esc(d.nomes[r.t] || r.t)}</td><td>${nf(r.n)}</td><td>${nf(r.f)}</td><td><b>${pf(r.p, 1)}</b></td>
        <td class="nw">${r.tm != null ? brl(r.tm) : '—'}</td><td class="nw">${r.val > 16 ? `<span class="pill ok">${brl(r.val)}</span>` : `<b>${brl(r.val)}</b>`}</td><td>${esc(r.obs)}</td></tr>`).join('')}</tbody></table>`;
  }
  if (rec.length) DS.rep.tabs.push({ t: 'Recorrente do líder', nota: 'Taxa = descontos fora do plantão ÷ adesões realizadas · acima de 30% = R$ 16,00 · 20% a 30% = R$ 16,50 · 10% a 20% = R$ 17,00 · abaixo de 10% = R$ 18,00 (mínimo de 15 vendas e ticket médio de R$ 225,00; senão R$ 17,00)', head: ['Mês', 'Líder', 'Equipe', 'Adesões', 'Desc. fora do plantão', '% fora do plantão', 'Ticket médio', 'Recorrente', 'Observação'], r: [3, 4, 5, 6, 7],
    body: rec.map(r => [mlab(r.m) + (dsParcial(r.m) ? '*' : ''), d.lidb[r.t], d.nomes[r.t] || r.t, nf(r.n), nf(r.f), pf(r.p, 1), r.tm != null ? brl(r.tm) : '—', brl(r.val), r.obs || '']), hl: rec.map((r, i) => r.val > 16 ? i : -1).filter(i => i >= 0) });
  const esp = rec.filter(r => r.val > 16).length;
  $('dsRecT').textContent = 'Recorrente do líder · ' + per + (rec.length ? ' (' + nf(esp) + (esp === 1 ? ' especial, acima de R$ 16,00)' : ' especiais, acima de R$ 16,00)') : '');
  dsLista();
  $('dsUpd').textContent = 'Dados atualizados em ' + new Date(d.atualizado).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) + ' · ativações do SGA × cotações do Power CRM até ' + (D.ate || '—') + ' (até ago/26: planilha BD_COTAÇÕES). * mês em andamento.';
}
$('dsTeam').addEventListener('change', e => { DS.team = e.target.value; renderDS(); });
$('dsMes').addEventListener('change', e => { DS.mes = e.target.value; renderDS(); });
document.querySelectorAll('#dsPl [data-pl]').forEach(b => b.addEventListener('click', () => { DS.pl = b.dataset.pl; renderDS(); }));

/* ---------- Reativação: prints dos especialistas (assets + db reativ/<id do usuário>) ---------- */
let RTCFG = { meses: [] };
try { RTCFG = JSON.parse(document.getElementById('rtcfg').textContent); } catch (e) {}
const RT = { db: null, assets: null, uid: null, mine: null, all: {}, files: [], ready: false, err: '' };
const rtEspNome = () => S.admin ? ($('rtEsp').value || '') : (S.specs[0] ? S.specs[0].nome : '');
function rtEncerrado(k) { const p = (RTCFG.prazos || {})[k]; return !!p && Date.now() > new Date(p).getTime(); }
function rtPrazo(k) { const p = (RTCFG.prazos || {})[k]; return p ? new Date(p).toLocaleString('pt-BR', { timeZone: 'America/Sao_Paulo', day: '2-digit', month: '2-digit', hour: '2-digit', minute: '2-digit' }).replace(',', ' às') : ''; }
async function setupRT() {
  const ms = []; { const d0 = new Date(); let y = d0.getFullYear(), m = d0.getMonth() + 1; while (y > 2026 || (y === 2026 && m >= 8)) { const k = y + '-' + String(m).padStart(2, '0'); ms.push(k); m--; if (m < 1) { m = 12; y--; } } }   // de ago/26 até o mês atual (as listas continuam aparecendo; só o envio de prints fecha no prazo)
  $('rtMes').innerHTML = ms.length ? ms.map(k => `<option value="${k}">${mlab(k)}${rtPrazo(k) ? (rtEncerrado(k) ? ' · envio encerrado em ' : ' · envio até ') + rtPrazo(k) : ''}</option>`).join('') : '<option value="">Nenhuma lista cadastrada</option>';
  { const ab = ms.find(k => !rtEncerrado(k)); if (ab) $('rtMes').value = ab; }
  const fech = Object.keys(RTCFG.prazos || {}).filter(rtEncerrado).sort();
  $('rtMsg').dataset.fech = fech.length ? 'Envio encerrado: ' + fech.map(k => mlab(k) + ' (prazo ' + rtPrazo(k) + ')').join(' · ') + '.' : '';
  if (S.admin) {
    $('rtEspL').hidden = false;
    $('rtEsp').innerHTML = '<option value="">Escolha o especialista…</option>' + S.specs.map(sp => sp.nome).sort().map(n => `<option>${esc(n)}</option>`).join('');
  }
  renderRT();
  try { RT.db = await window.claude.use('db'); } catch (e) { RT.db = null; }
  try { RT.assets = await window.claude.use('assets'); } catch (e) { RT.assets = null; }
  try { const u = await window.claude.use('user'); RT.uid = u ? await u.id() : null; RT.canW = u ? await u.can('data.write') : null; } catch (e) { RT.uid = null; }
  RT.ready = true;
  if (RT.db) {
    try {
      if (S.admin) RT.db.collection('reativ').onSnapshot(snap => { RT.all = {}; snap.docs.forEach(d => { RT.all[d.id] = d.data() || {}; }); renderRT(); }, () => renderRT());
      if (RT.uid) RT.db.collection('reativ').doc(RT.uid).onSnapshot(d => { RT.mine = d.exists ? (d.data() || {}) : {}; renderRT(); }, () => renderRT());
    } catch (e) {}
  }
  renderRT();
}
function rtItems() {
  if (S.admin) return Object.values(RT.all).flatMap(d => Object.values(d.p || {}));
  return Object.values((RT.mine || {}).p || {});
}
async function rtGasLink() {
  const box = $('rtGasBox'); if (!RTCFG.gas || !RING) { box.hidden = true; return; }
  const nome = rtEspNome(); const i = S.specs.findIndex(sp => sp.nome === nome);
  if (i < 0 || !RING.keys[i]) { box.hidden = !S.admin; $('rtGas').removeAttribute('href'); return; }
  const kb = b64(RING.keys[i]), pre = te.encode('rt-tok|'), all = new Uint8Array(pre.length + kb.length); all.set(pre); all.set(kb, pre.length);
  const tok = [...new Uint8Array(await crypto.subtle.digest('SHA-256', all))].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 16);
  if (!$('rtMes').value || rtEncerrado($('rtMes').value)) { box.hidden = true; return; }
  $('rtGas').href = RTCFG.gas + '?k=' + tok + '&m=' + encodeURIComponent($('rtMes').value || ''); box.hidden = false;
}
function renderRT() {
  rtGasLink();
  if ($('rtView').hidden && RT.ready) return;
  const can = !!(RT.assets && RT.db && RT.uid);
  const fechado = rtEncerrado($('rtMes').value);
  $('rtGo').disabled = !can || !RT.files.length || !$('rtMes').value || fechado;
  $('rtFile').disabled = !can || fechado;
  if (fechado) $('rtMsg').textContent = 'O envio de prints da lista de ' + mlab($('rtMes').value) + ' foi encerrado em ' + rtPrazo($('rtMes').value) + '. A lista e os prints já enviados continuam aqui para consulta.';
  else if (!RT.ready) $('rtMsg').textContent = 'Carregando…';
  else if (!can && RTCFG.gas) $('rtMsg').textContent = 'Use o botão abaixo para enviar os prints (não precisa de login no claude.ai).';
  else if (!can) $('rtMsg').textContent = !RT.uid ? 'Não dá para enviar: você não está logado no claude.ai. Entre com a sua conta da Exodus (a do convite) e abra este link de novo.' : 'Não dá para enviar: a sua conta do claude.ai ainda não tem permissão de colaborador neste sistema. Peça à coordenação para liberar o seu e-mail.' + (RT.canW === false ? ' (permissão atual: só visualização)' : '');
  else if (!RT.files.length && !RT.err) $('rtMsg').textContent = '';
  let it = rtItems().sort((a, b) => (b.at || 0) - (a.at || 0));
  $('rtFilt').hidden = !S.admin;
  if (S.admin) {
    const esps = [...new Set(it.map(x => x.esp).filter(Boolean))].sort(), mss = [...new Set(it.map(x => x.mes).filter(Boolean))].sort().reverse();
    const nk = x => String(x || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/\s+/g, ' ').trim();
    let fe = $('rtFEsp').value; const fm = $('rtFMes').value;
    if (!fe && $('rtEsp').value) fe = esps.find(n => nk(n) === nk($('rtEsp').value)) || '';
    $('rtFEsp').innerHTML = '<option value="">Todos os líderes</option>' + esps.map(n => `<option value="${esc(n)}"${n === fe ? ' selected' : ''}>${esc(n)} (${nf(it.filter(x => x.esp === n && (!fm || x.mes === fm)).length)})</option>`).join('');
    $('rtFMes').innerHTML = '<option value="">Todas as listas</option>' + mss.map(k => `<option value="${k}"${k === fm ? ' selected' : ''}>${mlab(k)}</option>`).join('');
    it = it.filter(x => (!fe || nk(x.esp) === nk(fe)) && (!fm || x.mes === fm));
  }
  $('rtListT').textContent = (S.admin ? 'Prints enviados pelos especialistas' : 'Seus prints enviados') + ' (' + nf(it.length) + ')';
  $('rtListS').textContent = 'A conferência (nome do associado × lista de reativação × boleto do mês seguinte) é feita na atualização pela coordenação.';
  const st = x => x.res ? x.res : 'Em análise';
  $('rtList').innerHTML = it.length ? it.map(x => `<div class="rt-item">${x.rm ? `<div class="rt-rm">Imagem apagada em ${esc(new Date(x.rm).toLocaleDateString('pt-BR'))} (prints com mais de 5 meses). O registro continua valendo.</div>` : `<a href="${esc(x.url || ('/_blob/' + x.id))}" target="_blank" rel="noopener"><img src="${esc(x.url || ('/_blob/' + x.id))}" alt="Print enviado" loading="lazy"></a>`}
      <div class="rt-cap"><b>${esc(st(x))}</b>${x.assoc ? `<span>Associado: ${esc(x.assoc)}</span>` : ''}${S.admin ? `<span>${esc(x.esp || '')}</span>` : ''}<span>Lista de ${x.mes ? mlab(x.mes) : '—'} · enviado ${new Date(x.at || 0).toLocaleDateString('pt-BR')}</span></div></div>`).join('')
    : '<p class="empty">Nenhum print enviado ainda.</p>';
}
async function rtShrink(file) {
  try {
    const bmp = await createImageBitmap(file); const k = Math.min(1, 1600 / Math.max(bmp.width, bmp.height));
    const c = document.createElement('canvas'); c.width = Math.round(bmp.width * k); c.height = Math.round(bmp.height * k);
    c.getContext('2d').drawImage(bmp, 0, 0, c.width, c.height);
    return await new Promise(r => c.toBlob(b => r(b || file), 'image/jpeg', 0.85));
  } catch (e) { return file; }
}
$('rtFile').addEventListener('change', e => {
  RT.files = [...e.target.files].filter(f => /^image\//.test(f.type)).slice(0, 20); RT.err = '';
  $('rtPrev').innerHTML = RT.files.map(f => `<img alt="" src="${URL.createObjectURL(f)}">`).join('');
  $('rtMsg').textContent = RT.files.length ? RT.files.length + (RT.files.length === 1 ? ' print selecionado.' : ' prints selecionados.') : '';
  renderRT();
});
$('rtGo').addEventListener('click', async () => {
  const esp = rtEspNome(), mes = $('rtMes').value;
  if (!esp) { $('rtMsg').textContent = 'Escolha o especialista.'; return; }
  if (!RT.files.length || !mes) return;
  if (rtEncerrado(mes)) { $('rtMsg').textContent = 'O envio de prints da lista de ' + mlab(mes) + ' foi encerrado em ' + rtPrazo(mes) + '.'; return; }
  $('rtGo').disabled = true; let ok = 0; RT.err = '';
  const ref = RT.db.collection('reativ').doc(RT.uid);
  for (const f of RT.files) {
    $('rtMsg').textContent = 'Enviando ' + (ok + 1) + ' de ' + RT.files.length + '…';
    try {
      const a = await RT.assets.upload(await rtShrink(f));
      const key = 'p' + Date.now().toString(36) + Math.random().toString(36).slice(2, 6);
      const item = { id: a.id, url: a.url, esp, mes, at: Date.now() };
      try { await ref.update({ p: { [key]: item } }); }
      catch (e) { const cur = (await ref.get()); const body = cur.exists ? (cur.data() || {}) : {}; body.p = Object.assign({}, body.p || {}, { [key]: item }); await ref.set(body); }
      ok++;
    } catch (e) { RT.err = 'Não foi possível enviar ' + (f.name || 'um print') + ' (' + (e && (e.code || e.message) || 'erro') + ').'; break; }
  }
  RT.files = []; $('rtFile').value = ''; $('rtPrev').innerHTML = '';
  $('rtMsg').textContent = (ok ? ok + (ok === 1 ? ' print enviado.' : ' prints enviados.') : '') + (RT.err ? ' ' + RT.err : '');
  renderRT(); toast(ok ? 'Prints enviados' : 'Envio não concluído');
});
['rtFEsp', 'rtFMes', 'rtMes'].forEach(id => $(id).addEventListener('change', renderRT));
$('rtEsp').addEventListener('change', () => { $('rtFEsp').value = ''; renderRT(); });   // escolher o líder no envio também filtra a lista de prints

/* ---------- listas completas de adesões (Adesões validadas e Descontos) ---------- */
VA.g = { cf: {}, sort: { c: '', d: 1 } }; DS.g = { cf: {}, sort: { c: '', d: 1 } };
const brD = v => v == null || v === '' ? '—' : brl(v);
const dnumBR = x => { const m = String(x || '').match(/(\d{2})\/(\d{2})\/(\d{4})/); return m ? +(m[3] + m[2] + m[1]) : 0; };
/* filtro e classificação por coluna (genérico): col = { id, h, v: valor mostrado/filtrado, s: chave de ordenação, ty: 'txt' p/ busca, r: alinhado à direita } */
function gridPrep(G, cols, items) {
  Object.keys(G.cf).forEach(k => { if (!cols.some(c => c.id === k) || !G.cf[k]) delete G.cf[k]; });
  if (G.sort.c && !cols.some(c => c.id === G.sort.c)) G.sort = { c: '', d: 1 };
  const passa = (x, skip) => cols.every(col => { const f = G.cf[col.id]; if (!f || col.id === skip) return true; const v = col.v(x); return col.ty === 'txt' ? norm(v).includes(norm(f)) : v === f; });
  const cmp = (A, B) => typeof A === 'number' && typeof B === 'number' ? A - B : String(A).localeCompare(String(B), 'pt-BR');
  let L = items.filter(x => passa(x));
  const sc = cols.find(c => c.id === G.sort.c);
  if (sc) { const key = sc.s || sc.v, vazio = x => x == null || x === '' || x === '—'; L = L.slice().sort((a, b) => { const A = key(a), B = key(b), na = vazio(A), nb = vazio(B); return na || nb ? (na === nb ? 0 : na ? 1 : -1) : cmp(A, B) * G.sort.d; }); }   // vazios sempre no fim
  const th = col => {
    const ar = G.sort.c === col.id ? (G.sort.d > 0 ? '▲' : '▼') : '↕';
    let f;
    if (col.ty === 'txt') f = `<input class="thf" data-gft="${col.id}" value="${esc(G.cf[col.id] || '')}" placeholder="Filtrar…" aria-label="Filtrar ${esc(col.h)}">`;
    else {
      const ct = {}, sk = {}; items.filter(x => passa(x, col.id)).forEach(x => { const v = col.v(x); ct[v] = (ct[v] || 0) + 1; if (!(v in sk)) sk[v] = col.s ? col.s(x) : v; });
      const ks = Object.keys(ct).sort((a, b) => cmp(sk[a], sk[b]));
      if (G.cf[col.id] && !ks.includes(G.cf[col.id])) ks.unshift(G.cf[col.id]);
      f = `<select class="thf" data-gfs="${col.id}" aria-label="Filtrar ${esc(col.h)}"><option value="">Todos</option>${ks.map(k => `<option value="${esc(k)}"${G.cf[col.id] === k ? ' selected' : ''}>${esc(k)} (${nf(ct[k] || 0)})</option>`).join('')}</select>`;
    }
    return `<th class="${col.r ? 'r ' : ''}${G.cf[col.id] ? 'fon' : ''}"><button type="button" class="ths" data-gsort="${col.id}" title="Classificar">${esc(col.h)} <i>${ar}</i></button>${f}</th>`;
  };
  return { L, thead: cols.map(th).join(''), nF: Object.keys(G.cf).length, n: items.length };
}
function gridBar(barId, G, g, nome) {
  const b = $(barId); if (!b) return;
  b.querySelector('span').textContent = g.nF ? 'Mostrando ' + nf(g.L.length) + ' de ' + nf(g.n) + ' ' + nome + ' · ' + g.nF + (g.nF > 1 ? ' filtros ativos' : ' filtro ativo') : 'Clique no nome da coluna para classificar · use o campo abaixo do nome para filtrar';
  b.querySelector('button').hidden = !g.nF && !G.sort.c;
}
function gridWire(el, barId, G, rerender) {
  el.addEventListener('change', e => { const s_ = e.target.closest('select[data-gfs]'); if (s_) { G.cf[s_.dataset.gfs] = s_.value; rerender(); } });
  el.addEventListener('input', e => {
    const t = e.target.closest('input[data-gft]'); if (!t) return;
    const id = t.dataset.gft, pos = t.selectionStart; G.cf[id] = t.value;
    clearTimeout(G._t); G._t = setTimeout(() => { rerender(); const n = el.querySelector(`input[data-gft="${id}"]`); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (er) {} } }, 250);
  });
  el.addEventListener('click', e => { const b = e.target.closest('button[data-gsort]'); if (!b) return; const c = b.dataset.gsort; G.sort = G.sort.c !== c ? { c, d: 1 } : G.sort.d > 0 ? { c, d: -1 } : { c: '', d: 1 }; rerender(); });
  $(barId).querySelector('button').addEventListener('click', () => { G.cf = {}; G.sort = { c: '', d: 1 }; rerender(); });
}
function vaPill(r) {
  const hj = new Date().toISOString().slice(0, 10), b = r.bol || '';
  if (r.ok) return ['ok', b || 'Validada'];
  if (r.reat) return ['ok2', 'Aguardando 2º boleto' + (r.venc ? ' · vence ' + r.venc.slice(0, 5) : '')];
  if (/valida/i.test(b)) return ['', 'Em validação'];
  if (/aberto/i.test(b) && r.venc) return r.venc.split('/').reverse().join('-') >= hj ? ['', 'Em aberto · a vencer'] : ['bad', 'Em aberto · vencido'];
  if (/cancel|não emit|sem boleto|nova adesão/i.test(b)) return ['bad', b];
  return ['mid', b || '—'];
}
function vaLista(d, t, idx, per, teamName) {
  const ms = idx.map(i => d.meses_ad[i]), todos = VA.mes === 'ano';
  const reat = ((d.pend || {}).rows || []).filter(r => r.tipo === 'reat').map(r => ({ m: r.mes, n: r.n, tel: r.tel, esp: r.esp, t: r.t, pl: r.pl, dc: 'Reativação ' + mlab(r.mes), ok: !!r.val, bol: r.sb, venc: r.venc, ss: r.ss, reat: true, teste: r.teste }));
  let rows = d.ades.concat(reat).filter(r => (!t || r.t === t) && ms.includes(r.m));
  rows.sort((a, b) => b.m.localeCompare(a.m) || (a.t || '').localeCompare(b.t || '') || (a.esp || '').localeCompare(b.esp || '') || (a.n || '').localeCompare(b.n || ''));
  const nReat = rows.filter(r => r.reat).length;
  $('vaFilt').innerHTML = ''; $('vaFilt').hidden = true;
  const bolCat = r => r.ok ? 'Pagou (validada)' : r.reat ? 'Aguardando 2º boleto' : vaPill(r)[1].replace(/ · vence .*/, '');
  const cols = [
    todos && { id: 'm', h: 'Mês', v: r => mlab(r.m), s: r => r.m },
    { id: 'tp', h: 'Tipo', v: r => r.reat ? 'Reativação' : 'Adesão' },
    { id: 'n', h: 'Associado', ty: 'txt', v: r => r.n || '' },
    { id: 'tel', h: 'Telefone', ty: 'txt', v: r => r.tel || '' },
    { id: 'esp', h: 'Especialista', v: r => r.esp || '—' },
    !t && { id: 't', h: 'Equipe', v: r => d.nomes[r.t] || r.t || '—' },
    { id: 'pl', h: 'Placa', ty: 'txt', v: r => r.pl || '' },
    { id: 'dc', h: 'Contrato', v: r => r.dc || '—', s: r => dnumBR(r.dc) || (r.reat ? +(r.m.replace('-', '') + '00') : null) },
    { id: 'venc', h: 'Venc. do boleto', v: r => r.venc || '—', s: r => dnumBR(r.venc) || null },
    { id: 'bol', h: '1º boleto', v: bolCat },
    { id: 'ss', h: 'Situação no SGA', v: r => r.ss || '—' }
  ].filter(Boolean);
  const g = gridPrep(VA.g, cols, rows);
  gridBar('vaFbar', VA.g, g, 'adesões');
  $('vaPendT').textContent = 'Adesões ' + (t ? 'da equipe ' + teamName : 'de todas as equipes') + ' · ' + per + ' (' + nf(rows.length) + ')';
  $('vaPendS').textContent = 'SGA · ativações do mês com a situação do 1º boleto · fundo azul = adesão validada (1º boleto pago) · nomes e telefones da cotação no Power CRM' + (nReat ? ' · reativação (print do líder + lista do financeiro ou SGA): fundo verde-escuro = validada (pagou o boleto seguinte); letras verdes = reativou e aguarda o 2º boleto' : '') + (ms.some(m => !(d.ades || []).some(a => a.m === m)) ? ' · a lista completa começa em ' + mlab(d.ades.reduce((a, r) => r.m < a ? r.m : a, '9999')) : '');
  const wa = tel => { const x = String(tel || '').replace(/\D/g, ''); return x.length >= 10 ? `<a href="https://wa.me/55${x}" target="_blank" rel="noopener">${esc(tel)}</a>` : esc(tel || '—'); };
  $('vaPend').innerHTML = !rows.length ? '<p class="empty">Nenhuma adesão nesta seleção.</p>' :
    `<table class="vtab gr"><thead><tr>${g.thead}</tr></thead><tbody>${!g.L.length ? `<tr><td colspan="${cols.length}" class="empty">Nenhuma adesão com esses filtros.</td></tr>` : ''}${g.L.map(r => { const [c, tx] = vaPill(r); return `<tr${r.reat ? (r.ok ? ' class="reat"' : ' class="reat aguard"') : r.ok ? ' class="vok"' : ''}>
      ${todos ? `<td class="nw">${mlab(r.m)}</td>` : ''}<td class="nw">${r.reat ? '<span class="pill rt">REATIVAÇÃO' + (r.teste ? ' · TESTE' : '') + '</span>' : 'Adesão'}</td><td>${esc(r.n || '—')}</td><td class="nw">${wa(r.tel)}</td><td>${esc(r.esp)}</td>${t ? '' : `<td>${esc(d.nomes[r.t] || r.t)}</td>`}
      <td class="nw">${esc(r.pl || '—')}</td><td class="nw">${esc(r.dc)}</td><td class="nw">${esc(r.venc || '—')}</td><td><span class="pill ${c}">${esc(tx)}</span></td><td>${esc(r.ss || '')}</td></tr>`; }).join('')}</tbody></table>`;
}
function dsLista() {
  const d = E.data, t = DS.team, meses = dsMeses(), todos = DS.mes === 'ano';
  const per = todos ? 'ano de ' + meses[0].slice(0, 4) : mlab(DS.mes);
  let rows = (d.ades || []).filter(r => (!t || r.t === t) && meses.includes(r.m));
  rows.sort((a, b) => b.m.localeCompare(a.m) || (b.dv || 0) - (a.dv || 0) || (a.esp || '').localeCompare(b.esp || '') || (a.n || '').localeCompare(b.n || ''));
  $('dsFilt').innerHTML = ''; $('dsFilt').hidden = true;
  const cols = [
    todos && { id: 'm', h: 'Mês', v: r => mlab(r.m), s: r => r.m },
    { id: 'n', h: 'Associado', ty: 'txt', v: r => r.n || '' },
    { id: 'esp', h: 'Especialista', v: r => r.esp || '—' },
    !t && { id: 't', h: 'Equipe', v: r => d.nomes[r.t] || r.t || '—' },
    { id: 'pl', h: 'Placa', ty: 'txt', v: r => r.pl || '' },
    { id: 'dc', h: 'Ativação', v: r => r.dc || '—', s: r => dnumBR(r.dc) || null },
    { id: 'cota', h: 'Mensalidade', v: r => r.cot ? brD(r.cota) : 'Sem cotação', s: r => r.cot && r.cota != null ? +r.cota : null },
    { id: 'dv', h: 'Desconto', v: r => r.dv > 0 ? 'Com desconto' : 'Sem desconto', s: r => r.dv > 0 ? +r.dv : 0 },
    { id: 'pt', h: 'Plantão', v: r => r.dv > 0 ? (r.pt === 'P' ? 'Plantão' : 'Fora do plantão') : '—' }
  ].filter(Boolean);
  const g = gridPrep(DS.g, cols, rows);
  gridBar('dsFbar', DS.g, g, 'adesões');
  $('dsListT').textContent = 'Adesões ' + (t ? 'da equipe ' + (d.nomes[t] || t) : 'de todas as equipes') + ' e descontos · ' + per + ' (' + nf(rows.length) + ')';
  $('dsListS').textContent = 'Ativações do SGA × cotação do Power CRM (data de migração mais próxima) · desconto = campo de desconto na mensalidade ou % escrito na observação' + (d.ades && d.ades.length ? ' · lista disponível de ' + mlab(d.ades.reduce((a, r) => r.m < a ? r.m : a, '9999')) + ' em diante' : '');
  $('dsList').innerHTML = !rows.length ? '<p class="empty">' + (d.ades ? 'Nenhuma adesão nesta seleção.' : 'A lista aparece na próxima atualização.') + '</p>' :
    `<table class="vtab gr"><thead><tr>${g.thead}</tr></thead><tbody>${!g.L.length ? `<tr><td colspan="${cols.length}" class="empty">Nenhuma adesão com esses filtros.</td></tr>` : ''}${g.L.map(r => `<tr>
      ${todos ? `<td class="nw">${mlab(r.m)}</td>` : ''}<td>${esc(r.n || '—')}</td><td>${esc(r.esp)}</td>${t ? '' : `<td>${esc(d.nomes[r.t] || r.t)}</td>`}<td class="nw">${esc(r.pl || '—')}</td><td class="nw">${esc(r.dc)}</td>
      <td class="nw">${r.cot ? brD(r.cota) : '<span class="sub">sem cotação</span>'}</td><td class="nw">${r.dv > 0 ? `<span class="pill bad">${brl(r.dv)}</span>` + (r.cota ? `<span class="sub">${pf(r.dv / r.cota, 0)} da mensalidade</span>` : '') : '—'}</td>
      <td class="nw">${r.dv > 0 ? (r.pt === 'P' ? 'Plantão' : 'Fora do plantão') : '—'}</td></tr>`).join('')}</tbody></table>`;
}
gridWire($('vaPend'), 'vaFbar', VA.g, () => renderVA());
gridWire($('dsList'), 'dsFbar', DS.g, () => renderDS());
document.querySelectorAll('.view-tab').forEach(b => b.addEventListener('click', () => showView(b.dataset.view)));
document.querySelectorAll('#evoSeg [data-g]').forEach(b => b.addEventListener('click', () => { E.seg = b.dataset.g; E.lid = ''; evoControls(); renderEvo(); }));
$('evoLid').addEventListener('change', e => { E.lid = e.target.value; if (E.lid) E.seg = 'liderados'; evoControls(); renderEvo(); });
$('evoTeam').addEventListener('change', e => { E.team = e.target.value; E.seg = 'equipe'; E.lid = ''; evoControls(); renderEvo(); });
let _rz; window.addEventListener('resize', () => { clearTimeout(_rz); _rz = setTimeout(() => { if (!$('evoView').hidden) renderEvo(); if (!$('vaView').hidden) renderVA(); if (!$('dsView').hidden) renderDS(); }, 150); });

/* motivo do cancelamento (SGA) — mapa público por hash de matrícula+placa, só categorias */
let MOTV = null;
try { MOTV = JSON.parse(document.getElementById('motivos').textContent); } catch (e) { MOTV = null; }
async function setupMotivos(rows) {
  if (!MOTV) return;
  await Promise.all(rows.map(async r => {
    const h = [...new Uint8Array(await crypto.subtle.digest('SHA-256', te.encode(MOTV.p + '|' + r.mat + '|' + String(r.pl || '').toUpperCase())))].slice(0, 8).map(b => b.toString(16).padStart(2, '0')).join('');
    const i = MOTV.k[h]; r._mot = i == null ? '' : MOTV.l[i];
  }));
}
const motivoDe = r => r._mot || (MOTV ? 'Sem motivo registrado no SGA' : '—');
/* ---------- Comprovante de adesões (a partir de out/26) ---------- */
const CP = { team: '', esp: '', mes: '', f: 'all', marks: {}, db: null, live: false, role: '', sel: new Set(), vis: [], cf: {}, sort: { c: '', d: 1 } };
const pnum = x => { let t = String(x == null ? '' : x).replace(/[^\d,.-]/g, ''); if (!t) return null; if (t.includes(',')) t = t.replace(/\./g, '').replace(',', '.'); const n = Math.round(parseFloat(t) * 100) / 100; return isFinite(n) ? n : null; };
const nfm = v => v == null ? '' : v.toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const CP_DESDE = '2026-10';
const INST_TXT = { B: 'Base', R: 'Residência' }, INST_VAL = { B: 50, R: 100 };
const LAGOS_VAL = 50, LAGOS = new Set(['RIO DAS OSTRAS', 'CABO FRIO', 'MACAE', 'ARARUAMA', 'SAO PEDRO DA ALDEIA', 'MARICA', 'SAQUAREMA', 'CASIMIRO DE ABREU', 'ARRAIAL DO CABO', 'ARMACAO DOS BUZIOS', 'BUZIOS', 'IGUABA GRANDE', 'SILVA JARDIM', 'CAMPOS DOS GOYTACAZES', 'CAMPOS']);   // lista do Rafael (04/11)   // regra do Rafael (04/11): associado da Região dos Lagos desconta R$ 50 do rastreador
const isLagos = r => LAGOS.has(String(r.cid || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/\s+/g, ' ').trim());
const TEAM_LEAD_ID = { 'RECREIO': 79, 'LUA': 70, 'ELITE': 81, 'ÁGUIAS': 44, 'PÉ NO CHÃO': 61, 'TUBARÕES': 71, 'MAGNATAS': 38, 'ELIM': 95 };
const cpKey = r => r.pl || r.ch || ('SP' + String(r.n || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/[^A-Z]/g, '').slice(0, 10) + String(r.dc || '').replace(/\D/g, '').slice(0, 4));   // sem placa: chassi; sem chassi: nome + data
const CP_SEM_DESC = new Set(['EXODUS BENEFÍCIOS']);   // Inside Sales: entra na lista, mas a instalação ainda não gera desconto
const TOK = {};
async function tokOf(keyB64) {
  if (TOK[keyB64]) return TOK[keyB64];
  const kb = b64(keyB64), pre = te.encode('rt-tok|'), all = new Uint8Array(pre.length + kb.length); all.set(pre); all.set(kb, pre.length);
  return TOK[keyB64] = [...new Uint8Array(await crypto.subtle.digest('SHA-256', all))].map(x => x.toString(16).padStart(2, '0')).join('').slice(0, 16);
}
function cpKeyFor(team) {          // chave do líder da equipe (a coordenação tem as chaves dos líderes; o líder usa a dele)
  if (!RING || !RING.keys || !RING.keys.length) return null;
  const id = TEAM_LEAD_ID[team], i = id == null ? -1 : RING.ids.indexOf(id);
  return RING.keys[i >= 0 ? i : 0];
}
function cpMark(r) {
  const RG = CP.marks.regras || {}, nmk = 'NOME:' + String(r.n || '').normalize('NFD').replace(/[\u0300-\u036f]/g, '').toUpperCase().replace(/\s+/g, ' ').trim();
  let rg = RG[cpKey(r)] || (!r.pl ? RG[nmk] : null) || {};   // lista do coordenador por placa (ou nome, quando não tem placa): instalação não cobrada
  if (rg.mes && rg.mes !== r.m) rg = {};                   // regra só vale para a ativação do mês indicado
  const live = Object.assign({}, rg.nc != null ? { nc: rg.nc, obs: rg.obs } : {}, (CP.marks[r.m] || {})[cpKey(r)] || {});
  return Object.assign({}, r.mk || {}, live || {});
}
function cpCalc(r) {
  const mk = cpMark(r), inst = r.inst || '', isen = CP_SEM_DESC.has(r.t), nc = !!mk.nc || isen;
  const lagos = isLagos(r), desc = inst && !nc ? (lagos ? LAGOS_VAL : INST_VAL[inst]) : 0;
  const vc = r.cp && r.cp.v != null && r.cp.v !== '' ? +r.cp.v : null;   // valor informado no comprovante
  const pg = mk.pg != null && mk.pg !== '' ? +mk.pg : null;                // valor lançado como pago pelo financeiro/coordenação
  const v = pg != null ? pg : vc;
  return { mk, inst, nc, isen, lagos, desc, v, vc, pg, rec: (v || 0) - desc, ok: !!mk.ok, tem: !!r.cp || pg != null, comp: !!r.cp };
}
if (location.protocol === 'file:') window.__teste = { cpMark: r => cpMark(r), cpCalc: r => cpCalc(r), cpKey: r => cpKey(r), get CP() { return CP; }, get E() { return E; } };   // só nos testes de regressão (arquivo local); no link publicado não existe
function setupCP() {
  const d = E.data, ms = (d.meses_ad || []).filter(k => k >= CP_DESDE);
  const tab = document.querySelector('[data-view="cp"]');
  if (!ms.length || (!E.esp && !(d.ades || []).some(a => a.m >= CP_DESDE))) { tab.hidden = true; return; }
  tab.hidden = false;
  CP.role = S.fin ? 'fin' : E.admin ? 'coord' : E.esp ? 'esp' : 'lider';
  $('cpEsp').hidden = !!E.esp;
  if (E.admin) {
    const t = $('cpTeam'); t.hidden = false;
    t.innerHTML = '<option value="">Todas as equipes</option>' + d.teams.map(n => `<option value="${esc(n)}">${esc(d.nomes[n] || n)}</option>`).join('');
  } else CP.team = d.vi ? d.vi.t : E.team;
  CP.mes = ms[ms.length - 1];
  $('cpMes').innerHTML = ms.slice().reverse().map(k => `<option value="${k}">${mlab(k)}</option>`).join('');
  $('cpMes').value = CP.mes;
  cpDb();
}
async function cpDb() {
  try { CP.db = await window.claude.use('db'); } catch (e) { CP.db = null; }
  if (!CP.db) { renderCP(); return; }
  try {
    CP.db.collection('comp').onSnapshot(snap => { CP.marks = {}; snap.docs.forEach(x => { CP.marks[x.id] = x.data() || {}; }); CP.live = true; renderCP(); if (E.data && E.data.vi && !$('vaView').hidden) renderVA(); }, () => renderCP());
  } catch (e) { renderCP(); }
}
function cpRows() {
  const d = E.data;
  return (d.ades || []).filter(a => a.m === CP.mes && (!CP.team || a.t === CP.team));
}
document.addEventListener('click', e => { const a = e.target.closest('[data-cpsent]'); if (!a) return; try { const m = JSON.parse(localStorage.getItem('cpSent') || '{}'); m[a.dataset.cpsent] = Date.now(); localStorage.setItem('cpSent', JSON.stringify(m)); } catch (x) {} setTimeout(() => renderCP(), 400); });
async function renderCP() {
  if (!E.data || $('cpView').hidden) return;
  const d = E.data, coord = CP.role === 'coord', fin = CP.role === 'fin', confere = coord || fin, todos = !CP.team;
  let rows = cpRows();
  const esps = [...new Set(rows.map(r => r.esp).filter(Boolean))].sort();
  if (!esps.includes(CP.esp)) CP.esp = '';
  $('cpEsp').innerHTML = '<option value="">Todos os especialistas</option>' + esps.map(n => `<option value="${esc(n)}"${n === CP.esp ? ' selected' : ''}>${esc(n)}</option>`).join('');
  if (CP.esp) rows = rows.filter(r => r.esp === CP.esp);
  const C = rows.map(r => ({ r, c: cpCalc(r) }));
  const sv = f => C.filter(x => f(x.c)).reduce((a, x) => a + (x.c.v || 0), 0);
  const tot = { n: C.length, com: C.filter(x => x.c.tem).length, ag: C.filter(x => x.c.tem && !x.c.ok).length, ok: C.filter(x => x.c.ok).length, vEnv: sv(c => c.tem), vAg: sv(c => c.tem && !c.ok), vOk: sv(c => c.ok), desc: C.reduce((a, x) => a + x.c.desc, 0), nd: C.filter(x => x.c.desc > 0).length, rec: C.reduce((a, x) => a + x.c.rec, 0) };
  const per = mlab(CP.mes), teamName = CP.team ? (d.nomes[CP.team] || CP.team) : (E.esp || '');
  $('cpTitle').textContent = 'Comprovante de adesões' + (teamName ? ' · ' + teamName : '');
  $('cpSub').textContent = (teamName && d.leaders[CP.team] ? 'Líder: ' + d.leaders[CP.team] + ' · ' : '') + per + ' · adesões do SGA · instalação do rastreador pelos atendimentos do SGA: na base desconta ' + brl(50) + ', na residência ' + brl(100) + ', associado da Região dos Lagos ' + brl(LAGOS_VAL) + ', sem atendimento de instalação não desconta · baixa = pagamento conferido e validado pelo financeiro.';
  const cpSt = [[nf(tot.n), 'Adesões'], [nf(tot.com) + ' · ' + brl(tot.vEnv), 'Comprovantes enviados'], [nf(tot.ag) + ' · ' + brl(tot.vAg), 'Aguardando baixa do financeiro'], [nf(tot.ok) + ' · ' + brl(tot.vOk), 'Com baixa (validadas)'], [nf(tot.nd) + ' · −' + brl(tot.desc), 'Desconto instalação do rastreador', 'neg'], [brl(tot.rec), 'Total a receber']];
  $('cpStats').innerHTML = cpSt.map(([v, l, c]) => `<div class="stat"><b class="num${c ? ' ' + c : ''}">${v}</b><span>${l}</span></div>`).join('');
  CP.rep = { arq: 'Comprovante de adesoes', titulo: 'Comprovante de adesões', eq: (teamName || 'Todas as equipes') + (CP.esp ? ' · ' + CP.esp : ''), lider: CP.team && d.leaders[CP.team] ? d.leaders[CP.team] : '', per, upd: d.atualizado, tabs: [], stats: cpSt };
  // resumo por especialista
  const g = {};
  C.forEach(({ r, c }) => { const k = r.esp || '—'; const o = g[k] || (g[k] = { esp: k, t: r.t, n: 0, com: 0, ag: 0, ok: 0, desc: 0, rec: 0 }); o.n++; if (c.tem) o.com++; if (c.tem && !c.ok) o.ag++; if (c.ok) o.ok++; o.desc += c.desc; o.rec += c.rec; });
  const gl = Object.values(g).sort((a, b) => b.n - a.n || a.esp.localeCompare(b.esp));
  $('cpResS').textContent = 'Por especialista · ' + per + ' · a receber = valor pago (lançado pelo financeiro ou, se não houver, o do comprovante) − desconto da instalação (sem pagamento e com instalação cobrada, o valor fica negativo)';
  const resCols = o => [nf(o.n), nf(o.com), nf(o.n - o.com), nf(o.ag), nf(o.ok)];
  $('cpRes').innerHTML = gl.length ? `<table class="vtab"><thead><tr><th>Especialista</th>${todos ? '<th>Equipe</th>' : ''}<th class="r">Adesões</th><th class="r">Comprovante enviado</th><th class="r">Sem comprovante</th><th class="r">Aguardando baixa</th><th class="r">Com baixa</th><th class="r">Desconto instalação</th><th class="r">A receber</th></tr></thead><tbody>${gl.map(o => `<tr>
      <td>${esc(o.esp)}</td>${todos ? `<td>${esc(d.nomes[o.t] || o.t || '—')}</td>` : ''}${resCols(o).map(v => `<td class="r num">${v}</td>`).join('')}<td class="r num">${o.desc ? '− ' + brl(o.desc) : '—'}</td><td class="r num"><b class="${o.rec < 0 ? 'neg' : ''}">${brl(o.rec)}</b></td></tr>`).join('')}
      <tr class="tot"><td>Total</td>${todos ? '<td></td>' : ''}${resCols(tot).map(v => `<td class="r num">${v}</td>`).join('')}<td class="r num">${tot.desc ? '− ' + brl(tot.desc) : '—'}</td><td class="r num"><b class="${tot.rec < 0 ? 'neg' : ''}">${brl(tot.rec)}</b></td></tr></tbody></table>` : '<p class="empty">Nenhuma adesão nesta seleção.</p>';
  CP.rep.tabs.push({ t: 'Resumo por especialista', nota: 'A receber = valor pago (lançado pelo financeiro ou, se não houver, o do comprovante) − desconto da instalação do rastreador (base ' + brl(50) + ', residência ' + brl(100) + ', Região dos Lagos ' + brl(LAGOS_VAL) + ') · baixa = pagamento conferido e validado pelo financeiro', head: ['Especialista'].concat(todos ? ['Equipe'] : [], ['Adesões', 'Comprovante enviado', 'Sem comprovante', 'Aguardando baixa', 'Com baixa', 'Desconto instalação', 'A receber']), r: todos ? [2, 3, 4, 5, 6, 7, 8] : [1, 2, 3, 4, 5, 6, 7],
    body: gl.map(o => [o.esp].concat(todos ? [d.nomes[o.t] || o.t || '—'] : [], resCols(o), [o.desc ? '− ' + brl(o.desc) : '—', brl(o.rec)])),
    foot: ['Total'].concat(todos ? [''] : [], resCols(tot), [tot.desc ? '− ' + brl(tot.desc) : '—', brl(tot.rec)]) });
  // lista
  const dnum = x => { const m = String(x || '').match(/(\d{2})\/(\d{2})\/(\d{4})/); return m ? +(m[3] + m[2] + m[1]) : 0; };
  const COLS = [
    { id: 'n', h: 'Associado', ty: 'txt', v: x => x.r.n || '' },
    { id: 'esp', h: 'Especialista', v: x => x.r.esp || '—' },
    todos && { id: 't', h: 'Equipe', v: x => d.nomes[x.r.t] || x.r.t || '—' },
    { id: 'pl', h: 'Placa / chassi', ty: 'txt', v: x => x.r.pl || x.r.ch || '' },
    { id: 'dc', h: 'Contrato', v: x => x.r.dc || '—', s: x => dnum(x.r.dc) },
    { id: 'inst', h: 'Instalação do rastreador', v: x => x.c.inst ? INST_TXT[x.c.inst] + (x.c.lagos ? ' · Região dos Lagos' : '') : 'Sem instalação' },
    { id: 'comp', h: 'Comprovante', v: x => x.c.comp ? (x.r.cp.vc === false ? 'Valor divergente' : 'Com comprovante') : 'Sem comprovante' },
    { id: 'pg', h: 'Pago', v: x => x.c.pg != null ? 'Lançado como pago' : 'Não lançado', s: x => x.c.pg == null ? -1 : x.c.pg },
    { id: 'desc', h: 'Desconto', r: 1, v: x => x.c.desc ? '− ' + brl(x.c.desc) : 'Sem desconto', s: x => x.c.desc },
    { id: 'rec', h: 'A receber', r: 1, v: x => x.c.rec < 0 ? 'Negativo' : x.c.rec > 0 ? 'Positivo' : 'Zerado', s: x => x.c.rec },
    { id: 'conf', h: 'Baixa do financeiro', v: x => x.c.ok ? 'Baixa dada (validado)' : x.c.tem ? 'Aguardando baixa' : 'Sem comprovante nem pagamento' },
    { id: 'nc', h: 'Cobrança da instalação', v: x => !x.c.inst ? 'Sem instalação' : x.c.isen ? 'Não descontada (Inside Sales)' : x.c.nc ? 'Não será cobrada' : 'Cobrada' }
  ].filter(Boolean);
  Object.keys(CP.cf).forEach(k => { if (!COLS.some(c => c.id === k) || !CP.cf[k]) delete CP.cf[k]; });
  const passa = (x, skip) => COLS.every(col => { const f = CP.cf[col.id]; if (!f || col.id === skip) return true; const v = col.v(x); return col.ty === 'txt' ? norm(v).includes(norm(f)) : v === f; });
  let L = C.filter(x => passa(x));
  const sc = COLS.find(c => c.id === CP.sort.c);
  if (sc) { const key = sc.s || sc.v; L = L.slice().sort((a, b) => { const A = key(a), B = key(b); return (typeof A === 'number' && typeof B === 'number' ? A - B : String(A).localeCompare(String(B), 'pt-BR')) * CP.sort.d || (a.r.n || '').localeCompare(b.r.n || ''); }); }
  else L = L.slice().sort((a, b) => (a.r.t || '').localeCompare(b.r.t || '') || (a.r.esp || '').localeCompare(b.r.esp || '') || (a.r.n || '').localeCompare(b.r.n || ''));
  const thOf = col => {
    const ar = CP.sort.c === col.id ? (CP.sort.d > 0 ? '▲' : '▼') : '↕';
    let f;
    if (col.ty === 'txt') f = `<input class="thf" data-cft="${col.id}" value="${esc(CP.cf[col.id] || '')}" placeholder="Filtrar…" aria-label="Filtrar ${esc(col.h)}">`;
    else {
      const ct = {}; C.filter(x => passa(x, col.id)).forEach(x => { const v = col.v(x); ct[v] = (ct[v] || 0) + 1; });
      const ks = Object.keys(ct).sort((a, b) => col.id === 'dc' ? dnum(a) - dnum(b) : a.localeCompare(b, 'pt-BR'));
      if (CP.cf[col.id] && !ks.includes(CP.cf[col.id])) ks.unshift(CP.cf[col.id]);
      f = `<select class="thf" data-cfs="${col.id}" aria-label="Filtrar ${esc(col.h)}"><option value="">Todos</option>${ks.map(k => `<option value="${esc(k)}"${CP.cf[col.id] === k ? ' selected' : ''}>${esc(k)} (${nf(ct[k] || 0)})</option>`).join('')}</select>`;
    }
    return `<th class="${col.r ? 'r ' : ''}${CP.cf[col.id] ? 'fon' : ''}"><button type="button" class="ths" data-sort="${col.id}" title="Classificar">${esc(col.h)} <i>${ar}</i></button>${f}</th>`;
  };
  const nF = Object.keys(CP.cf).length;
  $('cpFInfo').textContent = nF ? 'Mostrando ' + nf(L.length) + ' de ' + nf(C.length) + ' adesões · ' + nF + (nF > 1 ? ' filtros ativos' : ' filtro ativo') : 'Clique no nome da coluna para classificar · use o campo abaixo do nome para filtrar';
  $('cpClrF').hidden = !nF && !CP.sort.c;
  $('cpListT').textContent = 'Adesões de ' + per + (teamName ? ' · ' + teamName : ' · todas as equipes') + ' (' + nf(C.length) + ')';
  $('cpListS').textContent = 'Amarelo = anexado (verificação de hora em hora, sem ler o valor) · azul = valor conferido (atualização completa, 2 vezes ao dia ou pelo coordenador) · verde-escuro = baixa do financeiro' + (confere ? ' · coluna Pago: lance o valor já recebido (avulso, linha a linha) ou marque várias adesões e use os botões abaixo (pagamento acumulado e validação em lote)' : '') + (CP.db && CP.live ? '' : ' · validações e observações aparecem aqui na próxima atualização') + (RTCFG.comp ? '' : ' · o envio de comprovantes fica disponível assim que a página de envio do Google for publicada');
  const gasOk = !!(RTCFG.gas && RTCFG.comp);
  const toks = {};
  if (gasOk && E.esp) { if (d.cptok) for (const x of L) toks[x.r.t] = d.cptok; }
  else if (gasOk) for (const x of L) { const k = cpKeyFor(x.r.t); if (k && !toks[x.r.t]) toks[x.r.t] = await tokOf(k); }
  const cpLoc = (() => { try { return JSON.parse(localStorage.getItem('cpSent') || '{}'); } catch (e) { return {}; } })();
  const cpLs = r => { const t = cpLoc[r.m + '|' + cpKey(r)]; return !!t && Date.now() - t < 3 * 864e5; };
  const link = r => RTCFG.gas + '?tipo=comp&k=' + toks[r.t] + '&m=' + r.m + '&pl=' + encodeURIComponent(cpKey(r)) + '&n=' + encodeURIComponent(r.n || '') + '&esp=' + encodeURIComponent(r.esp || '') + '&eq=' + encodeURIComponent(d.nomes[r.t] || r.t || '');
  $('cpList').innerHTML = !C.length ? '<p class="empty">Nenhuma adesão nesta seleção.</p>' : `<table class="vtab cpt"><thead><tr>${confere ? `<th class="sel"><input type="checkbox" data-selall aria-label="Marcar todas as visíveis"${L.length && L.every(x => CP.sel.has(cpKey(x.r))) ? ' checked' : ''}></th>` : ''}${COLS.map(thOf).join('')}</tr></thead><tbody>${!L.length ? `<tr><td colspan="${COLS.length + (confere ? 1 : 0)}" class="empty">Nenhuma adesão com esses filtros.</td></tr>` : ''}${L.map(({ r, c }) => {
    const k = cpKey(r);
    const inst = c.inst ? `<span class="pill ${c.nc ? '' : 'mid'}">${INST_TXT[c.inst]}${r.instd ? ' · ' + esc(r.instd.slice(0, 5)) : ''}</span>${r.instst ? `<small class="sub">${esc(r.instst)}</small>` : ''}` : `<span class="pill">Sem instalação</span>${!r.pl && !r.ch ? '<small class="sub">sem placa no SGA</small>' : ''}`;
    const comp = c.comp ? `<a href="${esc(r.cp.url || '#')}" target="_blank" rel="noopener">Ver comprovante</a><small class="sub">${c.vc != null ? brl(c.vc) + (r.cp.vi != null && Math.abs(+r.cp.vi - c.vc) > 0.009 ? ' (lido no comprovante)' : '') : 'valor não informado'}${r.cp.vi != null && c.vc != null && Math.abs(+r.cp.vi - c.vc) > 0.009 ? ' · informado ' + brl(+r.cp.vi) + ' · divergente: vale o do comprovante' : r.cp.vc === false ? ' · valor divergente' : ''}</small>${gasOk && toks[r.t] && k ? `<a class="btn sm" style="margin-top:6px" href="${esc(link(r))}" target="_blank" rel="noopener">Anexar outro (foto ou PDF)</a>` : ''}`
      : (gasOk && toks[r.t] && k ? (cpLs(r) ? '<span class="pill mid">Anexado agora · conferência em até 1 hora</span>' : '') + `<a class="btn sm" data-cpsent="${esc(r.m + '|' + k)}" href="${esc(link(r))}" target="_blank" rel="noopener"${cpLs(r) ? ' style="margin-top:6px"' : ''}>${cpLs(r) ? 'Anexar de novo' : 'Anexar comprovante (foto ou PDF)'}</a>` : '<span class="pill bad">Sem comprovante</span>');
    const pgSub = c.pg != null ? `<small class="sub">${esc(c.mk.pgby || 'Lançado')}${c.mk.pgat ? ' · ' + new Date(c.mk.pgat).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' }) : ''}${c.mk.pgl ? ' · ' + esc(c.mk.pgl) : ''}</small>` : '';
    const pago = confere ? `<input class="cp-obs cp-pg num" data-pg="${esc(k)}" inputmode="decimal" value="${c.pg != null ? nfm(c.pg) : ''}" placeholder="${c.vc != null ? nfm(c.vc) : '0,00'}" aria-label="Valor pago"${CP.db ? '' : ' disabled'}>${pgSub}`
      : c.pg != null ? `<span class="pill ok">Pago · ${brl(c.pg)}</span>${pgSub}` : '<span class="sub">—</span>';
    const conf = confere && c.tem ? `<label class="chk"><input type="checkbox" data-ok="${esc(k)}"${c.ok ? ' checked' : ''}${CP.db ? '' : ' disabled'}> Dar baixa (validado)</label>${c.ok && c.mk.okat ? `<small class="sub">${esc(c.mk.okby || '')} · ${new Date(c.mk.okat).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}</small>` : ''}` : c.ok ? `<span class="pill ok">Baixa dada</span>${c.mk.okat ? `<small class="sub">${esc(c.mk.okby || 'Financeiro')} · ${new Date(c.mk.okat).toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' })}</small>` : ''}` : c.tem ? '<span class="pill mid">Aguardando baixa</span>' : '<span class="pill">—</span>';
    const nc = c.isen && c.inst ? '<span class="pill">Não descontada (Inside Sales)</span>' : coord && c.inst ? `<label class="chk"><input type="checkbox" data-nc="${esc(k)}"${c.nc ? ' checked' : ''}${CP.db ? '' : ' disabled'}> Não será cobrada</label>${c.nc ? `<input class="cp-obs" data-obs="${esc(k)}" value="${esc(c.mk.obs || '')}" placeholder="Observação (obrigatória)"${CP.db ? '' : ' disabled'}>` : ''}`
      : c.inst ? (c.nc ? `<span class="pill ok">Não será cobrada</span>${c.mk.obs ? `<small class="sub">${esc(c.mk.obs)}</small>` : ''}` : '<span class="pill">Cobrada</span>') : '<span class="sub">—</span>';
    const rc = c.ok ? 'okv' : (r.cp && (r.cp.vc === true || r.cp.vc === false)) || c.pg != null ? 'cpc' : c.comp || cpLs(r) ? 'cpe' : '';
    return `<tr${rc ? ' class="' + rc + '"' : ''}>
      ${confere ? `<td class="sel"><input type="checkbox" data-sel="${esc(k)}"${CP.sel.has(k) ? ' checked' : ''} aria-label="Marcar ${esc(r.n || '')}"></td>` : ''}<td>${esc(r.n || '—')}</td><td>${esc(r.esp)}</td>${todos ? `<td>${esc(d.nomes[r.t] || r.t)}</td>` : ''}<td class="nw">${esc(r.pl || r.ch || '—')}${!r.pl && r.ch ? '<small class="sub">chassi</small>' : ''}</td><td class="nw">${esc(r.dc)}</td>
      <td>${inst}</td><td>${comp}</td><td>${pago}</td><td class="r num nw">${c.desc ? '− ' + brl(c.desc) : '—'}</td><td class="r num nw"><b class="${c.rec < 0 ? 'neg' : ''}">${brl(c.rec)}</b></td><td>${conf}</td><td>${nc}</td></tr>`; }).join('')}</tbody></table>`;
  { const fl = COLS.filter(c => CP.cf[c.id]).map(c => c.h + ': ' + CP.cf[c.id]);
    // PDF: adesões separadas por equipe e, dentro de cada equipe, especialista por especialista
    CP.rep.tabs.push({ sec: 'Adesões do mês (' + nf(L.length) + (L.length !== C.length ? ' de ' + nf(C.length) : '') + ')', nota: 'Separadas por equipe e por especialista · fundo verde = baixa dada pelo financeiro (pagamento validado)' + (fl.length ? ' · filtros da lista: ' + fl.join(' · ') : '') });
    const linha = ({ r, c }) => [r.n || '—', r.pl || r.ch || '—', r.dc || '—',
      c.inst ? INST_TXT[c.inst] + (r.instd ? ' ' + r.instd.slice(0, 5) : '') + (c.isen ? ' (Inside Sales)' : c.nc ? ' (não cobrada)' : '') : 'Sem instalação',
      c.comp ? (c.vc != null ? brl(c.vc) : 'enviado') + (r.cp.vc === false ? ' (divergente)' : '') : 'Sem comprovante',
      c.pg != null ? brl(c.pg) : '—', c.desc ? '− ' + brl(c.desc) : '—', brl(c.rec), c.ok ? 'Baixa dada' : c.tem ? 'Aguardando baixa' : '—'];
    const tnome = t => d.nomes[t] || t || 'Sem equipe';
    const eqs = [...new Set(L.map(x => x.r.t))].sort((a, b) => tnome(a).localeCompare(tnome(b)));
    eqs.forEach(t => {
      const Lt = L.filter(x => x.r.t === t);
      if (eqs.length > 1 || todos) CP.rep.tabs.push({ sec: 'Equipe ' + tnome(t) + (d.leaders[t] ? ' · líder ' + d.leaders[t] : ''), sub: nf(Lt.length) + (Lt.length === 1 ? ' adesão' : ' adesões') + ' · a receber ' + brl(Lt.reduce((a, x) => a + x.c.rec, 0)) });
      const es = [...new Set(Lt.map(x => x.r.esp || '—'))].sort((a, b) => a.localeCompare(b));
      es.forEach(e => {
        const Le = Lt.filter(x => (x.r.esp || '—') === e).sort((a, b) => (a.r.n || '').localeCompare(b.r.n || ''));
        CP.rep.tabs.push({ t: e + ' · ' + nf(Le.length) + (Le.length === 1 ? ' adesão' : ' adesões'), keep: true,
          head: ['Associado', 'Placa / chassi', 'Contrato', 'Instalação', 'Comprovante', 'Pago', 'Desconto', 'A receber', 'Baixa'], r: [5, 6, 7],
          body: Le.map(linha), hl: Le.map((x, i) => x.c.ok ? i : -1).filter(i => i >= 0),
          foot: ['Total do especialista', '', '', '', nf(Le.filter(x => x.c.comp).length) + ' com comprovante', brl(Le.reduce((a, x) => a + (x.c.pg || 0), 0)), '− ' + brl(Le.reduce((a, x) => a + x.c.desc, 0)), brl(Le.reduce((a, x) => a + x.c.rec, 0)), nf(Le.filter(x => x.c.ok).length) + ' validadas'] });
      });
    }); }
  CP.vis = L.map(x => x.r); $('cpBulk').hidden = !confere || !C.length; cpSelInfo();
  $('cpUpd').textContent = 'Dados atualizados em ' + new Date(d.atualizado).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' }) + '. Adesões e instalações: direto do SGA. Comprovantes: pasta "Comprovantes de adesões" no Google Drive.';
}
async function cpSave(mes, key, patch) {
  if (!CP.db) { toast('Entre no claude.ai para marcar'); return; }
  const ref = CP.db.collection('comp').doc(mes);
  const cur = Object.assign({}, (CP.marks[mes] || {})[key] || {}, patch);
  CP.marks[mes] = Object.assign({}, CP.marks[mes] || {}, { [key]: cur }); renderCP();
  try { await ref.update({ [key]: cur }); }
  catch (e) { try { await ref.set(Object.assign({}, CP.marks[mes])); } catch (e2) { toast('Não foi possível salvar (' + (e2 && (e2.code || e2.message) || 'erro') + ')'); } }
}
async function cpSaveMany(mes, patches) {      // { chave: alterações } numa gravação só
  if (!CP.db) { toast('Entre no claude.ai para marcar'); return false; }
  const ref = CP.db.collection('comp').doc(mes), upd = {};
  for (const [key, patch] of Object.entries(patches)) upd[key] = Object.assign({}, (CP.marks[mes] || {})[key] || {}, patch);
  CP.marks[mes] = Object.assign({}, CP.marks[mes] || {}, upd); renderCP();
  try { await ref.update(upd); return true; }
  catch (e) { try { await ref.set(Object.assign({}, CP.marks[mes])); return true; } catch (e2) { toast('Não foi possível salvar (' + (e2 && (e2.code || e2.message) || 'erro') + ')'); return false; } }
}
const cpWho = () => CP.role === 'fin' ? 'Financeiro' : 'Coordenação';
function cpSelRows() { return CP.vis.filter(r => CP.sel.has(cpKey(r))); }
function cpSelInfo() {
  const R = cpSelRows(), n = R.length, C = R.map(cpCalc), soma = C.reduce((a, c) => a + (c.v || 0), 0), semv = C.filter(c => c.v == null).length;
  $('cpSelInfo').textContent = n ? n + (n > 1 ? ' adesões marcadas' : ' adesão marcada') + ' · soma dos valores: ' + brl(soma) + (semv ? ' · ' + semv + ' sem valor (o valor pago total informado é dividido entre elas)' : '')
    : 'Marque as adesões na primeira coluna para lançar o pagamento (acumulado) ou validar várias de uma vez.';
  ['cpBkPg', 'cpBkOk', 'cpBkNo', 'cpBkClr'].forEach(id => $(id).disabled = !n);
}
$('cpBkClr').addEventListener('click', () => { CP.sel.clear(); renderCP(); });
$('cpBkPg').addEventListener('click', async () => {
  const R = cpSelRows(); if (!R.length) return;
  const tot = pnum($('cpBkV').value), obs = $('cpBkO').value.trim(), at = new Date().toISOString(), who = cpWho();
  const C = R.map(r => ({ r, c: cpCalc(r) })), conh = C.filter(x => x.c.v != null), sem = C.filter(x => x.c.v == null);
  const somaConh = conh.reduce((a, x) => a + x.c.v, 0), vals = {};
  if (R.length === 1 && tot != null) vals[cpKey(R[0])] = tot;
  else {
    conh.forEach(x => vals[cpKey(x.r)] = x.c.v);
    if (sem.length) {
      if (tot == null) { toast(sem.length + ' adesão(ões) sem valor: informe o valor pago total ou o valor na coluna Pago'); return; }
      const resto = Math.round((tot - somaConh) * 100) / 100;
      if (resto <= 0) { toast('O valor total não cobre as adesões sem valor'); return; }
      const parte = Math.floor(resto / sem.length * 100) / 100;
      sem.forEach((x, i) => vals[cpKey(x.r)] = i === sem.length - 1 ? Math.round((resto - parte * (sem.length - 1)) * 100) / 100 : parte);
    }
  }
  const soma = Object.values(vals).reduce((a, b) => a + b, 0);
  if (tot != null && R.length > 1 && Math.abs(soma - tot) > 0.009) { toast('Valor total (' + brl(tot) + ') diferente da soma das adesões (' + brl(soma) + '). Ajuste na coluna Pago.'); return; }
  const lote = R.length > 1 ? 'acumulado de ' + R.length + ' adesões' + (tot != null ? ' (' + brl(tot) + ')' : '') : 'avulso';
  const P = {}; for (const [k, v] of Object.entries(vals)) P[k] = { pg: v, pgby: who, pgat: at, pgl: (obs ? obs + ' · ' : '') + lote };
  if (await cpSaveMany(CP.mes, P)) { toast(R.length > 1 ? R.length + ' adesões lançadas como pagas (' + brl(soma) + ')' : 'Pagamento lançado (' + brl(soma) + ')'); $('cpBkV').value = ''; $('cpBkO').value = ''; }
});
async function cpBulkOk(val) {
  const R = cpSelRows(); if (!R.length) return;
  const at = new Date().toISOString(), who = cpWho(), P = {}; let pul = 0;
  R.forEach(r => { const c = cpCalc(r); if (val && !c.tem) { pul++; return; } P[cpKey(r)] = { ok: val, okby: val ? who : '', okat: val ? at : '' }; });
  const n = Object.keys(P).length;
  if (!n) { toast('Nenhuma adesão marcada tem comprovante ou pagamento lançado'); return; }
  if (await cpSaveMany(CP.mes, P)) { toast((val ? n + ' validada(s)' : 'Validação retirada de ' + n) + (pul ? ' · ' + pul + ' sem comprovante nem pagamento ficaram de fora' : '')); if (val) CP.sel.clear(), renderCP(); }
}
$('cpBkOk').addEventListener('click', () => cpBulkOk(true));
$('cpBkNo').addEventListener('click', () => cpBulkOk(false));
$('cpList').addEventListener('change', e => {
  const s = e.target.closest('select[data-cf]'); if (s) { CP.f = s.value; renderCP(); return; }
  const cs = e.target.closest('select[data-cfs]'); if (cs) { CP.cf[cs.dataset.cfs] = cs.value; renderCP(); return; }
  const sa = e.target.closest('input[data-selall]'); if (sa) { CP.vis.forEach(r => sa.checked ? CP.sel.add(cpKey(r)) : CP.sel.delete(cpKey(r))); renderCP(); return; }
  const se = e.target.closest('input[data-sel]'); if (se) { se.checked ? CP.sel.add(se.dataset.sel) : CP.sel.delete(se.dataset.sel); const a = document.querySelector('#cpList input[data-selall]'); if (a) a.checked = CP.vis.every(r => CP.sel.has(cpKey(r))); cpSelInfo(); return; }
  const pg = e.target.closest('input[data-pg]'); if (pg) { const v = pnum(pg.value); cpSave(CP.mes, pg.dataset.pg, v == null ? { pg: null, pgby: '', pgat: '', pgl: '' } : { pg: v, pgby: cpWho(), pgat: new Date().toISOString(), pgl: 'avulso' }); toast(v == null ? 'Pagamento retirado' : 'Pagamento lançado: ' + brl(v)); return; }
  const who = cpWho(), at = new Date().toISOString();
  const ok = e.target.closest('input[data-ok]'); if (ok) { cpSave(CP.mes, ok.dataset.ok, { ok: ok.checked, okby: ok.checked ? who : '', okat: ok.checked ? at : '' }); toast(ok.checked ? 'Comprovante validado' : 'Validação retirada'); return; }
  const nc = e.target.closest('input[data-nc]'); if (nc) { cpSave(CP.mes, nc.dataset.nc, { nc: nc.checked }); return; }
  const ob = e.target.closest('input[data-obs]'); if (ob) { cpSave(CP.mes, ob.dataset.obs, { obs: ob.value.trim() }); toast('Observação salva'); }
});
$('cpTeam').addEventListener('change', e => { CP.team = e.target.value; CP.esp = ''; CP.sel.clear(); renderCP(); });
$('cpEsp').addEventListener('change', e => { CP.esp = e.target.value; renderCP(); });
$('cpMes').addEventListener('change', e => { CP.mes = e.target.value; CP.sel.clear(); renderCP(); });
$('cpList').addEventListener('input', async e => {
  const t = e.target.closest('input[data-cft]'); if (!t) return;
  const id = t.dataset.cft, pos = t.selectionStart; CP.cf[id] = t.value;
  clearTimeout(CP._ft); CP._ft = setTimeout(async () => { await renderCP(); const n = document.querySelector(`#cpList input[data-cft="${id}"]`); if (n) { n.focus(); try { n.setSelectionRange(pos, pos); } catch (er) {} } }, 250);
});
$('cpList').addEventListener('click', e => {
  const b = e.target.closest('button[data-sort]'); if (!b) return;
  const c = b.dataset.sort; CP.sort = CP.sort.c !== c ? { c, d: 1 } : CP.sort.d > 0 ? { c, d: -1 } : { c: '', d: 1 }; renderCP();
});
$('cpClrF').addEventListener('click', () => { CP.cf = {}; CP.sort = { c: '', d: 1 }; renderCP(); });
/* barra de rolagem horizontal também em cima das tabelas largas */
function topScroll(el) {
  const bar = document.createElement('div'); bar.className = 'topscroll'; bar.setAttribute('aria-hidden', 'true'); bar.innerHTML = '<div></div>';
  el.parentNode.insertBefore(bar, el);
  bar.addEventListener('scroll', () => { if (el.scrollLeft !== bar.scrollLeft) el.scrollLeft = bar.scrollLeft; });
  el.addEventListener('scroll', () => { if (bar.scrollLeft !== el.scrollLeft) bar.scrollLeft = el.scrollLeft; });
  const fit = () => { bar.firstChild.style.width = el.scrollWidth + 'px'; bar.hidden = el.scrollWidth <= el.clientWidth + 1; };
  try { new ResizeObserver(fit).observe(el); } catch (er) {}
  new MutationObserver(fit).observe(el, { childList: true, subtree: true });
  fit();
}
document.querySelectorAll('.tscroll').forEach(topScroll);

/* ---------- PDF dos resumos (Adesões validadas, Descontos, Comprovante de adesões) ---------- */
const LOGO_EXODUS = 'data:image/png;base64,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';
let JSPDF = null;
function carregaJs(src) { return new Promise((ok, er) => { const x = document.createElement('script'); x.src = src; x.onload = ok; x.onerror = () => er(new Error('não carregou a biblioteca de PDF')); document.head.appendChild(x); }); }
async function libPDF() {
  if (JSPDF) return JSPDF;
  if (!(window.jspdf && window.jspdf.jsPDF)) await carregaJs('https://cdn.jsdelivr.net/npm/jspdf@2.5.1/dist/jspdf.umd.min.js');
  if (!(window.jspdf.jsPDF.API && window.jspdf.jsPDF.API.autoTable)) await carregaJs('https://cdn.jsdelivr.net/npm/jspdf-autotable@3.8.2/dist/jspdf.plugin.autotable.min.js');
  return JSPDF = window.jspdf.jsPDF;
}
const pdfTx = x => String(x == null ? '' : x).replace(/−/g, '-').replace(/[  ]/g, ' ').replace(/[^\x00-\xff€–—‘’“”•…]/g, '');
async function emitirPDF(rep) {
  const J = await libPDF();
  const larg = rep.tabs.some(t => (t.head || []).length > 7);
  const doc = new J({ orientation: larg ? 'landscape' : 'portrait', unit: 'mm', format: 'a4' });
  const W = doc.internal.pageSize.getWidth(), H = doc.internal.pageSize.getHeight(), M = 14;
  const NAVY = [15, 45, 92], FG = [20, 32, 52], MUT = [93, 107, 128], LINE = [214, 222, 234];
  const agora = new Date().toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' });
  const topo = () => {
    doc.setFillColor(...NAVY); doc.rect(0, 0, W, 24, 'F');
    try { doc.addImage(LOGO_EXODUS, 'PNG', M, 4.5, 15, 15); } catch (e) {}
    doc.setTextColor(255, 255, 255); doc.setFont('helvetica', 'bold'); doc.setFontSize(15); doc.text(pdfTx('EXODUS BENEFÍCIOS'), M + 19, 12.6);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(8.5); doc.text(pdfTx('Proteção Veicular'), M + 19, 17.6);
    doc.setFont('helvetica', 'bold'); doc.setFontSize(11); doc.text(pdfTx(rep.titulo), W - M, 12.6, { align: 'right' });
    doc.setFont('helvetica', 'normal'); doc.setFontSize(8.5); doc.text(pdfTx(rep.per), W - M, 17.6, { align: 'right' });
  };
  topo();
  let y = 34;
  doc.setTextColor(...FG); doc.setFont('helvetica', 'bold'); doc.setFontSize(16); doc.text(pdfTx(rep.titulo + ' · ' + rep.eq), M, y);
  y += 6; doc.setFont('helvetica', 'normal'); doc.setFontSize(9); doc.setTextColor(...MUT);
  doc.text(pdfTx((rep.lider ? 'Líder: ' + rep.lider + ' · ' : '') + 'Período: ' + rep.per + ' · dados de ' + new Date(rep.upd).toLocaleString('pt-BR', { dateStyle: 'short', timeStyle: 'short' })), M, y);
  y += 7;
  const n = rep.stats.length, gap = 4, bw = (W - 2 * M - gap * (n - 1)) / n;
  rep.stats.forEach(([v, l, cl], i) => {
    const x = M + i * (bw + gap);
    doc.setFillColor(242, 245, 249); doc.setDrawColor(...LINE); doc.roundedRect(x, y, bw, 19, 2, 2, 'FD');
    doc.setTextColor(...(cl === 'neg' ? [163, 38, 31] : FG)); doc.setFont('helvetica', 'bold'); let fs = 13; doc.setFontSize(fs); while (fs > 8 && doc.getTextWidth(pdfTx(v)) > bw - 6) doc.setFontSize(fs -= 0.5); doc.text(pdfTx(v), x + 4, y + 8.5);
    doc.setTextColor(...MUT); doc.setFont('helvetica', 'normal'); doc.setFontSize(7.5); doc.text(pdfTx(String(l).toUpperCase()), x + 4, y + 15, { maxWidth: bw - 8 });
  });
  y += 27;
  const altTab = t => 12 + 6.5 * (t.body.length + 2);
  const pulaTab = (yy, t) => yy > H - 75 || (t.keep && altTab(t) < H - 50 && yy + altTab(t) > H - 18);
  const altSec = t => t.sub || t.nota ? 15 : 11;
  for (let ti = 0; ti < rep.tabs.length; ti++) {
    const tb = rep.tabs[ti];
    if (tb.sec) {                                   // título de seção (ex.: equipe): nunca fica sozinho no pé da página
      let yy = y, j = ti;
      while (j < rep.tabs.length && rep.tabs[j].sec) { yy += altSec(rep.tabs[j]); j++; }
      if (yy > H - 30 || (j < rep.tabs.length && pulaTab(yy, rep.tabs[j]))) { doc.addPage(); topo(); y = 34; }
      doc.setFillColor(0, 0, 0); doc.roundedRect(M, y - 5.5, W - 2 * M, tb.sub || tb.nota ? 13 : 9, 1.5, 1.5, 'F');   // título da equipe: fundo preto, letras brancas
      doc.setTextColor(255, 255, 255); doc.setFont('helvetica', 'bold'); doc.setFontSize(12.5); doc.text(pdfTx(tb.sec), M + 5, y);
      if (tb.sub || tb.nota) { doc.setFont('helvetica', 'normal'); doc.setFontSize(8); doc.setTextColor(220, 220, 220); doc.text(pdfTx(tb.sub || tb.nota), M + 5, y + 5, { maxWidth: W - 2 * M - 8 }); }
      y += altSec(tb); continue;
    }
    const alt = altTab(tb);                             // tabela curta: não começa no pé da página
    if (pulaTab(y, tb)) { doc.addPage(); topo(); y = 34; }
    doc.setTextColor(...FG); doc.setFont('helvetica', 'bold'); doc.setFontSize(11.5); doc.text(pdfTx(tb.t), M, y);
    if (tb.nota) { doc.setFont('helvetica', 'normal'); doc.setFontSize(7.8); doc.setTextColor(...MUT); const ls = doc.splitTextToSize(pdfTx(tb.nota), W - 2 * M); doc.text(ls, M, y + 4.5); y += 4 * ls.length; }
    const cs = {}; (tb.r || []).forEach(i => cs[i] = { halign: 'right', cellWidth: 'wrap' });   // números nunca quebram
    const fsz = tb.body.length > 30 || tb.head.length > 9 ? 7.4 : (larg ? 8 : 8.6);
    tb.head.forEach((h, i) => { if (!cs[i] && /^(Mês|Equipe|Faixa atingida|Ticket médio|Recorrente|Placa \/ chassi|Contrato|Comprovante|Baixa|Pago|Desconto|A receber)$/.test(h)) cs[i] = { cellWidth: 'wrap' }; });
    doc.autoTable({
      startY: y + 3, margin: { top: 30, left: M, right: M, bottom: 16 }, theme: 'grid',
      head: [tb.head.map(pdfTx)], body: tb.body.map(r => r.map(pdfTx)), foot: tb.foot ? [tb.foot.map(pdfTx)] : undefined, showFoot: 'lastPage',
      styles: { font: 'helvetica', fontSize: fsz, cellPadding: tb.body.length > 30 ? 1.4 : 1.8, textColor: FG, lineColor: LINE, lineWidth: 0.15, valign: 'middle' },
      headStyles: { fillColor: NAVY, textColor: [255, 255, 255], fontStyle: 'bold' },
      footStyles: { fillColor: [233, 238, 245], textColor: FG, fontStyle: 'bold' },
      alternateRowStyles: { fillColor: [248, 250, 252] }, columnStyles: cs,
      didParseCell: c => {
        const dir = (cs[c.column.index] || {}).halign === 'right';
        if (c.section === 'head' && dir) c.cell.styles.halign = 'right';
        if (c.section === 'foot' && dir) c.cell.styles.halign = 'right';
        if (c.section === 'body' && tb.hl && tb.hl.includes(c.row.index)) { c.cell.styles.fillColor = [227, 244, 234]; c.cell.styles.textColor = [18, 120, 74]; c.cell.styles.fontStyle = 'bold'; }
        if (c.section !== 'head' && /^-\s?R\$/.test(String(c.cell.raw || '').trim()) && !(c.section === 'body' && tb.hl && tb.hl.includes(c.row.index))) c.cell.styles.textColor = [163, 38, 31];
      },
      didDrawPage: () => topo()
    });
    y = doc.lastAutoTable.finalY + 10;
  }
  const np = doc.getNumberOfPages();
  for (let i = 1; i <= np; i++) {
    doc.setPage(i); doc.setDrawColor(...LINE); doc.line(M, H - 11, W - M, H - 11);
    doc.setFont('helvetica', 'normal'); doc.setFontSize(7.5); doc.setTextColor(...MUT);
    doc.text(pdfTx('Exodus Benefícios · Escritório do Especialista · emitido em ' + agora + ($('hName').textContent ? ' por ' + $('hName').textContent : '')), M, H - 6.5);
    doc.text('Página ' + i + ' de ' + np, W - M, H - 6.5, { align: 'right' });
  }
  const sem = x => String(x).normalize('NFD').replace(/[̀-ͯ]/g, '').replace(/[^\w .-]+/g, ' ').replace(/\s+/g, ' ').trim();
  const nome = sem('Exodus - ' + rep.arq + ' - ' + rep.eq + ' - ' + rep.per) + '.pdf';
  const blob = doc.output('blob');
  let dl = null; try { dl = window.claude && window.claude.use ? await window.claude.use('downloads') : null; } catch (e) { dl = null; }
  if (dl) {
    try { await dl.save({ filename: nome, data: blob }); toast('PDF salvo'); return; }
    catch (e) { if (e && e.code === 'declined') { toast('Download cancelado'); return; } if (e && e.code === 'rate_limited') { toast('Já há um download aguardando confirmação'); return; } }
  }
  doc.save(nome);
}
document.addEventListener('click', async e => {
  const b = e.target.closest('[data-pdf]'); if (!b) return;
  const rep = { va: VA.rep, ds: DS.rep, cp: CP.rep }[b.dataset.pdf];
  if (!rep) { toast('Abra o resumo antes de emitir o PDF'); return; }
  const tx = b.innerHTML; b.disabled = true; b.lastChild.textContent = 'Gerando PDF…';
  try { await emitirPDF(rep); } catch (er) { toast('Não foi possível gerar o PDF (' + (er && er.message || 'erro') + ')'); }
  finally { b.disabled = false; b.innerHTML = tx; }
});

function startFin(ring) {
  S.specs = []; S.admin = false; S.fin = true; RING = ring; S.rows = [];
  $('hName').textContent = 'Coordenação financeira';
  $('hWho').textContent = 'Adesões validadas, descontos e comprovantes de adesões de todas as equipes';
  $('login').hidden = true; $('app').hidden = false; $('listView').hidden = true;
  $('views').hidden = false;
  document.querySelectorAll('[data-view="list"],[data-view="evo"],[data-view="rt"]').forEach(b => b.hidden = true);
  setupEvo(ring);
  goHome();
}
let RING = null;
function startApp(specs, admin, ring) {
  if (ring && ring.fin) { startFin(ring); return; }
  S.specs = specs; S.admin = admin; RING = ring;
  let rows = [];
  specs.forEach(sp => sp.rows.forEach(r => { r._esp = sp.nome; rows.push(r); }));
  if (admin) {
    rows.sort((a, b) => (a.dif == null) - (b.dif == null) || (b.dif ?? 0) - (a.dif ?? 0) || (b.bp || 0) - (a.bp || 0));
    rows.forEach((r, i) => r._g = i + 1);
  }
  rows.forEach(r => r._s = norm([r.n, r.pl, r.mod, r.mon, r.cel, r.cid, r.eq, r._esp, r.orig, r.mat].join(' ')));
  S.rows = rows;
  if (admin) {
    $('hName').textContent = ring && ring.cad ? 'Cadastro' : 'Coordenação';
    $('hWho').textContent = specs.length + ' especialistas · ' + rows.length + ' ex-associados';
    const se = $('selEsp'); se.hidden = false;
    se.innerHTML = '<option value="">Todos os especialistas</option>' +
      specs.slice().sort((a, b) => a.nome.localeCompare(b.nome)).map(sp => `<option value="${esc(sp.nome)}">${esc(sp.nome)} (${sp.rows.length})</option>`).join('');
    const eqs = [...new Set(rows.map(r => r.eq).filter(Boolean))].sort();
    const sq = $('selEq'); sq.hidden = false;
    sq.innerHTML = '<option value="">Todas as equipes</option>' + eqs.map(e => `<option>${esc(e)}</option>`).join('');
  } else {
    const sp = specs[0];
    $('hName').textContent = sp.nome;
    $('hWho').textContent = (sp.equipes.length ? 'Equipe ' + sp.equipes.join(', ') + ' · ' : '') + sp.rows.length + ' ex-associados para contatar';
  }
  $('login').hidden = true; $('app').hidden = false;
  render();
  saveNote();
  setupSync();
  setupMotivos(S.rows).then(() => { const y = window.scrollY; render(); window.scrollTo(0, y); });
  $('views').hidden = false;
  if (!admin && /^VINICIUS FILEMO/.test(norm(specs[0] && specs[0].nome).toUpperCase())) document.querySelector('[data-view="rt"]').hidden = false;   // líder da Elim (sem a aba de evolução)
  setupRT();
  if (ring) setupEvo(ring);
  goHome();
}

function filtered() {
  const q = norm(S.q.trim());
  return S.rows.filter(r =>
    (S.type === 'all' || (S.type === 'moto') === !!r.moto) &&
    (S.sit === 'all' || (S.sit === 'resg' ? !!rsDe(r) : !rsDe(r) && (S.sit === 'sent') === isSent(r))) &&
    (!S.esp || r._esp === S.esp) && (!S.eq || r.eq === S.eq) &&
    (!q || r._s.includes(q)));
}

const RS_IC = '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="9.5"/><path d="M7.5 12.5l3 3 6-6.5"/></svg>';
function rsDe(r) { try { return (E.data && E.data.resg || {})[String(r.mat)] || null; } catch (e) { return null; } }
function rsBox(rs) {
  const d = String(rs.dc || '').split('-').reverse().join('/');
  return `<div class="resg-ok">${RS_IC}<div><b>Parabéns! Você conseguiu realizar esse remarketing.</b><span>${rs.tp === 'reativado' ? 'Reativado' : 'Contrato'} em ${esc(d)}${rs.pl ? ' · ' + esc(rs.pl) : ''}${rs.sit ? ' · ' + esc(rs.sit) + ' no SGA' : ''}. A mensagem da promoção foi travada.</span></div></div>`;
}
function card(r) {
  const rs = rsDe(r);
  const sent = isSent(r);
  const rank = S.admin ? (S.esp ? r.rk : r._g) : r.rk;
  const alert = r.fipe != null && r.vp && r.fipe < 0.5 * r.vp;
  let diff;
  if (r.dif == null) diff = `<div class="diff none"><b>—</b><span>Sem valor do último boleto ou do plano</span></div>`;
  else if (r.dif >= 0) diff = `<div class="diff gain"><b>${brl(r.dif)}</b><span>por mês a menos que pagava</span></div>`;
  else diff = `<div class="diff loss"><b>${brl(-r.dif)}</b><span>por mês a mais que pagava</span></div>`;
  const veh = [r.mod, r.ano, r.pl].filter(Boolean).map(esc).join(' · ');
  const dd = [
    ['Associado', r.n], ['Matrícula', r.mat], ['Especialista', r._esp], ...(r.orig ? [['Carteira de origem', r.orig]] : []), ['Equipe', r.eq], ['Indicação externa', r.ind || '—'],
    ['Celular', r.cel || '—'], ['Cidade', r.cid], ['Montadora', r.mon], ['Modelo', r.mod], ['Ano modelo', r.ano || '—'], ['Placa', r.pl || '—'],
    ['Margem relativa', pct(r.mg)], ['Boletos pagos', r.bp ?? '—'],
    ['Último boleto pago – data', r.ud || '—'], ['Último boleto pago – valor', brl(r.uv)],
    ['Valor protegido', brl(r.vp)], ['FIPE atual', brl(r.fipe)], ['Referência da FIPE', r.rf || '—'],
    ['Mensalidade na FIPE atual', brl(r.m)], ['Mensalidade c/ 10%', brl(r.m10)],
    ...(r.moto ? [] : [['Mensalidade c/ 20% (adesivo)', brl(r.m20)]]),
    ['1º boleto c/ 50%', brl(r.m50)], ['Plano de referência', r.plano || '—'],
  ];
  return `<article class="card${rs ? ' resg' : sent ? ' sent' : ''}" data-k="${esc(sentKey(r))}">
    <div class="rank">${rank}<small>${S.admin && !S.esp ? 'GERAL' : 'ORDEM'}</small></div>
    <div style="min-width:0">
      <div class="who-line"><h3>${esc(r.n)}</h3>
        <span class="chip${r.moto ? ' moto' : ''}">${r.moto ? 'MOTO' : 'CARRO'}</span>
        ${alert ? '<span class="chip alert" title="FIPE atual menor que metade do valor protegido">CONFERIR FIPE</span>' : ''}
        ${rs ? '<span class="chip ok">REMARKETING REALIZADO</span>' : sent ? '<span class="chip ok">ENVIADO</span>' : ''}
      </div>
      <p class="veh">${veh}</p>
      <p class="mot"><b>Motivo do cancelamento:</b> ${esc(motivoDe(r))}</p>
      <div class="meta">
        <span class="num">${esc(r.cel || 'Sem celular')}</span>
        ${r.cid ? `<span>${esc(r.cid)}</span>` : ''}
        ${r.eq ? `<span>Equipe ${esc(r.eq)}</span>` : ''}
        ${S.admin ? `<span>${esc(r._esp)}</span>` : ''}
        ${r.orig ? `<span>Origem: ${esc(r.orig)}</span>` : ''}
        <span>${r.bp ?? 0} boletos pagos</span>
      </div>
    </div>
    <div class="money">
      <div class="row2"><span>Pagava (último boleto)</span><b>${brl(r.uv)}</b></div>
      <div class="row2"><span>Hoje c/ 10%</span><b>${brl(r.m10)}</b></div>
      ${r.moto ? '' : `<div class="row2"><span>Hoje c/ 20% (adesivo)</span><b>${brl(r.m20)}</b></div>`}
      <div class="row2"><span>1º boleto c/ 50%</span><b>${brl(r.m50)}</b></div>
      ${diff}
    </div>
    ${rs ? rsBox(rs) : `<div class="actions">
      ${r.wa ? `<a class="btn wa" href="${waLink(r)}" target="_blank" rel="noopener">Abrir WhatsApp</a>` : `<span class="btn wa off">Sem celular válido</span>`}
      <button class="btn mark" type="button" data-act="mark">${sent ? 'Enviado ✓' : 'Marcar como enviado'}</button>
      <button class="btn" type="button" data-act="copy">Copiar mensagem</button>
    </div>`}
    <details class="more"><summary>Todos os dados e mensagem</summary>
      <dl class="grid-data">${dd.map(([k, v]) => `<div><dt>${esc(k)}</dt><dd>${esc(v)}</dd></div>`).join('')}</dl>
      ${rs ? '' : `<div class="msg">${esc(message(r))}</div>`}
    </details>
  </article>`;
}

function render() {
  const rows = filtered();
  const base = S.rows.filter(r => (!S.esp || r._esp === S.esp) && (!S.eq || r.eq === S.eq));
  const nResg = base.filter(r => rsDe(r)).length, nSent = base.filter(r => !rsDe(r) && isSent(r)).length;
  $('sTotal').textContent = base.length.toLocaleString('pt-BR');
  $('sSent').textContent = nSent.toLocaleString('pt-BR');
  $('sPend').textContent = (base.length - nSent - nResg).toLocaleString('pt-BR');
  $('sResg').textContent = nResg.toLocaleString('pt-BR');
  $('sGain').textContent = base.filter(r => r.dif != null && r.dif > 0).length.toLocaleString('pt-BR');
  const list = $('list');
  if (!rows.length) {
    // não está na lista do remarketing: procura nos cancelados recentes (aba Evolução da base)
    const q = norm($('q').value.trim()), qp = q.replace(/[^a-z0-9]/g, '');
    const cx = q && typeof E !== 'undefined' && E.data && E.data.canc ? E.data.canc.filter(r => (!E.team || r.t === E.team || r.lt === E.team) && (norm(r.n).includes(q) || (qp.length >= 3 && norm(r.pl).replace(/[^a-z0-9]/g, '').includes(qp)))) : [];
    list.innerHTML = '<p class="empty">Nenhum contato com esses filtros.</p>' + (cx.length ? `<div class="cx mid" style="grid-template-columns:1fr"><div><h3>${cx.length === 1 ? esc(cx[0].n) + ' está' : nf(cx.length) + ' associados com essa busca estão'} em <b>Cancelados recentes</b></h3>
      <p class="mot">Quem cancelou no mês passado ou neste mês não fica na lista do remarketing: fica em Cancelados recentes, na aba Evolução da base, com a mensagem e o botão do WhatsApp.</p>
      <div class="actions" style="margin-top:10px">${cx.slice(0, 5).map(r => `<button type="button" class="btn" data-goc="${esc(r.pl || r.n)}">Ver ${esc(r.n)}${r.pl ? ' · ' + esc(r.pl) : ''}</button>`).join('')}</div></div></div>` : '');
    return;
  }
  const part = rows.slice(0, S.shown);
  list.innerHTML = part.map(card).join('') +
    (rows.length > S.shown ? `<button class="btn more-btn" type="button" data-act="more">Mostrar mais (${(rows.length - S.shown).toLocaleString('pt-BR')} restantes)</button>` : '');
  list._rows = part;
}

function toast(t) { const el = $('toast'); el.textContent = t; el.hidden = false; clearTimeout(el._t); el._t = setTimeout(() => el.hidden = true, 2200); }

$('list').addEventListener('click', async ev => {
  const b = ev.target.closest('[data-act]'); if (!b) return;
  if (b.dataset.act === 'more') { S.shown += 50; render(); return; }
  const cardEl = b.closest('.card'); const idx = [...$('list').querySelectorAll('.card')].indexOf(cardEl);
  const r = $('list')._rows[idx]; if (!r) return;
  if (b.dataset.act === 'mark') {
    const on = !isSent(r), k = sentKey(r);
    MEM.set(k, on);
    sset('localStorage', k, on ? '1' : null);
    if (r._h) CLOUD.set(r._h, on ? Date.now() : 0);
    const y = window.scrollY; render(); window.scrollTo(0, y);
    cloudSet(r, on).then(() => saveNote());
  } else if (b.dataset.act === 'copy') {
    try { await navigator.clipboard.writeText(message(r)); toast('Mensagem copiada'); }
    catch (e) { cardEl.querySelector('details').open = true; const m = cardEl.querySelector('.msg'); const sel = getSelection(); const rg = document.createRange(); rg.selectNodeContents(m); sel.removeAllRanges(); sel.addRange(rg); toast('Selecionei a mensagem: copie com Ctrl+C'); }
  }
});
$('q').addEventListener('input', e => { S.q = e.target.value; S.shown = 50; render(); });
document.querySelectorAll('[data-t]').forEach(b => b.addEventListener('click', () => { S.type = b.dataset.t; document.querySelectorAll('[data-t]').forEach(x => x.setAttribute('aria-pressed', x === b)); S.shown = 50; render(); }));
document.querySelectorAll('[data-s]').forEach(b => b.addEventListener('click', () => { S.sit = b.dataset.s; document.querySelectorAll('[data-s]').forEach(x => x.setAttribute('aria-pressed', x === b)); S.shown = 50; render(); }));
{ const st = document.getElementById('stResg'), go = () => { const b = document.querySelector('[data-s="resg"]'); if (b) b.click(); };
  if (st) { st.addEventListener('click', go); st.addEventListener('keydown', e => { if (e.key === 'Enter' || e.key === ' ') { e.preventDefault(); go(); } }); } }
$('selEsp').addEventListener('change', e => { S.esp = e.target.value; S.shown = 50; render(); });
$('selEq').addEventListener('change', e => { S.eq = e.target.value; S.shown = 50; render(); });

let fails = 0, lockUntil = 0;
$('loginForm').addEventListener('submit', async ev => {
  ev.preventDefault();
  const err = $('err'); err.hidden = true;
  if (Date.now() < lockUntil) { err.textContent = 'Muitas tentativas. Aguarde 30 segundos e tente de novo.'; err.hidden = false; return; }
  const user = userKey($('u').value), pass = $('p').value.trim();
  if (!crypto.subtle || !window.DecompressionStream) { err.textContent = 'Este navegador é antigo demais. Abra o link no Chrome, Edge ou Safari atualizado.'; err.hidden = false; return; }
  $('go').disabled = true; $('go').textContent = 'Entrando…';
  try {
    const ring = await unlock(user, pass);
    const specs = await openRing(ring);
    sset('sessionStorage', 'retorno_exodus_sess', JSON.stringify(ring));
    fails = 0; startApp(specs, !!ring.admin, ring);
  } catch (x) {
    fails++; if (fails >= 5) { lockUntil = Date.now() + 30000; fails = 0; }
    err.textContent = x.message === 'user' ? 'Usuário não encontrado. Use seu primeiro e segundo nome, ex.: PAULO SERGIO.' : x.message === 'pass' ? 'Senha incorreta. Confira os 4 dígitos com a coordenação.' : 'Não foi possível abrir a lista neste navegador.';
    err.hidden = false;
  } finally { $('go').disabled = false; $('go').textContent = 'Entrar'; }
});
$('logout').addEventListener('click', () => { location.href = '/auth/sair'; });

// ---------- Sistema novo (Render): login pelo Google e dados de /api/dados ----------
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
})();
})();
