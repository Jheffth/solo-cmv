/* ============================================================
   INVENTÁRIOS — listagem, filtros e ações.

   Colunas: Nº | Descrição | Data | Status | Ações

   CICLO DE VIDA
     Aberto ──congelar──> Congelado ──contagem──> Em Contagem ──finalizar──> Finalizado
        └──────────────── Cancelado <───────────────┘

   Inventário apenas ABERTO não recebe contagem: é preciso congelar primeiro,
   pois é o congelamento que fotografa o estoque e permite medir a divergência.
   ============================================================ */
window.Paginas = window.Paginas || {};

const STATUS_INVENTARIO = {
  ABERTO:      { rotulo: 'Aberto',       classe: 'status-aberto' },
  CONGELADO:   { rotulo: 'Congelado',    classe: 'status-congelado' },
  EM_CONTAGEM: { rotulo: 'Em Contagem',  classe: 'status-contagem' },
  FINALIZADO:  { rotulo: 'Finalizado',   classe: 'status-fechado' },
  CANCELADO:   { rotulo: 'Cancelado',    classe: 'status-cancelado' },
};

window.Paginas.inventario = (function () {
  const filtros = { busca: '', status: '', dataInicio: '', dataFim: '' };
  let sessoesCarregadas = [];

  const dataHora = (iso) => {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR') + ' ' + d.toLocaleTimeString('pt-BR', { hour: '2-digit', minute: '2-digit' });
  };

  const badge = (status) => {
    const s = STATUS_INVENTARIO[status] || { rotulo: status, classe: '' };
    return `<span class="status-badge ${s.classe}">${s.rotulo}</span>`;
  };

  // Inventário ainda "vivo": ocupa o setor e aceita ações
  const emAndamento = (st) => ['ABERTO', 'CONGELADO', 'EM_CONTAGEM'].includes(st);
  // Só congela quem está apenas aberto
  const podeCongelar = (st) => st === 'ABERTO';
  // Só finaliza quem já foi congelado (tem a fotografia do estoque)
  const podeFinalizar = (st) => ['CONGELADO', 'EM_CONTAGEM'].includes(st);
  // Relatório existe a partir do congelamento (antes não há itens)
  const temRelatorio = (st) => st !== 'ABERTO';
  /* Folha de contagem cega: SÓ com o inventário aberto, antes de congelar.
     É um controle antifraude — depois do congelamento ninguém emite uma
     segunda via, nem tira folha de inventário já encerrado. */
  const podeFolha = (st) => st === 'ABERTO';

  const regional = () => typeof emRegional === 'function' && emRegional();

  function botoesDaLinha(s) {
    // Na Regional o histórico é consulta: congelar, finalizar e cancelar são
    // atos de uma loja. Só "Ver" e os PDFs seguem valendo — abrir o
    // inventário de outra unidade para ler não muda nada nela.
    if (regional()) {
      return `
        <div class="acoes-linha">
          <button class="btn-acao ver" data-acao="ver" data-id="${s.id}" type="button">Ver</button>
          <button class="btn-acao pdf" data-acao="pdf" data-id="${s.id}" type="button"${
            temRelatorio(s.status) ? '' : ' disabled title="Disponível depois do congelamento"'
            }>Relatório</button>
        </div>`;
    }
    const rotulo = (STATUS_INVENTARIO[s.status] || {}).rotulo || s.status;
    const trava = (permitido, motivo) =>
      permitido ? '' : ` disabled title="${motivo}"`;
    return `
      <div class="acoes-linha">
        <button class="btn-acao ver" data-acao="ver" data-id="${s.id}" type="button">Ver</button>
        <button class="btn-acao congelar" data-acao="congelar" data-id="${s.id}" type="button"${
          trava(podeCongelar(s.status), `Só é possível congelar um inventário Aberto (este está ${rotulo})`)}>Congelar</button>
        <button class="btn-acao finalizar" data-acao="finalizar" data-id="${s.id}" type="button"${
          trava(podeFinalizar(s.status), s.status === 'ABERTO'
            ? 'Congele o inventário antes de finalizar'
            : `Inventário já está ${rotulo}`)}>Finalizar</button>
        <button class="btn-acao folha" data-acao="folha" data-id="${s.id}" type="button"${
          trava(podeFolha(s.status),
            `A folha só é emitida com o inventário aberto, antes do congelamento (este está ${rotulo})`)
          } title="Folha de contagem cega — A4 para imprimir e contar à mão. Só antes de congelar.">Folha</button>
        <button class="btn-acao pdf" data-acao="pdf" data-id="${s.id}" type="button"${
          trava(temRelatorio(s.status), 'O relatório fica disponível depois do congelamento')
          } title="Relatório de divergências — estoque anterior, contado e perdas">Relatório</button>
        <button class="btn-acao cancelar" data-acao="cancelar" data-id="${s.id}" type="button"${
          trava(emAndamento(s.status), `Inventário já está ${rotulo}`)}>Cancelar</button>
      </div>`;
  }

  function tabela(sessoes) {
    const houveFiltro = filtros.busca || filtros.status || filtros.dataInicio || filtros.dataFim;
    const naRede = regional();
    const colunas = naRede ? 6 : 5;
    const corpo = sessoes.length
      ? sessoes.map((s) => `
          <tr>
            ${naRede ? `<td><span class="marca-unidade">${s.unidade_nome || '—'}</span></td>` : ''}
            <td><span class="codigo-item">${s.numero_documento}</span></td>
            <td>${s.descricao || '<span class="zerado">—</span>'}</td>
            <td>${dataHora(s.data_abertura)}</td>
            <td>${badge(s.status)}</td>
            <td>${botoesDaLinha(s)}</td>
          </tr>`).join('')
      : `<tr class="linha-vazia">
           <td colspan="${colunas}">
             ${houveFiltro
               ? 'Nenhum inventário encontrado com os filtros aplicados.'
               : (naRede ? 'Nenhum inventário registrado em nenhuma unidade.'
                         : 'Nenhum inventário registrado nesta unidade.')}
             <div class="obs">${houveFiltro
               ? 'Ajuste ou limpe os filtros para ver os demais registros.'
               : (naRede ? 'Escolha uma unidade para abrir o primeiro.'
                         : 'Use o botão "Abrir Inventário" para iniciar o primeiro.')}</div>
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
            <th>Data</th>
            <th>Status</th>
            <th class="col-acoes">Ações</th>
          </tr>
        </thead>
        <tbody>${corpo}</tbody>
      </table>
      </div>`;
  }

  function aviso(container, texto, tipo) {
    const el = container.querySelector('#inv-aviso-acao');
    el.hidden = false;
    el.textContent = texto;
    el.className = 'aviso-acao ' + (tipo || '');
    clearTimeout(el._t);
    el._t = setTimeout(() => { el.hidden = true; }, 6000);
  }

  // ---------- Ações ----------
  async function acaoCongelar(container, sessao) {
    if (!confirm(
      `Congelar o inventário nº ${sessao.numero_documento}?\n\n` +
      `O estoque atual dos itens do escopo será fotografado, e só a partir daí ` +
      `o inventário passa a aceitar contagens.`)) return;
    try {
      const d = await api.post(`/inventario/sessoes/${sessao.id}/congelar`, {});
      aviso(container, `Inventário nº ${sessao.numero_documento} congelado — ${d.resumo.total_itens} item(ns) no escopo. Já aceita contagem pelo Lançador.`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  async function acaoFinalizar(container, sessao) {
    if (!confirm(
      `Finalizar o inventário nº ${sessao.numero_documento}?\n\n` +
      `As quantidades contadas passarão a valer como estoque real dos itens. ` +
      `Itens sem contagem não são alterados. Esta ação não pode ser desfeita.`)) return;
    try {
      const d = await api.post(`/inventario/sessoes/${sessao.id}/finalizar`, {});
      const r = d.resumo;
      aviso(container, `Inventário nº ${sessao.numero_documento} finalizado — ${r.itens_contados} item(ns) aplicados ao estoque. ` +
        `Resultado: ${brl(r.valor_liquido)} (perdas ${brl(r.valor_perdas)}, sobras ${brl(r.valor_sobras)}).`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  async function acaoCancelar(container, sessao) {
    if (!confirm(
      `Cancelar o inventário nº ${sessao.numero_documento}?\n\n` +
      `Ele deixa de valer, mas continua consultável para análise. ` +
      `O número não é reaproveitado.`)) return;
    try {
      await api.post(`/inventario/sessoes/${sessao.id}/cancelar`, {});
      aviso(container, `Inventário nº ${sessao.numero_documento} cancelado.`, 'sucesso');
      await carregar(container);
    } catch (e) { aviso(container, e.message, 'erro'); }
  }

  // Abrir PDF autenticado agora mora em api.js (abrirArquivo), usado também
  // pela tela de Relatórios — uma implementação só.
  const acaoPdf = (sessao) =>
    abrirArquivo(`/inventario/sessoes/${sessao.id}/relatorio.pdf`);

  const acaoFolha = (sessao) =>
    abrirArquivo(`/inventario/sessoes/${sessao.id}/contagem-cega.pdf`);

  const brl = (v) => 'R$ ' + Number(v || 0).toFixed(2).replace('.', ',');

  function ligarBotoes(container) {
    container.querySelectorAll('[data-acao]').forEach((botao) => {
      botao.addEventListener('click', async () => {
        const acao = botao.dataset.acao;
        const sessao = sessoesCarregadas.find((s) => String(s.id) === botao.dataset.id) || null;

        if (acao === 'abrir') {
          window.AbrirInventario.abrir({
            aoConcluir: async (nova) => {
              aviso(container, `Inventário nº ${nova.numero_documento} aberto. Use "Congelar" para liberar a contagem.`, 'sucesso');
              await carregar(container);
            },
          });
          return;
        }
        if (!sessao) return;

        try {
          if (acao === 'congelar') await acaoCongelar(container, sessao);
          else if (acao === 'finalizar') await acaoFinalizar(container, sessao);
          else if (acao === 'cancelar') await acaoCancelar(container, sessao);
          else if (acao === 'pdf') await acaoPdf(sessao);
          else if (acao === 'folha') await acaoFolha(sessao);
          else if (acao === 'ver') await abrirDetalhe(container, sessao);
        } catch (e) {
          aviso(container, e.message || 'Não foi possível concluir a ação.', 'erro');
        }
      });
    });
  }

  async function abrirDetalhe(container, sessao) {
    const d = await api.get(`/inventario/sessoes/${sessao.id}`);
    const r = d.resumo;
    const painel = container.querySelector('#inv-detalhe');
    painel.hidden = false;
    painel.innerHTML = `
      <div class="card-header">
        <h2>Inventário nº ${d.sessao.numero_documento} — ${d.sessao.descricao || 'sem descrição'}</h2>
        <button class="btn secundario" type="button" id="inv-detalhe-fechar">Fechar</button>
      </div>
      <div class="kpi-grid">
        <div class="kpi-card"><div class="rotulo">Itens no escopo</div><div class="valor">${r.total_itens}</div></div>
        <div class="kpi-card"><div class="rotulo">Contados</div><div class="valor">${r.itens_contados}</div></div>
        <div class="kpi-card"><div class="rotulo">Com divergência</div><div class="valor">${r.itens_com_divergencia}</div></div>
        <div class="kpi-card"><div class="rotulo">Resultado</div><div class="valor">${brl(r.valor_liquido)}</div></div>
      </div>
      ${d.itens.length ? `
        <table class="tabela-simples">
          <thead><tr>
            <th>Código</th><th>Produto</th><th class="num">Estoque anterior</th>
            <th class="num">Contado</th><th class="num">Divergência</th><th class="num">Valor</th>
          </tr></thead>
          <tbody>${d.itens.map((i) => `
            <tr>
              <td><span class="codigo-item">${i.codigo || '—'}</span></td>
              <td>${i.produto || '—'}</td>
              <td class="num">${i.quantidade_sistema}</td>
              <td class="num">${i.quantidade_contada != null ? i.quantidade_contada : '<span class="zerado">não contado</span>'}</td>
              <td class="num ${i.divergencia < 0 ? 'diverg-neg' : (i.divergencia > 0 ? 'diverg-pos' : '')}">${i.quantidade_contada != null ? i.divergencia : '—'}</td>
              <td class="num ${i.valor_divergencia < 0 ? 'diverg-neg' : (i.valor_divergencia > 0 ? 'diverg-pos' : '')}">${i.quantidade_contada != null ? brl(i.valor_divergencia) : '—'}</td>
            </tr>`).join('')}
          </tbody>
        </table>` : `<div class="estado-vazio">Este inventário ainda não foi congelado, então não possui itens.</div>`}
    `;
    painel.querySelector('#inv-detalhe-fechar').addEventListener('click', () => { painel.hidden = true; });
    painel.scrollIntoView({ behavior: 'smooth', block: 'start' });
  }

  async function carregar(container) {
    const alvo = container.querySelector('#inv-tabela');
    alvo.innerHTML = `<div class="estado-vazio">Carregando…</div>`;

    const params = new URLSearchParams({ unidade_id: UNIDADE_SELECIONADA });
    if (filtros.busca) params.set('busca', filtros.busca);
    if (filtros.status) params.set('status', filtros.status);
    if (filtros.dataInicio) params.set('data_inicio', filtros.dataInicio);
    if (filtros.dataFim) params.set('data_fim', filtros.dataFim);

    sessoesCarregadas = await api.get('/inventario/sessoes?' + params.toString());
    alvo.innerHTML = tabela(sessoesCarregadas);
    container.querySelector('#inv-contagem').textContent = `${sessoesCarregadas.length} registro(s)`;

    const temFiltro = !!(filtros.busca || filtros.status || filtros.dataInicio || filtros.dataFim);
    container.querySelector('#inv-limpar').hidden = !temFiltro;

    ligarBotoes(container);
  }

  return {
    async render(container) {
      container.innerHTML = `
        <div class="card">
          <div class="card-header">
            <h2>Inventários <span class="tag" id="inv-contagem"></span></h2>
            ${regional() ? '' : '<button class="btn" type="button" data-acao="abrir">Abrir Inventário</button>'}
          </div>

          ${regional() ? `<div class="faixa-regional">${icone('unidades')}
            <span>Histórico de inventários de todas as unidades, só para consulta.
            Abrir, congelar e finalizar são atos de uma loja — escolha a unidade
            na barra de topo para operar.</span></div>` : ''}

          <div class="filtros-barra">
            <div class="form-group cresce">
              <label for="inv-busca">Buscar</label>
              <input id="inv-busca" placeholder="Número ou descrição…">
            </div>
            <div class="form-group">
              <label for="inv-status">Status</label>
              <select id="inv-status">
                <option value="">Todos</option>
                ${Object.entries(STATUS_INVENTARIO)
                  .map(([chave, s]) => `<option value="${chave}">${s.rotulo}</option>`).join('')}
              </select>
            </div>
            <div class="form-group data">
              <label for="inv-data-inicio">Aberto de</label>
              <input id="inv-data-inicio" type="date">
            </div>
            <div class="form-group data">
              <label for="inv-data-fim">até</label>
              <input id="inv-data-fim" type="date">
            </div>
            <button class="btn secundario" type="button" id="inv-limpar" hidden>Limpar filtros</button>
          </div>

          <p class="aviso-acao" id="inv-aviso-acao" hidden></p>
          <div id="inv-tabela"></div>
        </div>

        <div class="card" id="inv-detalhe" hidden></div>

        <div class="card">
          <div class="card-header"><h2>Status do inventário</h2></div>
          <div class="legenda-status">
            <div><span class="status-badge status-aberto">Aberto</span> criado e com escopo definido — <strong>ainda não recebe contagem</strong></div>
            <div><span class="status-badge status-congelado">Congelado</span> estoque fotografado; a partir daqui aceita contagem</div>
            <div><span class="status-badge status-contagem">Em Contagem</span> já tem contagem lançada</div>
            <div><span class="status-badge status-fechado">Finalizado</span> contagens aplicadas ao estoque; encerrado</div>
            <div><span class="status-badge status-cancelado">Cancelado</span> descartado, mas segue consultável para análise</div>
          </div>
        </div>
      `;

      // Botão geral "Abrir Inventário" (fora da tabela)
      ligarBotoes(container);

      let debounce = null;
      container.querySelector('#inv-busca').addEventListener('input', (ev) => {
        filtros.busca = ev.target.value.trim();
        clearTimeout(debounce);
        debounce = setTimeout(() => carregar(container), 300);
      });
      container.querySelector('#inv-status').addEventListener('change', (ev) => {
        filtros.status = ev.target.value;
        carregar(container);
      });
      container.querySelector('#inv-data-inicio').addEventListener('change', (ev) => {
        filtros.dataInicio = ev.target.value;
        carregar(container);
      });
      container.querySelector('#inv-data-fim').addEventListener('change', (ev) => {
        filtros.dataFim = ev.target.value;
        carregar(container);
      });
      container.querySelector('#inv-limpar').addEventListener('click', () => {
        filtros.busca = ''; filtros.status = ''; filtros.dataInicio = ''; filtros.dataFim = '';
        container.querySelector('#inv-busca').value = '';
        container.querySelector('#inv-status').value = '';
        container.querySelector('#inv-data-inicio').value = '';
        container.querySelector('#inv-data-fim').value = '';
        carregar(container);
      });

      await carregar(container);
    },
  };
})();
