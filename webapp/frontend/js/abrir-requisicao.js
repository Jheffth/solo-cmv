/* ============================================================
   MODAL "ABRIR REQUISIÇÃO"

   Mesmas características do Lançador: janela flutuante, arrastável e que
   NÃO fecha ao clicar fora — só pelo X.

   Diferente do inventário, a requisição não tem escopo por família: quem
   requisita escolhe livremente qualquer item, na hora de lançar. Por isso
   aqui só se define o cabeçalho do pedido.
   ============================================================ */

window.AbrirRequisicao = (function () {
  let janela = null;
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
    const nx = Math.max(0, Math.min(elX + (x - iniX), window.innerWidth - r.width));
    const ny = Math.max(0, Math.min(elY + (y - iniY), window.innerHeight - 48));
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

  function centralizar() {
    if (window.innerWidth <= 620) {
      janela.style.left = '6px';
      janela.style.top = '6px';
      janela.style.transform = 'none';
      posicao = null;
      return;
    }
    const w = janela.offsetWidth || 500;
    janela.style.left = Math.max(0, (window.innerWidth - w) / 2) + 'px';
    janela.style.top = '90px';
    janela.style.transform = 'none';
    posicao = null;
  }

  function garantirVisivel() {
    if (!janela || !estaAberto()) return;
    if (window.innerWidth <= 620) {
      janela.style.left = '6px';
      janela.style.top = '6px';
      posicao = null;
      return;
    }
    const r = janela.getBoundingClientRect();
    const left = Math.min(Math.max(0, r.left), Math.max(0, window.innerWidth - r.width));
    const top = Math.min(Math.max(0, r.top), Math.max(0, window.innerHeight - 60));
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

  const hoje = () => new Date().toISOString().slice(0, 10);

  function criarJanela() {
    janela = document.createElement('div');
    janela.className = 'lancador-janela modal-requisicao';
    janela.id = 'modal-abrir-requisicao';
    janela.innerHTML = `
      <div class="lancador-header">
        ${icone('requisicoes')}
        <span class="titulo">Abrir Requisição</span>
        <span class="unidade-atual" id="mar-unidade"></span>
        <button class="lancador-close-btn" type="button" title="Fechar">${icone('fechar')}</button>
      </div>

      <div class="lancador-corpo">
        <div class="lancador-dica">
          O número é gerado automaticamente, na sequência desta unidade. Depois de aberta,
          é preciso <strong>iniciar</strong> a requisição para lançar os itens.
          O destino é a <strong>produção</strong>.
        </div>

        <div class="form-group">
          <label for="mar-descricao">Descrição da requisição</label>
          <input id="mar-descricao" placeholder="Ex.: Produção do almoço" maxlength="255">
        </div>

        <div class="lancador-grid col-2">
          <div>
            <label for="mar-solicitante">Solicitante</label>
            <input id="mar-solicitante" placeholder="Ex.: Cozinha" maxlength="120">
          </div>
          <div>
            <label for="mar-data">Data da produção</label>
            <input id="mar-data" type="date" value="${hoje()}">
          </div>
        </div>

        <div class="form-group" style="margin-bottom:0">
          <label for="mar-observacao">Observação (opcional)</label>
          <input id="mar-observacao" placeholder="Ex.: retirar até as 10h" maxlength="500">
        </div>
      </div>

      <div class="lancador-rodape">
        <span class="lancador-msg" id="mar-msg"></span>
        <button class="btn" type="button" id="mar-abrir">Abrir Requisição</button>
      </div>
    `;
    document.body.appendChild(janela);

    janela.querySelector('.lancador-close-btn').addEventListener('click', fechar);
    janela.querySelector('#mar-abrir').addEventListener('click', enviar);
    ligarArrasto();
  }

  function mensagem(texto, tipo) {
    const el = janela.querySelector('#mar-msg');
    el.textContent = texto;
    el.className = 'lancador-msg ' + (tipo || '');
  }

  async function enviar() {
    const botao = janela.querySelector('#mar-abrir');
    mensagem('', '');
    botao.disabled = true;
    try {
      const req = await api.post('/requisicoes', {
        unidade_id: UNIDADE_SELECIONADA,
        descricao: janela.querySelector('#mar-descricao').value.trim() || null,
        solicitante: janela.querySelector('#mar-solicitante').value.trim() || null,
        data_producao: janela.querySelector('#mar-data').value || null,
        observacao: janela.querySelector('#mar-observacao').value.trim() || null,
      });
      mensagem(`Requisição nº ${req.numero} aberta. Inicie-a para lançar os itens.`, 'sucesso');
      setTimeout(() => {
        fechar();
        if (typeof aoConcluir === 'function') aoConcluir(req);
      }, 1100);
    } catch (erro) {
      mensagem(erro.message || 'Não foi possível abrir a requisição.', 'erro');
    } finally {
      botao.disabled = false;
    }
  }

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
    janela.querySelector('#mar-unidade').textContent = u ? u.nome : '';

    ['#mar-descricao', '#mar-solicitante', '#mar-observacao']
      .forEach((s) => { janela.querySelector(s).value = ''; });
    janela.querySelector('#mar-data').value = hoje();
    mensagem('', '');
  }

  function fechar() { if (janela) janela.classList.remove('visible'); }
  function estaAberto() { return !!janela && janela.classList.contains('visible'); }

  return { abrir, fechar, estaAberto };
})();
