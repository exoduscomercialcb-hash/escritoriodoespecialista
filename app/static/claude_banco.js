/* Adaptador: a página dos cards (cards.js, vinda da página atual) usa window.claude.use('db' | 'user' | 'assets' |
   'downloads'), que existia na página publicada no Claude. Aqui, 'db' conversa com /api/banco do servidor
   (coleção + documento, mesmas operações); as mudanças de outras pessoas chegam a cada 20 segundos.
   'assets' (envio de prints) e 'downloads' ficam para a etapa 4: devolvem null e a página usa o caminho alternativo. */
(() => {
  'use strict';
  const INTERVALO = 20000;
  const assinaturas = new Set();

  async function pedir(metodo, caminho, corpo) {
    const init = { method: metodo, credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } };
    if (corpo !== undefined) init.body = JSON.stringify(corpo);
    const r = await fetch('/api/banco/' + caminho, init);
    let dados = {};
    try { dados = await r.json(); } catch (e) { /* sem corpo */ }
    if (!r.ok) { const e = new Error(dados.erro || ('erro ' + r.status)); e.code = r.status === 404 ? 'not-found' : 'erro'; throw e; }
    return dados;
  }

  const fotoDoc = (id, data, existe) => ({ id, exists: existe, data: () => (existe ? data : undefined) });

  function avisar(colecao) { assinaturas.forEach(a => { if (a.colecao === colecao) a.buscar(); }); }

  function assinar(colecao, buscar) {
    const a = { colecao, buscar };
    assinaturas.add(a);
    buscar();
    const t = setInterval(buscar, INTERVALO);
    return () => { clearInterval(t); assinaturas.delete(a); };
  }

  function doc(colecao, id) {
    const caminho = encodeURIComponent(colecao) + '/' + encodeURIComponent(id);
    return {
      id,
      async get() { const r = await pedir('GET', caminho); return fotoDoc(id, r.data, r.exists); },
      async set(dados) { await pedir('PUT', caminho, dados); avisar(colecao); },
      async update(dados) { await pedir('PATCH', caminho, dados); avisar(colecao); },
      async delete() { await pedir('DELETE', caminho, {}); avisar(colecao); },
      onSnapshot(ok, falha) {
        return assinar(colecao, () => pedir('GET', caminho).then(r => ok(fotoDoc(id, r.data, r.exists)), e => falha && falha(e)));
      },
    };
  }

  function colecao(nome, limite) {
    return {
      doc: id => doc(nome, id),
      limit: n => colecao(nome, n),
      async add(dados) { const r = await pedir('POST', encodeURIComponent(nome), dados); avisar(nome); return doc(nome, r.id); },
      async get() { return fotoColecao(await pedir('GET', encodeURIComponent(nome)), limite); },
      onSnapshot(ok, falha) {
        return assinar(nome, () => pedir('GET', encodeURIComponent(nome)).then(r => ok(fotoColecao(r, limite)), e => falha && falha(e)));
      },
    };
  }

  function fotoColecao(r, limite) {
    const docs = (r.docs || []).slice(0, limite || undefined).map(d => fotoDoc(d.id, d.data, true));
    return { docs, size: docs.length, empty: !docs.length, forEach: f => docs.forEach(f) };
  }

  const banco = { collection: nome => colecao(nome) };

  window.claude = {
    async use(nome) {
      if (nome === 'db') return banco;
      if (nome === 'user') {
        let eu = null;
        try { const r = await fetch('/api/eu', { credentials: 'same-origin' }); eu = await r.json(); } catch (e) { eu = null; }
        const id = eu && eu.pessoa ? String(eu.pessoa.id) : null;
        return { id: async () => id, can: async () => !!id };
      }
      return null;  // 'assets' e 'downloads': etapa 4
    },
  };
})();
