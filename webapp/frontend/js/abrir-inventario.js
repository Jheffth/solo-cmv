/* ============================================================
   MODAL "ABRIR INVENTÁRIO"

   Mesmas características do Lançador: janela flutuante, arrastável pelo
   cabeçalho (mouse e toque) e que NÃO fecha ao clicar fora — só pelo X.
   Por isso não há backdrop nem listener de clique no document.

   Campos:
     - Descrição (nome livre, ex.: "INV ROTATIVO CARNES")
     - Escopo: famílias selecionadas OU inventário geral (todas)
     - Observação (opcional)
   O número é atribuído automaticamente pelo servidor, na sequência da
   unidade (01, 02, 03…), sem reaproveitar número de cancelado.
   ============================================================ */

window.AbrirInventario = (function () {
  let janela = null;
  let categorias = [];
  let posicao = null;
  let aoConcluir = null;

  // ---------- Arrastar ----------
  let arrastando = false, iniX = 0, iniY = 0, elX = 0, elY = 0;

  function iniciarArrasto(x, y) {
    arrastando = true;
    iniX = x; iniY = y;
    const r = janela.getBoundingClientRect();
    elX = r.left; elY = r.top;
    janela.style.transform = 'none';
    janela.style.left = elX + 'px';
    janela.style.top = elY + 'px';
    janela.classList.add('dragging');
  }
  function moverPara(x, y) {
    const r = janela.getBoundingClientRect();
    let nx = Math.max(0, Math.min(elX + (x - iniX), window.innerWidth - r.width));
    let ny = Math.max(0, Math.min(elY + (y - iniY), window.innerHeight - 48));
    janela.style.left = nx + 'px';
    janela.style.top = ny + 'px';
    posicao = { left: nx, top: ny };
  }
  const aoMoverMouse = (e) => { if (arrastando) moverPara(e.clientX, e.clientY); };
  const aoMoverToque = (e) => {
    if (!arrastando) return;
    e.preventDefault();
    moverPara(e.touches[0].clientX, e.touches[0].clientY);
  };
  const encerrarArrasto = () => {
    arrastando = false;
    if (janela) janela.classList.remove('dragging');
    document.removeEventListener('mousemove', aoMoverMouse);
    document.removeEventListener('mouseup', encerrarArrasto);
    document.removeEventListener('touchmove', aoMoverToque);
    document.removeEventListener('touchend', encerrarArrasto);
  };
  function ligarArrasto() {
    const header = janela.querySelector('.lancador-header');
    header.addEventListener('mousedown', (e) => {
      if (e.target.closest('.lancador-close-btn')) return;
      iniciarArrasto(e.clientX, e.clientY);
      document.addEventListener('mousemove', aoMoverMouse);
      document.addEventListener('mouseup', encerrarArrasto);
    });
    header.addEventListener('touchstart', (e) => {
      if (e.target.closest('.lancador-close-btn')) return;
      const t = e.touches[0];
      iniciarArrasto(t.clientX, t.clientY);
      document.addEventListener('touchmove', aoMoverToque, { passive: false });
      document.addEventListener('touchend', encerrarArrasto);
    }, { passive: true });
  }

  // ---------- Montagem ----------
  function criarJanela() {
    janela = document.createElement('div');
    janela.className = 'lancador-janela modal-inventario';
    janela.id = 'modal-abrir-inventario';
    janela.innerHTML = `
      <div class="lancador-header">
        ${icone('inventario')}
        <span class="titulo">Abrir Inventário</span>
        <span class="unidade-atual" id="mai-unidade"></span>
        <button class="lancador-close-btn" type="button" title="Fechar">${icone('fechar')}</button>
      </div>

      <div class="lancador-corpo">
        <div class="lancador-dica">
          O número do inventário é gerado automaticamente, na sequência desta unidade.
          Depois de aberto, é preciso <strong>congelar</strong> para poder lançar contagens.
        </div>

        <div class="form-group">
          <label for="mai-descricao">Descrição do inventário</label>
          <input id="mai-descricao" placeholder="Ex.: INV ROTATIVO CARNES" maxlength="255">
        </div>

        <span class="mai-secao">Escopo do inventário</span>
        <label class="mai-geral" for="mai-geral" id="mai-geral-cartao">
          <input type="checkbox" id="mai-geral">
          <span class="mai-geral-texto">
            <strong>Inventário geral</strong>
            <small>Cobre todas as famílias de uma vez</small>
          </span>
        </label>

        <div id="mai-categorias-bloco">
          <div class="mai-cat-acoes">
            <span class="mai-cat-titulo">Famílias <span class="contagem-sel" id="mai-cat-contagem"></span></span>
            <button class="btn-acao" type="button" id="mai-marcar-todas">Marcar todas</button>
            <button class="btn-acao" type="button" id="mai-limpar-todas">Limpar</button>
          </div>
          <div class="mai-categorias" id="mai-categorias"></div>
        </div>

        <div class="form-group" style="margin-top:1rem;margin-bottom:0">
          <label for="mai-observacao">Observação (opcional)</label>
          <input id="mai-observacao" placeholder="Ex.: contagem após feriado" maxlength="500">
        </div>
      </div>

      <div class="lancador-rodape">
        <span class="lancador-msg" id="mai-msg"></span>
        <button class="btn" type="button" id="mai-abrir">Abrir Inventário</button>
      </div>
    `;
    document.body.appendChild(janela);

    janela.querySelector('.lancador-close-btn').addEventListener('click', fechar);
    janela.querySelector('#mai-abrir').addEventListener('click', enviar);
    janela.querySelector('#mai-geral').addEventListener('change', aoTrocarGeral);
    janela.querySelector('#mai-marcar-todas').addEventListener('click', () => marcarTodas(true));
    janela.querySelector('#mai-limpar-todas').addEventListener('click', () => marcarTodas(false));

    ligarArrasto();
  }

  function centralizar() {
    const w = janela.offsetWidth || 540;
    janela.style.left = Math.max(0, (window.innerWidth - w) / 2) + 'px';
    janela.style.top = window.innerWidth <= 620 ? '8px' : '80px';
    janela.style.transform = 'none';
    posicao = null;
  }

  /* Traz a janela de volta para dentro da tela quando o navegador encolhe —
     sem isso, a posição salva a jogava para fora e ela parecia sumir. */
  function garantirVisivel() {
    if (!janela || !estaAberto()) return;
    const r = janela.getBoundingClientRect();
    const limiteX = Math.max(0, window.innerWidth - r.width);
    const limiteY = Math.max(0, window.innerHeight - 60);
    const left = Math.min(Math.max(0, r.left), limiteX);
    const top = Math.min(Math.max(0, r.top), limiteY);
    janela.style.left = left + 'px';
    janela.style.top = top + 'px';
    posicao = { left, top };
  }

  function posicaoValida() {
    if (!posicao || !janela) return false;
    const r = janela.getBoundingClientRect();
    return posicao.left >= 0 && posicao.top >= 0
      && posicao.left <= Math.max(0, window.innerWidth - r.width)
      && posicao.top <= Math.max(0, window.innerHeight - 60);
  }

  window.addEventListener('resize', garantirVisivel);

  function renderCategorias() {
    janela.querySelector('#mai-categorias').innerHTML = categorias.map((c) => `
      <label class="mai-cat" for="mai-cat-${c.id}">
        <input type="checkbox" id="mai-cat-${c.id}" value="${c.id}" class="mai-cat-check">
        <span>${c.nome.replace('Família - ', '')}</span>
      </label>
    `).join('');
    janela.querySelectorAll('.mai-cat-check').forEach((el) => {
      el.addEventListener('change', atualizarContagem);
    });
    atualizarContagem();
  }

  const selecionadas = () =>
    Array.from(janela.querySelectorAll('.mai-cat-check:checked')).map((e) => parseInt(e.value, 10));

  function atualizarContagem() {
    const n = selecionadas().length;
    janela.querySelector('#mai-cat-contagem').textContent =
      n ? `— ${n} selecionada${n > 1 ? 's' : ''}` : '';
    // Destaca visualmente a linha marcada
    janela.querySelectorAll('.mai-cat-check').forEach((el) => {
      el.closest('.mai-cat').classList.toggle('marcada', el.checked);
    });
  }

  function marcarTodas(marcar) {
    janela.querySelectorAll('.mai-cat-check').forEach((e) => { e.checked = marcar; });
    atualizarContagem();
  }

  function aoTrocarGeral() {
    const geral = janela.querySelector('#mai-geral').checked;
    janela.querySelector('#mai-categorias-bloco').hidden = geral;
    janela.querySelector('#mai-geral-cartao').classList.toggle('ativo', geral);
    if (geral) marcarTodas(false);
  }

  function mensagem(texto, tipo) {
    const el = janela.querySelector('#mai-msg');
    el.textContent = texto;
    el.className = 'lancador-msg ' + (tipo || '');
  }

  async function enviar() {
    const botao = janela.querySelector('#mai-abrir');
    const geral = janela.querySelector('#mai-geral').checked;
    const cats = selecionadas();
    mensagem('', '');

    if (!geral && !cats.length) {
      mensagem('Selecione ao menos uma família, ou marque "Inventário geral".', 'erro');
      return;
    }

    botao.disabled = true;
    try {
      const sessao = await api.post('/inventario/sessoes/abrir', {
        unidade_id: UNIDADE_SELECIONADA,
        descricao: janela.querySelector('#mai-descricao').value.trim() || null,
        geral,
        categoria_ids: geral ? [] : cats,
        observacao: janela.querySelector('#mai-observacao').value.trim() || null,
      });
      mensagem(`Inventário nº ${sessao.numero_documento} aberto. Congele-o para começar a contagem.`, 'sucesso');
      setTimeout(() => {
        fechar();
        if (typeof aoConcluir === 'function') aoConcluir(sessao);
      }, 1100);
    } catch (erro) {
      mensagem(erro.message || 'Não foi possível abrir o inventário.', 'erro');
    } finally {
      botao.disabled = false;
    }
  }

  // ---------- API pública ----------
  async function abrir(opcoes = {}) {
    aoConcluir = opcoes.aoConcluir || null;
    if (!janela) criarJanela();
    janela.classList.add('visible');
    if (posicaoValida()) {
      janela.style.left = posicao.left + 'px';
      janela.style.top = posicao.top + 'px';
    } else {
      requestAnimationFrame(centralizar);
    }

    const u = (UNIDADES_DISPONIVEIS || []).find((x) => x.id === UNIDADE_SELECIONADA);
    janela.querySelector('#mai-unidade').textContent = u ? u.nome : '';

    // Limpa o formulário a cada abertura
    janela.querySelector('#mai-descricao').value = '';
    janela.querySelector('#mai-observacao').value = '';
    janela.querySelector('#mai-geral').checked = false;
    janela.querySelector('#mai-categorias-bloco').hidden = false;
    janela.querySelector('#mai-geral-cartao').classList.remove('ativo');
    mensagem('', '');

    try {
      categorias = await api.get('/categorias');
      renderCategorias();
    } catch (erro) {
      janela.querySelector('#mai-categorias').innerHTML =
        `<div class="estado-vazio">Não foi possível carregar as famílias: ${erro.message}</div>`;
    }
  }

  function fechar() { if (janela) janela.classList.remove('visible'); }
  function estaAberto() { return !!janela && janela.classList.contains('visible'); }

  /* Família cadastrada em outra tela: entra na lista sem fechar o modal,
     preservando o que já estava marcado. */
  document.addEventListener('cadastro:alterado', async (ev) => {
    if ((ev.detail || {}).tipo !== 'categoria') return;
    if (!estaAberto()) return;
    const marcadas = selecionadas();
    try {
      categorias = await api.get('/categorias');
      renderCategorias();
      marcadas.forEach((id) => {
        const el = janela.querySelector(`#mai-cat-${id}`);
        if (el) el.checked = true;
      });
      atualizarContagem();
    } catch (e) { /* silencioso */ }
  });

  return { abrir, fechar, estaAberto };
})();
