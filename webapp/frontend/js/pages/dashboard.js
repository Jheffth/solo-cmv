/* ============================================================
   PAINEL — a primeira tela, em seis faixas.

   Cada faixa responde uma pergunta, e só uma:

     0. contexto      · de que período estamos falando, e de onde ele vem
     1. pendências    · o que exige ação hoje  (some quando não há nada)
     2. indicadores   · como estamos
     3. tendência     · para onde estamos indo
     4. detalhamento  · onde está o dinheiro
     5. atividade     · o que acabou de acontecer

   Tudo vem de UMA chamada (/dashboard/painel). Nenhuma regra de negócio
   mora aqui: a tela só desenha o que o serviço já calculou.

   Todo número é uma porta — clicar leva à tela onde ele nasce.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.dashboard = (function () {
  let referencia = null;          // "2026-08"
  const graficos = {};            // instâncias do Chart.js, para destruir ao redesenhar

  const CORES = {
    navy: '#1F3B57', gold: '#B08D3E', vermelho: '#A6231F',
    verde: '#1C7A3C', azul: '#4A7CA6', cinza: '#B0B4BB',
  };

  const MESES = ['jan', 'fev', 'mar', 'abr', 'mai', 'jun',
                 'jul', 'ago', 'set', 'out', 'nov', 'dez'];

  const brl = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR',
    { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const brlCurto = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR',
    { maximumFractionDigits: 0 }));
  const pct = (v) => (v == null ? '—' : (v * 100).toFixed(1).replace('.', ',') + '%');
  const num = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });
  const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');

  const formatar = (valor, formato) => {
    if (valor == null) return '—';
    if (formato === 'PERCENTUAL') return pct(valor);
    if (formato === 'NUMERO') return num(valor);
    return brlCurto(valor);
  };

  function mesAtual() {
    const h = new Date();
    return `${h.getFullYear()}-${String(h.getMonth() + 1).padStart(2, '0')}`;
  }

  function deslocarMes(ref, passos) {
    const [ano, mes] = ref.split('-').map(Number);
    const d = new Date(ano, mes - 1 + passos, 1);
    return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, '0')}`;
  }

  /* Sparkline em SVG puro. Cinco instâncias de Chart.js só para desenhar
     cinco linhas de 40px seria desperdício — isto são 12 linhas de código
     e nenhum objeto vivo depois do render. */
  function sparkline(serie, cor) {
    if (!serie || serie.length < 2) return '';
    const min = Math.min(...serie);
    const max = Math.max(...serie);
    const faixa = (max - min) || 1;
    const pontos = serie.map((v, i) => {
      const x = (i / (serie.length - 1)) * 100;
      const y = 22 - ((v - min) / faixa) * 18 - 2;
      return `${x.toFixed(1)},${y.toFixed(1)}`;
    }).join(' ');
    return `<svg class="sparkline" viewBox="0 0 100 22" preserveAspectRatio="none"
              aria-hidden="true"><polyline points="${pontos}" fill="none"
              stroke="${cor}" stroke-width="2" vector-effect="non-scaling-stroke"/></svg>`;
  }

  function variacao(kpi) {
    if (kpi.variacao == null) return '<span class="kpi-variacao neutra">sem período anterior</span>';
    const seta = kpi.variacao > 0 ? '&#9650;' : '&#9660;';
    const texto = kpi.formato === 'PERCENTUAL'
      ? `${Math.abs(kpi.variacao * 100).toFixed(1).replace('.', ',')} pp`
      : `${Math.abs(kpi.variacao * 100).toFixed(0)}%`;
    return `<span class="kpi-variacao ${kpi.direcao || 'neutra'}">${seta} ${texto} vs anterior</span>`;
  }

  function cartaoKpi(chave, rotulo, kpi, rota, corSerie) {
    const classeValor = kpi.dentro_da_meta === true ? 'valor-bom'
      : kpi.dentro_da_meta === false ? 'valor-ruim' : '';
    const complemento = kpi.meta != null
      ? `<span class="kpi-meta">meta ${pct(kpi.meta)}</span>`
      : (kpi.detalhe ? `<span class="kpi-meta">${kpi.detalhe}</span>` : '');
    return `
      <button class="kpi-card clicavel" type="button" data-ir="${rota}" data-kpi="${chave}">
        <div class="rotulo">${rotulo}</div>
        <div class="valor ${classeValor}">${formatar(kpi.valor, kpi.formato)}</div>
        <div class="kpi-rodape">${variacao(kpi)}${complemento}</div>
        ${sparkline(kpi.serie, corSerie)}
      </button>`;
  }

  function faixaPendencias(pendencias) {
    if (!pendencias.length) return '';
    return `
      <div class="pendencias">
        ${pendencias.map((p) => {
          // Sem rota, não é botão. O aviso de backup se resolve no servidor,
          // não numa tela — e um botão que leva a lugar nenhum ensina a
          // desconfiar de todos os outros.
          if (!p.rota) {
            return `
              <div class="pendencia ${p.gravidade} sem-rota">
                ${icone('alerta')}
                <span class="pendencia-texto">${p.texto}</span>
              </div>`;
          }
          return `
            <button class="pendencia ${p.gravidade}" type="button" data-ir="${p.rota}">
              ${icone('alerta')}
              <span class="pendencia-texto">${p.texto}</span>
              <span class="pendencia-rota">${p.rota} &rarr;</span>
            </button>`;
        }).join('')}
      </div>`;
  }

  /* O selo de proteção. Aparece só para a diretoria, e só quando o backup
     está EM DIA — quando não está, a pendência acima já grita, e repetir a
     mesma coisa em dois lugares dilui as duas.

     Existir mesmo estando tudo certo é o ponto: saber que se está protegido
     não deveria depender de um alerta. É a única informação do painel que
     vale justamente por ser silenciosa. */
  function seloProtecao(p) {
    if (!p || p.estado !== 'ok') return '';
    return `
      <div class="selo-protecao" title="${p.detalhe}">
        ${icone('cadeado') || ''}
        <span><strong>${p.titulo}</strong> · ${p.detalhe}</span>
      </div>`;
  }

  function blocoTopItens(itens) {
    if (!itens.length) {
      return `<div class="estado-vazio">Sem itens apurados neste período.</div>`;
    }
    const maior = itens[0].cmv || 1;
    return `<div class="barras-itens">
      ${itens.map((i) => `
        <div class="barra-item">
          <div class="barra-cabecalho">
            <span class="barra-nome"><span class="codigo-item">${i.codigo || '—'}</span> ${i.produto}</span>
            <span class="barra-valor">${brlCurto(i.cmv)} · ${pct(i.participacao)}</span>
          </div>
          <div class="barra-trilho">
            <div class="barra-preenchimento${i.eh_bebida ? ' bebida' : ''}"
                 style="width:${((i.cmv / maior) * 100).toFixed(1)}%"></div>
          </div>
        </div>`).join('')}
    </div>`;
  }

  function blocoEstoqueParado(itens) {
    if (!itens.length) {
      return `<div class="estado-vazio">Nenhum item com saldo parado há mais de 30 dias.</div>`;
    }
    const total = itens.reduce((s, i) => s + i.valor, 0);
    return `
      <p class="nota-formula" style="margin:0 0 .7rem">
        ${brlCurto(total)} imobilizados em itens sem giro.
      </p>
      <table class="tabela-simples">
        <thead><tr><th>Código</th><th>Produto</th><th class="num">Saldo</th>
          <th class="num">Valor</th><th class="num">Parado há</th></tr></thead>
        <tbody>
          ${itens.map((i) => `
            <tr>
              <td><span class="codigo-item">${i.codigo || '—'}</span></td>
              <td>${i.produto}</td>
              <td class="num">${num(i.quantidade)} ${i.unidade_medida || ''}</td>
              <td class="num">${brlCurto(i.valor)}</td>
              <td class="num">${i.dias == null ? 'nunca movimentou' : i.dias + ' dias'}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  const ROTULO_TIPO = {
    COMPRA: 'Compra', CONTAGEM_INICIAL: 'Contagem', CONTAGEM_FINAL: 'Contagem',
    REQUISICAO: 'Requisição', PERDA: 'Perda',
  };
  const CLASSE_TIPO = {
    COMPRA: 'status-aberto', CONTAGEM_INICIAL: 'status-congelado',
    CONTAGEM_FINAL: 'status-congelado', REQUISICAO: 'status-contagem',
    PERDA: 'status-perda',
  };

  function blocoAtividade(itens) {
    if (!itens.length) return `<div class="estado-vazio">Nenhum lançamento ainda.</div>`;
    return `
      <table class="tabela-simples">
        <thead><tr><th>Data</th><th>Tipo</th><th>Nº Documento</th><th>Produto</th>
          <th class="num">Qtd.</th><th class="num">Valor</th></tr></thead>
        <tbody>
          ${itens.map((a) => `
            <tr>
              <td>${dataBR(a.data)}</td>
              <td><span class="status-badge ${CLASSE_TIPO[a.tipo] || ''}">${ROTULO_TIPO[a.tipo] || a.tipo}</span></td>
              <td><span class="codigo-item">${a.documento || '—'}</span></td>
              <td>${a.produto}</td>
              <td class="num">${num(a.quantidade)}</td>
              <td class="num">${a.valor == null ? '—' : brl(a.valor)}</td>
            </tr>`).join('')}
        </tbody>
      </table>`;
  }

  /* Chart.js guarda referência global ao canvas; sem destruir, cada troca
     de período deixa uma instância viva desenhando por baixo. */
  function destruirGraficos() {
    Object.keys(graficos).forEach((k) => {
      if (graficos[k]) { graficos[k].destroy(); delete graficos[k]; }
    });
  }

  function desenharTendencia(historico, atual, meta) {
    const canvas = document.getElementById('grafico-tendencia');
    if (!canvas || typeof Chart === 'undefined') return;

    const pontos = [...historico, atual].filter((p) => p && p.cmv_percentual != null);
    if (pontos.length < 2) {
      canvas.parentElement.innerHTML =
        `<div class="grafico-vazio">${icone('grafico')}<span>É preciso pelo menos dois
         períodos apurados para desenhar a tendência.</span></div>`;
      return;
    }

    graficos.tendencia = new Chart(canvas, {
      type: 'line',
      data: {
        labels: pontos.map((p) => p.rotulo),
        datasets: [
          {
            label: 'CMV %',
            data: pontos.map((p) => p.cmv_percentual * 100),
            borderColor: CORES.navy, backgroundColor: CORES.navy,
            borderWidth: 2.5, tension: .25, pointRadius: 4, pointHoverRadius: 6,
          },
          {
            // A meta é linha em degraus: ela muda na data da vigência, e o
            // gráfico precisa mostrar isso — senão o histórico seria julgado
            // por um alvo que não existia na época.
            label: 'Meta',
            data: pontos.map((p) => (p.meta != null ? p.meta * 100 : meta * 100)),
            borderColor: CORES.gold, borderDash: [6, 4], borderWidth: 2,
            pointRadius: 0, stepped: true, tension: 0,
          },
        ],
      },
      options: {
        responsive: true, maintainAspectRatio: false,
        plugins: {
          legend: { display: true, position: 'bottom', labels: { boxWidth: 12, font: { size: 11 } } },
          tooltip: { callbacks: { label: (c) => `${c.dataset.label}: ${c.parsed.y.toFixed(1)}%` } },
        },
        scales: {
          y: { ticks: { callback: (v) => v + '%', font: { size: 11 } }, grid: { color: '#EEF0F3' } },
          x: { grid: { display: false }, ticks: { font: { size: 11 } } },
        },
      },
    });
  }

  function desenharRosca(id, chave, rotulos, valores, cores, centro) {
    const canvas = document.getElementById(id);
    if (!canvas || typeof Chart === 'undefined') return;
    if (!valores.some((v) => v > 0)) {
      canvas.parentElement.innerHTML =
        `<div class="grafico-vazio">${icone('grafico')}<span>Sem dados no período.</span></div>`;
      return;
    }
    graficos[chave] = new Chart(canvas, {
      type: 'doughnut',
      data: { labels: rotulos, datasets: [{ data: valores, backgroundColor: cores, borderWidth: 0 }] },
      options: {
        responsive: true, maintainAspectRatio: false, cutout: '62%',
        plugins: {
          legend: { position: 'bottom', labels: { boxWidth: 11, font: { size: 11 }, padding: 10 } },
          tooltip: { callbacks: { label: (c) => `${c.label}: ${brl(c.parsed)}` } },
        },
      },
    });
    if (centro) {
      canvas.insertAdjacentHTML('afterend', `<div class="rosca-centro">${centro}</div>`);
    }
  }

  /* ------------------------------------------------------------------
     PAINEL REGIONAL

     A soma da rede. Duas coisas mudam em relação ao painel de uma loja:

     · a procedência não é um par de inventários, e sim "cada unidade no
       próprio ciclo" — Josefina pode fechar dia 10 e Casa Josefina dia 12;
     · aparece a COBERTURA: quantas lojas entraram na soma e quais ficaram
       de fora. Um total incompleto é aceitável; um total incompleto
       disfarçado, não.
     ------------------------------------------------------------------ */
  function faixaCobertura(c) {
    if (c.completa) {
      return `<div class="cobertura completa">${icone('check')}
        <span>Todas as ${c.unidades_totais} unidades entraram na consolidação</span></div>`;
    }
    return `
      <div class="cobertura incompleta">
        ${icone('alerta')}
        <div>
          <strong>${c.unidades_apuradas} de ${c.unidades_totais} unidades na soma.</strong>
          Fora: ${c.fora.map((f) => `${f.unidade} (${f.motivo})`).join('; ')}.
          Os totais da rede estão incompletos.
        </div>
      </div>`;
  }

  function quadroUnidades(unidades) {
    return `
      <div class="card">
        <div class="card-header">
          <div>
            <h2>Por unidade</h2>
            <p class="card-subtitulo">cada uma apurada no próprio ciclo de inventário</p>
          </div>
        </div>
        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th>Unidade</th><th>Inventários</th><th class="num">CMV %</th>
              <th class="num">Meta</th><th class="num">CMV</th>
              <th class="num">Faturamento</th><th class="num">Peso na rede</th>
            </tr></thead>
            <tbody>
              ${unidades.map((u) => {
                if (!u.entrou) {
                  return `<tr class="fora">
                    <td>${u.unidade}</td>
                    <td colspan="6"><em>${u.motivo || 'não apurada'}</em></td>
                  </tr>`;
                }
                const classe = u.dentro_da_meta ? 'valor-bom' : 'valor-ruim';
                return `<tr>
                  <td><strong>${u.unidade}</strong></td>
                  <td><span class="codigo-item">${u.inventarios}</span></td>
                  <td class="num ${classe}"><strong>${pct(u.cmv_percentual)}</strong></td>
                  <td class="num">${pct(u.meta)}</td>
                  <td class="num">${brlCurto(u.cmv)}</td>
                  <td class="num">${brlCurto(u.faturamento)}</td>
                  <td class="num">${pct(u.participacao_faturamento)}</td>
                </tr>`;
              }).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  function renderRegional(container, d) {
    const g = d.geral;
    const dentro = g.cmv_percentual != null && g.cmv_percentual <= d.meta.valor;
    const classe = dentro ? 'valor-bom' : 'valor-ruim';
    const anterior = d.historico.length ? d.historico[d.historico.length - 1] : null;

    container.innerHTML = `
      <div class="painel-contexto regional">
        <div class="seletor-mes">
          <button class="btn-icone" type="button" id="mes-anterior" aria-label="Mês anterior">&#8249;</button>
          <span class="mes-atual">${d.periodo.rotulo}</span>
          <button class="btn-icone" type="button" id="mes-proximo" aria-label="Próximo mês">&#8250;</button>
        </div>
        <div class="procedencia">
          ${icone('unidades')}<span>${d.periodo.explicacao}</span>
        </div>
        <button class="btn secundario" type="button" id="ir-mes-atual">Mês atual</button>
      </div>

      ${faixaCobertura(d.cobertura)}

      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="rotulo">CMV da rede</div>
          <div class="valor ${classe}">${pct(g.cmv_percentual)}</div>
          <div class="kpi-rodape">
            <span class="kpi-meta">meta ${pct(d.meta.valor)}</span>
          </div>
          ${sparkline(d.historico.map((h) => h.cmv_percentual).filter((v) => v != null), CORES.navy)}
        </div>
        <div class="kpi-card">
          <div class="rotulo">CMV em reais</div>
          <div class="valor">${brlCurto(g.cmv)}</div>
          <div class="kpi-rodape"><span class="kpi-meta">soma das unidades</span></div>
          ${sparkline(d.historico.map((h) => h.cmv), CORES.cinza)}
        </div>
        <div class="kpi-card">
          <div class="rotulo">Faturamento</div>
          <div class="valor">${brlCurto(g.faturamento)}</div>
          <div class="kpi-rodape"><span class="kpi-meta">${anterior
            ? 'anterior ' + brlCurto(anterior.faturamento) : 'sem período anterior'}</span></div>
          ${sparkline(d.historico.map((h) => h.faturamento), CORES.gold)}
        </div>
        <div class="kpi-card">
          <div class="rotulo">Perdas</div>
          <div class="valor">${brlCurto(d.perdas.valor_total)}</div>
          <div class="kpi-rodape"><span class="kpi-meta">${pct(g.cmv
            ? d.perdas.valor_total / g.cmv : null)} do CMV</span></div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">Em estoque</div>
          <div class="valor">${brlCurto(d.estoque.valor_total)}</div>
          <div class="kpi-rodape"><span class="kpi-meta">${d.estoque.itens_com_saldo}
            itens com saldo</span></div>
        </div>
      </div>

      <p class="nota-formula" style="margin:-.6rem 0 1.1rem">
        O CMV da rede é recalculado sobre os totais (${brlCurto(g.cmv)} ÷
        ${brlCurto(g.faturamento)}), nunca a média dos percentuais das lojas —
        uma unidade pequena não pode puxar o número da rede como se fosse grande.
        ${d.meta.origem === 'PONDERADA' ? ' A meta segue o mesmo critério: ' + d.meta.explicacao : ''}
      </p>

      ${quadroUnidades(d.por_unidade)}

      <div class="grid-tendencia">
        <div class="card">
          <div class="card-header">
            <div>
              <h2>CMV da rede × meta</h2>
              <p class="card-subtitulo">${d.historico.length + 1} períodos consolidados</p>
            </div>
          </div>
          <div class="area-grafico alto"><canvas id="grafico-tendencia"></canvas></div>
        </div>
        <div class="card">
          <div class="card-header">
            <div>
              <h2>Estoque por unidade</h2>
              <p class="card-subtitulo">posição de agora</p>
            </div>
          </div>
          <div class="area-grafico alto"><canvas id="grafico-estoque-unidades"></canvas></div>
        </div>
      </div>

      <div class="grid-detalhe">
        <div class="card">
          <div class="card-header">
            <div>
              <h2>Itens que puxam o CMV da rede</h2>
              <p class="card-subtitulo">mesmo produto somado entre as lojas</p>
            </div>
          </div>
          ${blocoTopItens(d.top_itens)}
        </div>
        <div class="card">
          <div class="card-header">
            <div>
              <h2>Perdas por motivo</h2>
              <p class="card-subtitulo">${brlCurto(d.perdas.valor_total)} na rede</p>
            </div>
          </div>
          <div class="area-grafico"><canvas id="grafico-perdas"></canvas></div>
        </div>
      </div>

      ${d.avisos.length ? `<div class="aviso-acao">${d.avisos.join('<br>')}</div>` : ''}
    `;

    desenharTendencia(d.historico, {
      rotulo: MESES[parseInt(referencia.split('-')[1], 10) - 1],
      cmv_percentual: g.cmv_percentual, meta: d.meta.valor,
    }, d.meta.valor);

    const canvasEstoque = document.getElementById('grafico-estoque-unidades');
    if (canvasEstoque && typeof Chart !== 'undefined' && d.estoque.por_unidade.length) {
      graficos.estoqueUnidades = new Chart(canvasEstoque, {
        type: 'bar',
        data: {
          labels: d.estoque.por_unidade.map((u) => u.unidade),
          datasets: [{ data: d.estoque.por_unidade.map((u) => u.valor),
                       backgroundColor: CORES.navy }],
        },
        options: {
          indexAxis: 'y', responsive: true, maintainAspectRatio: false,
          plugins: { legend: { display: false },
                     tooltip: { callbacks: { label: (c) => brl(c.parsed.x) } } },
          scales: { x: { ticks: { callback: (v) => brlCurto(v), font: { size: 10 } } },
                    y: { grid: { display: false } } },
        },
      });
    }

    desenharRosca('grafico-perdas', 'perdas',
      d.perdas.por_motivo.map((m) => m.rotulo),
      d.perdas.por_motivo.map((m) => m.valor),
      [CORES.vermelho, '#EF9F27', CORES.cinza, CORES.azul, CORES.verde, CORES.gold, CORES.navy]);
  }

  function esqueleto(container) {
    container.innerHTML = `
      <div class="painel-esqueleto">
        <div class="esq-barra" style="height:64px"></div>
        <div class="kpi-grid">
          ${'<div class="esq-barra" style="height:118px"></div>'.repeat(5)}
        </div>
        <div class="grid-tendencia">
          <div class="esq-barra" style="height:280px"></div>
          <div class="esq-barra" style="height:280px"></div>
        </div>
      </div>`;
  }

  return {
    async render(container) {
      destruirGraficos();
      esqueleto(container);
      referencia = referencia || mesAtual();

      let d;
      try {
        // Na primeira pintura os números já vieram junto com a sessão, numa
        // viagem só. Só aproveitamos se forem do mesmo mês e da mesma
        // unidade que a tela vai mostrar — trocar de loja ou de mês exige
        // dado novo. Depois de usado, o adiantamento é descartado: qualquer
        // atualização daqui em diante busca do servidor.
        const adiantado = window.ABERTURA && ABERTURA.painel;
        const serve = adiantado
          && String(ABERTURA.unidade) === String(UNIDADE_SELECIONADA)
          && referencia === mesAtual();
        if (window.ABERTURA) ABERTURA.painel = null;

        d = serve ? adiantado : await api.get(
          `/dashboard/painel?unidade_id=${UNIDADE_SELECIONADA}&referencia=${referencia}`);
      } catch (erro) {
        container.innerHTML =
          `<div class="estado-vazio">Não foi possível carregar o painel: ${erro.message}</div>`;
        return;
      }

      // A Regional tem estrutura própria: soma, cobertura e quadro por loja
      if (d.regional) {
        renderRegional(container, d);
        ligarNavegacaoDeMes(container);
        return;
      }

      const p = d.periodo;
      const k = d.kpis;
      const procedencia = p.sem_ciclo
        ? `Nenhum inventário finalizado delimita este período — os números de CMV não podem ser apurados.`
        : `Apurado de INV-${p.inventario_abertura || '—'} (${dataBR(p.data_inicio)})`
          + ` a INV-${p.inventario_fechamento || '—'} (${dataBR(p.data_fim)})`;

      container.innerHTML = `
        <!-- Faixa 0 · contexto -->
        <div class="painel-contexto">
          <div class="seletor-mes">
            <button class="btn-icone" type="button" id="mes-anterior" aria-label="Mês anterior">&#8249;</button>
            <span class="mes-atual">${p.rotulo}</span>
            <button class="btn-icone" type="button" id="mes-proximo" aria-label="Próximo mês">&#8250;</button>
          </div>
          <div class="procedencia ${p.sem_ciclo ? 'alerta' : ''}">
            ${icone('inventario')}<span>${procedencia}</span>
          </div>
          <button class="btn secundario" type="button" id="ir-mes-atual">Mês atual</button>
        </div>

        <!-- Faixa 1 · o que exige ação -->
        ${faixaPendencias(d.pendencias)}
        ${seloProtecao(d.protecao)}

        <!-- Faixa 2 · como estamos -->
        <div class="kpi-grid">
          ${cartaoKpi('cmv_percentual', 'CMV', k.cmv_percentual, 'cmv', CORES.navy)}
          ${cartaoKpi('cmv_valor', 'CMV em reais', k.cmv_valor, 'cmv', CORES.cinza)}
          ${cartaoKpi('faturamento', 'Faturamento', k.faturamento, 'vendas', CORES.gold)}
          ${cartaoKpi('perdas', 'Perdas', k.perdas, 'movimentos', CORES.vermelho)}
          ${cartaoKpi('estoque', 'Em estoque', k.estoque, 'estoque', CORES.cinza)}
        </div>

        <!-- Faixa 3 · para onde estamos indo -->
        <div class="grid-tendencia">
          <div class="card">
            <div class="card-header">
              <div>
                <h2>CMV × meta</h2>
                <p class="card-subtitulo">últimos ${d.historico.length + 1} períodos apurados</p>
              </div>
            </div>
            <div class="area-grafico alto"><canvas id="grafico-tendencia"></canvas></div>
          </div>
          <div class="card">
            <div class="card-header">
              <div>
                <h2>Composição</h2>
                <p class="card-subtitulo">comida × bebida</p>
              </div>
            </div>
            <div class="area-grafico alto"><canvas id="grafico-composicao"></canvas></div>
            <div class="composicao-numeros">
              <div><span class="ponto navy"></span>Comida
                <strong>${pct(d.composicao.comida ? d.composicao.comida.cmv_percentual : null)}</strong></div>
              <div><span class="ponto azul"></span>Bebida
                <strong>${pct(d.composicao.bebida ? d.composicao.bebida.cmv_percentual : null)}</strong></div>
            </div>
          </div>
        </div>

        <!-- Faixa 4 · onde está o dinheiro -->
        <div class="grid-detalhe">
          <div class="card">
            <div class="card-header">
              <div>
                <h2>Itens que puxam o CMV</h2>
                <p class="card-subtitulo">os 10 maiores do período</p>
              </div>
            </div>
            ${blocoTopItens(d.top_itens)}
          </div>
          <div class="card">
            <div class="card-header">
              <div>
                <h2>Perdas por motivo</h2>
                <p class="card-subtitulo">${brlCurto(d.perdas.valor_total)} no período</p>
              </div>
            </div>
            <div class="area-grafico"><canvas id="grafico-perdas"></canvas></div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <div>
              <h2>Estoque parado</h2>
              <p class="card-subtitulo">com saldo e sem movimento há mais de 30 dias</p>
            </div>
          </div>
          ${blocoEstoqueParado(d.estoque_parado)}
        </div>

        <!-- Faixa 5 · atividade recente -->
        <div class="card">
          <div class="card-header">
            <div>
              <h2>Atividade recente</h2>
              <p class="card-subtitulo">últimos 10 lançamentos</p>
            </div>
            <button class="btn secundario" type="button" data-ir="movimentos">Ver tudo</button>
          </div>
          ${blocoAtividade(d.atividade)}
        </div>

        ${d.avisos.length ? `<div class="aviso-acao">${d.avisos.join('<br>')}</div>` : ''}
      `;

      // Gráficos só depois do HTML existir
      desenharTendencia(d.historico, {
        rotulo: MESES[parseInt(referencia.split('-')[1], 10) - 1],
        cmv_percentual: k.cmv_percentual.valor,
        meta: k.cmv_percentual.meta,
      }, k.cmv_percentual.meta || 0.29);

      desenharRosca('grafico-composicao', 'composicao',
        ['Comida', 'Bebida'],
        [d.composicao.comida ? d.composicao.comida.cmv : 0,
         d.composicao.bebida ? d.composicao.bebida.cmv : 0],
        [CORES.navy, CORES.azul]);

      desenharRosca('grafico-perdas', 'perdas',
        d.perdas.por_motivo.map((m) => m.rotulo),
        d.perdas.por_motivo.map((m) => m.valor),
        [CORES.vermelho, '#EF9F27', CORES.cinza, CORES.azul, CORES.verde, CORES.gold, CORES.navy]);

      // Todo número é uma porta
      container.querySelectorAll('[data-ir]').forEach((el) => {
        el.addEventListener('click', () => { location.hash = el.dataset.ir; });
      });

      ligarNavegacaoDeMes(container);
    },
  };

  function ligarNavegacaoDeMes(container) {
    const ligar = (seletor, acao) => {
      const el = container.querySelector(seletor);
      if (el) el.addEventListener('click', () => { acao(); window.roteador.rerenderizar(); });
    };
    ligar('#mes-anterior', () => { referencia = deslocarMes(referencia, -1); });
    ligar('#mes-proximo', () => { referencia = deslocarMes(referencia, 1); });
    ligar('#ir-mes-atual', () => { referencia = mesAtual(); });
  }
})();
