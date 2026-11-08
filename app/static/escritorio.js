/* Escritório do Especialista: tela de login, cadastro pelo link, menu principal e painel do administrador.
   Tudo que vem do servidor entra na tela como texto (função h), nunca como HTML. */
(() => {
  'use strict';
  const $ = id => document.getElementById(id);

  function h(tag, attrs, ...filhos) {
    const el = document.createElement(tag);
    for (const [k, v] of Object.entries(attrs || {})) {
      if (v === null || v === undefined || v === false) continue;
      if (k === 'class') el.className = v;
      else if (k.startsWith('on')) el.addEventListener(k.slice(2), v);
      else if (k === 'value') el.value = v;
      else el.setAttribute(k, v === true ? '' : v);
    }
    for (const f of filhos.flat()) if (f !== null && f !== undefined && f !== false) el.append(f instanceof Node ? f : String(f));
    return el;
  }
  const svg = (html, cls) => { const s = document.createElementNS('http://www.w3.org/2000/svg', 'svg'); s.setAttribute('viewBox', '0 0 24 24'); s.setAttribute('aria-hidden', 'true'); if (cls) s.setAttribute('class', cls); s.innerHTML = html; return s; };

  async function api(url, opcoes = {}) {
    const init = { credentials: 'same-origin', headers: {} };
    if (opcoes.metodo) init.method = opcoes.metodo;
    if (opcoes.corpo !== undefined) { init.method = init.method || 'POST'; init.headers['Content-Type'] = 'application/json'; init.body = JSON.stringify(opcoes.corpo); }
    const r = await fetch(url, init);
    let dados = {};
    try { dados = await r.json(); } catch (e) { /* resposta sem JSON */ }
    if (!r.ok) { const err = new Error(dados.erro || 'Não foi possível concluir. Tente de novo.'); err.status = r.status; throw err; }
    return dados;
  }

  let toastT;
  function toast(msg) { const t = $('toast'); t.textContent = msg; t.hidden = false; clearTimeout(toastT); toastT = setTimeout(() => { t.hidden = true; }, 2600); }

  function registrar(aba) { api('/api/acesso', { corpo: { aba } }).catch(() => {}); }

  /* ------------------------------------------------------------ login e cadastro */
  const G_ICON = '<path fill="#4285F4" d="M21.6 12.2c0-.7-.1-1.4-.2-2H12v3.8h5.4a4.6 4.6 0 0 1-2 3v2.5h3.2c1.9-1.7 3-4.3 3-7.3Z"/><path fill="#34A853" d="M12 22c2.7 0 5-.9 6.6-2.4l-3.2-2.5c-.9.6-2 1-3.4 1-2.6 0-4.8-1.8-5.6-4.1H3.1v2.6A10 10 0 0 0 12 22Z"/><path fill="#FBBC05" d="M6.4 14c-.2-.6-.3-1.3-.3-2s.1-1.4.3-2V7.4H3.1a10 10 0 0 0 0 9.2L6.4 14Z"/><path fill="#EA4335" d="M12 5.9c1.5 0 2.8.5 3.8 1.5l2.9-2.9A10 10 0 0 0 3.1 7.4L6.4 10c.8-2.4 3-4.1 5.6-4.1Z"/>';
  const botaoGoogle = (href) => h('a', { class: 'primary gbtn', id: 'go', href }, svg(G_ICON), 'Entrar com Google');

  function telaLogin(...conteudo) {
    $('app').hidden = true; $('login').hidden = false;
    $('loginBody').replaceChildren(...conteudo.flat().filter(Boolean));
  }

  const ERROS_URL = {
    google: 'O Google não confirmou o login. Tente de novo.',
    email: 'Sua conta Google não tem o e-mail confirmado. Use outra conta.',
  };

  function telaAnonimo(eu) {
    const erro = ERROS_URL[new URLSearchParams(location.search).get('erro')];
    telaLogin(
      eu.aviso ? h('p', { class: 'ok-msg' }, eu.aviso) : null,
      erro ? h('p', { class: 'err' }, erro) : null,
      eu.google_configurado === false ? h('p', { class: 'err' }, 'O login com Google ainda não foi configurado no servidor.') : null,
      botaoGoogle('/auth/login'),
      h('p', { class: 'hint' }, 'Use a sua conta Google. Primeiro acesso? Peça à coordenação o link de cadastro do seu tipo de acesso.'));
  }

  function telaNaoLiberado(eu, extra, sair) {
    telaLogin(
      extra ? h('p', { class: 'ok-msg' }, extra) : null,
      h('p', { class: 'err', id: 'naoLiberado' }, eu.mensagem || 'Seu acesso ainda não foi liberado. Fale com a coordenação.'),
      eu.email ? h('p', { class: 'quem' }, 'Conta Google: ', h('b', {}, eu.email)) : null,
      h('a', { class: 'btn sec', id: 'outraConta', href: sair || '/auth/sair' }, 'Entrar com outra conta'));
  }

  async function telaCadastro(codigo, eu) {
    let link;
    try { link = await api('/api/cadastro/' + encodeURIComponent(codigo)); } catch (e) { link = { valido: false, mensagem: e.message }; }
    if (!link.valido) return telaLogin(h('p', { class: 'err' }, link.mensagem), h('a', { class: 'btn sec', href: '/' }, 'Ir para o início'));
    $('loginSub').textContent = 'Cadastro de acesso: ' + link.tipo_nome + '.';
    // Sair mantendo o link: depois de sair, a pessoa volta para este cadastro (e não para o login comum).
    const sairComLink = '/auth/sair?link=' + encodeURIComponent(codigo);
    if (eu.estado === 'ativo') {
      return telaLogin(
        h('p', { class: 'hint', id: 'jaConectado' }, 'Você já está conectado como ', h('b', {}, eu.pessoa.nome),
          eu.pessoa.email ? ' (' + eu.pessoa.email + ')' : '', '. Este link é para cadastrar outra conta Google.'),
        h('a', { class: 'primary', id: 'sairCadastrar', href: sairComLink }, 'Sair e cadastrar outra conta'),
        h('a', { class: 'btn sec', href: '/' }, 'Continuar como ' + eu.pessoa.nome));
    }
    if (eu.estado === 'pendente' || eu.estado === 'bloqueado') return telaNaoLiberado(eu, null, sairComLink);
    if (eu.estado !== 'sem_cadastro') {
      // Quem abre o link sem estar logado vai direto para o login do Google.
      const destino = '/auth/login?link=' + encodeURIComponent(codigo);
      if (eu.google_configurado !== false) location.replace(destino);
      return telaLogin(
        h('p', { class: 'hint' }, eu.google_configurado !== false ? 'Abrindo o login do Google…' :
          'Entre com a sua conta Google. Depois, escreva o seu nome completo. A coordenação aprova o cadastro e libera o acesso.'),
        botaoGoogle(destino));
    }
    const nome = h('input', { class: 'field', id: 'cadNome', name: 'nome', autocomplete: 'name', required: true, minlength: 3, maxlength: 120, value: eu.nome || '' });
    const erro = h('p', { class: 'err', hidden: true });
    const enviar = h('button', { class: 'primary', type: 'submit', id: 'cadEnviar' }, 'Enviar cadastro');
    const form = h('form', { class: 'login-body', id: 'cadForm', onsubmit: async ev => {
      ev.preventDefault(); erro.hidden = true; enviar.disabled = true;
      try {
        const r = await api('/api/cadastro/' + encodeURIComponent(codigo), { corpo: { nome: nome.value } });
        history.replaceState(null, '', '/');
        telaNaoLiberado({ mensagem: r.mensagem, email: eu.email }, 'Cadastro enviado. Assim que a coordenação aprovar, é só entrar com o Google.');
      } catch (e) { erro.textContent = e.message; erro.hidden = false; enviar.disabled = false; }
    } },
      h('p', { class: 'quem' }, 'Conta Google: ', h('b', {}, eu.email), ' · ', h('a', { href: sairComLink }, 'usar outra conta')),
      h('label', { for: 'cadNome' }, 'Nome completo', nome),
      erro, enviar);
    $('app').hidden = true; $('login').hidden = false;
    $('loginBody').replaceWith(Object.assign(form, { id: 'loginBody' }));
  }

  /* ------------------------------------------------------------ app */
  let EU = null;
  const HOME_ARROW = '<path d="M5 12h14M13 6l6 6-6 6"/>';
  const CARDS = {
    adm: { t: 'Painel do administrador', d: 'Cadastros, links de cadastro e acessos: quem entrou, quando e quantas vezes.', cls: 'g-adm',
      ic: '<path d="M12 3l8 3v6c0 4.5-3.4 8.2-8 9-4.6-.8-8-4.5-8-9V6l8-3Z"/><path d="M9 12l2 2 4-4"/>' },
  };

  function telaApp(eu) {
    EU = eu; $('login').hidden = true; $('app').hidden = false;
    const p = eu.pessoa;
    $('hName').textContent = p.nome;
    $('hWho').textContent = [p.tipo_nome, p.equipe ? 'Equipe ' + p.equipe : null].filter(Boolean).join(' · ');
    carregarAtualizar();
    if (location.hash === '#painel' && eu.painel) abrirPainel(); else irMenu();
  }

  async function carregarAtualizar() {
    try {
      const s = await api('/api/meus-dados/situacao');
      $('updTexto').textContent = s.texto;
      $('updUltima').textContent = s.ultima_atualizacao_txt ? 'Última atualização: ' + s.ultima_atualizacao_txt : 'Disponível em breve.';
      $('btnAtualizar').disabled = !s.disponivel;
    } catch (e) { $('upd').hidden = true; }
  }

  async function irMenu() {
    $('app').classList.add('mhome'); $('adminView').hidden = true; $('btnHome').hidden = true;
    $('coverEyebrow').textContent = 'Menu principal'; $('coverTitle').textContent = 'Escritório do Especialista';
    if (location.hash) history.replaceState(null, '', location.pathname);
    const cards = EU.painel ? ['adm'] : [];
    $('home').hidden = !cards.length; $('homeVazio').hidden = !!cards.length;
    $('home').replaceChildren(...cards.map((k, i) => {
      const c = CARDS[k];
      return h('button', { type: 'button', class: 'pcard ' + c.cls, 'data-go': k, onclick: () => abrirPainel() },
        h('span', { class: 'pv' }, h('span', { class: 'pn' }, String(i + 1).padStart(2, '0')), svg(c.ic, 'pbig')),
        h('span', { class: 'pb' }, h('span', { class: 'pic' }, svg(c.ic)), h('h3', {}, c.t), h('p', {}, c.d)),
        h('span', { class: 'pf' }, h('span', { class: 'pfs', id: 'pfs-' + k }, 'Abrir'), h('span', { class: 'pgo' }, 'Abrir', svg(HOME_ARROW))));
    }));
    registrar('menu'); window.scrollTo(0, 0);
    if (EU.painel) {
      try { const r = await api('/api/admin/pessoas?situacao=pendente'); const n = r.pessoas.length;
        $('pfs-adm').textContent = n ? n + (n === 1 ? ' cadastro pendente' : ' cadastros pendentes') : 'Nenhum cadastro pendente';
      } catch (e) { /* o card continua com "Abrir" */ }
    }
  }
  $('btnHome').addEventListener('click', irMenu);

  /* ------------------------------------------------------------ painel do administrador */
  let OP = null; // opções: tipos, equipes, líderes
  const ABA_NOME = { entrada: 'Entrou', menu: 'Menu principal', admin_cadastros: 'Painel: Cadastros', admin_links: 'Painel: Links', admin_acessos: 'Painel: Acessos' };
  const SIT_CHIP = { pendente: ['chip pend', 'Pendente'], ativo: ['chip ok', 'Ativo'], bloqueado: ['chip bloq', 'Bloqueado'] };

  async function abrirPainel(parte) {
    $('app').classList.remove('mhome'); $('home').hidden = true; $('homeVazio').hidden = true; $('adminView').hidden = false; $('btnHome').hidden = false;
    $('coverEyebrow').textContent = 'Painel do administrador'; $('coverTitle').textContent = 'Cadastros e acessos';
    if (location.hash !== '#painel') history.replaceState(null, '', '#painel');
    window.scrollTo(0, 0);
    try { OP = await api('/api/admin/opcoes'); } catch (e) { toast(e.message); return; }
    mostrarParte(parte || 'cad');
  }

  function mostrarParte(parte) {
    document.querySelectorAll('[data-adm]').forEach(b => b.setAttribute('aria-pressed', String(b.dataset.adm === parte)));
    $('admCad').hidden = parte !== 'cad'; $('admLnk').hidden = parte !== 'lnk'; $('admAcs').hidden = parte !== 'acs';
    if (parte === 'cad') { registrar('admin_cadastros'); carregarCadastros(); }
    if (parte === 'lnk') { registrar('admin_links'); carregarLinks(); }
    if (parte === 'acs') { registrar('admin_acessos'); prepararAcessos(); }
  }
  document.querySelectorAll('[data-adm]').forEach(b => b.addEventListener('click', () => mostrarParte(b.dataset.adm)));

  const opcoesSelect = (lista, atual, vazio) => [...(vazio !== undefined ? [h('option', { value: '' }, vazio)] : []),
    ...lista.map(o => h('option', { value: o.id, selected: String(o.id) === String(atual ?? '') }, o.nome))];

  /* Cadastros */
  let filtroSit = 'pendente', buscaT;
  document.querySelectorAll('#cadFiltro [data-sit]').forEach(b => b.addEventListener('click', () => {
    filtroSit = b.dataset.sit;
    document.querySelectorAll('#cadFiltro [data-sit]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    carregarCadastros();
  }));
  $('cadBusca').addEventListener('input', () => { clearTimeout(buscaT); buscaT = setTimeout(carregarCadastros, 250); });

  async function carregarCadastros() {
    const q = new URLSearchParams({ situacao: filtroSit, q: $('cadBusca').value });
    let r;
    try { r = await api('/api/admin/pessoas?' + q); } catch (e) { toast(e.message); return; }
    $('cadLista').replaceChildren(...(r.pessoas.length ? r.pessoas.map(cartaoPessoa)
      : [h('p', { class: 'empty' }, filtroSit === 'pendente' ? 'Nenhum cadastro pendente.' : 'Nenhum cadastro encontrado.')]));
  }

  function cartaoPessoa(p) {
    const eu = p.id === EU.pessoa.id;
    const [chipCls, chipTxt] = SIT_CHIP[p.situacao] || ['chip', p.situacao];
    const f = {
      nome: h('input', { class: 'field', value: p.nome, maxlength: 120 }),
      tipo: h('select', { class: 'field', disabled: eu }, ...opcoesSelect(OP.tipos, p.tipo)),
      equipe: h('select', { class: 'field' }, ...opcoesSelect(OP.equipes.map(e => ({ id: e, nome: e })), p.equipe, 'Sem equipe')),
      nome_sga: h('input', { class: 'field', value: p.nome_sga || '', maxlength: 160, placeholder: 'EX.: JOAO DA SILVA' }),
      lider_id: h('select', { class: 'field' }, ...opcoesSelect(OP.lideres.filter(l => l.id !== p.id).map(l => ({ id: l.id, nome: l.nome + (l.equipe ? ' (' + l.equipe + ')' : '') })), p.lider_id, 'Sem líder')),
    };
    const campoLider = h('label', {}, 'Líder', f.lider_id);
    const ajustaLider = () => { campoLider.hidden = f.tipo.value !== 'especialista'; };
    f.tipo.addEventListener('change', ajustaLider); ajustaLider();
    const form = h('div', { class: 'pc-form', hidden: p.situacao !== 'pendente' },
      h('label', {}, 'Nome', f.nome), h('label', {}, 'Tipo de acesso', f.tipo), h('label', {}, 'Equipe', f.equipe),
      h('label', {}, 'Nome no SGA ', h('small', {}, '(exatamente como está no SGA)'), f.nome_sga), campoLider);
    const erro = h('p', { class: 'err', hidden: true });
    const valores = () => ({ nome: f.nome.value, tipo: f.tipo.value, equipe: f.equipe.value || null, nome_sga: f.nome_sga.value || null,
      lider_id: f.tipo.value === 'especialista' && f.lider_id.value ? Number(f.lider_id.value) : null });

    async function salvar(btn, corpo, msg) {
      erro.hidden = true; btn.disabled = true;
      try { await api('/api/admin/pessoas/' + p.id, { metodo: 'PATCH', corpo }); toast(msg); OP = await api('/api/admin/opcoes'); carregarCadastros(); }
      catch (e) { erro.textContent = e.message; erro.hidden = false; form.hidden = false; btn.disabled = false; }
    }
    const botoes = [];
    const b = (txt, cls, fn) => { const el = h('button', { type: 'button', class: 'btn ' + cls, onclick: () => fn(el) }, txt); botoes.push(el); return el; };
    if (p.situacao === 'pendente') b('Aprovar', 'go', el => salvar(el, { ...valores(), situacao: 'ativo' }, 'Cadastro aprovado.'));
    if (p.situacao === 'bloqueado') b('Liberar acesso', 'go', el => salvar(el, { ...valores(), situacao: 'ativo' }, 'Acesso liberado.'));
    if (p.situacao !== 'pendente') {
      const editar = b('Editar', '', el => {
        if (form.hidden) { form.hidden = false; el.textContent = 'Salvar'; return; }
        salvar(el, valores(), 'Cadastro salvo.');
      });
      editar.dataset.acao = 'editar';
    }
    if (p.situacao !== 'bloqueado' && !eu) b('Bloquear', 'no', el => { if (confirm('Bloquear o acesso de ' + p.nome + '?')) salvar(el, { situacao: 'bloqueado' }, 'Acesso bloqueado.'); });

    const meta = [p.email || 'sem e-mail Google', p.equipe ? 'Equipe ' + p.equipe : null, p.nome_sga ? 'SGA: ' + p.nome_sga : null,
      p.lider_nome ? 'Líder: ' + p.lider_nome : null, 'Cadastro: ' + p.criado_em_txt, p.aprovado_em_txt ? 'Aprovado: ' + p.aprovado_em_txt : null].filter(Boolean);
    return h('article', { class: 'pc ' + p.situacao, 'data-pessoa': p.id },
      h('div', { class: 'pc-head' }, h('h3', {}, p.nome), h('span', { class: 'chip' }, p.tipo_nome), h('span', { class: chipCls }, chipTxt), eu ? h('span', { class: 'chip' }, 'Você') : null),
      h('div', { class: 'meta' }, ...meta.map(m => h('span', {}, m))),
      form, erro, h('div', { class: 'pc-act' }, ...botoes));
  }

  /* Links de cadastro */
  async function carregarLinks() {
    const sel = $('lnkTipo');
    if (!sel.options.length) sel.replaceChildren(...opcoesSelect(OP.tipos.filter(t => t.id !== 'admin' || EU.pessoa.tipo === 'admin'), 'especialista'));
    let r;
    try { r = await api('/api/admin/links'); } catch (e) { toast(e.message); return; }
    const SIT = { ativo: ['chip ok', 'Ativo'], vencido: ['chip alert', 'Vencido'], desativado: ['chip', 'Desativado'] };
    $('lnkTabela').replaceChildren(
      h('thead', {}, h('tr', {}, ...['Tipo', 'Link', 'Situação', 'Pessoas cadastradas', 'Válido até', 'Criado em', ''].map(t => h('th', {}, t)))),
      h('tbody', {}, ...(r.links.length ? r.links.map(l => {
        const campo = h('input', { readonly: true, value: l.url, 'aria-label': 'Link de cadastro', onfocus: e => e.target.select() });
        const [cc, ct] = SIT[l.situacao];
        return h('tr', { 'data-link': l.id, 'data-codigo': l.codigo },
          h('td', { class: 'nw' }, l.tipo_nome),
          h('td', {}, h('div', { class: 'lnk' }, campo, h('button', { type: 'button', class: 'btn', onclick: () => copiar(campo) }, 'Copiar'))),
          h('td', {}, h('span', { class: cc }, ct)),
          h('td', { class: 'r' }, l.usos),
          h('td', { class: 'nw' }, l.validade_txt || 'Sem validade'),
          h('td', { class: 'nw' }, l.criado_em_txt),
          h('td', {}, h('button', { type: 'button', class: 'btn' + (l.ativo ? ' no' : ''), onclick: async () => {
            try { await api('/api/admin/links/' + l.id, { metodo: 'PATCH', corpo: { ativo: !l.ativo } }); toast(l.ativo ? 'Link desativado.' : 'Link reativado.'); carregarLinks(); }
            catch (e) { toast(e.message); } } }, l.ativo ? 'Desativar' : 'Reativar')));
      }) : [h('tr', {}, h('td', { colspan: 7, class: 'empty' }, 'Nenhum link gerado ainda.'))])));
  }

  async function copiar(campo) {
    try { await navigator.clipboard.writeText(campo.value); }
    catch (e) { campo.select(); document.execCommand('copy'); }
    toast('Link copiado.');
  }

  $('lnkForm').addEventListener('submit', async ev => {
    ev.preventDefault();
    try { await api('/api/admin/links', { corpo: { tipo: $('lnkTipo').value, validade: $('lnkValidade').value || null } });
      toast('Link gerado.'); $('lnkValidade').value = ''; carregarLinks(); }
    catch (e) { toast(e.message); }
  });

  /* Acessos */
  async function prepararAcessos() {
    try {
      const todos = await api('/api/admin/pessoas');
      const atual = $('acsPessoa').value;
      $('acsPessoa').replaceChildren(...opcoesSelect(todos.pessoas.map(p => ({ id: p.id, nome: p.nome })), atual, 'Todas as pessoas'));
      if (!$('acsEquipe').options.length) $('acsEquipe').replaceChildren(...opcoesSelect(OP.equipes.map(e => ({ id: e, nome: e })), '', 'Todas as equipes'));
    } catch (e) { toast(e.message); return; }
    carregarAcessos();
  }
  $('acsForm').addEventListener('submit', ev => { ev.preventDefault(); carregarAcessos(); });

  async function carregarAcessos() {
    const q = new URLSearchParams();
    for (const [k, id] of [['pessoa_id', 'acsPessoa'], ['equipe', 'acsEquipe'], ['de', 'acsDe'], ['ate', 'acsAte']]) if ($(id).value) q.set(k, $(id).value);
    let r;
    try { r = await api('/api/admin/acessos?' + q); } catch (e) { toast(e.message); return; }
    const nomeAba = a => ABA_NOME[a] || a;
    $('acsResumo').replaceChildren(
      h('thead', {}, h('tr', {}, ...['Pessoa', 'Equipe', 'Entradas', 'Último acesso', 'Primeiro acesso', 'Abas abertas'].map((t, i) => h('th', { class: i === 2 ? 'r' : null }, t)))),
      h('tbody', {}, ...(r.resumo.length ? r.resumo.map(x => h('tr', { 'data-pessoa': x.pessoa_id },
        h('td', {}, x.nome, h('small', { class: 'sub' }, x.tipo_nome)), h('td', { class: 'nw' }, x.equipe || '—'),
        h('td', { class: 'r' }, x.entradas), h('td', { class: 'nw' }, x.ultimo_txt), h('td', { class: 'nw' }, x.primeiro_txt),
        h('td', {}, h('div', { class: 'abas' }, ...Object.entries(x.abas).map(([a, n]) => h('span', { class: 'chip' }, nomeAba(a) + ' · ' + n))))))
        : [h('tr', {}, h('td', { colspan: 6, class: 'empty' }, 'Nenhum acesso no período.'))])));
    $('acsEventos').replaceChildren(
      h('thead', {}, h('tr', {}, ...['Data e hora', 'Pessoa', 'Equipe', 'O que fez', 'IP (resumido)'].map(t => h('th', {}, t)))),
      h('tbody', {}, ...(r.eventos.length ? r.eventos.map(x => h('tr', {},
        h('td', { class: 'nw' }, x.data_hora_txt), h('td', {}, x.nome), h('td', { class: 'nw' }, x.equipe || '—'),
        h('td', {}, nomeAba(x.aba)), h('td', { class: 'nw' }, x.ip || '—')))
        : [h('tr', {}, h('td', { colspan: 5, class: 'empty' }, 'Nenhum acesso no período.'))])));
  }

  /* ------------------------------------------------------------ início */
  async function iniciar() {
    let eu;
    try { eu = await api('/api/eu'); } catch (e) { return telaLogin(h('p', { class: 'err' }, 'Não foi possível falar com o servidor. Aperte F5 para tentar de novo.')); }
    const m = location.pathname.match(/^\/cadastro\/([^/]+)$/);
    if (m) return telaCadastro(decodeURIComponent(m[1]), eu);
    if (eu.estado === 'ativo') return telaApp(eu);
    if (eu.estado === 'anonimo') return telaAnonimo(eu);
    return telaNaoLiberado(eu);
  }
  iniciar();
})();
