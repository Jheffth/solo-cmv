window.Paginas = window.Paginas || {};

window.Paginas.vendas = {
  async render(container) {
    const vendas = await api.get(`/vendas?unidade_id=${UNIDADE_SELECIONADA}`);

    container.innerHTML = `
      <div class="card">
        <div class="card-header"><h2>Informar faturamento do período</h2></div>
        <p style="color:var(--muted);font-size:.85rem">Enquanto não há integração automática com PDV ou certificado digital, o faturamento de cada período é informado manualmente aqui — é a base do cálculo de CMV % assim que o motor de CMV (Fase 4) entrar em operação.</p>
        <form id="form-venda" class="form-inline">
          <div class="form-group">
            <label for="venda-inicio">Início do período</label>
            <input id="venda-inicio" type="date" required>
          </div>
          <div class="form-group">
            <label for="venda-fim">Fim do período</label>
            <input id="venda-fim" type="date" required>
          </div>
          <div class="form-group">
            <label for="venda-total">Faturamento total (R$)</label>
            <input id="venda-total" type="number" step="0.01" required style="width:140px">
          </div>
          <div class="form-group">
            <label for="venda-comida">Faturamento comida (opcional)</label>
            <input id="venda-comida" type="number" step="0.01" style="width:140px">
          </div>
          <div class="form-group">
            <label for="venda-bebida">Faturamento bebida (opcional)</label>
            <input id="venda-bebida" type="number" step="0.01" style="width:140px">
          </div>
          <button class="btn" type="submit">Salvar período</button>
        </form>
        <p class="aviso-acao" id="venda-erro" hidden></p>
      </div>
      <div class="card">
        <div class="card-header"><h2>Períodos informados (${vendas.length})</h2></div>
        ${vendas.length ? `
          <table class="tabela-simples">
            <thead><tr><th>Período</th><th class="num">Total</th><th class="num">Comida</th><th class="num">Bebida</th><th class="col-acoes">Ações</th></tr></thead>
            <tbody>${[...vendas].sort((a,b)=>b.data_inicio.localeCompare(a.data_inicio)).map(v => `<tr>
              <td>${v.data_inicio.split('-').reverse().join('/')} a ${v.data_fim.split('-').reverse().join('/')}</td>
              <td class="num">R$ ${v.faturamento_total.toFixed(2).replace('.', ',')}</td>
              <td class="num">${v.faturamento_comida != null ? 'R$ ' + v.faturamento_comida.toFixed(2).replace('.', ',') : '—'}</td>
              <td class="num">${v.faturamento_bebida != null ? 'R$ ' + v.faturamento_bebida.toFixed(2).replace('.', ',') : '—'}</td>
              <td><div class="acoes-linha">
                <button class="btn-acao cancelar" data-excluir="${v.id}" type="button"
                  title="Excluir este faturamento">Excluir</button>
              </div></td>
            </tr>`).join('')}</tbody>
          </table>` : `<div class="estado-vazio">Nenhum período de venda informado ainda.</div>`}
      </div>
    `;

    document.getElementById('form-venda').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const comida = document.getElementById('venda-comida').value;
      const bebida = document.getElementById('venda-bebida').value;
      const erro = container.querySelector('#venda-erro');
      erro.hidden = true;
      try {
        await api.post('/vendas', {
          unidade_id: UNIDADE_SELECIONADA,
          data_inicio: document.getElementById('venda-inicio').value,
          data_fim: document.getElementById('venda-fim').value,
          faturamento_total: parseFloat(document.getElementById('venda-total').value),
          faturamento_comida: comida ? parseFloat(comida) : null,
          faturamento_bebida: bebida ? parseFloat(bebida) : null,
        });
        window.roteador.rerenderizar();
      } catch (e) {
        erro.hidden = false;
        erro.textContent = e.message;
        erro.className = 'aviso-acao erro';
      }
    });

    container.querySelectorAll('[data-excluir]').forEach((botao) => {
      botao.addEventListener('click', async () => {
        if (!confirm('Excluir este lançamento de faturamento?')) return;
        try {
          await api.del(`/vendas/${botao.dataset.excluir}`);
          window.roteador.rerenderizar();
        } catch (e) {
          const erro = container.querySelector('#venda-erro');
          erro.hidden = false;
          erro.textContent = e.message;
          erro.className = 'aviso-acao erro';
        }
      });
    });
  },
};
