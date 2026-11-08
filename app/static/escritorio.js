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

  // Primeiro acesso: CPF (acha o cadastro feito pela coordenação) e WhatsApp (contato). Depois, o Google.
  function formPrimeiroAcesso(jaEntrou) {
    const cpf = h('input', { class: 'field', id: 'paCpf', name: 'cpf', inputmode: 'numeric', autocomplete: 'off', required: true, maxlength: 14, placeholder: '000.000.000-00' });
    const whats = h('input', { class: 'field', id: 'paWhats', name: 'whatsapp', type: 'tel', inputmode: 'tel', autocomplete: 'tel', required: true, maxlength: 20, placeholder: '(21) 98765-4321' });
    const erro = h('p', { class: 'err', id: 'paErro', hidden: true });
    const enviar = jaEntrou ? h('button', { class: 'primary', type: 'submit', id: 'paEnviar' }, 'Liberar meu acesso')
      : h('button', { class: 'btn sec gbtn', type: 'submit', id: 'paEnviar' }, svg(G_ICON), 'Continuar com Google');
    return h('form', { class: 'pa', id: 'paForm', onsubmit: async ev => {
      ev.preventDefault(); erro.hidden = true; enviar.disabled = true;
      try { const r = await api('/api/primeiro-acesso', { corpo: { cpf: cpf.value, whatsapp: whats.value } }); location.assign(r.proximo); }
      catch (e) { erro.textContent = e.message; erro.hidden = false; enviar.disabled = false; }
    } }, h('label', { for: 'paCpf' }, 'CPF', cpf), h('label', { for: 'paWhats' }, 'WhatsApp (com DDD)', whats), erro, enviar);
  }

  function telaAnonimo(eu) {
    const erro = ERROS_URL[new URLSearchParams(location.search).get('erro')];
    telaLogin(
      eu.aviso ? h('p', { class: 'ok-msg' }, eu.aviso) : null,
      erro ? h('p', { class: 'err' }, erro) : null,
      eu.google_configurado === false ? h('p', { class: 'err' }, 'O login com Google ainda não foi configurado no servidor.') : null,
      botaoGoogle('/auth/login'),
      h('p', { class: 'hint' }, 'Já fez o primeiro acesso? É só entrar com a sua conta Google.'),
      h('div', { class: 'sep' }, h('span', {}, 'Primeiro acesso')),
      h('p', { class: 'hint' }, 'Informe o seu CPF e o seu WhatsApp e continue com a sua conta Google. Ela passa a ser o seu acesso ao escritório.'),
      formPrimeiroAcesso(false));
  }

  function telaSemCadastro(eu) {
    telaLogin(
      h('p', { class: 'quem' }, 'Conta Google: ', h('b', {}, eu.email)),
      h('p', { class: 'hint', id: 'semCadastro' }, 'É o seu primeiro acesso. Informe o seu CPF e o seu WhatsApp para liberar o escritório nesta conta Google.'),
      formPrimeiroAcesso(true),
      h('a', { class: 'btn sec', id: 'outraConta', href: '/auth/sair' }, 'Entrar com outra conta'));
  }

  function telaNaoLiberado(eu, extra) {
    telaLogin(
      extra ? h('p', { class: 'ok-msg' }, extra) : null,
      h('p', { class: 'err', id: 'naoLiberado' }, eu.mensagem || 'Seu acesso ainda não foi liberado. Fale com a coordenação.'),
      eu.email ? h('p', { class: 'quem' }, 'Conta Google: ', h('b', {}, eu.email)) : null,
      h('a', { class: 'btn sec', id: 'outraConta', href: '/auth/sair' }, 'Entrar com outra conta'));
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
      try { const r = await api('/api/admin/pessoas?situacao=aguardando'); const n = r.pessoas.length;
        $('pfs-adm').textContent = n ? n + (n === 1 ? ' pessoa aguardando 1º acesso' : ' pessoas aguardando 1º acesso') : 'Todos os cadastrados já entraram';
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
    $('admCad').hidden = parte !== 'cad'; $('admAcs').hidden = parte !== 'acs';
    if (parte === 'cad') { registrar('admin_cadastros'); carregarCadastros(); }
    if (parte === 'acs') { registrar('admin_acessos'); prepararAcessos(); }
  }
  document.querySelectorAll('[data-adm]').forEach(b => b.addEventListener('click', () => mostrarParte(b.dataset.adm)));

  const opcoesSelect = (lista, atual, vazio) => [...(vazio !== undefined ? [h('option', { value: '' }, vazio)] : []),
    ...lista.map(o => h('option', { value: o.id, selected: String(o.id) === String(atual ?? '') }, o.nome))];

  /* Cadastros */
  let filtroSit = '', buscaT;
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
    prepararNovo();
  }

  function prepararNovo() {
    if ($('novoTipo').options.length) {  // só atualiza a lista de líderes
      $('novoLider').replaceChildren(...opcoesSelect(OP.lideres.map(l => ({ id: l.id, nome: l.nome + (l.equipe ? ' (' + l.equipe + ')' : '') })), $('novoLider').value, 'Sem líder'));
      return;
    }
    $('novoTipo').replaceChildren(...opcoesSelect(OP.tipos.filter(t => t.id !== 'admin' || EU.pessoa.tipo === 'admin'), 'especialista'));
    $('novoEquipe').replaceChildren(...opcoesSelect(OP.equipes.map(e => ({ id: e, nome: e })), '', 'Sem equipe'));
    $('novoLider').replaceChildren(...opcoesSelect(OP.lideres.map(l => ({ id: l.id, nome: l.nome + (l.equipe ? ' (' + l.equipe + ')' : '') })), '', 'Sem líder'));
    const ajusta = () => { $('novoLiderCampo').hidden = $('novoTipo').value !== 'especialista'; };
    $('novoTipo').addEventListener('change', ajusta); ajusta();
  }

  $('novoForm').addEventListener('submit', async ev => {
    ev.preventDefault(); $('novoErro').hidden = true;
    const corpo = { nome: $('novoNome').value, tipo: $('novoTipo').value, cpf: $('novoCpf').value, equipe: $('novoEquipe').value || null,
      nome_sga: $('novoSga').value || null, whatsapp: $('novoWhats').value || null,
      lider_id: $('novoTipo').value === 'especialista' && $('novoLider').value ? Number($('novoLider').value) : null };
    try {
      await api('/api/admin/pessoas', { corpo });
      toast('Cadastro feito. No primeiro acesso, a pessoa informa o CPF e entra com o Google.');
      for (const id of ['novoNome', 'novoCpf', 'novoSga', 'novoWhats']) $(id).value = '';
      OP = await api('/api/admin/opcoes'); carregarCadastros();
    } catch (e) { $('novoErro').textContent = e.message; $('novoErro').hidden = false; }
  });

  $('impArquivo').addEventListener('change', async ev => {
    const arq = ev.target.files[0]; if (!arq) return;
    $('impTexto').value = await arq.text(); ev.target.value = '';
  });

  $('impEnviar').addEventListener('click', async () => {
    const res = $('impResultado'); res.replaceChildren(); $('impEnviar').disabled = true;
    try {
      const r = await api('/api/admin/importar', { corpo: { texto: $('impTexto').value } });
      if (r.importado) {
        res.replaceChildren(h('p', { class: 'ok-msg' }, 'Planilha importada: ' + r.criados + ' cadastro(s) novo(s) e ' + r.atualizados + ' atualizado(s).'));
        $('impTexto').value = ''; OP = await api('/api/admin/opcoes'); carregarCadastros();
      } else {
        res.replaceChildren(h('p', { class: 'err' }, 'Nada foi gravado. Corrija estas linhas da planilha e importe de novo:'),
          h('ul', { class: 'imp-res' }, ...r.erros.map(e => h('li', {}, 'Linha ' + e.linha + ': ' + e.mensagem))));
      }
    } catch (e) { res.replaceChildren(h('p', { class: 'err' }, e.message)); }
    $('impEnviar').disabled = false;
  });

  function cartaoPessoa(p) {
    const eu = p.id === EU.pessoa.id;
    const [chipCls, chipTxt] = SIT_CHIP[p.situacao] || ['chip', p.situacao];
    const f = {
      nome: h('input', { class: 'field', value: p.nome, maxlength: 120 }),
      tipo: h('select', { class: 'field', disabled: eu }, ...opcoesSelect(OP.tipos, p.tipo)),
      equipe: h('select', { class: 'field' }, ...opcoesSelect(OP.equipes.map(e => ({ id: e, nome: e })), p.equipe, 'Sem equipe')),
      nome_sga: h('input', { class: 'field', value: p.nome_sga || '', maxlength: 160, placeholder: 'EX.: JOAO DA SILVA' }),
      lider_id: h('select', { class: 'field' }, ...opcoesSelect(OP.lideres.filter(l => l.id !== p.id).map(l => ({ id: l.id, nome: l.nome + (l.equipe ? ' (' + l.equipe + ')' : '') })), p.lider_id, 'Sem líder')),
      cpf: h('input', { class: 'field', value: p.cpf || '', inputmode: 'numeric', maxlength: 14 }),
      whatsapp: h('input', { class: 'field', value: p.whatsapp || '', type: 'tel', maxlength: 20 }),
    };
    const campoLider = h('label', {}, 'Líder', f.lider_id);
    const ajustaLider = () => { campoLider.hidden = f.tipo.value !== 'especialista'; };
    f.tipo.addEventListener('change', ajustaLider); ajustaLider();
    const form = h('div', { class: 'pc-form', hidden: p.situacao !== 'pendente' },
      h('label', {}, 'Nome', f.nome), h('label', {}, 'Tipo de acesso', f.tipo), h('label', {}, 'Equipe', f.equipe),
      h('label', {}, 'Nome no SGA ', h('small', {}, '(exatamente como está no SGA)'), f.nome_sga), campoLider,
      h('label', {}, 'CPF', f.cpf), h('label', {}, 'WhatsApp', f.whatsapp));
    const erro = h('p', { class: 'err', hidden: true });
    const valores = () => ({ nome: f.nome.value, tipo: f.tipo.value, equipe: f.equipe.value || null, nome_sga: f.nome_sga.value || null,
      cpf: f.cpf.value || null, whatsapp: f.whatsapp.value || null,
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

    const meta = [p.cpf ? 'CPF ' + p.cpf : null, p.whatsapp ? 'WhatsApp ' + p.whatsapp : null, p.email || 'ainda não entrou com o Google',
      p.equipe ? 'Equipe ' + p.equipe : null, p.nome_sga ? 'SGA: ' + p.nome_sga : null,
      p.lider_nome ? 'Líder: ' + p.lider_nome : null, 'Cadastro: ' + p.criado_em_txt, p.vinculado_em_txt ? '1º acesso: ' + p.vinculado_em_txt : null].filter(Boolean);
    const aguardando = p.aguardando_primeiro_acesso && p.situacao !== 'bloqueado';
    return h('article', { class: 'pc ' + p.situacao, 'data-pessoa': p.id },
      h('div', { class: 'pc-head' }, h('h3', {}, p.nome), h('span', { class: 'chip' }, p.tipo_nome),
        aguardando ? h('span', { class: 'chip aguarda' }, 'Aguardando 1º acesso') : h('span', { class: chipCls }, chipTxt),
        p.faltando.length ? h('span', { class: 'chip alert' }, 'Falta: ' + p.faltando.join(', ')) : null,
        eu ? h('span', { class: 'chip' }, 'Você') : null),
      h('div', { class: 'meta' }, ...meta.map(m => h('span', {}, m))),
      form, erro, h('div', { class: 'pc-act' }, ...botoes));
  }

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
    if (eu.estado === 'ativo') return telaApp(eu);
    if (eu.estado === 'anonimo') return telaAnonimo(eu);
    if (eu.estado === 'sem_cadastro') return telaSemCadastro(eu);
    return telaNaoLiberado(eu);
  }
  iniciar();
})();
