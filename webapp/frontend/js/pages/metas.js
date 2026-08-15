/* ============================================================
   METAS — os números que a diretoria define e a operação persegue.

   Duas ideias sustentam a tela:

   1. META E REALIZADO LADO A LADO. Definir 25% de CMV para carne quando
      a operação roda em 41% é fantasia. O número real ao lado transforma
      a meta em conversa — e o botão "usar realizado" dá um ponto de
      partida honesto para quem nunca definiu meta nenhuma.

   2. HERANÇA VISÍVEL. Meta definida aparece em preto; meta herdada, em
      cinza, dizendo de onde veio. Sem isso ninguém sabe se o 34% da carne
      foi decidido ou é reflexo de outra coisa.

   Salvar nunca sobrescreve: abre uma vigência nova e fecha a anterior.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.metas = (function () {
  let dados = null;
  let periodo = null;
  let mostrarHerdadas = false;

  const pct = (v) => (v === null || v === undefined)
    ? '—' : (v * 100).toFixed(1).replace('.', ',') + ' %';
  const brl = (v) => (v === null || v === undefined)
    ? '—' : 'R$ ' + Number(v).toLocaleString('pt-BR', { maximumFractionDigits: 0 });
  const dataBR = (iso) => (iso ? iso.slice(0, 10).split('-').reverse().join('/') : '—');
  const hoje = () => new Date().toISOString().slice(0, 10);

  const formatar = (linha, valor) =>
    (linha.formato === 'REAIS' ? brl(valor) : pct(valor));

  /* Período padrão: mês corrente. É o recorte que a diretoria usa para
     falar de meta — ninguém define meta por semana de inventário. */
  function mesCorrente() {
    const h = new Date();
    const ini = new Date(h.getFullYear(), h.getMonth(), 1);
    const fim = new Date(h.getFullYear(), h.getMonth() + 1, 0);
    const iso = (d) => new Date(d.getTime() - d.getTimezoneOffset() * 60000)
      .toISOString().slice(0, 10);
    return { inicio: iso(ini), fim: iso(fim) };
  }

  /* Barra que mostra a distância entre alvo e realizado. O olho lê a
     distância antes de ler o algarismo. */
  function barra(linha) {
    if (linha.valor == null || linha.realizado == null) {
      return `<div class="meta-barra vazia"></div>`;
    }
    const escala = Math.max(linha.valor, linha.realizado) * 1.25 || 1;
    const larguraReal = Math.min(100, (linha.realizado / escala) * 100);
    const posicaoMeta = Math.min(100, (linha.valor / escala) * 100);
    const classe = linha.atingida === false ? 'ruim' : 'bom';
    return `
      <div class="meta-barra">
        <div class="preenchimento ${classe}" style="width:${larguraReal.toFixed(1)}%"></div>
        <div class="marca-meta" style="left:${posicaoMeta.toFixed(1)}%" title="Meta"></div>
      </div>`;
  }

  function selo(linha) {
    if (linha.realizado == null || linha.valor == null) return '';
    return linha.atingida
      ? `<span class="meta-selo bom">${icone('check')}</span>`
      : `<span class="meta-selo ruim">${icone('x')}</span>`;
  }

  function origem(linha) {
    if (linha.definida) {
      // Distinguir importa: redistribuir a meta geral respeita o que foi
      // negociado à mão e refaz o que veio da distribuição anterior.
      const como = linha.manual ? 'definida' : 'distribuída';
      return `<span class="meta-origem">${como} em ${dataBR(linha.vigencia_inicio)}</span>`;
    }
    if (linha.herdada_rotulo) {
      return `<span class="meta-origem herdada">herdado de ${linha.herdada_rotulo}</span>`;
    }
    if (linha.padrao_do_sistema) {
      return `<span class="meta-origem herdada">padrão do sistema</span>`;
    }
    return `<span class="meta-origem herdada">não definida</span>`;
  }

  function linhaCMV(linha) {
    const chave = linha.categoria_id ? `${linha.tipo}:${linha.categoria_id}` : linha.tipo;
    return `
      <div class="meta-linha" data-chave="${chave}">
        <div class="meta-nome">${linha.rotulo}${origem(linha)}</div>
        <button class="meta-valor${linha.definida ? '' : ' herdado'}" type="button"
                data-editar="${chave}" title="Clique para definir">
          ${formatar(linha, linha.valor)}
        </button>
        ${barra(linha)}
        <div class="meta-realizado">
          ${formatar(linha, linha.realizado)} ${selo(linha)}
        </div>
      </div>`;
  }

  function blocoFamilias() {
    const lista = mostrarHerdadas
      ? dados.familias
      : dados.familias.filter((f) => f.definida || f.realizado != null);

    if (!lista.length) {
      return `<div class="estado-vazio">Nenhuma família com meta própria.
        Todas seguem a meta de Comida ou Bebida.</div>`;
    }
    return lista.map((f) => `
      <div class="meta-linha familia" data-chave="CMV_FAMILIA:${f.categoria_id}">
        <div class="meta-nome">${f.rotulo}${origem(f)}</div>
        <button class="meta-valor${f.definida ? '' : ' herdado'}" type="button"
                data-editar="CMV_FAMILIA:${f.categoria_id}">
          ${pct(f.valor)}
        </button>
        ${barra(f)}
        <div class="meta-realizado">${pct(f.realizado)} ${selo(f)}</div>
        ${f.realizado != null ? `
          <button class="btn-acao usar-realizado" type="button"
                  data-usar="CMV_FAMILIA:${f.categoria_id}" data-valor="${f.realizado}">
            usar realizado
          </button>` : '<span></span>'}
      </div>`).join('');
  }

  function achar(chave) {
    const [tipo, categoria] = chave.split(':');
    if (tipo === 'CMV_FAMILIA') {
      return dados.familias.find((f) => String(f.categoria_id) === categoria);
    }
    if (tipo === 'PERDAS') return dados.perdas;
    if (tipo === 'FATURAMENTO') return dados.faturamento;
    return dados.cmv.find((l) => l.tipo === tipo);
  }

  /* Modal de definição. Pergunta a partir de quando vale, porque é isso
     que impede a meta nova de reescrever o passado. */
  function abrirEditor(chave, valorSugerido) {
    const linha = achar(chave);
    if (!linha) return;
    const emReais = linha.formato === 'REAIS' || linha.tipo === 'FATURAMENTO';
    const atual = valorSugerido != null ? valorSugerido : linha.valor;
    const mostrado = atual == null ? '' : (emReais ? atual : (atual * 100).toFixed(1));

    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa" role="dialog" aria-label="Definir meta">
        <div class="modal-cabecalho">
          <h3>${linha.rotulo}</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x')}</button>
        </div>
        <div class="modal-corpo">
          <div class="lancador-grid">
            <div>
              <label for="meta-valor">${emReais ? 'Valor (R$)' : 'Percentual (%)'}</label>
              <input id="meta-valor" type="number" step="${emReais ? '100' : '0.1'}"
                     value="${mostrado}" autocomplete="off">
            </div>
            <div>
              <label for="meta-vigencia">Vale a partir de</label>
              <input id="meta-vigencia" type="date" value="${hoje()}">
            </div>
          </div>
          <label for="meta-obs" style="margin-top:.5rem">Por quê (opcional)</label>
          <input id="meta-obs" placeholder="Ex.: meta do 2º semestre, após renegociar carnes">
          <p class="nota-formula" style="margin-top:.6rem">
            A meta anterior não é apagada: ela é fechada na véspera desta data.
            Períodos já apurados continuam sendo julgados pela meta que valia neles.
          </p>
          <div class="modal-mensagem" id="meta-msg" hidden></div>
        </div>
        <div class="modal-rodape">
          <button class="btn secundario" type="button" data-fechar>Cancelar</button>
          <button class="btn" type="button" id="meta-salvar">Definir meta</button>
        </div>
      </div>`;
    document.body.appendChild(fundo);

    const fechar = () => fundo.remove();
    fundo.querySelectorAll('[data-fechar]').forEach((b) => b.addEventListener('click', fechar));
    fundo.addEventListener('click', (ev) => { if (ev.target === fundo) fechar(); });

    fundo.querySelector('#meta-salvar').addEventListener('click', async () => {
      const bruto = parseFloat(fundo.querySelector('#meta-valor').value);
      const msg = fundo.querySelector('#meta-msg');
      if (isNaN(bruto) || bruto <= 0) {
        msg.hidden = false; msg.textContent = 'Informe um valor maior que zero.';
        return;
      }
      try {
        await api.post('/metas', {
          unidade_id: UNIDADE_SELECIONADA,
          tipo: linha.tipo,
          categoria_id: linha.categoria_id || null,
          valor: emReais ? bruto : bruto / 100,
          formato: emReais ? 'REAIS' : 'PERCENTUAL',
          periodicidade: emReais ? 'MENSAL' : null,
          vigencia_inicio: fundo.querySelector('#meta-vigencia').value || null,
          observacao: fundo.querySelector('#meta-obs').value.trim() || null,
        });
        fechar();
        window.roteador.rerenderizar();
      } catch (erro) {
        msg.hidden = false;
        msg.textContent = erro.message || 'Não foi possível definir a meta.';
      }
    });

    setTimeout(() => fundo.querySelector('#meta-valor').focus(), 40);
  }

  /* ------------------------------------------------------------------
     DISTRIBUIÇÃO AUTOMÁTICA

     Um número só — a meta de CMV geral — vira meta para cada família.

     A repartição é PROPORCIONAL AO CUSTO, não igual entre famílias.
     Dividir 29% por oito famílias daria 3,6% para cada: condenaria carnes
     (que sozinha pode responder por 40% do custo) a uma meta impossível e
     daria à mercearia uma folga que não cobra nada de ninguém.

     A prévia aparece antes de gravar, e a soma das famílias tem que bater
     exatamente com a meta geral — é a conferência que prova a conta.
     ------------------------------------------------------------------ */
  function abrirDistribuicao() {
    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa larga" role="dialog" aria-label="Distribuir meta por família">
        <div class="modal-cabecalho">
          <h3>Distribuir meta entre as famílias</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x')}</button>
        </div>
        <div class="modal-corpo">
          <div class="lancador-grid">
            <div>
              <label for="dist-meta">Meta de CMV geral (%)</label>
              <input id="dist-meta" type="number" step="0.1" min="1" max="99"
                     value="${dados.cmv[0].valor ? (dados.cmv[0].valor * 100).toFixed(1) : '29'}">
            </div>
            <div>
              <label for="dist-vigencia">Vale a partir de</label>
              <input id="dist-vigencia" type="date" value="${hoje()}">
            </div>
          </div>

          <div class="dist-base">
            <label>Base de cálculo — de onde vem o peso de cada família</label>
            <div class="lancador-grid">
              <div><input id="dist-ini" type="date" value="${periodo.inicio}"></div>
              <div><input id="dist-fim" type="date" value="${periodo.fim}"></div>
            </div>
          </div>

          <label class="dist-opcao">
            <input type="checkbox" id="dist-preservar" checked>
            <span>Preservar as famílias com meta negociada à mão
              <small>(metas de distribuições anteriores são refeitas)</small></span>
          </label>
          <label class="dist-opcao">
            <input type="checkbox" id="dist-blocos" checked>
            <span>Recalcular também as metas de comida e bebida</span>
          </label>

          <div id="dist-previa" class="dist-previa">
            <div class="estado-vazio">Calculando…</div>
          </div>

          <label for="dist-obs" style="margin-top:.6rem">Por quê (opcional)</label>
          <input id="dist-obs" placeholder="Ex.: metas do 2º semestre">
          <div class="modal-mensagem" id="dist-msg" hidden></div>
        </div>
        <div class="modal-rodape">
          <button class="btn secundario" type="button" data-fechar>Cancelar</button>
          <button class="btn" type="button" id="dist-aplicar" disabled>Aplicar distribuição</button>
        </div>
      </div>`;
    document.body.appendChild(fundo);

    const fechar = () => fundo.remove();
    fundo.querySelectorAll('[data-fechar]').forEach((b) => b.addEventListener('click', fechar));
    fundo.addEventListener('click', (ev) => { if (ev.target === fundo) fechar(); });

    const alvo = fundo.querySelector('#dist-previa');
    const botao = fundo.querySelector('#dist-aplicar');
    let debounce = null;

    async function calcular() {
      const meta = parseFloat(fundo.querySelector('#dist-meta').value);
      if (isNaN(meta) || meta <= 0 || meta >= 100) {
        alvo.innerHTML = `<div class="estado-vazio">Informe um percentual entre 0 e 100.</div>`;
        botao.disabled = true;
        return;
      }
      alvo.innerHTML = `<div class="estado-vazio">Calculando…</div>`;
      const params = new URLSearchParams({
        meta_geral: meta / 100,
        unidade_id: UNIDADE_SELECIONADA,
        data_inicio: fundo.querySelector('#dist-ini').value,
        data_fim: fundo.querySelector('#dist-fim').value,
        preservar_definidas: fundo.querySelector('#dist-preservar').checked,
      });
      try {
        const r = await api.get('/metas/previa-distribuicao?' + params.toString());
        if (r.sem_base) {
          alvo.innerHTML = `<div class="estado-vazio">${r.aviso}</div>`;
          botao.disabled = true;
          return;
        }
        const bate = Math.abs(r.soma - r.meta_geral) < 0.0001;
        alvo.innerHTML = `
          <table class="tabela-simples dist-tabela">
            <thead><tr>
              <th>Família</th>
              <th class="num">Peso no custo</th>
              <th class="num">Meta resultante</th>
            </tr></thead>
            <tbody>
              ${r.linhas.map((l) => `
                <tr class="${l.travada ? 'travada' : ''}">
                  <td>${l.categoria}${l.travada ? ' <span class="tag">negociada</span>' : ''}</td>
                  <td class="num">${pct(l.participacao)}</td>
                  <td class="num"><strong>${pct(l.meta)}</strong></td>
                </tr>`).join('')}
            </tbody>
            <tfoot><tr class="${bate ? 'confere' : 'diverge'}">
              <td>Soma</td>
              <td class="num">100,0 %</td>
              <td class="num"><strong>${pct(r.soma)}</strong>
                ${bate ? icone('check') : ''}</td>
            </tr></tfoot>
          </table>
          <p class="nota-formula">
            Base: CMV de ${brl(r.periodo.cmv_apurado)} sobre faturamento de
            ${brl(r.periodo.faturamento)} no período escolhido.
            A meta de cada família é a fração do faturamento que ela pode custar.
          </p>
          ${r.aviso ? `<div class="aviso-acao">${r.aviso}</div>` : ''}`;
        botao.disabled = false;
      } catch (erro) {
        alvo.innerHTML = `<div class="estado-vazio">${erro.message}</div>`;
        botao.disabled = true;
      }
    }

    ['#dist-meta', '#dist-ini', '#dist-fim'].forEach((s) => {
      fundo.querySelector(s).addEventListener('input', () => {
        clearTimeout(debounce);
        debounce = setTimeout(calcular, 350);
      });
    });
    fundo.querySelector('#dist-preservar').addEventListener('change', calcular);

    botao.addEventListener('click', async () => {
      const msg = fundo.querySelector('#dist-msg');
      botao.disabled = true;
      try {
        await api.post('/metas/distribuir', {
          unidade_id: UNIDADE_SELECIONADA,
          meta_geral: parseFloat(fundo.querySelector('#dist-meta').value) / 100,
          data_inicio: fundo.querySelector('#dist-ini').value,
          data_fim: fundo.querySelector('#dist-fim').value,
          vigencia_inicio: fundo.querySelector('#dist-vigencia').value || null,
          preservar_definidas: fundo.querySelector('#dist-preservar').checked,
          incluir_blocos: fundo.querySelector('#dist-blocos').checked,
          observacao: fundo.querySelector('#dist-obs').value.trim() || null,
        });
        fechar();
        mostrarHerdadas = true;   // para o resultado ficar visível de imediato
        window.roteador.rerenderizar();
      } catch (erro) {
        msg.hidden = false;
        msg.textContent = erro.message || 'Não foi possível distribuir.';
        botao.disabled = false;
      }
    });

    calcular();
  }

  async function abrirHistorico() {
    const registros = await api.get(`/metas/historico?unidade_id=${UNIDADE_SELECIONADA}`);
    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa larga" role="dialog" aria-label="Histórico de metas">
        <div class="modal-cabecalho">
          <h3>Histórico de metas</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x')}</button>
        </div>
        <div class="modal-corpo">
          ${registros.length ? `
            <table class="tabela-simples">
              <thead><tr>
                <th>Vigência</th><th>Meta</th><th class="num">Valor</th>
                <th>Definida por</th><th>Motivo</th>
              </tr></thead>
              <tbody>
                ${registros.map((r) => `
                  <tr>
                    <td>${dataBR(r.vigencia_inicio)}${r.vigencia_fim ? ' a ' + dataBR(r.vigencia_fim) : ' · vigente'}</td>
                    <td>${r.rotulo}${r.categoria ? ' · ' + r.categoria : ''}</td>
                    <td class="num">${r.formato === 'REAIS' ? brl(r.valor) : pct(r.valor)}</td>
                    <td>${r.usuario || '—'}</td>
                    <td>${r.observacao || '—'}</td>
                  </tr>`).join('')}
              </tbody>
            </table>` : `<div class="estado-vazio">Nenhuma meta definida ainda.</div>`}
        </div>
      </div>`;
    document.body.appendChild(fundo);
    const fechar = () => fundo.remove();
    fundo.querySelectorAll('[data-fechar]').forEach((b) => b.addEventListener('click', fechar));
    fundo.addEventListener('click', (ev) => { if (ev.target === fundo) fechar(); });
  }

  return {
    async render(container) {
      periodo = periodo || mesCorrente();
      dados = await api.get(`/metas/painel?unidade_id=${UNIDADE_SELECIONADA}`
        + `&data_inicio=${periodo.inicio}&data_fim=${periodo.fim}`);

      const semDefinir = dados.familias.filter((f) => !f.definida).length;

      container.innerHTML = `
        <div class="card">
          <div class="card-header">
            <div>
              <h2>Metas</h2>
              <p style="color:var(--muted);font-size:.8rem;margin:.15rem 0 0">
                Realizado apurado de ${dados.periodo_rotulo}
              </p>
            </div>
            <div class="acoes-linha">
              <button class="btn secundario" type="button" id="meta-historico">Histórico</button>
            </div>
          </div>
          <div class="filtros-barra">
            <div class="form-group data">
              <label for="meta-ini">Período do realizado</label>
              <input id="meta-ini" type="date" value="${periodo.inicio}">
            </div>
            <div class="form-group data">
              <label for="meta-fim">até</label>
              <input id="meta-fim" type="date" value="${periodo.fim}">
            </div>
          </div>
        </div>

        <div class="card">
          <div class="card-header">
            <h2>CMV</h2>
            <button class="btn" type="button" id="meta-distribuir">
              ${icone('metas')} Distribuir por família
            </button>
          </div>
          <div class="meta-tabela">
            <div class="meta-cabecalho">
              <span>Indicador</span><span>Meta</span><span></span><span>Realizado</span>
            </div>
            ${dados.cmv.map(linhaCMV).join('')}
          </div>
          ${dados.aviso_coerencia ? `
            <div class="aviso-acao" style="margin-top:.8rem">${dados.aviso_coerencia}</div>` : ''}
        </div>

        <div class="card">
          <div class="card-header">
            <h2>Por família</h2>
            <button class="btn secundario" type="button" id="meta-toggle-herdadas">
              ${mostrarHerdadas ? 'Ocultar herdadas' : `Mostrar herdadas (${semDefinir})`}
            </button>
          </div>
          <div class="meta-tabela com-acao">${blocoFamilias()}</div>
        </div>

        <div class="grid-2">
          <div class="card">
            <div class="card-header"><h2>Perdas</h2></div>
            <div class="meta-destaque">
              <button class="meta-valor grande${dados.perdas.definida ? '' : ' herdado'}"
                      type="button" data-editar="PERDAS">
                ${dados.perdas.valor == null ? 'definir' : 'máx. ' + pct(dados.perdas.valor)}
              </button>
              <div class="meta-legenda">do CMV do período</div>
              <div class="meta-realizado">
                realizado ${pct(dados.perdas.realizado)} ${selo(dados.perdas)}
              </div>
            </div>
          </div>
          <div class="card">
            <div class="card-header"><h2>Faturamento</h2></div>
            <div class="meta-destaque">
              <button class="meta-valor grande${dados.faturamento.definida ? '' : ' herdado'}"
                      type="button" data-editar="FATURAMENTO">
                ${dados.faturamento.valor == null ? 'definir' : brl(dados.faturamento.valor)}
              </button>
              <div class="meta-legenda">por mês</div>
              <div class="meta-realizado">
                realizado ${brl(dados.faturamento.realizado)}
                ${dados.faturamento.valor ? ` · <strong>${((dados.faturamento.realizado || 0) / dados.faturamento.valor * 100).toFixed(1).replace('.', ',')} %</strong>` : ''}
              </div>
            </div>
          </div>
        </div>
      `;

      const botaoDistribuir = container.querySelector('#meta-distribuir');
      if (!dados.pode_editar) {
        container.querySelectorAll('.meta-valor, .usar-realizado').forEach((b) => {
          b.disabled = true;
          b.title = 'Somente Diretor e Arquiteto definem metas.';
        });
        botaoDistribuir.remove();
      } else {
        botaoDistribuir.addEventListener('click', abrirDistribuicao);
        container.querySelectorAll('[data-editar]').forEach((b) => {
          b.addEventListener('click', () => abrirEditor(b.dataset.editar));
        });
        container.querySelectorAll('[data-usar]').forEach((b) => {
          b.addEventListener('click', () =>
            abrirEditor(b.dataset.usar, parseFloat(b.dataset.valor)));
        });
      }

      container.querySelector('#meta-historico').addEventListener('click', abrirHistorico);
      container.querySelector('#meta-toggle-herdadas').addEventListener('click', () => {
        mostrarHerdadas = !mostrarHerdadas;
        window.roteador.rerenderizar();
      });
      ['#meta-ini', '#meta-fim'].forEach((s) => {
        container.querySelector(s).addEventListener('change', () => {
          periodo = {
            inicio: container.querySelector('#meta-ini').value,
            fim: container.querySelector('#meta-fim').value,
          };
          window.roteador.rerenderizar();
        });
      });
    },
  };
})();
