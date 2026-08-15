/* ============================================================
   RELATÓRIOS — quatro documentos, quatro perguntas.

     fechamento   · como fechou o período
     comparativo  · melhorou ou piorou
     curva ABC    · onde negociar primeiro
     famílias     · qual setor está fora da meta

   Cada um sai em dois formatos pela mesma rota: JSON para a tela,
   PDF para imprimir e mandar. A tela não calcula nada — quem apura é
   o mesmo motor de CMV que alimenta o Painel, então relatório e
   painel nunca discordam.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.relatorios = (function () {
  let aba = 'fechamento';
  let referencia = null;
  let catalogo = [];
  const graficos = {};

  const brl = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const brlCurto = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR',
    { maximumFractionDigits: 0 }));
  const pct = (v, casas = 1) => (v == null ? '—'
    : (v * 100).toFixed(casas).replace('.', ',') + '%');
  const pontos = (v) => (v == null ? '—'
    : (v > 0 ? '+' : '') + (v * 100).toFixed(1).replace('.', ',') + ' pp');
  const num = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });
  const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');

  const MESES = ['janeiro', 'fevereiro', 'março', 'abril', 'maio', 'junho',
                 'julho', 'agosto', 'setembro', 'outubro', 'novembro', 'dezembro'];

  function mesAtual() {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}`;
  }

  function deslocarMes(ref, passos) {
    const [ano, mes] = ref.split('-').map(Number);
    const d = new Date(ano, mes - 1 + passos, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }

  function rotuloMes(ref) {
    const [ano, mes] = ref.split('-').map(Number);
    return `${MESES[mes - 1][0].toUpperCase()}${MESES[mes - 1].slice(1)}/${ano}`;
  }

  function destruirGraficos() {
    Object.keys(graficos).forEach((k) => {
      if (graficos[k]) { graficos[k].destroy(); delete graficos[k]; }
    });
  }

  /* Estado vazio que ensina: se não dá para apurar, o relatório diz o
     porquê e o que fazer, em vez de mostrar uma tela de zeros. */
  function indisponivel(d) {
    return `
      <div class="card">
        <div class="estado-vazio">
          ${icone('alerta')}
          <p style="margin:.6rem 0 .2rem"><strong>Relatório não disponível</strong></p>
          <p>${d.motivo || 'Não há dados suficientes no período.'}</p>
          <p style="font-size:.8rem;margin-top:.8rem">
            Um número inventado seria pior que a ausência dele.
            <a href="#inventario">Feche um inventário</a> no período e o relatório passa a existir.
          </p>
        </div>
      </div>`;
  }

  function procedencia(c) {
    // Na Regional não há um par de inventários: cada loja tem o ciclo dela
    if (c.regional) {
      const cob = c.cobertura || {};
      if (cob.completa) {
        return `<span class="rel-procedencia">${icone('unidades')}
          Todas as ${cob.unidades_totais} unidades, cada uma no próprio ciclo</span>`;
      }
      return `<span class="rel-procedencia alerta">${icone('alerta')}
        ${cob.unidades_apuradas} de ${cob.unidades_totais} unidades na soma —
        totais incompletos</span>`;
    }
    if (c.sem_ciclo) {
      return `<span class="rel-procedencia alerta">${icone('inventario')}
        Nenhum inventário finalizado delimita este período</span>`;
    }
    return `<span class="rel-procedencia">${icone('inventario')}
      Estoque de INV-${c.inventario_abertura || '—'} (${dataBR(c.data_inicio)})
      a INV-${c.inventario_fechamento || '—'} (${dataBR(c.data_fim)})</span>`;
  }

  /* Na Regional, todo relatório ganha o desdobramento por loja — o total
     da rede sem saber quem o compõe não serve para decidir nada. */
  function blocoPorUnidade(linhas, titulo = 'Por unidade') {
    if (!linhas || !linhas.length) return '';
    return `
      <div class="card">
        <div class="card-header">
          <div>
            <h2>${titulo}</h2>
            <p class="card-subtitulo">cada uma apurada no próprio ciclo de inventário</p>
          </div>
        </div>
        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th>Unidade</th><th>Inventários</th>
              <th class="num">Est. inicial</th><th class="num">Compras</th>
              <th class="num">Est. final</th><th class="num">CMV</th>
              <th class="num">Faturamento</th><th class="num">CMV %</th><th class="num">Meta</th>
            </tr></thead>
            <tbody>
              ${linhas.map((u) => {
                const dentro = u.cmv_percentual != null && u.meta != null
                  && u.cmv_percentual <= u.meta;
                return `<tr>
                  <td><strong>${u.unidade}</strong></td>
                  <td><span class="codigo-item">${u.inventarios || '—'}</span></td>
                  <td class="num">${brl(u.estoque_inicial)}</td>
                  <td class="num">${brl(u.compras)}</td>
                  <td class="num">${brl(u.estoque_final)}</td>
                  <td class="num"><strong>${brl(u.cmv)}</strong></td>
                  <td class="num">${brl(u.faturamento)}</td>
                  <td class="num ${dentro ? 'valor-bom' : 'valor-ruim'}">
                    <strong>${pct(u.cmv_percentual)}</strong></td>
                  <td class="num">${pct(u.meta)}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  function avisoCobertura(d) {
    const c = d.cobertura;
    if (!c || c.completa) return '';
    return `<div class="aviso-acao">
      <strong>${c.unidades_apuradas} de ${c.unidades_totais} unidades entraram na soma.</strong>
      Fora: ${c.fora.map((f) => `${f.unidade} (${f.motivo})`).join('; ')}.
      Os totais da rede estão incompletos.
    </div>`;
  }

  // ---------------------------------------------------------------- 1 · fechamento
  function verFechamento(d) {
    if (!d.disponivel) return indisponivel(d);
    const cor = d.dentro_da_meta ? 'valor-bom' : 'valor-ruim';
    const conf = d.confiabilidade;
    return `
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="rotulo">CMV do período</div>
          <div class="valor ${cor}">${pct(d.geral.cmv_percentual)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">Em reais</div>
          <div class="valor">${brlCurto(d.geral.cmv)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">Meta</div>
          <div class="valor">${pct(d.meta)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">${d.dentro_da_meta ? 'Folga' : 'Acima da meta'}</div>
          <div class="valor ${cor}">${pontos(d.desvio)}</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header"><h2>Composição</h2></div>
        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th></th><th class="num">Estoque inicial</th><th class="num">Compras</th>
              <th class="num">Estoque final</th><th class="num">CMV</th>
              <th class="num">Faturamento</th><th class="num">CMV %</th>
            </tr></thead>
            <tbody>
              ${['geral', 'comida', 'bebida'].map((chave) => {
                const b = d[chave];
                return `<tr>
                  <td><strong>${chave[0].toUpperCase() + chave.slice(1)}</strong></td>
                  <td class="num">${brl(b.estoque_inicial)}</td>
                  <td class="num">${brl(b.compras)}</td>
                  <td class="num">${brl(b.estoque_final)}</td>
                  <td class="num"><strong>${brl(b.cmv)}</strong></td>
                  <td class="num">${brl(b.faturamento)}</td>
                  <td class="num"><strong>${pct(b.cmv_percentual)}</strong></td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
        <p class="nota-formula">${d.formula} · Comida é tudo que não é bebida.${
          d.regional && d.meta_explicacao ? ' · ' + d.meta_explicacao : ''}</p>
      </div>

      <div class="card">
        <div class="card-header"><h2>Confiabilidade</h2></div>
        <p style="font-size:.88rem;margin:0">
          ${conf.itens_apurados} itens apurados no período.
          ${conf.itens_estimados
            ? `<strong>${conf.itens_estimados} deles (${brl(conf.valor_estimado)})
               não tiveram contagem de fechamento</strong> e entraram com estoque final
               estimado pelo saldo teórico. Quanto maior esse número, mais o CMV
               depende de estimativa.`
            : 'Todos com contagem de fechamento — nenhum valor estimado.'}
        </p>
      </div>

      ${d.regional ? blocoPorUnidade(d.por_unidade) : ''}
      ${avisoCobertura(d)}
      ${d.avisos.length ? `<div class="aviso-acao">${d.avisos.join('<br>')}</div>` : ''}`;
  }

  // ---------------------------------------------------------------- 2 · comparativo
  function tabelaItens(titulo, itens, classe) {
    if (!itens.length) return '';
    return `
      <div class="card">
        <div class="card-header"><h2>${titulo}</h2></div>
        <table class="tabela-simples">
          <thead><tr><th>Código</th><th>Produto</th><th class="num">Atual</th>
            <th class="num">Anterior</th><th class="num">Diferença</th></tr></thead>
          <tbody>
            ${itens.map((i) => `
              <tr>
                <td><span class="codigo-item">${i.codigo || '—'}</span></td>
                <td>${i.produto}</td>
                <td class="num">${brl(i.atual)}</td>
                <td class="num">${brl(i.anterior)}</td>
                <td class="num ${classe}"><strong>${i.delta > 0 ? '+' : ''}${brl(i.delta)}</strong>
                  ${i.delta_percentual != null
                    ? `<span class="rel-delta-pct">${pct(i.delta_percentual, 0)}</span>` : ''}</td>
              </tr>`).join('')}
          </tbody>
        </table>
      </div>`;
  }

  function verComparativo(d) {
    if (!d.disponivel) return indisponivel(d);
    return `
      <div class="card">
        <div class="card-header">
          <h2>${d.cabecalho.rotulo} × ${d.periodo_anterior.rotulo}</h2>
          <span class="tag">meta ${pct(d.meta)}</span>
        </div>
        <table class="tabela-simples">
          <thead><tr><th>Indicador</th><th class="num">${d.cabecalho.rotulo}</th>
            <th class="num">${d.periodo_anterior.rotulo}</th><th class="num">Variação</th></tr></thead>
          <tbody>
            ${d.indicadores.map((i) => {
              const fmt = i.formato === 'PERCENTUAL' ? (v) => pct(v) : brl;
              const variacao = i.formato === 'PERCENTUAL'
                ? pontos(i.variacao)
                : (i.variacao == null ? '—'
                   : (i.variacao > 0 ? '+' : '') + (i.variacao * 100).toFixed(1).replace('.', ',') + '%');
              return `<tr>
                <td>${i.rotulo}</td>
                <td class="num"><strong>${fmt(i.atual)}</strong></td>
                <td class="num">${fmt(i.anterior)}</td>
                <td class="num valor-${i.direcao === 'boa' ? 'bom' : i.direcao === 'ruim' ? 'ruim' : ''}">
                  <strong>${variacao}</strong></td>
              </tr>`;
            }).join('')}
          </tbody>
        </table>
      </div>

      ${d.regional && d.por_unidade && d.por_unidade.length ? `
        <div class="card">
          <div class="card-header"><h2>CMV por unidade</h2></div>
          <table class="tabela-simples">
            <thead><tr><th>Unidade</th><th class="num">${d.cabecalho.rotulo}</th>
              <th class="num">${d.periodo_anterior.rotulo}</th>
              <th class="num">Variação</th><th class="num">Meta</th></tr></thead>
            <tbody>
              ${d.por_unidade.map((u) => `
                <tr>
                  <td><strong>${u.unidade}</strong></td>
                  <td class="num"><strong>${pct(u.atual)}</strong></td>
                  <td class="num">${pct(u.anterior)}</td>
                  <td class="num ${u.variacao == null ? '' : (u.variacao < 0 ? 'valor-bom' : 'valor-ruim')}">
                    <strong>${pontos(u.variacao)}</strong></td>
                  <td class="num">${pct(u.meta)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>` : ''}

      ${tabelaItens('Itens que mais subiram', d.pioraram, 'valor-ruim')}
      ${tabelaItens('Itens que mais caíram', d.melhoraram, 'valor-bom')}
      ${avisoCobertura(d)}`;
  }

  // ---------------------------------------------------------------- 3 · curva ABC
  function verCurvaAbc(d) {
    if (!d.disponivel) return indisponivel(d);
    const r = d.resumo;
    return `
      <div class="kpi-grid">
        ${[['A', '80% do custo', 'faixa-a'], ['B', '15%', 'faixa-b'], ['C', '5%', 'faixa-c']]
          .map(([faixa, legenda, classe]) => `
            <div class="kpi-card">
              <div class="rotulo">Faixa ${faixa} · ${legenda}</div>
              <div class="valor ${classe}">${r[faixa].itens}</div>
              <div class="kpi-meta">${brlCurto(r[faixa].valor)} · ${pct(r[faixa].participacao)}</div>
            </div>`).join('')}
        <div class="kpi-card">
          <div class="rotulo">Total apurado</div>
          <div class="valor">${brlCurto(d.total_cmv)}</div>
          <div class="kpi-meta">${d.total_itens} itens</div>
        </div>
      </div>

      <div class="card">
        <div class="card-header">
          <h2>Concentração do custo</h2>
          <p class="card-subtitulo">Os ${r.A.itens} itens da faixa A concentram
            ${pct(r.A.participacao)} do custo</p>
        </div>
        <div class="area-grafico"><canvas id="grafico-abc"></canvas></div>
      </div>

      <div class="card">
        <div class="card-header">
          <h2>Itens ordenados por custo</h2>
          <input id="abc-busca" placeholder="Buscar produto ou código…" style="max-width:230px">
        </div>
        <div class="tabela-rolavel">
          <table class="tabela-simples" id="abc-tabela">
            <thead><tr>
              <th class="num">#</th><th>Faixa</th><th>Código</th><th>Produto</th>
              <th>Família</th><th class="num">Qtd.</th><th class="num">Custo un.</th>
              <th class="num">CMV</th><th class="num">% do total</th><th class="num">Acumulado</th>
            </tr></thead>
            <tbody>
              ${d.linhas.map((l) => `
                <tr data-busca="${(l.produto + ' ' + (l.codigo || '')).toLowerCase()}">
                  <td class="num">${l.posicao}</td>
                  <td><span class="faixa-abc faixa-${l.faixa.toLowerCase()}">${l.faixa}</span></td>
                  <td><span class="codigo-item">${l.codigo || '—'}</span></td>
                  <td>${l.produto}</td>
                  <td>${l.categoria || '—'}</td>
                  <td class="num">${num(l.quantidade)} ${l.unidade_medida || ''}</td>
                  <td class="num">${brl(l.custo_unitario)}</td>
                  <td class="num"><strong>${brl(l.cmv)}</strong></td>
                  <td class="num">${pct(l.participacao, 2)}</td>
                  <td class="num">${pct(l.acumulado)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>
      ${avisoCobertura(d)}`;
  }

  function desenharAbc(d) {
    const canvas = document.getElementById('grafico-abc');
    if (!canvas || typeof Chart === 'undefined' || !d.linhas.length) return;
    const topo = d.linhas.slice(0, 25);
    graficos.abc = new Chart(canvas, {
      data: {
        labels: topo.map((l) => l.produto.slice(0, 16)),
        datasets: [
          {
            type: 'bar', label: 'CMV do item',
            data: topo.map((l) => l.cmv),
            backgroundColor: topo.map((l) => ({ A: '#A6231F', B: '#B08D3E', C: '#B0B4BB' }[l.faixa])),
            yAxisID: 'y', order: 2,
          },
          {
            type: 'line', label: 'Acumulado',
            data: topo.map((l) => l.acumulado * 100),
            borderColor: '#1F3B57', borderWidth: 2, pointRadius: 0,
            yAxisID: 'y2', order: 1, tension: .2,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: false },
          tooltip: {
            callbacks: {
              label: (c) => (c.dataset.yAxisID === 'y2'
                ? `Acumulado: ${c.parsed.y.toFixed(1).replace('.', ',')}%`
                : `CMV: ${brl(c.parsed.y)}`),
            },
          },
        },
        scales: {
          y: { ticks: { callback: (v) => brlCurto(v), font: { size: 10 } },
               grid: { color: '#EEF0F3' } },
          y2: { position: 'right', min: 0, max: 100, grid: { display: false },
                ticks: { callback: (v) => v + '%', font: { size: 10 } } },
          x: { ticks: { font: { size: 9 }, maxRotation: 60, minRotation: 45 },
               grid: { display: false } },
        },
      },
    });
  }

  // ---------------------------------------------------------------- 4 · famílias
  function verFamilias(d) {
    if (!d.disponivel) return indisponivel(d);
    const maior = Math.max(...d.linhas.map((l) => l.cmv), 1);
    return `
      <div class="card">
        <div class="card-header">
          <h2>Consumo por família</h2>
          <span class="tag">meta geral ${pct(d.meta_geral)}</span>
        </div>
        <p class="nota-formula" style="margin:0 0 .9rem">
          CMV total de ${brl(d.total_cmv)} sobre faturamento de ${brl(d.faturamento)}.
          O percentual de cada família é sobre o faturamento total — por isso a soma
          delas dá exatamente o CMV geral.
        </p>
        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th>Família</th><th class="num">Itens</th><th class="num">CMV</th>
              <th style="min-width:120px">Peso</th>
              <th class="num">% do faturamento</th><th class="num">Meta</th><th>Situação</th>
            </tr></thead>
            <tbody>
              ${d.linhas.map((l) => `
                <tr>
                  <td>${l.familia}${l.eh_bebida ? ' <span class="tag">bebida</span>' : ''}</td>
                  <td class="num">${l.itens}</td>
                  <td class="num"><strong>${brl(l.cmv)}</strong></td>
                  <td>
                    <div class="barra-trilho">
                      <div class="barra-preenchimento${l.eh_bebida ? ' bebida' : ''}"
                           style="width:${((l.cmv / maior) * 100).toFixed(1)}%"></div>
                    </div>
                  </td>
                  <td class="num">${pct(l.percentual, 2)}</td>
                  <td class="num">${pct(l.meta, 2)}${
                    !l.meta_definida && l.meta_herdada_de
                      ? ` <span class="rel-herdada" title="Herdada de ${l.meta_herdada_de}">*</span>` : ''}</td>
                  <td>${l.dentro_da_meta == null ? '—'
                    : l.dentro_da_meta
                      ? `<span class="status-badge status-aberto">dentro</span>`
                      : `<span class="status-badge status-perda">acima</span>`}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
        <p class="nota-formula">
          * meta herdada do bloco — a família ainda não tem meta própria.
          Defina em <a href="#metas">Metas</a>.
        </p>
      </div>

      ${d.evolucao.length ? `
        <div class="card">
          <div class="card-header">
            <h2>Evolução</h2>
            <p class="card-subtitulo">% do faturamento, mês a mês</p>
          </div>
          <div class="area-grafico alto"><canvas id="grafico-familias"></canvas></div>
        </div>` : ''}`;
  }

  function desenharFamilias(d) {
    const canvas = document.getElementById('grafico-familias');
    if (!canvas || typeof Chart === 'undefined') return;
    const cores = ['#1F3B57', '#B08D3E', '#A6231F', '#4A7CA6', '#1C7A3C',
                   '#8A6A1F', '#6B7280', '#9B2C2C'];
    const rotulos = [...d.evolucao.map((e) => e.rotulo.split('/')[0].slice(0, 3)),
                     d.cabecalho.rotulo.split('/')[0].slice(0, 3)];
    const series = d.linhas.slice(0, 6).map((l, i) => ({
      label: l.familia,
      data: [...d.evolucao.map((e) => {
        const v = e.por_familia[l.categoria_id];
        return v == null ? null : v * 100;
      }), l.percentual == null ? null : l.percentual * 100],
      borderColor: cores[i % cores.length],
      backgroundColor: cores[i % cores.length],
      borderWidth: 2, tension: .25, pointRadius: 3, spanGaps: true,
    }));
    graficos.familias = new Chart(canvas, {
      type: 'line',
      data: { labels: rotulos, datasets: series },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 11, font: { size: 11 }, padding: 10 } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(2).replace('.', ',')}%` } },
        },
        scales: {
          y: { ticks: { callback: (v) => v + '%', font: { size: 10 } }, grid: { color: '#EEF0F3' } },
          x: { grid: { display: false } },
        },
      },
    });
  }

  const VISUALIZADORES = {
    fechamento: verFechamento,
    comparativo: verComparativo,
    'curva-abc': verCurvaAbc,
    familias: verFamilias,
  };

  return {
    async render(container) {
      destruirGraficos();
      referencia = referencia || mesAtual();
      if (!catalogo.length) catalogo = await api.get('/relatorios');

      const params = `unidade_id=${UNIDADE_SELECIONADA}&referencia=${referencia}`;
      const atual = catalogo.find((r) => r.chave === aba) || catalogo[0];

      container.innerHTML = `
        <div class="painel-contexto">
          <div class="seletor-mes">
            <button class="btn-icone" type="button" id="rel-anterior" aria-label="Mês anterior">&#8249;</button>
            <span class="mes-atual">${rotuloMes(referencia)}</span>
            <button class="btn-icone" type="button" id="rel-proximo" aria-label="Próximo mês">&#8250;</button>
          </div>
          <div class="procedencia" id="rel-procedencia"></div>
          <button class="btn" type="button" id="rel-pdf">${icone('relatorios')} Gerar PDF</button>
        </div>

        <div class="abas-pagina" id="rel-abas">
          ${catalogo.map((r) => `
            <button class="aba-pagina${r.chave === aba ? ' ativa' : ''}" type="button"
                    data-aba="${r.chave}" title="${r.descricao}">
              <span>${r.nome}</span>
            </button>`).join('')}
        </div>

        <p class="rel-descricao">${atual ? atual.descricao : ''}</p>
        <div id="rel-conteudo"><div class="estado-vazio">Gerando relatório…</div></div>
      `;

      const alvo = container.querySelector('#rel-conteudo');
      let dados;
      try {
        dados = await api.get(`/relatorios/${aba}?${params}`);
      } catch (erro) {
        alvo.innerHTML = `<div class="estado-vazio">Não foi possível gerar: ${erro.message}</div>`;
        return;
      }

      container.querySelector('#rel-procedencia').innerHTML = procedencia(dados.cabecalho);
      alvo.innerHTML = (VISUALIZADORES[aba] || verFechamento)(dados);

      if (aba === 'curva-abc' && dados.disponivel) {
        desenharAbc(dados);
        const busca = container.querySelector('#abc-busca');
        if (busca) {
          busca.addEventListener('input', () => {
            const termo = busca.value.trim().toLowerCase();
            container.querySelectorAll('#abc-tabela tbody tr').forEach((tr) => {
              tr.hidden = termo ? !tr.dataset.busca.includes(termo) : false;
            });
          });
        }
      }
      if (aba === 'familias' && dados.disponivel) desenharFamilias(dados);

      container.querySelectorAll('[data-aba]').forEach((b) => {
        b.addEventListener('click', () => {
          aba = b.dataset.aba;
          window.roteador.rerenderizar();
        });
      });
      container.querySelector('#rel-anterior').addEventListener('click', () => {
        referencia = deslocarMes(referencia, -1);
        window.roteador.rerenderizar();
      });
      container.querySelector('#rel-proximo').addEventListener('click', () => {
        referencia = deslocarMes(referencia, 1);
        window.roteador.rerenderizar();
      });

      // O PDF sai pela mesma rota, só mudando o formato. Abre em aba nova
      // já autenticada, porque a API exige token no cabeçalho.
      container.querySelector('#rel-pdf').addEventListener('click', async () => {
        const botao = container.querySelector('#rel-pdf');
        const original = botao.innerHTML;
        botao.disabled = true;
        botao.textContent = 'Gerando…';
        try {
          await abrirArquivo(`/relatorios/${aba}?${params}&formato=pdf`);
        } catch (erro) {
          alert('Não foi possível gerar o PDF: ' + (erro.message || erro));
        } finally {
          botao.disabled = false;
          botao.innerHTML = original;
        }
      });
    },
  };
})();
