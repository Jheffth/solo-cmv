/* ============================================================
   ESTOQUE — posição atual de todos os itens cadastrados na unidade.

   O saldo é o saldo teórico desde a última contagem física:
       saldo = quantidade da última contagem + compras lançadas depois dela
   Item sem contagem e sem compra aparece zerado — é o estado inicial de
   todo produto recém-cadastrado.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.estoque = (function () {
  let filtroBusca = '';
  let filtroCategoria = '';
  let somenteComSaldo = false;

  const brl = (v) => 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');
  const qtd = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });

  /* `comValores` vem do servidor (campo `com_valores`), não de uma checagem
     de papel aqui. A tela não decide quem vê dinheiro — ela desenha o que
     chegou. Se a régua mudar no backend, esta tela acompanha sem edição. */
  function linhas(itens, regional, comValores) {
    if (!itens.length) {
      return `<div class="estado-vazio">Nenhum item encontrado com os filtros atuais.</div>`;
    }
    return `
      <div class="tabela-rolavel">
      <table class="tabela-simples">
        <thead>
          <tr>
            ${regional ? '<th>Unidade</th>' : ''}
            <th>Código</th>
            <th>Produto</th>
            <th>Família</th>
            <th>Un.</th>
            <th class="num">Estoque</th>
            ${comValores ? '<th class="num">Último custo</th>' : ''}
            ${comValores ? '<th class="num">Valor em estoque</th>' : ''}
          </tr>
        </thead>
        <tbody>
          ${itens.map((i) => `
            <tr>
              ${regional ? `<td><span class="marca-unidade">${i.unidade_nome || '—'}</span></td>` : ''}
              <td><span class="codigo-item">${i.codigo || '—'}</span></td>
              <td>${i.nome}</td>
              <td>${i.categoria || '—'}</td>
              <td>${i.unidade_medida || '—'}</td>
              <td class="num ${i.quantidade > 0 ? '' : 'zerado'}">${qtd(i.quantidade)}</td>
              ${comValores ? `<td class="num">${i.ultimo_custo != null ? brl(i.ultimo_custo) : '<span class="zerado">sem custo</span>'}</td>` : ''}
              ${comValores ? `<td class="num">${i.valor_em_estoque ? brl(i.valor_em_estoque) : '<span class="zerado">—</span>'}</td>` : ''}
            </tr>`).join('')}
        </tbody>
      </table>
      </div>`;
  }

  /* Na Regional, saber quanto cada loja tem parado importa tanto quanto o
     total: R$ 160 mil na rede, com R$ 148 mil numa loja só, é outra
     conversa. */
  function resumoPorUnidade(dados) {
    if (!dados.regional || !dados.por_unidade || !dados.por_unidade.length) return '';
    return `
      <div class="faixa-unidades">
        ${dados.por_unidade.map((u) => `
          <div class="faixa-unidade">
            <span class="marca-unidade">${u.unidade}</span>
            ${u.valor != null ? `<strong>${brl(u.valor)}</strong>` : ''}
            <small>${u.itens_com_saldo} itens com saldo</small>
          </div>`).join('')}
      </div>`;
  }

  async function carregarTabela(container) {
    const alvo = container.querySelector('#estoque-tabela');
    alvo.innerHTML = `<div class="estado-vazio">Carregando…</div>`;

    const params = new URLSearchParams({ unidade_id: UNIDADE_SELECIONADA });
    if (filtroBusca) params.set('busca', filtroBusca);
    if (filtroCategoria) params.set('categoria_id', filtroCategoria);

    const dados = await api.get('/estoque?' + params.toString());
    let itens = dados.itens;
    if (somenteComSaldo) itens = itens.filter((i) => i.quantidade > 0);

    alvo.innerHTML = resumoPorUnidade(dados)
      + linhas(itens, dados.regional, dados.com_valores !== false);
    container.querySelector('#estoque-contagem').textContent =
      `${itens.length} item(ns)` + (somenteComSaldo ? ' com saldo' : '')
      + (dados.regional ? ` em ${dados.resumo.unidades} unidades` : '');
    return dados;
  }

  function atualizarKpis(container, resumo) {
    container.querySelector('#kpi-total').textContent = resumo.total_itens;
    container.querySelector('#kpi-com-saldo').textContent = resumo.itens_com_saldo;
    container.querySelector('#kpi-zerados').textContent = resumo.itens_zerados;
    // O cartão de valor não vira "R$ 0,00" para quem não vê dinheiro: zero
    // mente. Ele sai da tela inteiro — e o CSS reacomoda os outros três.
    const cartaoValor = container.querySelector('#kpi-valor');
    if (cartaoValor) {
      const bloco = cartaoValor.closest('.kpi') || cartaoValor.parentElement;
      if (resumo.valor_total == null) {
        if (bloco) bloco.style.display = 'none';
      } else {
        if (bloco) bloco.style.display = '';
        cartaoValor.textContent = brl(resumo.valor_total);
      }
    }
  }

  return {
    async render(container) {
      const categorias = await api.get('/categorias');
      const regional = typeof emRegional === 'function' && emRegional();

      container.innerHTML = `
        ${regional ? `<div class="faixa-regional">${icone('unidades')}
          <span>Posição consolidada de todas as unidades. Só itens com saldo
          aparecem, uma linha por loja — somar saldo de lojas diferentes
          esconderia onde o estoque realmente está.</span></div>` : ''}
        <div class="kpi-grid">
          <div class="kpi-card"><div class="rotulo">${regional
            ? 'Linhas com saldo' : 'Itens cadastrados'}</div><div class="valor" id="kpi-total">—</div></div>
          <div class="kpi-card"><div class="rotulo">Com saldo</div><div class="valor" id="kpi-com-saldo">—</div></div>
          <div class="kpi-card"><div class="rotulo">Zerados</div><div class="valor" id="kpi-zerados">—</div></div>
          <div class="kpi-card"><div class="rotulo">Valor em estoque</div><div class="valor" id="kpi-valor">—</div></div>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>Posição de estoque <span class="tag" id="estoque-contagem"></span></h2>
            <div style="display:flex;gap:.5rem;align-items:center;flex-wrap:wrap">
              <input id="estoque-busca" placeholder="Buscar por nome ou código…" style="max-width:220px">
              <select id="estoque-categoria" style="max-width:200px">
                <option value="">Todas as famílias</option>
                ${categorias.map((c) => `<option value="${c.id}">${c.nome}</option>`).join('')}
              </select>
              <label style="display:flex;align-items:center;gap:.35rem;font-size:.8rem;color:var(--muted);white-space:nowrap">
                <input type="checkbox" id="estoque-com-saldo" style="width:auto"> só com saldo
              </label>
            </div>
          </div>
          <div class="lancador-dica" style="margin-bottom:1rem">
            O saldo considera a última contagem física do item mais as compras lançadas depois dela.
            Itens recém-cadastrados, sem contagem e sem compra, aparecem zerados.
          </div>
          <div id="estoque-tabela"></div>
        </div>
      `;

      const dados = await carregarTabela(container);
      atualizarKpis(container, dados.resumo);

      let debounce = null;
      container.querySelector('#estoque-busca').addEventListener('input', (ev) => {
        filtroBusca = ev.target.value.trim();
        clearTimeout(debounce);
        debounce = setTimeout(async () => {
          const d = await carregarTabela(container);
          atualizarKpis(container, d.resumo);
        }, 300);
      });

      container.querySelector('#estoque-categoria').addEventListener('change', async (ev) => {
        filtroCategoria = ev.target.value;
        const d = await carregarTabela(container);
        atualizarKpis(container, d.resumo);
      });

      container.querySelector('#estoque-com-saldo').addEventListener('change', async (ev) => {
        somenteComSaldo = ev.target.checked;
        await carregarTabela(container);
      });
    },
  };
})();
