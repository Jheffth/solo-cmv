/* ============================================================
   MOVIMENTAÇÕES — livro-razão de tudo que entrou e saiu do estoque.

   Tela de consulta. Nada é lançado aqui:
     · compras      → Lançador, aba Compras
     · contagens    → nascem do inventário, ao finalizá-lo
     · requisições  → Requisições, ao atender
     · perdas       → Lançador, aba Perda

   Todo movimento carrega o documento que o originou — nº da nota na compra,
   INV-xx no inventário, REQ-xx na requisição, PER-xx na perda. É por ele que
   se volta à origem de qualquer número; por isso ele é o índice da tabela.
   ============================================================ */
window.Paginas = window.Paginas || {};

const RÓTULOS_TIPO_MOVIMENTO = {
  COMPRA: 'Compra',
  CONTAGEM_INICIAL: 'Contagem (inventário)',
  CONTAGEM_FINAL: 'Contagem (inventário)',
  REQUISICAO: 'Requisição',
  PERDA: 'Perda',
};

const CLASSES_TIPO_MOVIMENTO = {
  COMPRA: 'status-aberto',
  CONTAGEM_INICIAL: 'status-congelado',
  CONTAGEM_FINAL: 'status-congelado',
  REQUISICAO: 'status-contagem',
  PERDA: 'status-perda',
};

// O que cada tipo usa como documento, para explicar a coluna sem legenda
const ORIGEM_DOCUMENTO = {
  COMPRA: 'Nota fiscal',
  CONTAGEM_INICIAL: 'Inventário',
  CONTAGEM_FINAL: 'Inventário',
  REQUISICAO: 'Requisição',
  PERDA: 'Perda',
};

// A API devolve data ISO (2026-08-10); na tela vai em pt-BR
const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
const moedaBR = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR',
  { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
const qtdBR = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });

