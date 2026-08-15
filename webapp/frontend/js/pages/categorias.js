window.Paginas = window.Paginas || {};

window.Paginas.categorias = {
  async render(container) {
    const categorias = await api.get('/categorias');
    container.innerHTML = `
      <div class="card">
        <div class="card-header"><h2>Nova categoria (família)</h2></div>
        <form id="form-categoria" class="form-inline">
          <div class="form-group">
            <label for="cat-nome">Nome</label>
            <input id="cat-nome" required placeholder="Ex.: Família - Hortifruti">
          </div>
          <button class="btn" type="submit">Adicionar</button>
        </form>
      </div>
      <div class="card">
        <div class="card-header"><h2>Categorias cadastradas (${categorias.length})</h2></div>
        ${categorias.length ? `
          <table class="tabela-simples">
            <thead><tr><th>Nome</th></tr></thead>
            <tbody>${categorias.map(c => `<tr><td>${c.nome}</td></tr>`).join('')}</tbody>
          </table>` : `<div class="estado-vazio">Nenhuma categoria cadastrada ainda.</div>`}
      </div>
    `;

    document.getElementById('form-categoria').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const nome = document.getElementById('cat-nome').value.trim();
      if (!nome) return;
      const nova = await api.post('/categorias', { nome });
      avisarCadastroAlterado('categoria', nova);   // atualiza modal de inventário, filtros etc.
      window.roteador.rerenderizar();
    });
  },
};
