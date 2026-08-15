/* ============================================================
   MOTOR DE CMV — apuração do Custo de Mercadoria Vendida.

       CMV = Estoque Inicial + Compras − Estoque Final
       CMV % = CMV ÷ Faturamento

   Duas escolhas ficam na mão do usuário, sem precisar salvar preferência:
     · Modo: Período isolado ou Acumulado (do início até a data final)
     · Custo: Custo médio (padrão) ou Último custo (como a planilha fazia)
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.cmv = (function () {
  let modo = null;          // null = usa a configuração da unidade
  let metodoCusto = null;
  let periodo = null;
  let config = null;

  const brl = (v) => 'R$ ' + Number(v || 0).toLocaleString('pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
  const pct = (v) => (v === null || v === undefined) ? '—' : (v * 100).toFixed(2).replace('.', ',') + '%';
  const num = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 3 });

  const iso = (d) => d.toISOString().slice(0, 10);

  // Semana (segunda a domingo) que contém a data informada — o mesmo recorte
  // das abas SEM__ da planilha
  function semanaDe(data) {
    const seg = new Date(data); seg.setDate(data.getDate() - ((data.getDay() + 6) % 7));
    const dom = new Date(seg); dom.setDate(seg.getDate() + 6);
    return { inicio: iso(seg), fim: iso(dom) };
  }

  /* Período inicial da tela.

     Um ciclo de CMV vai de um inventário ao seguinte — é assim que a
     operação fecha o número. Então o padrão é o intervalo entre os dois
     últimos inventários finalizados.

     Abrir na semana corrente faria a tela mostrar zeros sempre que os
     lançamentos fossem de outra semana, sem deixar claro que é só o
     recorte de datas. */
  async function periodoInicial() {
    const atual = semanaDe(new Date());
    try {
      const invs = await api.get(
        `/inventario/sessoes?unidade_id=${UNIDADE_SELECIONADA}&status=FINALIZADO`);
      const datas = invs
        .map((s) => (s.data_fechamento || s.data_abertura || '').slice(0, 10))
        .filter(Boolean)
        .sort();
      if (datas.length >= 2) {
        return { inicio: datas[datas.length - 2], fim: datas[datas.length - 1] };
      }
      if (datas.length === 1) return semanaDe(new Date(datas[0] + 'T12:00:00'));

      // Sem inventário finalizado: cai na semana do último lançamento
      const movs = await api.get(`/movimentos?unidade_id=${UNIDADE_SELECIONADA}`);
      if (!movs.length) return atual;
      const temNaSemana = movs.some((m) => m.data >= atual.inicio && m.data <= atual.fim);
      return temNaSemana ? atual : semanaDe(new Date(movs[0].data + 'T12:00:00'));
    } catch (e) {
      return atual;
    }
  }

  function blocoIndicadores(r) {
    const g = r.geral;
    const acima = r.lacuna !== null && r.lacuna < 0;
    return `
      <div class="kpi-grid">
        <div class="kpi-card">
          <div class="rotulo">CMV Real</div>
          <div class="valor">${brl(g.cmv)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">CMV sobre faturamento</div>
          <div class="valor ${acima ? 'valor-ruim' : 'valor-bom'}">${pct(g.cmv_percentual)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">Meta</div>
          <div class="valor">${pct(r.meta)}</div>
        </div>
        <div class="kpi-card">
          <div class="rotulo">${acima ? 'Acima da meta' : 'Folga para a meta'}</div>
          <div class="valor ${acima ? 'valor-ruim' : 'valor-bom'}">${r.lacuna === null ? '—' : pct(Math.abs(r.lacuna))}</div>
        </div>
      </div>`;
  }

  function linhaBloco(nome, b) {
    return `
      <tr>
        <td><strong>${nome}</strong></td>
        <td class="num">${brl(b.estoque_inicial)}</td>
        <td class="num">${brl(b.compras)}</td>
        <td class="num">${brl(b.estoque_final)}</td>
        <td class="num"><strong>${brl(b.cmv)}</strong></td>
        <td class="num">${b.perdas ? `<span class="valor-ruim">${brl(b.perdas)}</span>` : '—'}</td>
        <td class="num">${brl(b.faturamento)}</td>
        <td class="num"><strong>${pct(b.cmv_percentual)}</strong></td>
      </tr>`;
  }

  /* Quantidade e valor são grandezas diferentes e precisam de colunas
     diferentes — juntas na mesma célula ("70,5 · R$ 748,00") o olho não
     consegue somar nenhuma das duas ao percorrer a coluna. O cabeçalho
     agrupado mantém a leitura de qual bloco é qual. */
  function tabelaItens(linhas) {
    if (!linhas.length) return `<div class="estado-vazio">Nenhum movimento no período.</div>`;
    return `
      <div class="tabela-rolavel">
      <table class="tabela-simples tabela-agrupada">
        <thead>
          <tr class="grupos">
            <th rowspan="2">Código</th>
            <th rowspan="2">Produto</th>
            <th rowspan="2">Família</th>
            <th rowspan="2">Un.</th>
            <th colspan="2" class="grupo inicio-grupo">Estoque inicial</th>
            <th colspan="2" class="grupo inicio-grupo">Compras</th>
            <th colspan="2" class="grupo inicio-grupo">Estoque final</th>
            <th rowspan="2" class="num inicio-grupo">Consumo</th>
            <th rowspan="2" class="num">Custo un.</th>
            <th rowspan="2" class="num">CMV</th>
          </tr>
          <tr>
            <th class="num inicio-grupo">Qtd.</th><th class="num">Valor</th>
            <th class="num inicio-grupo">Qtd.</th><th class="num">Valor</th>
            <th class="num inicio-grupo">Qtd.</th><th class="num">Valor</th>
          </tr>
        </thead>
        <tbody>
          ${linhas.map((l) => `
            <tr>
              <td><span class="codigo-item">${l.codigo || '—'}</span></td>
              <td>${l.produto}${l.final_estimado ? ' <span class="tag" title="Sem contagem de fechamento — estoque final estimado pelo saldo teórico">estimado</span>' : ''}</td>
              <td>${(l.categoria || '—').replace('Família - ', '')}${l.eh_bebida ? ' <span class="tag">bebida</span>' : ''}</td>
              <td class="un-medida">${l.unidade_medida || '—'}</td>
              <td class="num inicio-grupo">${num(l.qtd_inicial)}</td>
              <td class="num">${brl(l.valor_inicial)}</td>
              <td class="num inicio-grupo">${num(l.qtd_comprada)}</td>
              <td class="num">${brl(l.valor_comprado)}</td>
              <td class="num inicio-grupo">${num(l.qtd_final)}</td>
              <td class="num">${brl(l.valor_final)}</td>
              <td class="num inicio-grupo">${num(l.qtd_consumida)}</td>
              <td class="num">${brl(l.custo_unitario)}${l.unidade_medida ? `<span class="por-unidade">/${l.unidade_medida}</span>` : ''}</td>
              <td class="num"><strong>${brl(l.cmv)}</strong></td>
            </tr>`).join('')}
        </tbody>
      </table>
      </div>`;
  }

  async function apurar(container) {
    const alvo = container.querySelector('#cmv-resultado');
    alvo.innerHTML = `<div class="estado-vazio">Apurando…</div>`;

    const params = new URLSearchParams({
      unidade_id: UNIDADE_SELECIONADA,
      data_inicio: container.querySelector('#cmv-inicio').value,
      data_fim: container.querySelector('#cmv-fim').value,
    });
    if (modo) params.set('modo', modo);
    if (metodoCusto) params.set('metodo_custo', metodoCusto);

    try {
      const r = await api.get('/cmv/apuracao?' + params.toString());
      const lista = (invs) => invs.length
        ? invs.map((i) => `nº ${i.numero} (${i.data.split('-').reverse().join('/')})`).join(', ')
        : '—';

      alvo.innerHTML = `
        ${blocoIndicadores(r)}

        <div class="origem-inventarios">
          ${icone('inventario')}
          <div>
            <strong>Estoque inicial</strong> vem do inventário ${lista(r.inventarios.abertura)}
            &nbsp;·&nbsp;
            <strong>estoque final</strong> do inventário ${lista(r.inventarios.fechamento)}.
            As compras contadas são as lançadas entre eles.
          </div>
        </div>

        ${r.avisos.length ? `<div class="aviso-acao">${r.avisos.join('<br>')}</div>` : ''}

        <div class="card">
          <div class="card-header"><h2>Composição do CMV</h2></div>
          <table class="tabela-simples">
            <thead><tr>
              <th></th>
              <th class="num">Estoque inicial</th><th class="num">Compras</th><th class="num">Estoque final</th>
              <th class="num">CMV</th><th class="num">Perdas</th><th class="num">Faturamento</th><th class="num">CMV %</th>
            </tr></thead>
            <tbody>
              ${linhaBloco('Geral', r.geral)}
              ${linhaBloco('Comida', r.comida)}
              ${linhaBloco('Bebida', r.bebida)}
            </tbody>
          </table>
          <p class="nota-formula">
            CMV = Estoque Inicial + Compras − Estoque Final &nbsp;·&nbsp; CMV % = CMV ÷ Faturamento
            &nbsp;·&nbsp; Comida é tudo que não é bebida.
            <br>A coluna <strong>Perdas</strong> não soma nem subtrai do CMV — ela já está
            dentro dele. Mostra que parte do custo foi desperdício, e não venda.
          </p>
          ${r.geral.perdas ? `
            <div class="aviso-acao">
              ${brl(r.geral.perdas)} do CMV do período são perdas registradas
              (${pct(r.geral.perdas_sobre_cmv)} do CMV${r.geral.faturamento
                ? `, ${pct(r.geral.perdas_percentual)} do faturamento`
                : ''}).
              ${r.geral.faturamento
                ? `Sem elas, o CMV % seria ${pct((r.geral.cmv - r.geral.perdas) / r.geral.faturamento)}.`
                : ''}
            </div>` : ''}
        </div>

        <div class="card">
          <div class="card-header">
            <h2>Item a item <span class="tag">${r.total_linhas} produto(s)</span></h2>
          </div>
          ${tabelaItens(r.linhas)}
        </div>
      `;
    } catch (e) {
      alvo.innerHTML = `<div class="estado-vazio">Não foi possível apurar: ${e.message}</div>`;
    }
  }

  return {
    async render(container) {
      periodo = periodo || await periodoInicial();
      config = await api.get(`/cmv/configuracao?unidade_id=${UNIDADE_SELECIONADA}`);
      const modoAtual = modo || config.modo_apuracao;
      const custoAtual = metodoCusto || config.metodo_custo;

      container.innerHTML = `
        <div class="card">
          <div class="card-header">
            <h2>Apuração de CMV</h2>
            <span class="tag">${config.familias_bebida.length
              ? 'Bebida: ' + config.familias_bebida.map((f) => f.nome.replace('Família - ', '')).join(' + ')
              : 'Nenhuma família marcada como bebida'}</span>
          </div>

          <div class="filtros-barra">
            <div class="form-group data">
              <label for="cmv-inicio">Início</label>
              <input id="cmv-inicio" type="date" value="${periodo.inicio}">
            </div>
            <div class="form-group data">
              <label for="cmv-fim">Fim</label>
              <input id="cmv-fim" type="date" value="${periodo.fim}">
            </div>

            <div class="form-group opcao">
              <label>Apuração</label>
              <div class="seletor-opcoes" id="cmv-modo">
                <button type="button" data-valor="PERIODO"${modoAtual === 'PERIODO' ? ' class="ativo"' : ''}
                  title="Só o intervalo escolhido — equivale a uma aba SEM__ da planilha">Período</button>
                <button type="button" data-valor="ACUMULADO"${modoAtual === 'ACUMULADO' ? ' class="ativo"' : ''}
                  title="Do início do controle até a data final">Acumulado</button>
              </div>
            </div>

            <div class="form-group opcao">
              <label>Custo do estoque</label>
              <div class="seletor-opcoes" id="cmv-custo">
                <button type="button" data-valor="CUSTO_MEDIO"${custoAtual === 'CUSTO_MEDIO' ? ' class="ativo"' : ''}
                  title="Custo médio ponderado do período (padrão)">Custo médio</button>
                <button type="button" data-valor="ULTIMO_CUSTO"${custoAtual === 'ULTIMO_CUSTO' ? ' class="ativo"' : ''}
                  title="Último custo conhecido — reproduz a planilha">Último custo</button>
              </div>
            </div>

            <button class="btn" type="button" id="cmv-apurar">Apurar</button>
          </div>
        </div>

        <div id="cmv-resultado"></div>
      `;

      // Alternadores
      container.querySelectorAll('.seletor-opcoes button').forEach((b) => {
        b.addEventListener('click', () => {
          const grupo = b.closest('.seletor-opcoes');
          grupo.querySelectorAll('button').forEach((x) => x.classList.remove('ativo'));
          b.classList.add('ativo');
          if (grupo.id === 'cmv-modo') modo = b.dataset.valor;
          else metodoCusto = b.dataset.valor;
          apurar(container);
        });
      });

      ['#cmv-inicio', '#cmv-fim'].forEach((s) => {
        container.querySelector(s).addEventListener('change', () => {
          periodo = {
            inicio: container.querySelector('#cmv-inicio').value,
            fim: container.querySelector('#cmv-fim').value,
          };
          apurar(container);
        });
      });
      container.querySelector('#cmv-apurar').addEventListener('click', () => apurar(container));

      await apurar(container);
    },
  };
})();
