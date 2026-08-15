/* ============================================================
   FORNECEDORES — cadastro e histórico de compras por fornecedor.

   Ganhou entrada própria no menu (antes era aba de Cadastros)
   porque é a origem de toda compra: o Lançador só oferece na
   aba Compras quem estiver cadastrado aqui.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.fornecedores = (function () {
  let busca = '';

  const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
  const brl = (v) => 'R$ ' + Number(v || 0).toLocaleString('pt-BR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 });

  /* Resumo de compras por fornecedor, montado a partir das movimentações
     da unidade selecionada. Fornecedor sem compra aparece zerado. */
  function resumirCompras(movimentos) {
    const porFornecedor = {};
    movimentos
      .filter((m) => m.tipo === 'COMPRA' && m.fornecedor_id)
      .forEach((m) => {
        const r = porFornecedor[m.fornecedor_id]
          || (porFornecedor[m.fornecedor_id] = { notas: new Set(), itens: 0, valor: 0, ultima: null });
        r.notas.add(m.numero_documento || `#${m.id}`);
        r.itens += 1;
        r.valor += Number(m.custo_total || 0);
        const d = (m.data || '').slice(0, 10);
        if (d && (!r.ultima || d > r.ultima)) r.ultima = d;
      });
    return porFornecedor;
  }

  function tabela(fornecedores, resumo) {
    const termo = busca.toLowerCase();
    const lista = termo
      ? fornecedores.filter((f) => (f.nome || '').toLowerCase().includes(termo)
        || (f.cnpj || '').includes(termo))
      : fornecedores;

    if (!lista.length) {
      return `<div class="estado-vazio">Nenhum fornecedor encontrado${busca ? ' para "' + busca + '"' : ' ainda'}.</div>`;
    }

    return `
      <table class="tabela-simples">
        <thead><tr>
          <th>Nome</th><th>CNPJ</th>
          <th class="num">Notas</th><th class="num">Itens</th>
          <th class="num">Total comprado</th><th>Última compra</th>
        </tr></thead>
        <tbody>
          ${lista.map((f) => {
            const r = resumo[f.id];
            return `<tr>
              <td>${f.nome}</td>
              <td>${f.cnpj || '—'}</td>
              <td class="num">${r ? r.notas.size : 0}</td>
              <td class="num">${r ? r.itens : 0}</td>
              <td class="num">${r ? brl(r.valor) : '—'}</td>
              <td>${r ? dataBR(r.ultima) : '—'}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>`;
  }

  async function pintar(container) {
    const [fornecedores, movimentos] = await Promise.all([
      api.get('/fornecedores'),
      api.get(`/movimentos?unidade_id=${UNIDADE_SELECIONADA}&tipo=COMPRA`).catch(() => []),
    ]);
    const resumo = resumirCompras(movimentos);

    container.querySelector('#forn-tabela').innerHTML = tabela(fornecedores, resumo);
    container.querySelector('#forn-contagem').textContent = `${fornecedores.length} cadastrado(s)`;
  }

  return {
    async render(container) {
      container.innerHTML = `
        <div class="card">
          <div class="card-header"><h2>Novo fornecedor</h2></div>
          <form id="form-fornecedor" class="form-inline">
            <div class="form-group">
              <label for="forn-nome">Nome</label>
              <input id="forn-nome" required placeholder="Razão social">
            </div>
            <div class="form-group">
              <label for="forn-cnpj">CNPJ (opcional)</label>
              <input id="forn-cnpj" placeholder="00.000.000/0000-00">
            </div>
            <button class="btn" type="submit">Adicionar</button>
          </form>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>Fornecedores <span class="tag" id="forn-contagem"></span></h2>
          </div>
          <p style="color:var(--muted);font-size:.83rem;margin:0 0 .9rem">
            Quem está aqui aparece na aba <strong>Compras</strong> do Lançador.
            Notas, itens e total consideram a unidade selecionada.
          </p>
          <div class="filtros-barra">
            <div class="form-group cresce">
              <label for="forn-busca">Buscar</label>
              <input id="forn-busca" placeholder="Nome ou CNPJ…" value="${busca}">
            </div>
          </div>
          <div id="forn-tabela"><div class="estado-vazio">Carregando…</div></div>
        </div>
      `;

      let debounce = null;
      container.querySelector('#forn-busca').addEventListener('input', (ev) => {
        busca = ev.target.value.trim();
        clearTimeout(debounce);
        debounce = setTimeout(() => pintar(container), 250);
      });

      container.querySelector('#form-fornecedor').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const nome = container.querySelector('#forn-nome').value.trim();
        const cnpj = container.querySelector('#forn-cnpj').value.trim() || null;
        if (!nome) return;
        const novo = await api.post('/fornecedores', { nome, cnpj });
        avisarCadastroAlterado('fornecedor', novo);   // atualiza listas abertas (Lançador etc.)
        container.querySelector('#forn-nome').value = '';
        container.querySelector('#forn-cnpj').value = '';
        await pintar(container);
      });

      await pintar(container);
    },
  };
})();
