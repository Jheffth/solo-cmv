window.Paginas = window.Paginas || {};

window.Paginas.unidades = {
  async render(container) {
    const unidades = await api.get('/unidades');
    container.innerHTML = `
      <div class="card">
        <div class="card-header"><h2>Nova unidade</h2></div>
        <form id="form-unidade" class="form-inline">
          <div class="form-group">
            <label for="uni-nome">Nome</label>
            <input id="uni-nome" required placeholder="Ex.: Josefina Lago Sul">
          </div>
          <div class="form-group">
            <label for="uni-apelido">Apelido (opcional)</label>
            <input id="uni-apelido" placeholder="Ex.: Lago Sul">
          </div>
          <button class="btn" type="submit">Adicionar</button>
        </form>
      </div>
      <div class="card">
        <div class="card-header"><h2>Unidades (${unidades.length})</h2></div>
        <table class="tabela-simples">
          <thead><tr><th>Nome</th><th>Apelido</th><th>Status</th></tr></thead>
          <tbody>${unidades.map(u => `<tr><td>${u.nome}</td><td>${u.apelido || '—'}</td><td><span class="tag ${u.ativo ? 'aberta' : 'fechada'}">${u.ativo ? 'Ativa' : 'Inativa'}</span></td></tr>`).join('')}</tbody>
        </table>
      </div>
    `;

    document.getElementById('form-unidade').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const nome = document.getElementById('uni-nome').value.trim();
      if (!nome) return;
      const apelido = document.getElementById('uni-apelido').value.trim() || null;
      await api.post('/unidades', { empresa_id: USUARIO_ATUAL.empresa_id, nome, apelido });
      window.roteador.rerenderizar();
    });
  },
};