window.Paginas.movimentos = (function () {
  let filtroTipo = '';
  let filtroBusca = '';
  // Os ids marcados, e a última lista carregada — a confirmação precisa
  // NOMEAR o que vai sair, e para isso precisa dos dados, não só dos ids.
  let selecionados = new Set();
  let ultimaLista = [];

  /* A CAIXINHA DE SELEÇÃO É UMA PERMISSÃO, NÃO UM ENFEITE.

     Quem decide se ela aparece é o servidor, em dois níveis: a capacidade
     EXCLUIR_MOVIMENTO diz se a coluna existe para esta pessoa, e o campo
     `travado_para_excluir` de cada linha — calculado pela MESMA função que
     recusa no POST — diz se aquela linha pode ser marcada.

     Nada disso é conferido aqui por conta própria. Tela que decide sozinha
     quem pode o quê é uma segunda régua de permissão, escrita em
     JavaScript e nunca testada contra a primeira; as duas concordam até o
     dia em que uma mudar. */
  function podeExcluir() {
    return typeof window.pode === 'function' && window.pode('EXCLUIR_MOVIMENTO');
  }

  function tabela(movimentos, produtos, fornecedores) {
    const acha = (id) => produtos.find((p) => p.id === id) || {};
    const achaForn = (id) => fornecedores.find((f) => f.id === id) || {};
    if (!movimentos.length) {
      return `<div class="estado-vazio">Nenhuma movimentação encontrada com os filtros atuais.</div>`;
    }
    const regional = typeof emRegional === 'function' && emRegional();
    const selecionavel = podeExcluir();
    return `
      <div class="tabela-rolavel">
      <table class="tabela-simples">
        <thead><tr>
          ${selecionavel ? '<th class="mov-sel"><input type="checkbox" id="mov-todos" title="selecionar todos os que podem ser excluídos"></th>' : ''}
          ${regional ? '<th>Unidade</th>' : ''}
          <th>Data</th><th>Tipo</th><th>Nº Documento</th><th>Produto</th>
          <th class="num">Qtd.</th><th class="num">Custo unit.</th><th class="num">Total</th>
          <th>Fornecedor / Motivo</th>
        </tr></thead>
        <tbody>
          ${movimentos.map((m) => {
            const p = acha(m.produto_id);
            const origem = ORIGEM_DOCUMENTO[m.tipo] || 'Documento';
            // Perda mostra o motivo no lugar do fornecedor: é a informação
            // equivalente — de onde veio, para onde foi.
            const contexto = m.tipo === 'PERDA'
              ? (m.motivo ? `<span class="tag">${(m.motivo || '').replace(/_/g, ' ').toLowerCase()}</span>` : '—')
              : (achaForn(m.fornecedor_id).nome || '—');
            const travado = m.travado_para_excluir;
            const selecao = selecionavel ? `
              <td class="mov-sel">
                <input type="checkbox" class="mov-marca" data-id="${m.id}"
                       ${travado ? 'disabled' : ''}
                       ${selecionados.has(m.id) ? 'checked' : ''}
                       title="${travado ? String(travado).replace(/"/g, '&quot;') : 'selecionar para excluir'}">
                ${travado ? '<span class="mov-cadeado" aria-hidden="true">🔒</span>' : ''}
              </td>` : '';
            return `<tr class="${selecionados.has(m.id) ? 'mov-marcado' : ''}">
              ${selecao}
              ${regional ? `<td><span class="marca-unidade">${m.unidade_nome || '—'}</span></td>` : ''}
              <td>${dataBR(m.data)}</td>
              <td><span class="status-badge ${CLASSES_TIPO_MOVIMENTO[m.tipo] || ''}">${RÓTULOS_TIPO_MOVIMENTO[m.tipo] || m.tipo}</span></td>
              <td><span class="codigo-item" title="${origem}">${m.documento || m.numero_documento || '—'}</span></td>
              <td>${p.nome || `#${m.produto_id}`}${m.observacao ? ` <span class="tag" title="${m.observacao}">obs.</span>` : ''}</td>
              <td class="num">${qtdBR(m.quantidade)}</td>
              <td class="num">${moedaBR(m.custo_unitario)}</td>
              <td class="num">${moedaBR(m.custo_total)}</td>
              <td>${contexto}</td>
            </tr>`;
          }).join('')}
        </tbody>
      </table>
      </div>`;
  }

  /* A CONFIRMAÇÃO NOMEIA O QUE VAI SAIR.

     "Excluir 3 lançamentos?" não é uma pergunta que alguém consiga responder
     — é um pedido de coragem. Quem está prestes a mexer no estoque precisa
     ver O QUÊ, QUANTO e DE QUAL NOTA, porque é aí que se percebe que a linha
     marcada era a do mês passado.

     E o texto avisa do efeito real: sai do saldo E do CMV. Quem só pensou
     em "arrumar a lista" precisa saber que o número do mês vai mudar. */
  function textoDaConfirmacao(marcados, produtos) {
    const nome = (id) => (produtos.find((p) => p.id === id) || {}).nome || `#${id}`;
    const linhas = marcados.slice(0, 8).map((m) =>
      `  · ${dataBR(m.data)}  ${nome(m.produto_id)}  ${qtdBR(m.quantidade)}`
      + `  ${moedaBR(m.custo_total)}  ${m.documento || m.numero_documento || ''}`);
    const resto = marcados.length > 8
      ? `\n  … e mais ${marcados.length - 8} lançamento(s)` : '';
    const total = marcados.reduce((t, m) => t + (Number(m.custo_total) || 0), 0);
    const notas = [...new Set(marcados
      .filter((m) => m.tipo === 'COMPRA' && m.documento)
      .map((m) => m.documento))];

    return `Excluir ${marcados.length} lançamento(s) do estoque?\n\n`
      + linhas.join('\n') + resto
      + `\n\nTotal: ${moedaBR(total)}`
      + `\n\nIsto sai do saldo E do CMV do período — o número do mês vai mudar.`
      + (notas.length
        ? `\nA(s) nota(s) ${notas.join(', ')} voltam a poder ser lançadas.` : '')
      + `\n\nFica registrado quem excluiu e quando.`;
  }

  async function excluirMarcados(container, produtos, fornecedores) {
    const marcados = ultimaLista.filter((m) => selecionados.has(m.id));
    if (!marcados.length) return;
    if (!confirm(textoDaConfirmacao(marcados, produtos))) return;

    const motivo = prompt(
      'Por que estes lançamentos estão sendo excluídos?\n'
      + '(fica no registro, para quem olhar isto depois entender)', '') ;
    if (motivo === null) return;   // desistiu no meio: nada é excluído

    try {
      const r = await api.post('/movimentos/excluir', {
        ids: [...selecionados], motivo,
      });
      selecionados = new Set();
      await carregar(container, produtos, fornecedores);
      alert(`${r.excluidos} lançamento(s) saíram do estoque.`
        + (r.avisos && r.avisos.length ? '\n\n' + r.avisos.join('\n') : ''));
    } catch (erro) {
      alert(erro.message || 'Não foi possível excluir.');
    }
  }

  function atualizarBarra(container) {
    const barra = container.querySelector('#mov-acoes');
    if (!barra) return;
    barra.hidden = selecionados.size === 0;
    const contador = container.querySelector('#mov-selecionados');
    if (contador) contador.textContent = `${selecionados.size} selecionado(s)`;
  }

  async function carregar(container, produtos, fornecedores) {
    const alvo = container.querySelector('#mov-tabela');
    alvo.innerHTML = `<div class="estado-vazio">Carregando…</div>`;

    const params = new URLSearchParams({ unidade_id: UNIDADE_SELECIONADA });
    if (filtroTipo) params.set('tipo', filtroTipo);
    let movs = await api.get('/movimentos?' + params.toString());

    if (filtroBusca) {
      const termo = filtroBusca.toLowerCase();
      const ids = produtos
        .filter((p) => (p.nome || '').toLowerCase().includes(termo) || (p.codigo || '').includes(termo))
        .map((p) => p.id);
      const idsForn = fornecedores
        .filter((f) => (f.nome || '').toLowerCase().includes(termo))
        .map((f) => f.id);
      movs = movs.filter((m) => ids.includes(m.produto_id)
        || idsForn.includes(m.fornecedor_id)
        || (m.documento || m.numero_documento || '').toLowerCase().includes(termo));
    }

    ultimaLista = movs;
    // Marcado que saiu da lista (por filtro ou por já ter sido excluído) não
    // pode continuar contando: senão o botão diz "3 selecionados" apontando
    // para linhas que a pessoa não está mais vendo.
    const visiveis = new Set(movs.map((m) => m.id));
    selecionados = new Set([...selecionados].filter((id) => visiveis.has(id)));

    alvo.innerHTML = tabela(movs, produtos, fornecedores);
    container.querySelector('#mov-contagem').textContent = `${movs.length} registro(s)`;
    container.querySelector('#mov-limpar').hidden = !(filtroTipo || filtroBusca);
    ligarSelecao(container, produtos, fornecedores);
    atualizarBarra(container);
  }

  function ligarSelecao(container, produtos, fornecedores) {
    container.querySelectorAll('.mov-marca').forEach((caixa) => {
      caixa.addEventListener('change', () => {
        const id = Number(caixa.dataset.id);
        if (caixa.checked) selecionados.add(id); else selecionados.delete(id);
        caixa.closest('tr').classList.toggle('mov-marcado', caixa.checked);
        atualizarBarra(container);
      });
    });
    const todos = container.querySelector('#mov-todos');
    if (todos) todos.addEventListener('change', () => {
      // Só os que PODEM. "Selecionar todos" que marcasse o travado só para
      // a exclusão recusar o lote inteiro depois seria uma armadilha.
      container.querySelectorAll('.mov-marca:not([disabled])').forEach((caixa) => {
        caixa.checked = todos.checked;
        caixa.dispatchEvent(new Event('change'));
      });
    });
  }

  return {
    async render(container) {
      const [produtos, fornecedores] = await Promise.all([
        api.get('/produtos'),
        api.get('/fornecedores').catch(() => []),
      ]);

      container.innerHTML = `
        <div class="card">
          <div class="card-header">
            <h2>Movimentações <span class="tag" id="mov-contagem"></span></h2>
          </div>

          ${typeof emRegional === 'function' && emRegional() ? `
            <div class="faixa-regional">${icone('unidades')}
              <span>Livro-razão consolidado de todas as unidades. Cada linha
              é um lançamento de uma loja específica — movimento não se soma.</span>
            </div>` : ''}
          <p style="color:var(--muted);font-size:.83rem;margin:0 0 .9rem">
            Livro-razão de tudo que entrou e saiu do estoque. Esta tela é só de consulta —
            compras e perdas são lançadas pelo <strong>Lançador</strong>, contagens nascem do
            <strong>inventário</strong> ao finalizá-lo, e requisições ao serem atendidas.
            O <strong>Nº Documento</strong> identifica a origem: nota fiscal na compra,
            INV no inventário, REQ na requisição, PER na perda.
          </p>

          <div class="filtros-barra">
            <div class="form-group cresce">
              <label for="mov-busca">Buscar</label>
              <input id="mov-busca" placeholder="Produto, código, fornecedor ou documento…">
            </div>
            <div class="form-group">
              <label for="mov-tipo">Tipo</label>
              <select id="mov-tipo">
                <option value="">Todos</option>
                <option value="COMPRA">Compra</option>
                <option value="CONTAGEM_FINAL">Contagem (inventário)</option>
                <option value="REQUISICAO">Requisição</option>
                <option value="PERDA">Perda</option>
              </select>
            </div>
            <button class="btn secundario" type="button" id="mov-limpar" hidden>Limpar filtros</button>
          </div>

          ${podeExcluir() ? `
            <div class="mov-acoes" id="mov-acoes" hidden>
              <span id="mov-selecionados"></span>
              <button class="btn btn-perigo" type="button" id="mov-excluir">
                Excluir do estoque
              </button>
              <button class="btn secundario" type="button" id="mov-desmarcar">
                Desmarcar
              </button>
            </div>` : ''}

          <div id="mov-tabela"></div>
        </div>
      `;

      let debounce = null;
      container.querySelector('#mov-busca').addEventListener('input', (ev) => {
        filtroBusca = ev.target.value.trim();
        clearTimeout(debounce);
        debounce = setTimeout(() => carregar(container, produtos, fornecedores), 300);
      });
      container.querySelector('#mov-tipo').addEventListener('change', (ev) => {
        filtroTipo = ev.target.value;
        carregar(container, produtos, fornecedores);
      });
      container.querySelector('#mov-limpar').addEventListener('click', () => {
        filtroTipo = ''; filtroBusca = '';
        container.querySelector('#mov-busca').value = '';
        container.querySelector('#mov-tipo').value = '';
        carregar(container, produtos, fornecedores);
      });

      const botaoExcluir = container.querySelector('#mov-excluir');
      if (botaoExcluir) botaoExcluir.addEventListener('click',
        () => excluirMarcados(container, produtos, fornecedores));
      const desmarcar = container.querySelector('#mov-desmarcar');
      if (desmarcar) desmarcar.addEventListener('click', () => {
        selecionados = new Set();
        carregar(container, produtos, fornecedores);
      });

      await carregar(container, produtos, fornecedores);
    },
  };
})();
