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

  // Entrada: CPF (acha o cadastro feito pela coordenação) e WhatsApp (contato). O botão do Google só libera
  // depois dos dois preenchidos (decisão de 08/11: senão as pessoas não preenchem o telefone).
  function formPrimeiroAcesso(jaEntrou) {
    const cpf = h('input', { class: 'field', id: 'paCpf', name: 'cpf', inputmode: 'numeric', autocomplete: 'off', required: true, maxlength: 14, placeholder: '000.000.000-00' });
    const whats = h('input', { class: 'field', id: 'paWhats', name: 'whatsapp', type: 'tel', inputmode: 'tel', autocomplete: 'tel', required: true, maxlength: 20, placeholder: '(21) 98765-4321' });
    const erro = h('p', { class: 'err', id: 'paErro', hidden: true });
    const enviar = jaEntrou ? h('button', { class: 'primary', type: 'submit', id: 'paEnviar', disabled: true }, 'Liberar meu acesso')
      : h('button', { class: 'primary gbtn', type: 'submit', id: 'paEnviar', disabled: true }, svg(G_ICON), 'Entrar com Google');
    const aviso = h('p', { class: 'hint', id: 'paAviso' }, 'Preencha o CPF e o WhatsApp para liberar o botão.');
    const numeros = v => v.replace(/\D/g, '');
    const confere = () => {
      const ok = numeros(cpf.value).length === 11 && numeros(whats.value).length >= 10;
      enviar.disabled = !ok; aviso.hidden = ok;
    };
    cpf.addEventListener('input', confere); whats.addEventListener('input', confere);
    return h('form', { class: 'pa', id: 'paForm', onsubmit: async ev => {
      ev.preventDefault(); erro.hidden = true; enviar.disabled = true;
      try { const r = await api('/api/primeiro-acesso', { corpo: { cpf: cpf.value, whatsapp: whats.value } }); location.assign(r.proximo); }
      catch (e) { erro.textContent = e.message; erro.hidden = false; enviar.disabled = false; }
    } }, h('label', { for: 'paCpf' }, 'CPF', cpf), h('label', { for: 'paWhats' }, 'WhatsApp (com DDD)', whats), erro, enviar, aviso);
  }

  function telaAnonimo(eu) {
    const erro = ERROS_URL[new URLSearchParams(location.search).get('erro')];
    telaLogin(
      eu.aviso ? h('p', { class: 'ok-msg' }, eu.aviso) : null,
      erro ? h('p', { class: 'err' }, erro) : null,
      eu.google_configurado === false ? h('p', { class: 'err' }, 'O login com Google ainda não foi configurado no servidor.') : null,
      h('p', { class: 'hint' }, 'Informe o seu CPF e o seu WhatsApp e entre com a sua conta Google. No primeiro acesso, essa conta Google passa a ser o seu acesso ao escritório.'),
      formPrimeiroAcesso(false),
      h('p', { class: 'hint adm-link' }, h('a', { href: '/auth/login', id: 'entrarAdmin' }, 'Acesso do administrador')));
  }

  function telaSemCadastro(eu) {
    if (eu.dica) return telaNaoLiberado(eu);
    telaLogin(
      h('p', { class: 'quem' }, 'Conta Google: ', h('b', {}, eu.email)),
      h('p', { class: 'hint', id: 'semCadastro' }, 'É o seu primeiro acesso. Informe o seu CPF e o seu WhatsApp para liberar o escritório nesta conta Google.'),
      formPrimeiroAcesso(true),
      h('a', { class: 'btn sec', id: 'outraConta', href: '/auth/sair' }, 'Entrar com outra conta'));
  }

  function telaNaoLiberado(eu, extra) {
    telaLogin(
      extra ? h('p', { class: 'ok-msg' }, extra) : null,
      eu.dica ? h('p', { class: 'ok-msg', id: 'dicaConta' }, eu.dica) : h('p', { class: 'err', id: 'naoLiberado' }, eu.mensagem || 'Seu acesso ainda não foi liberado. Fale com a coordenação.'),
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
  const ABA_NOME = { entrada: 'Entrou', menu: 'Menu principal', admin_cadastros: 'Painel: Cadastros', admin_links: 'Painel: Links', admin_acessos: 'Painel: Acessos', admin_atualizacoes: 'Painel: Atualizações' };
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
    $('admCad').hidden = parte !== 'cad'; $('admAcs').hidden = parte !== 'acs'; $('admAtu').hidden = parte !== 'atu';
    if (parte === 'cad') { registrar('admin_cadastros'); carregarCadastros(); }
    if (parte === 'acs') { registrar('admin_acessos'); prepararAcessos(); }
    if (parte === 'atu') { registrar('admin_atualizacoes'); carregarAtualizacoes(); }
  }
  document.querySelectorAll('[data-adm]').forEach(b => b.addEventListener('click', () => mostrarParte(b.dataset.adm)));

  const opcoesSelect = (lista, atual, vazio) => [...(vazio !== undefined ? [h('option', { value: '' }, vazio)] : []),
    ...lista.map(o => h('option', { value: o.id, selected: String(o.id) === String(atual ?? '') }, o.nome))];

  /* Cadastros (tabela: uma linha por pessoa; E-mail Google e WhatsApp se preenchem no primeiro acesso) */
  let filtroSit = '', buscaT;
  document.querySelectorAll('#cadFiltro [data-sit]').forEach(b => b.addEventListener('click', () => {
    filtroSit = b.dataset.sit;
    document.querySelectorAll('#cadFiltro [data-sit]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    carregarCadastros();
  }));
  $('cadBusca').addEventListener('input', () => { clearTimeout(buscaT); buscaT = setTimeout(carregarCadastros, 250); });

  const vazio = txt => h('span', { class: 'vazio' }, txt);
  const opcoesLider = (atual, menos) => opcoesSelect(OP.lideres.filter(l => l.id !== menos).map(l => ({ id: l.id, nome: l.nome + (l.equipe ? ' (' + l.equipe + ')' : '') })), atual, 'Sem líder');

  function caixasEquipes(marcadas) {
    const caixa = h('div', { class: 'equipes' }, ...OP.equipes.map(e => h('label', {}, h('input', { type: 'checkbox', value: e, checked: (marcadas || []).includes(e) }), e)));
    caixa.valor = () => [...caixa.querySelectorAll('input:checked')].map(i => i.value);
    return caixa;
  }

  async function carregarCadastros() {
    const q = new URLSearchParams({ situacao: filtroSit, q: $('cadBusca').value });
    let r;
    try { r = await api('/api/admin/pessoas?' + q); } catch (e) { toast(e.message); return; }
    $('cadTotal').textContent = r.pessoas.length + (r.pessoas.length === 1 ? ' cadastro' : ' cadastros');
    $('cadTabela').replaceChildren(
      h('thead', {}, h('tr', {}, ...['Nome', 'CPF', 'Telefone (WhatsApp)', 'E-mail Google', 'Tipo', 'Equipe(s)', 'Líder', 'Situação', ''].map(t => h('th', {}, t)))),
      h('tbody', {}, ...(r.pessoas.length ? r.pessoas.flatMap(linhasPessoa)
        : [h('tr', {}, h('td', { colspan: 9, class: 'empty' }, 'Nenhum cadastro encontrado.'))])));
    prepararNovo();
  }

  function linhasPessoa(p) {
    const eu = p.id === EU.pessoa.id;
    const [chipCls, chipTxt] = SIT_CHIP[p.situacao] || ['chip', p.situacao];
    const aguardando = p.aguardando_primeiro_acesso && p.situacao !== 'bloqueado';
    const editor = h('tr', { class: 'editor', hidden: true }, h('td', { colspan: 9 }, editorPessoa(p)));
    const botao = h('button', { type: 'button', class: 'btn', 'data-acao': 'editar', onclick: () => { editor.hidden = !editor.hidden; botao.textContent = editor.hidden ? 'Editar' : 'Fechar'; } }, 'Editar');
    const linha = h('tr', { class: 'pessoa ' + p.situacao, 'data-pessoa': p.id },
      h('td', {}, h('b', {}, p.nome), eu ? h('small', { class: 'sub' }, 'Você') : null),
      h('td', { class: 'nw' }, p.cpf || vazio('—')),
      h('td', { class: 'nw' }, p.whatsapp || vazio('no 1º acesso')),
      h('td', {}, p.email || vazio('no 1º acesso')),
      h('td', { class: 'nw' }, p.tipo_nome),
      h('td', {}, p.equipe || vazio('—')),
      h('td', {}, p.lider_nome || (p.tipo === 'especialista' ? vazio('sem líder') : '—')),
      h('td', {}, h('div', { class: 'chips' },
        aguardando ? h('span', { class: 'chip aguarda' }, 'Aguardando 1º acesso') : h('span', { class: chipCls }, chipTxt),
        p.faltando.length ? h('span', { class: 'chip alert', title: 'Falta: ' + p.faltando.join(', ') }, 'Falta: ' + p.faltando.join(', ')) : null),
        p.vinculado_em_txt ? h('small', { class: 'sub' }, '1º acesso: ' + p.vinculado_em_txt) : null),
      h('td', {}, botao));
    if (p.situacao === 'pendente') { editor.hidden = false; botao.textContent = 'Fechar'; }
    return [linha, editor];
  }

  function prepararNovo() {
    if ($('novoTipo').options.length) {  // só atualiza a lista de líderes
      $('novoLider').replaceChildren(...opcoesLider($('novoLider').value));
      return;
    }
    $('novoTipo').replaceChildren(...opcoesSelect(OP.tipos.filter(t => t.id !== 'admin' || EU.pessoa.tipo === 'admin'), 'especialista'));
    $('novoEquipes').replaceWith(Object.assign(caixasEquipes([]), { id: 'novoEquipes' }));
    $('novoLider').replaceChildren(...opcoesLider(''));
    const ajusta = () => { $('novoLiderCampo').hidden = $('novoTipo').value !== 'especialista'; };
    $('novoTipo').addEventListener('change', ajusta); ajusta();
  }

  $('novoForm').addEventListener('submit', async ev => {
    ev.preventDefault(); $('novoErro').hidden = true;
    const corpo = { nome: $('novoNome').value, tipo: $('novoTipo').value, cpf: $('novoCpf').value, equipe: $('novoEquipes').valor().join(', ') || null,
      whatsapp: $('novoWhats').value || null,
      email: $('novoEmail').value || null,
      lider_id: $('novoTipo').value === 'especialista' && $('novoLider').value ? Number($('novoLider').value) : null };
    try {
      await api('/api/admin/pessoas', { corpo });
      toast('Cadastro feito. No primeiro acesso, a pessoa informa o CPF e entra com o Google.');
      for (const id of ['novoNome', 'novoCpf', 'novoWhats', 'novoEmail']) $(id).value = '';
      $('novoEquipes').querySelectorAll('input').forEach(i => { i.checked = false; });
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
        const extras = [r.lideres_pela_equipe ? r.lideres_pela_equipe + ' liderado(s) ligado(s) ao líder pela equipe' : null,
          r.ligado_ao_admin ? 'o CPF de administrador foi ligado ao seu cadastro' : null].filter(Boolean);
        res.replaceChildren(h('p', { class: 'ok-msg' }, 'Planilha importada: ' + r.criados + ' cadastro(s) novo(s) e ' + r.atualizados + ' atualizado(s)' + (extras.length ? '; ' + extras.join('; ') : '') + '.'));
        $('impTexto').value = ''; OP = await api('/api/admin/opcoes'); carregarCadastros();
      } else {
        res.replaceChildren(h('p', { class: 'err' }, 'Nada foi gravado. Corrija estas linhas da planilha e importe de novo:'),
          h('ul', { class: 'imp-res' }, ...r.erros.map(e => h('li', {}, 'Linha ' + e.linha + ': ' + e.mensagem))));
      }
    } catch (e) { res.replaceChildren(h('p', { class: 'err' }, e.message)); }
    $('impEnviar').disabled = false;
  });

  function editorPessoa(p) {
    const eu = p.id === EU.pessoa.id;
    const f = {
      nome: h('input', { class: 'field', value: p.nome, maxlength: 120 }),
      tipo: h('select', { class: 'field', disabled: eu }, ...opcoesSelect(OP.tipos, p.tipo)),
      equipes: caixasEquipes(p.equipes),
      lider_id: h('select', { class: 'field' }, ...opcoesLider(p.lider_id, p.id)),
      cpf: h('input', { class: 'field', value: p.cpf || '', inputmode: 'numeric', maxlength: 14 }),
      whatsapp: h('input', { class: 'field', value: p.whatsapp || '', type: 'tel', maxlength: 20 }),
      email: h('input', { class: 'field', value: p.email || '', type: 'email', maxlength: 254, disabled: eu }),
    };
    const campoLider = h('label', {}, 'Líder', f.lider_id);
    const ajustaLider = () => { campoLider.hidden = f.tipo.value !== 'especialista'; };
    f.tipo.addEventListener('change', ajustaLider); ajustaLider();
    const form = h('div', { class: 'pc-form' },
      h('label', {}, 'Nome', f.nome), h('label', {}, 'Tipo de conta', f.tipo),
      campoLider,
      h('label', {}, 'CPF', f.cpf), h('label', {}, 'Telefone (WhatsApp)', f.whatsapp),
      h('label', {}, 'E-mail Google ', h('small', {}, '(a pessoa só entra com este e-mail)'), f.email),
      h('fieldset', { class: 'equipes-campo' }, h('legend', {}, 'Equipe(s)'), f.equipes));
    const erro = h('p', { class: 'err', hidden: true });
    const valores = () => ({ nome: f.nome.value, tipo: f.tipo.value, equipe: f.equipes.valor().join(', ') || null,
      cpf: f.cpf.value || null, whatsapp: f.whatsapp.value || null, ...(eu ? {} : { email: f.email.value || null }),
      lider_id: f.tipo.value === 'especialista' && f.lider_id.value ? Number(f.lider_id.value) : null });

    async function salvar(btn, corpo, msg) {
      erro.hidden = true; btn.disabled = true;
      try { await api('/api/admin/pessoas/' + p.id, { metodo: 'PATCH', corpo }); toast(msg); OP = await api('/api/admin/opcoes'); carregarCadastros(); }
      catch (e) { erro.textContent = e.message; erro.hidden = false; btn.disabled = false; }
    }
    const botoes = [];
    const b = (txt, cls, fn) => { const el = h('button', { type: 'button', class: 'btn ' + cls, onclick: () => fn(el) }, txt); botoes.push(el); return el; };
    if (p.situacao === 'pendente') b('Aprovar', 'go', el => salvar(el, { ...valores(), situacao: 'ativo' }, 'Cadastro aprovado.'));
    if (p.situacao === 'bloqueado') b('Liberar acesso', 'go', el => salvar(el, { ...valores(), situacao: 'ativo' }, 'Acesso liberado.'));
    b('Salvar', '', el => salvar(el, valores(), 'Cadastro salvo.'));
    if (p.situacao !== 'bloqueado' && !eu) b('Bloquear', 'no', el => { if (confirm('Bloquear o acesso de ' + p.nome + '?')) salvar(el, { situacao: 'bloqueado' }, 'Acesso bloqueado.'); });
    if (!eu) b('Excluir', 'no', async el => {
      if (!confirm('Excluir o cadastro de ' + p.nome + '? Os acessos registrados dessa pessoa também são apagados. Não dá para desfazer.')) return;
      erro.hidden = true; el.disabled = true;
      try { await api('/api/admin/pessoas/' + p.id + '/excluir', { corpo: {} }); toast('Cadastro excluído.'); OP = await api('/api/admin/opcoes'); carregarCadastros(); }
      catch (e) { erro.textContent = e.message; erro.hidden = false; el.disabled = false; }
    });
    return h('div', { class: 'pc ' + p.situacao, 'data-editor': p.id }, form, erro, h('div', { class: 'pc-act' }, ...botoes));
  }

  /* Atualizações: última busca de cada fonte, erros, trava do SGA e teste de conexão */
  async function carregarAtualizacoes() {
    let r;
    try { r = await api('/api/admin/atualizacoes'); } catch (e) { toast(e.message); return; }
    const pausa = $('atuPausa');
    pausa.hidden = !r.sga_pausado;
    if (r.sga_pausado) pausa.textContent = 'SGA pausado até ' + r.sga_pausado.ate_txt + ': ' + r.sga_pausado.motivo + '. Nenhuma busca chama o SGA antes disso.';
    $('atuProxima').textContent = 'Próxima busca completa do SGA: ' + r.proxima_busca_sga_txt + '.';
    $('atuFontes').replaceChildren(...r.fontes.map(f => h('div', { class: 'atu-fonte', 'data-fonte': f.fonte },
      h('b', {}, f.nome),
      h('span', { class: f.ultimo_ok_txt ? 'chip ok' : 'chip' }, f.ultimo_ok_txt ? 'Último sucesso: ' + f.ultimo_ok_txt + (f.ultimo_ok_tipo === 'teste' ? ' (teste)' : '') : 'Ainda sem busca'),
      f.rodando ? h('span', { class: 'chip aguarda' }, 'Rodando agora') : null,
      f.ultimo_erro ? h('small', { class: 'sub erro-fonte' }, 'Último erro (' + f.ultimo_erro_txt + '): ' + f.ultimo_erro) : null)));
    $('atuHistorico').replaceChildren(
      h('thead', {}, h('tr', {}, ...['Início', 'Fim', 'Fonte', 'Tipo', 'Resultado', 'Mensagem'].map(t => h('th', {}, t)))),
      h('tbody', {}, ...(r.historico.length ? r.historico.map(a => h('tr', {},
        h('td', { class: 'nw' }, a.inicio_txt), h('td', { class: 'nw' }, a.fim_txt || '—'), h('td', { class: 'nw' }, a.fonte_nome),
        h('td', {}, a.tipo), h('td', {}, a.ok === null ? h('span', { class: 'chip aguarda' }, 'rodando') : h('span', { class: a.ok ? 'chip ok' : 'chip bloq' }, a.ok ? 'ok' : 'erro')),
        h('td', {}, a.mensagem || '')))
        : [h('tr', {}, h('td', { colspan: 6, class: 'empty' }, 'Nenhuma busca registrada ainda.'))])));
  }

  $('atuTestar').addEventListener('click', async () => {
    const b = $('atuTestar'); b.disabled = true; $('atuResultado').replaceChildren(h('p', { class: 'hint' }, 'Testando…'));
    try {
      const r = await api('/api/admin/atualizacoes/testar', { corpo: {} });
      $('atuResultado').replaceChildren(...[['SGA', r.sga], ['Power CRM', r.powercrm]].map(([n, x]) => h('p', { class: x.ok ? 'ok-msg' : 'err' }, n + ': ' + x.mensagem)));
      carregarAtualizacoes();
    } catch (e) { $('atuResultado').replaceChildren(h('p', { class: 'err' }, e.message)); }
    b.disabled = false;
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
