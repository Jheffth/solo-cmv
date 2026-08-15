window.Paginas = window.Paginas || {};

window.Paginas.produtos = {
  async render(container) {
    const [produtos, categorias, unidades] = await Promise.all([
      api.get('/produtos'),
      api.get('/categorias'),
      // Lista fechada de unidades: é o que impede "kg", "Kg" e "KG" de
      // nascerem como três unidades diferentes no mesmo catálogo.
      api.get('/produtos/unidades-medida').catch(() => ['Kg', 'Und', 'L']),
    ]);
    const nomeCategoria = (id) => (categorias.find(c => c.id === id) || {}).nome || '—';
    const opcoesCategoria = categorias.map(c => `<option value="${c.id}">${c.nome}</option>`).join('');

    container.innerHTML = `
      <div class="card">
        <div class="card-header"><h2>Novo produto</h2></div>
        <form id="form-produto" class="form-inline">
          <div class="form-group">
            <label for="prod-nome">Nome</label>
            <input id="prod-nome" required placeholder="Ex.: Filé Mignon kg">
          </div>
          <div class="form-group">
            <label for="prod-un">Unidade</label>
            <input id="prod-un" list="lista-unidades" placeholder="Kg, L, Und…" style="width:90px" autocomplete="off">
            <datalist id="lista-unidades">${unidades.map((u) => `<option value="${u}">`).join('')}</datalist>
          </div>
          <div class="form-group">
            <label for="prod-cat">Categoria</label>
            <select id="prod-cat"><option value="">—</option>${opcoesCategoria}</select>
          </div>
          <button class="btn" type="submit">Adicionar</button>
        </form>
        <p style="font-size:.76rem;color:var(--muted);margin:.6rem 0 0">
          O código de 6 dígitos é gerado automaticamente, no bloco da família escolhida.
        </p>
      </div>
      <div class="card">
        <div class="card-header">
          <h2>Catálogo de produtos (${produtos.length})</h2>
          <input id="prod-busca" placeholder="Buscar por nome ou código…" style="max-width:220px">
        </div>
        <div id="prod-tabela-wrap">${tabelaProdutos(produtos, nomeCategoria)}</div>
      </div>
    `;

    document.getElementById('form-produto').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const nome = document.getElementById('prod-nome').value.trim();
      if (!nome) return;
      const unidade_medida = document.getElementById('prod-un').value.trim() || null;
      const categoria_id = document.getElementById('prod-cat').value || null;
      const novo = await api.post('/produtos', { nome, unidade_medida, categoria_id: categoria_id ? parseInt(categoria_id, 10) : null });
      avisarCadastroAlterado('produto', novo);   // atualiza listas abertas (Lançador etc.)
      window.roteador.rerenderizar();
    });

    document.getElementById('prod-busca').addEventListener('input', async (ev) => {
      const termo = ev.target.value.trim();
      const filtrados = await api.get(`/produtos${termo ? `?busca=${encodeURIComponent(termo)}` : ''}`);
      document.getElementById('prod-tabela-wrap').innerHTML = tabelaProdutos(filtrados, nomeCategoria);
    });
  },
};

function tabelaProdutos(produtos, nomeCategoria) {
  if (!produtos.length) return `<div class="estado-vazio">Nenhum produto encontrado.</div>`;
  return `
    <table class="tabela-simples">
      <thead><tr><th>Código</th><th>Produto</th><th>Unidade</th><th>Categoria</th></tr></thead>
      <tbody>
        ${produtos.map(p => `<tr>
          <td><span class="codigo-item">${p.codigo || '—'}</span></td>
          <td>${p.nome}</td>
          <td>${p.unidade_medida || '—'}</td>
          <td>${nomeCategoria(p.categoria_id)}</td>
        </tr>`).join('')}
      </tbody>
    </table>`;
}
