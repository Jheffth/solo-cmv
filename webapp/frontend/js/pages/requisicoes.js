/* ============================================================
   REQUISIÇÕES — retirada de itens do estoque para a produção.

   Colunas: Nº | Descrição | Solicitante | Produção | Data | Status | Ações

   CICLO DE VIDA
     Aberta ──iniciar──> Iniciada ──atender──> Atendida
        └──────────── Cancelada <──────┘

   Requisição apenas ABERTA não recebe itens: é preciso iniciar. Lançar item
   não mexe no estoque — a baixa acontece no atendimento, de uma vez.
   ============================================================ */
window.Paginas = window.Paginas || {};

const STATUS_REQUISICAO = {
  ABERTA:    { rotulo: 'Aberta',    classe: 'status-aberto' },
  INICIADA:  { rotulo: 'Iniciada',  classe: 'status-contagem' },
  ATENDIDA:  { rotulo: 'Atendida',  classe: 'status-fechado' },
  CANCELADA: { rotulo: 'Cancelada', classe: 'status-cancelado' },
};

window.Paginas.requisicoes = (function () {
  const filtros = { busca: '', status: '', dataInicio: '', dataFim: '' };
  let carregadas = [];

  const brl = (v) => 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');
  const dataHora = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  };
  const dataSimples = (iso) => (iso ? iso.split('-').reverse().join('/') : '—');

  const badge = (st) => {
    const s = STATUS_REQUISICAO[st] || { rotulo: st, classe: '' };
    return `<span class="status-badge ${s.classe}">${s.rotulo}</span>`;
  };

  const podeIniciar = (st) => st === 'ABERTA';
  const podeAtender = (st) => st === 'INICIADA';
  const ativa = (st) => ['ABERTA', 'INICIADA'].includes(st);

  const regional = () => typeof emRegional === 'function' && emRegional();

  function botoesDaLinha(r) {
    // Na Regional, iniciar/atender/cancelar são atos de uma loja. Só a
    // consulta atravessa unidades.
    if (regional()) {
      return `
        <div class="acoes-linha">
          <button class="btn-acao ver" data-acao="ver" data-id="${r.id}" type="button">Ver</button>
        </div>`;
    }
    const rotulo = (STATUS_REQUISICAO[r.status] || {}).rotulo || r.status;
    const trava = (ok, motivo) => (ok ? '' : ` disabled title="${motivo}"`);
    return `
      <div class="acoes-linha">
        <button class="btn-acao ver" data-acao="ver" data-id="${r.id}" type="button">Ver</button>
        <button class="btn-acao congelar" data-acao="iniciar" data-id="${r.id}" type="button"${
          trava(podeIniciar(r.status), `Só é possível iniciar uma requisição aberta (esta está ${rotulo})`)
          } title="Iniciar — libera o lançamento dos itens">Iniciar</button>
        <button class="btn-acao finalizar" data-acao="atender" data-id="${r.id}" type="button"${
          trava(podeAtender(r.status), r.status === 'ABERTA'
            ? 'Inicie a requisição antes de atender'
            : `Requisição já está ${rotulo}`)
          } title="Atender — baixa os itens do estoque">Atender</button>
        <button class="btn-acao cancelar" data-acao="cancelar" data-id="${r.id}" type="button"${
          trava(ativa(r.status), `Requisição já está ${rotulo}`)}>Cancelar</button>
      </div>`;
  }

  function tabela(lista) {
    const comFiltro = filtros.busca || filtros.status || filtros.dataInicio || filtros.dataFim;
    const naRede = regional();
    const corpo = lista.length
      ? lista.map((r) => `
          <tr>
            ${naRede ? `<td><span class="marca-unidade">${r.unidade_nome || '—'}</span></td>` : ''}
            <td><span class="codigo-item">${r.numero}</span></td>
            <td>${r.descricao || '<span class="zerado">—</span>'}</td>
            <td>${r.solicitante || '<span class="zerado">—</span>'}</td>
            <td>${dataSimples(r.data_producao)}</td>
            <td>${dataHora(r.data_abertura)}</td>
            <td>${badge(r.status)}</td>
            <td>${botoesDaLinha(r)}</td>
          </tr>`).join('')
      : `<tr class="linha-vazia">
           <td colspan="${naRede ? 8 : 7}">
             ${comFiltro ? 'Nenhuma requisição encontrada com os filtros aplicados.'
                         : (naRede ? 'Nenhuma requisição registrada em nenhuma unidade.'
                                   : 'Nenhuma requisição registrada nesta unidade.')}
             <div class="obs">${comFiltro ? 'Ajuste ou limpe os filtros para ver os demais registros.'
                                          : (naRede ? 'Escolha uma unidade para criar a primeira.'
                                                    : 'Use o botão "Abrir Requisição" para criar a primeira.')}</div>
           </td>
         </tr>`;

    return `
      <div class="tabela-rolavel">
      <table class="tabela-simples">
        <thead>
          <tr>
            ${naRede ? '<th>Unidade</th>' : ''}
            <th class="col-num-inv">Nº</th>
            <th>Descrição</th>
            <th>Solicitante</th>
            <th>Produção</th>
            <th>Aberta em</th>
            <th>Status</th>
            <th class="col-acoes">Ações</th>
          </tr>
        </thead>
        <tbody>${corpo}</tbody>
      </table>
      </div>`;
  }

  function aviso(container, texto, tipo) {
    const el = container.querySelector('#req-aviso');
    el.hidden = false;
    el.textContent = texto;
    el.className = 'aviso-acao ' + (tipo || '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, 6000);
  }

  // ---------- Ações ----------
  async function acaoIniciar(container, req) {
    try {
      await api.post(`/requisicoes/${req.id}/iniciar`, {});
      aviso(container, `Requisição nº ${req.numero} iniciada — já aceita itens pelo Lançador.`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  async function acaoAtender(container, req) {
    if (!confirm(
      `Atender a requisição nº ${req.numero}?\n\n` +
      `Os itens lançados sairão do estoque e serão enviados para a produção. ` +
      `Esta ação não pode ser desfeita.`)) return;
    try {
      const d = await api.post(`/requisicoes/${req.id}/atender`, {});
      aviso(container, `Requisição nº ${req.numero} atendida — ${d.resumo.total_itens} item(ns), ` +
        `${brl(d.resumo.valor_total)} retirados do estoque.`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  async function acaoCancelar(container, req) {
    if (!confirm(`Cancelar a requisição nº ${req.numero}?\n\nEla continua consultável, e o número não é reaproveitado.`)) return;
    try {
      await api.post(`/requisicoes/${req.id}/cancelar`, {});
      aviso(container, `Requisição nº ${req.numero} cancelada.`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  async function abrirDetalhe(container, req) {
    const d = await api.get(`/requisicoes/${req.id}`);
    const r = d.resumo;
    const painel = container.querySelector('#req-detalhe');
    painel.hidden = false;
    painel.innerHTML = `
      <div class="card-header">
        <h2>Requisição nº ${d.requisicao.numero} — ${d.requisicao.descricao || 'sem descrição'}</h2>
        <button class="btn secundario" type="button" id="req-detalhe-fechar">Fechar</button>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="rotulo">Itens</div><div class="valor">${r.total_itens}</div></div>
        <div class="kpi-card"><div class="rotulo">Quantidade total</div><div class="valor">${r.quantidade_total}</div></div>
        <div class="kpi-card"><div class="rotulo">Valor</div><div class="valor">${brl(r.valor_total)}</div></div>
        <div class="kpi-card"><div class="rotulo">Sem saldo</div><div class="valor">${r.itens_sem_saldo}</div></div>
      </div>
      ${d.itens.length ? `
        <table class="tabela-simples">
          <thead><tr>
            <th>Código</th><th>Produto</th><th>Un.</th>
            <th class="num">Pedido</th><th class="num">Saldo atual</th><th class="num">Valor</th>
          </tr></thead>
          <tbody>${d.itens.map((i) => `
            <tr>
              <td><span class="codigo-item">${i.codigo || '—'}</span></td>
              <td>${i.produto || '—'}</td>
              <td>${i.unidade_medida || '—'}</td>
              <td class="num">${i.quantidade}</td>
              <td class="num ${(i.saldo_atual ?? 0) < i.quantidade ? 'diverg-neg' : ''}">${i.saldo_atual ?? '—'}</td>
              <td class="num">${brl(i.valor_total)}</td>
            </tr>`).join('')}
          </tbody>
        </table>` : `<div class="estado-vazio">Nenhum item lançado nesta requisição ainda.</div>`}
    `;
    painel.querySelector('#req-detalhe-fechar').addEventListener('click', () => { painel.hidden = true; });
    painel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  function ligarBotoes(container) {
    container.querySelectorAll('[data-acao]').forEach((botao) => {
      botao.addEventListener('click', async () => {
        const acao = botao.dataset.acao;
        const req = carregadas.find((r) => String(r.id) === botao.dataset.id) || null;

        if (acao === 'abrir') {
          window.AbrirRequisicao.abrir({
            aoConcluir: async (nova) => {
              aviso(container, `Requisição nº ${nova.numero} aberta. Use "Iniciar" para liberar o lançamento dos itens.`, 'sucesso');
              await carregar(container);
            },
          });
          return;
        }
        if (!req) return;

        try {
          if (acao === 'iniciar') await acaoIniciar(container, req);
          else if (acao === 'atender') await acaoAtender(container, req);
          else if (acao === 'cancelar') await acaoCancelar(container, req);
          else if (acao === 'ver') await abrirDetalhe(container, req);
        } catch (e) {
          aviso(container, e.message || 'Não foi possível concluir a ação.', 'erro');
        }
      });
    });
  }

  async function carregar(container) {
    const alvo = container.querySelector('#req-tabela');
    alvo.innerHTML = `<div class="estado-vazio">Carregando…</div>`;

    const params = new URLSearchParams({ unidade_id: UNIDADE_SELECIONADA });
    if (filtros.busca) params.set('busca', filtros.busca);
    if (filtros.status) params.set('status', filtros.status);
    if (filtros.dataInicio) params.set('data_inicio', filtros.dataInicio);
    if (filtros.dataFim) params.set('data_fim', filtros.dataFim);

    carregadas = await api.get('/requisicoes?' + params.toString());
    alvo.innerHTML = tabela(carregadas);
    container.querySelector('#req-contagem').textContent = `${carregadas.length} registro(s)`;
    container.querySelector('#req-limpar').hidden =
      !(filtros.busca || filtros.status || filtros.dataInicio || filtros.dataFim);
    ligarBotoes(container);
  }

  return {
    async render(container) {
      container.innerHTML = `
        <div class="card">
          <div class="card-header">
            <h2>Requisições <span class="tag" id="req-contagem"></span></h2>
            ${regional() ? '' : '<button class="btn" type="button" data-acao="abrir">Abrir Requisição</button>'}
          </div>

          ${regional() ? `<div class="faixa-regional">${icone('unidades')}
            <span>Histórico de requisições de todas as unidades, só para consulta.
            Abrir, iniciar e atender são atos de uma loja — escolha a unidade
            na barra de topo para operar.</span></div>` : ''}

          <div class="filtros-barra">
            <div class="form-group cresce">
              <label for="req-busca">Buscar</label>
              <input id="req-busca" placeholder="Número, descrição ou solicitante…">
            </div>
            <div class="form-group">
              <label for="req-status">Status</label>
              <select id="req-status">
                <option value="">Todos</option>
                ${Object.entries(STATUS_REQUISICAO).map(([k, s]) => `<option value="${k}">${s.rotulo}</option>`).join('')}
              </select>
            </div>
            <div class="form-group data">
              <label for="req-data-inicio">Aberta de</label>
              <input id="req-data-inicio" type="date">
            </div>
            <div class="form-group data">
              <label for="req-data-fim">até</label>
              <input id="req-data-fim" type="date">
            </div>
            <button class="btn secundario" type="button" id="req-limpar" hidden>Limpar filtros</button>
          </div>

          <p class="aviso-acao" id="req-aviso" hidden></p>
          <div id="req-tabela"></div>
        </div>

        <div class="card" id="req-detalhe" hidden></div>

        <div class="card">
          <div class="card-header"><h2>Como funciona</h2></div>
          <div class="legenda-status">
            <div><span class="status-badge status-aberto">Aberta</span> criada — <strong>ainda não recebe itens</strong></div>
            <div><span class="status-badge status-contagem">Iniciada</span> aceita o lançamento dos itens pelo Lançador</div>
            <div><span class="status-badge status-fechado">Atendida</span> itens baixados do estoque e enviados à produção</div>
            <div><span class="status-badge status-cancelado">Cancelada</span> descartada, mas segue consultável</div>
          </div>
          <p style="font-size:.82rem;color:var(--muted);margin-top:.9rem">
            Lançar um item não mexe no estoque — a baixa acontece de uma vez no atendimento.
            Isso permite montar o pedido com calma e conferir antes de efetivar.
          </p>
        </div>
      `;

      ligarBotoes(container);

      let debounce = null;
      container.querySelector('#req-busca').addEventListener('input', (ev) => {
        filtros.busca = ev.target.value.trim();
        clearTimeout(debounce);
        debounce = setTimeout(() => carregar(container), 300);
      });
      container.querySelector('#req-status').addEventListener('change', (ev) => {
        filtros.status = ev.target.value; carregar(container);
      });
      container.querySelector('#req-data-inicio').addEventListener('change', (ev) => {
        filtros.dataInicio = ev.target.value; carregar(container);
      });
      container.querySelector('#req-data-fim').addEventListener('change', (ev) => {
        filtros.dataFim = ev.target.value; carregar(container);
      });
      container.querySelector('#req-limpar').addEventListener('click', () => {
        filtros.busca = ''; filtros.status = ''; filtros.dataInicio = ''; filtros.dataFim = '';
        ['#req-busca', '#req-status', '#req-data-inicio', '#req-data-fim']
          .forEach((s) => { container.querySelector(s).value = ''; });
        carregar(container);
      });

      await carregar(container);
    },
  };
})();
