/* ============================================================
   LANÇADOR — janela flutuante para lançamentos rápidos.

   REGRA DO BLOQUEIO: vale APENAS para a aba "Inventário".
   Nessa aba aparecem "Número do Inventário" e "Descrição do Inventário", e
   os campos de contagem só liberam depois que o número for validado contra a
   base. Trocar o número invalida de novo.
   As demais abas (Compras, Perda e Vendas) ficam sempre liberadas — se houver
   um inventário validado, o lançamento é vinculado a ele; se não houver, é
   lançado sem vínculo. A aba Requisição tem trava própria, pelo número da
   requisição.

   O código do produto tem campo próprio: digita-se o código e o produto é
   localizado automaticamente (e vice-versa, ao escolher pelo nome).

   COMPORTAMENTO OBRIGATÓRIO: a janela NÃO fecha ao clicar fora dela.
   Só fecha pelo X — por isso não há backdrop nem listener no document.
   ============================================================ */

window.Lancador = (function () {
  let janela = null;
  let abaAtiva = 'compras';
  let dados = { produtos: [], fornecedores: [], categorias: [], motivosPerda: [] };
  let carregado = false;
  let itensNF = [];
  let posicao = null;

  let inventarioAtivo = null;   // inventário validado (aba Inventário)
  let requisicaoAtiva = null;   // requisição validada (aba Requisição)
  let validando = false;

  // ---------- Arrastar (mouse + toque) ----------
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
    let novoX = elX + (x - iniX);
    let novoY = elY + (y - iniY);
    novoX = Math.max(0, Math.min(novoX, window.innerWidth - r.width));
    novoY = Math.max(0, Math.min(novoY, window.innerHeight - 48));
    janela.style.left = novoX + 'px';
    janela.style.top = novoY + 'px';
    posicao = { left: novoX, top: novoY };
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

  // ---------- Abas ----------
  /* "Compras" cobre a nota inteira: cabeçalho (fornecedor, nº da nota, data)
     mais um ou vários itens. Antes havia uma aba separada de "Notas Fiscais"
     que fazia a mesma coisa em lote — redundância que virou uma aba só. */
  const ABAS = [
    { chave: 'compras',    rotulo: 'Compras',    icone: 'movimentos' },
    { chave: 'inventario', rotulo: 'Inventário', icone: 'inventario' },
    { chave: 'requisicao', rotulo: 'Requisição', icone: 'requisicoes' },
    { chave: 'perda',      rotulo: 'Perda',      icone: 'perdas' },
    { chave: 'vendas',     rotulo: 'Vendas',     icone: 'vendas', exige: 'LANCAR_FATURAMENTO' },
  ];

  /* Pela capacidade, não pelo papel — mesma razão do menu lateral (app.js):
     a lista de papéis aqui era uma segunda régua, que só descobriria estar
     errada quando alguém levasse um 403 depois de clicar. */
  function abasPermitidas() {
    const pode = (typeof window.pode === 'function') ? window.pode : () => true;
    return ABAS.filter((a) => !a.exige || pode(a.exige));
  }

  function montarAbas() {
    return abasPermitidas().map((a) =>
      `<button class="lancador-aba" data-aba="${a.chave}" type="button">${icone(a.icone)}<span>${a.rotulo}</span></button>`
    ).join('');
  }

  // ---------- Montagem da janela ----------
  function criarJanela() {
    janela = document.createElement('div');
    janela.className = 'lancador-janela';
    janela.id = 'lancador-janela';
    janela.innerHTML = `
      <div class="lancador-header">
        ${icone('lancador')}
        <span class="titulo">Lançador</span>
        <span class="unidade-atual" id="lancador-unidade"></span>
        <button class="lancador-close-btn" type="button" title="Fechar">${icone('fechar')}</button>
      </div>

      <div class="inv-bloco" id="inv-bloco">
        <div class="inv-linha">
          <div class="form-group inv-numero">
            <label for="inv-num" id="inv-rotulo-num">Número do Documento</label>
            <div class="inv-numero-campo">
              <input id="inv-num" placeholder="Ex.: 01" autocomplete="off" list="inv-sugestoes">
              <datalist id="inv-sugestoes"></datalist>
              <button class="btn" type="button" id="inv-validar">Validar</button>
            </div>
          </div>
          <div class="form-group inv-desc">
            <label for="inv-descricao" id="inv-rotulo-desc">Descrição</label>
            <input id="inv-descricao" readonly placeholder="preenchida ao validar o número">
          </div>
        </div>
        <div class="inv-estado" id="inv-estado"></div>
      </div>

      <div class="lancador-abas">${montarAbas()}</div>

      <div class="lancador-area">
        <div class="lancador-corpo" id="lancador-corpo"></div>
        <div class="lancador-trava" id="lancador-trava">
          ${icone('cadeado')}
          <p id="lancador-trava-texto"></p>
        </div>
      </div>

      <div class="lancador-rodape">
        <span class="lancador-msg" id="lancador-msg"></span>
        <button class="btn" type="button" id="lancador-salvar" disabled>Lançar</button>
      </div>
    `;
    document.body.appendChild(janela);

    janela.querySelector('.lancador-close-btn').addEventListener('click', fechar);
    janela.querySelectorAll('.lancador-aba').forEach((b) => {
      b.addEventListener('click', () => trocarAba(b.dataset.aba));
    });
    janela.querySelector('#lancador-salvar').addEventListener('click', salvar);

    const campoNum = janela.querySelector('#inv-num');
    janela.querySelector('#inv-validar').addEventListener('click', validarDocumento);
    campoNum.addEventListener('keydown', (e) => {
      if (e.key === 'Enter') { e.preventDefault(); validarDocumento(); }
    });
    // Mexeu no número: o que estava validado deixa de valer
    campoNum.addEventListener('input', () => {
      const ctx = contextoDaAba();
      const doc = ctx && ctx.obter();
      if (doc && campoNum.value.trim() !== ctx.numeroDe(doc)) invalidarDocumento();
    });

    ligarArrasto();
  }

  function centralizar() {
    const w = janela.offsetWidth || 580;
    janela.style.left = Math.max(0, (window.innerWidth - w) / 2) + 'px';
    janela.style.top = window.innerWidth <= 620 ? '8px' : '70px';
    janela.style.transform = 'none';
    posicao = null;
  }

  /* Ao encolher a janela do navegador, a posição salva pode ficar fora da
     tela e a janela "sumia". Aqui ela é trazida de volta para dentro. */
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

  // A posição guardada só serve se ainda couber na tela atual
  function posicaoValida() {
    if (!posicao || !janela) return false;
    const r = janela.getBoundingClientRect();
    return posicao.left >= 0 && posicao.top >= 0
      && posicao.left <= Math.max(0, window.innerWidth - r.width)
      && posicao.top <= Math.max(0, window.innerHeight - 60);
  }

  window.addEventListener('resize', garantirVisivel);

  // ---------- Documento exigido por aba ----------
  /* Duas abas trabalham sobre um documento que precisa existir e estar no
     estado certo: Inventário (contagem) e Requisição (itens pedidos). As
     demais abas seguem livres. */
  const CONTEXTOS = {
    inventario: {
      rotuloNumero: 'Número do Inventário',
      rotuloDescricao: 'Descrição do Inventário',
      textoTrava: 'Informe e valide o <strong>Número do Inventário</strong> acima para liberar o lançamento da contagem.',
      caminhoValidar: (num) => `/inventario/sessoes/buscar?numero=${encodeURIComponent(num)}&unidade_id=${UNIDADE_SELECIONADA}`,
      caminhosSugestao: () => [
        `/inventario/sessoes?unidade_id=${UNIDADE_SELECIONADA}&status=CONGELADO`,
        `/inventario/sessoes?unidade_id=${UNIDADE_SELECIONADA}&status=EM_CONTAGEM`,
      ],
      numeroDe: (d) => d.numero_documento,
      rotulosStatus: { CONGELADO: 'Congelado', EM_CONTAGEM: 'Em Contagem' },
      obter: () => inventarioAtivo,
      definir: (v) => { inventarioAtivo = v; },
    },
    requisicao: {
      rotuloNumero: 'Número da Requisição',
      rotuloDescricao: 'Descrição da Requisição',
      textoTrava: 'Informe e valide o <strong>Número da Requisição</strong> acima para liberar o lançamento dos itens.',
      caminhoValidar: (num) => `/requisicoes/buscar?numero=${encodeURIComponent(num)}&unidade_id=${UNIDADE_SELECIONADA}`,
      caminhosSugestao: () => [`/requisicoes?unidade_id=${UNIDADE_SELECIONADA}&status=INICIADA`],
      numeroDe: (d) => d.numero,
      rotulosStatus: { INICIADA: 'Iniciada' },
      obter: () => requisicaoAtiva,
      definir: (v) => { requisicaoAtiva = v; },
    },
  };

  const contextoDaAba = () => CONTEXTOS[abaAtiva] || null;
  const documentoAtivo = () => {
    const ctx = contextoDaAba();
    return ctx ? ctx.obter() : null;
  };

  function aplicarTrava() {
    const ctx = contextoDaAba();
    const liberado = !ctx || !!ctx.obter();

    // O bloco de número/descrição só aparece nas abas que exigem documento
    janela.querySelector('#inv-bloco').hidden = !ctx;
    if (ctx) {
      janela.querySelector('#inv-rotulo-num').textContent = ctx.rotuloNumero;
      janela.querySelector('#inv-rotulo-desc').textContent = ctx.rotuloDescricao;
      janela.querySelector('#lancador-trava-texto').innerHTML = ctx.textoTrava;
    }

    janela.classList.toggle('travado', !liberado);
    janela.querySelector('#lancador-trava').hidden = liberado;
    janela.querySelector('#lancador-salvar').disabled = !liberado;
    janela.querySelectorAll('#lancador-corpo input, #lancador-corpo select, #lancador-corpo button')
      .forEach((el) => { el.disabled = !liberado; });
  }

  function invalidarDocumento() {
    const ctx = contextoDaAba();
    if (ctx) ctx.definir(null);
    janela.querySelector('#inv-descricao').value = '';
    mostrarEstadoDocumento('', '');
    aplicarTrava();
  }

  function mostrarEstadoDocumento(texto, tipo) {
    const el = janela.querySelector('#inv-estado');
    el.textContent = texto;
    el.className = 'inv-estado ' + (tipo || '');
    el.hidden = !texto;
  }

  async function validarDocumento() {
    const ctx = contextoDaAba();
    if (!ctx) return;

    const numero = janela.querySelector('#inv-num').value.trim();
    if (!numero) {
      invalidarDocumento();
      mostrarEstadoDocumento(`Informe o ${ctx.rotuloNumero.toLowerCase()}.`, 'erro');
      return;
    }
    if (validando) return;
    validando = true;
    mostrarEstadoDocumento('Validando…', '');
    try {
      const doc = await api.get(ctx.caminhoValidar(numero));
      ctx.definir(doc);
      janela.querySelector('#inv-descricao').value = doc.descricao || '(sem descrição)';

      const status = ctx.rotulosStatus[doc.status] || doc.status;
      let texto = `${abaAtiva === 'requisicao' ? 'Requisição' : 'Inventário'} nº ${ctx.numeroDe(doc)} validado — ${status}.`;
      if (abaAtiva === 'inventario') texto += ` Escopo: ${escopoDoInventario()}.`;
      mostrarEstadoDocumento(texto, 'ok');

      renderAba();   // redesenha para a lista sair filtrada, quando for o caso
      aplicarTrava();
      limparMensagem();
    } catch (erro) {
      ctx.definir(null);
      janela.querySelector('#inv-descricao').value = '';
      mostrarEstadoDocumento(erro.message || 'Não foi possível validar.', 'erro');
      aplicarTrava();
    } finally {
      validando = false;
    }
  }

  async function carregarSugestoes() {
    const ctx = contextoDaAba();
    const alvo = janela.querySelector('#inv-sugestoes');
    if (!ctx) { alvo.innerHTML = ''; return; }
    try {
      const listas = await Promise.all(ctx.caminhosSugestao().map((c) => api.get(c)));
      alvo.innerHTML = listas.flat()
        .map((d) => `<option value="${ctx.numeroDe(d)}">${d.descricao || 'sem descrição'}</option>`)
        .join('');
    } catch (e) { /* sugestão é opcional */ }
  }

  // ---------- Dados auxiliares ----------
  /* Recarrega produtos e fornecedores.
     Sempre busca de novo ao abrir a janela — assim um produto ou fornecedor
     cadastrado depois já aparece, sem precisar recarregar a página. */
  async function carregarDados(forcar = true) {
    if (carregado && !forcar) return;
    const [produtos, fornecedores, categorias, motivos] = await Promise.all([
      api.get('/produtos'),
      api.get('/fornecedores'),
      api.get('/categorias'),
      // Motivos vêm do backend para não existir uma segunda lista aqui que
      // silenciosamente diverge da que valida o lançamento.
      api.get('/perdas/motivos').catch(() => []),
    ]);
    dados.produtos = produtos;
    dados.fornecedores = fornecedores;
    dados.categorias = categorias;
    dados.motivosPerda = motivos;
    carregado = true;
  }

  function opcoesMotivoPerda() {
    const lista = dados.motivosPerda || [];
    if (!lista.length) return '<option value="">—</option>';
    return lista.map((m) => `<option value="${m.valor}">${m.rotulo}</option>`).join('');
  }

  /* Atualiza as listas suspensas sem redesenhar o formulário, para não apagar
     o que o usuário já digitou. Mantém o item que estava selecionado. */
  function atualizarListasEmTela() {
    if (!janela) return;

    janela.querySelectorAll('select').forEach((sel) => {
      const ehProduto = sel.id === 'li-produto' || sel.classList.contains('nf-produto');
      const ehFornecedor = sel.id === 'lnf-fornecedor';
      if (!ehProduto && !ehFornecedor) return;

      const selecionado = sel.value;
      const vazio = ehFornecedor ? '<option value="">—</option>' : '';
      sel.innerHTML = vazio + (ehProduto ? opcoesProduto() : opcoesFornecedor());
      // Só restaura se o item ainda existir na lista nova
      if (selecionado && sel.querySelector(`option[value="${selecionado}"]`)) {
        sel.value = selecionado;
      }
    });
  }

  /* Outra tela cadastrou produto/fornecedor: atualiza se estiver aberto. */
  document.addEventListener('cadastro:alterado', async (ev) => {
    const tipo = (ev.detail || {}).tipo;
    if (!['produto', 'fornecedor'].includes(tipo)) return;
    if (!estaAberto()) { carregado = false; return; }   // recarrega na próxima abertura
    try {
      await carregarDados(true);
      atualizarListasEmTela();
    } catch (e) { /* silencioso: a próxima abertura tenta de novo */ }
  });

  /* Produtos disponíveis na aba atual.
     Na aba Inventário, só valem os produtos das famílias do inventário
     validado — um inventário do Bar não pode receber Hortifruti. */
  function produtosDisponiveis() {
    if (abaAtiva !== 'inventario' || !inventarioAtivo) return dados.produtos;
    if (inventarioAtivo.geral) return dados.produtos;
    const familias = (inventarioAtivo.categorias || []).map((c) => c.id);
    if (!familias.length) return [];
    return dados.produtos.filter((p) => familias.includes(p.categoria_id));
  }

  const opcoesProduto = () => produtosDisponiveis()
    .map((p) => `<option value="${p.id}">${p.nome}${p.unidade_medida ? ' (' + p.unidade_medida + ')' : ''}</option>`)
    .join('');
  const opcoesFornecedor = () => dados.fornecedores
    .map((f) => `<option value="${f.id}">${f.nome}</option>`)
    .join('');
  const hoje = () => new Date().toISOString().slice(0, 10);
  const produtoPorCodigo = (codigo) => dados.produtos.find((p) => (p.codigo || '') === String(codigo).trim());
  const produtoPorId = (id) => dados.produtos.find((p) => p.id === parseInt(id, 10));

  // Produto existe, mas está fora do escopo do inventário validado?
  function foraDoEscopo(produto) {
    if (abaAtiva !== 'inventario' || !inventarioAtivo || !produto) return false;
    return !produtosDisponiveis().some((p) => p.id === produto.id);
  }

  function nomeFamilia(produto) {
    const cat = (dados.categorias || []).find((c) => c.id === produto.categoria_id);
    return cat ? cat.nome.replace('Família - ', '') : 'sem família';
  }

  /* Liga um par de campos código <-> produto:
     digitar o código seleciona o produto; trocar o produto preenche o código.
     Na aba Inventário, código de item fora do escopo é recusado na hora. */
  function ligarCodigoProduto(campoCodigo, campoProduto, campoUnidade) {
    const sincronizarDoProduto = () => {
      const p = produtoPorId(campoProduto.value);
      campoCodigo.value = p && p.codigo ? p.codigo : '';
      campoCodigo.classList.remove('codigo-invalido');
      if (campoUnidade) campoUnidade.value = p && p.unidade_medida ? p.unidade_medida : '';
    };

    campoCodigo.addEventListener('input', () => {
      const texto = campoCodigo.value.trim();
      const p = produtoPorCodigo(texto);

      if (p && foraDoEscopo(p)) {
        campoCodigo.classList.add('codigo-invalido');
        if (campoUnidade) campoUnidade.value = '';
        mensagem(
          `${p.codigo} — ${p.nome} é da família ${nomeFamilia(p)} e não faz parte do inventário ` +
          `nº ${inventarioAtivo.numero_documento} (${escopoDoInventario()}).`, 'erro');
        return;
      }

      if (p) {
        campoProduto.value = p.id;
        campoCodigo.classList.remove('codigo-invalido');
        if (campoUnidade) campoUnidade.value = p.unidade_medida || '';
        limparMensagem();
      } else {
        campoCodigo.classList.toggle('codigo-invalido', texto !== '');
        if (texto === '') limparMensagem();
      }
    });
    campoProduto.addEventListener('change', sincronizarDoProduto);
    sincronizarDoProduto();
  }

  function escopoDoInventario() {
    if (!inventarioAtivo) return '';
    if (inventarioAtivo.geral) return 'todas as famílias';
    const nomes = (inventarioAtivo.categorias || []).map((c) => c.nome.replace('Família - ', ''));
    return nomes.join(', ') || 'sem famílias definidas';
  }

  // ---------- Conteúdo de cada aba ----------
  function renderAba() {
    const corpo = janela.querySelector('#lancador-corpo');
    const botaoSalvar = janela.querySelector('#lancador-salvar');
    limparMensagem();

    if (abaAtiva === 'compras') {
      botaoSalvar.textContent = 'Lançar compra';
      if (!itensNF.length) itensNF = [{}];
      corpo.innerHTML = `
        <div class="lancador-dica">
          Lançamento manual da compra: preencha o cabeçalho da nota e adicione os itens.
          Para um item só, basta deixar uma linha. Informando o custo, o histórico de
          último custo do produto é atualizado.
        </div>
        <div class="lancador-grid">
          <div><label for="lnf-fornecedor">Fornecedor</label><select id="lnf-fornecedor"><option value="">—</option>${opcoesFornecedor()}</select></div>
          <div><label for="lnf-doc">Nº da nota</label><input id="lnf-doc" placeholder="NF"></div>
          <div><label for="lnf-data">Data</label><input id="lnf-data" type="date" value="${hoje()}"></div>
        </div>
        <label style="margin-top:.4rem">Itens da nota</label>
        <div class="nf-itens" id="lnf-itens"></div>
        <button class="btn secundario" type="button" id="lnf-add" style="margin-top:.3rem">+ Adicionar item</button>
        <div class="nf-total" id="lnf-total">Total: R$ 0,00</div>
      `;
      renderItensNF();
      corpo.querySelector('#lnf-add').addEventListener('click', () => {
        lerItensNF();
        itensNF.push({});
        renderItensNF();
      });

    } else if (abaAtiva === 'inventario') {
      botaoSalvar.textContent = 'Lançar contagem';
      const disponiveis = produtosDisponiveis().length;
      corpo.innerHTML = `
        <div class="lancador-dica">
          Quantidade contada na prateleira. Ela é comparada com o estoque fotografado no
          congelamento para apurar a divergência — e só vira estoque real quando o inventário for finalizado.
          ${inventarioAtivo ? `<br><strong>Escopo:</strong> ${escopoDoInventario()} — ${disponiveis} item(ns) disponíveis.` : ''}
        </div>
        <div class="linha-produto">
          <div class="form-group campo-codigo">
            <label for="li-codigo">Código</label>
            <input id="li-codigo" placeholder="000000" autocomplete="off" inputmode="numeric">
          </div>
          <div class="form-group campo-produto">
            <label for="li-produto">Produto</label>
            <select id="li-produto">${opcoesProduto()}</select>
          </div>
          <div class="form-group campo-un">
            <label for="li-un">Un.</label>
            <input id="li-un" readonly tabindex="-1">
          </div>
        </div>
        <div class="lancador-grid col-2">
          <div><label for="li-qtd">Quantidade contada</label><input id="li-qtd" type="number" step="0.001" placeholder="0"></div>
        </div>
      `;
      ligarCodigoProduto(corpo.querySelector('#li-codigo'), corpo.querySelector('#li-produto'), corpo.querySelector('#li-un'));

    } else if (abaAtiva === 'requisicao') {
      botaoSalvar.textContent = 'Adicionar item';
      corpo.innerHTML = `
        <div class="lancador-dica">
          Item que sai do estoque para a produção. Qualquer produto cadastrado pode ser
          requisitado. O estoque só é baixado quando a requisição for <strong>atendida</strong>.
        </div>
        <div class="linha-produto">
          <div class="form-group campo-codigo">
            <label for="lr-codigo">Código</label>
            <input id="lr-codigo" placeholder="000000" autocomplete="off" inputmode="numeric">
          </div>
          <div class="form-group campo-produto">
            <label for="lr-produto">Produto</label>
            <select id="lr-produto">${opcoesProduto()}</select>
          </div>
          <div class="form-group campo-un">
            <label for="lr-un">Un.</label>
            <input id="lr-un" readonly tabindex="-1">
          </div>
        </div>
        <div class="lancador-grid col-2">
          <div><label for="lr-qtd">Quantidade</label><input id="lr-qtd" type="number" step="0.001" placeholder="0"></div>
          <div><label for="lr-obs">Observação (opcional)</label><input id="lr-obs" placeholder="Ex.: para o molho"></div>
        </div>
        <div class="lancador-aviso" id="lr-saldo" hidden></div>
      `;
      ligarCodigoProduto(corpo.querySelector('#lr-codigo'), corpo.querySelector('#lr-produto'), corpo.querySelector('#lr-un'));
      corpo.querySelector('#lr-produto').addEventListener('change', mostrarSaldoRequisicao);
      corpo.querySelector('#lr-codigo').addEventListener('input', mostrarSaldoRequisicao);

    } else if (abaAtiva === 'perda') {
      botaoSalvar.textContent = 'Lançar perda';
      corpo.innerHTML = `
        <div class="lancador-dica">
          Item que saiu do estoque e <strong>não virou venda</strong>. Diferente da
          requisição, a baixa é imediata — a perda já aconteceu. O motivo é obrigatório:
          é ele que diz onde agir (compra em excesso, manuseio, refrigeração, controle).
        </div>
        <div class="linha-produto">
          <div class="form-group campo-codigo">
            <label for="lp-codigo">Código</label>
            <input id="lp-codigo" placeholder="000000" autocomplete="off" inputmode="numeric">
          </div>
          <div class="form-group campo-produto">
            <label for="lp-produto">Produto</label>
            <select id="lp-produto">${opcoesProduto()}</select>
          </div>
          <div class="form-group campo-un">
            <label for="lp-un">Un.</label>
            <input id="lp-un" readonly tabindex="-1">
          </div>
        </div>
        <div class="lancador-grid">
          <div><label for="lp-qtd">Quantidade perdida</label><input id="lp-qtd" type="number" step="0.001" placeholder="0"></div>
          <div>
            <label for="lp-motivo">Motivo</label>
            <select id="lp-motivo">${opcoesMotivoPerda()}</select>
          </div>
          <div><label for="lp-data">Data</label><input id="lp-data" type="date" value="${hoje()}"></div>
        </div>
        <div><label for="lp-obs">Observação</label><input id="lp-obs" placeholder="Ex.: caixa esquecida fora da câmara"></div>
        <div class="lancador-aviso" id="lp-saldo" hidden></div>
      `;
      ligarCodigoProduto(corpo.querySelector('#lp-codigo'), corpo.querySelector('#lp-produto'), corpo.querySelector('#lp-un'));
      corpo.querySelector('#lp-produto').addEventListener('change', mostrarSaldoPerda);
      corpo.querySelector('#lp-codigo').addEventListener('input', mostrarSaldoPerda);

    } else {
      botaoSalvar.textContent = 'Lançar venda';
      const p = periodoSemanaAtual();
      corpo.innerHTML = `
        <div class="lancador-dica">Faturamento do período informado pela loja. É o valor que divide o CMV Real para chegar no CMV %.</div>
        <div class="lancador-grid col-2">
          <div><label for="lv-inicio">Início do período</label><input id="lv-inicio" type="date" value="${p.inicio}"></div>
          <div><label for="lv-fim">Fim do período</label><input id="lv-fim" type="date" value="${p.fim}"></div>
        </div>
        <div class="lancador-grid">
          <div><label for="lv-total">Faturamento total (R$)</label><input id="lv-total" type="number" step="0.01" placeholder="0,00"></div>
          <div><label for="lv-comida">Comida (opcional)</label><input id="lv-comida" type="number" step="0.01" placeholder="0,00"></div>
          <div><label for="lv-bebida">Bebida (opcional)</label><input id="lv-bebida" type="number" step="0.01" placeholder="0,00"></div>
        </div>
        <div><label for="lv-obs">Observação (opcional)</label><input id="lv-obs" placeholder="Ex.: semana com feriado"></div>
        <div class="lancador-aviso" id="lv-aviso" hidden></div>
      `;
      ['#lv-total', '#lv-comida', '#lv-bebida'].forEach((sel) => {
        corpo.querySelector(sel).addEventListener('input', conferirSomaVenda);
      });
    }

    aplicarTrava();   // campos novos nascem bloqueados se não houver inventário validado
  }

  function periodoSemanaAtual() {
    const hj = new Date();
    const diaSemana = (hj.getDay() + 6) % 7;
    const seg = new Date(hj); seg.setDate(hj.getDate() - diaSemana);
    const dom = new Date(seg); dom.setDate(seg.getDate() + 6);
    const iso = (d) => d.toISOString().slice(0, 10);
    return { inicio: iso(seg), fim: iso(dom) };
  }

  function conferirSomaVenda() {
    const aviso = janela.querySelector('#lv-aviso');
    if (!aviso) return;
    const total = parseFloat(valor('#lv-total'));
    const comida = parseFloat(valor('#lv-comida'));
    const bebida = parseFloat(valor('#lv-bebida'));
    if (isNaN(total) || (isNaN(comida) && isNaN(bebida))) { aviso.hidden = true; return; }
    const soma = (comida || 0) + (bebida || 0);
    const dif = Math.round((total - soma) * 100) / 100;
    if (Math.abs(dif) < 0.01) { aviso.hidden = true; return; }
    aviso.hidden = false;
    aviso.textContent = `Comida + bebida somam R$ ${soma.toFixed(2).replace('.', ',')} — ` +
      (dif > 0 ? `R$ ${dif.toFixed(2).replace('.', ',')} a menos que o total.`
               : `R$ ${Math.abs(dif).toFixed(2).replace('.', ',')} a mais que o total.`);
  }

  // ---------- Itens da nota fiscal ----------
  function renderItensNF() {
    const cont = janela.querySelector('#lnf-itens');
    cont.innerHTML = itensNF.map((item, i) => `
      <div class="nf-item" data-i="${i}">
        <div>
          ${i === 0 ? '<label>Código</label>' : ''}
          <input class="nf-codigo" placeholder="000000" autocomplete="off" inputmode="numeric">
        </div>
        <div>
          ${i === 0 ? '<label>Produto</label>' : ''}
          <select class="nf-produto">${opcoesProduto()}</select>
        </div>
        <div>
          ${i === 0 ? '<label>Qtd.</label>' : ''}
          <input class="nf-qtd" type="number" step="0.001" value="${item.quantidade ?? ''}" placeholder="0">
        </div>
        <div>
          ${i === 0 ? '<label>Custo un.</label>' : ''}
          <input class="nf-custo" type="number" step="0.0001" value="${item.custo_unitario ?? ''}" placeholder="0,00">
        </div>
        <button class="nf-item-remover" type="button" title="Remover item">&times;</button>
      </div>
    `).join('');

    cont.querySelectorAll('.nf-item').forEach((linha, i) => {
      const sel = linha.querySelector('.nf-produto');
      if (itensNF[i].produto_id) sel.value = itensNF[i].produto_id;
      ligarCodigoProduto(linha.querySelector('.nf-codigo'), sel, null);

      linha.querySelector('.nf-item-remover').addEventListener('click', () => {
        lerItensNF();
        itensNF.splice(i, 1);
        if (!itensNF.length) itensNF = [{}];
        renderItensNF();
        aplicarTrava();
      });
      linha.querySelectorAll('input, select').forEach((campo) => {
        campo.addEventListener('input', () => { lerItensNF(); atualizarTotalNF(); });
      });
    });
    atualizarTotalNF();
  }

  function lerItensNF() {
    const linhas = janela.querySelectorAll('#lnf-itens .nf-item');
    itensNF = Array.from(linhas).map((l) => ({
      produto_id: parseInt(l.querySelector('.nf-produto').value, 10) || null,
      quantidade: parseFloat(l.querySelector('.nf-qtd').value) || null,
      custo_unitario: parseFloat(l.querySelector('.nf-custo').value) || null,
    }));
  }

  function atualizarTotalNF() {
    const el = janela.querySelector('#lnf-total');
    if (!el) return;
    const total = itensNF.reduce((soma, i) => soma + ((i.quantidade || 0) * (i.custo_unitario || 0)), 0);
    el.textContent = 'Total: R$ ' + total.toFixed(2).replace('.', ',');
  }

  // ---------- Envio ----------
  async function salvar() {
    const ctx = contextoDaAba();
    if (ctx && !ctx.obter()) {
      mensagem(`Valide o ${ctx.rotuloNumero.toLowerCase()} antes de lançar.`, 'erro');
      return;
    }
    const botao = janela.querySelector('#lancador-salvar');
    limparMensagem();
    botao.disabled = true;
    try {
      if (abaAtiva === 'compras') await salvarCompra();
      else if (abaAtiva === 'inventario') await salvarContagem();
      else if (abaAtiva === 'requisicao') await salvarRequisicao();
      else if (abaAtiva === 'perda') await salvarPerda();
      else await salvarVenda();
    } catch (erro) {
      mensagem(erro.message || 'Não foi possível lançar.', 'erro');
    } finally {
      botao.disabled = !!(ctx && !ctx.obter());
    }
  }

  // Vincula ao inventário quando houver um validado; senão, lança sem vínculo
  const vinculoInventario = () => (inventarioAtivo ? inventarioAtivo.id : null);

  function valor(id) { const el = janela.querySelector(id); return el ? el.value.trim() : ''; }

  /* Uma compra é sempre uma nota: cabeçalho + N itens. Com uma linha só,
     é a antiga "compra avulsa"; com várias, a antiga aba de notas fiscais. */
  async function salvarCompra() {
    lerItensNF();
    const validos = itensNF.filter((i) => i.produto_id && i.quantidade);
    if (!validos.length) throw new Error('Adicione ao menos um item com produto e quantidade.');
    const resultado = await api.post('/movimentos/nota-fiscal', {
      unidade_id: UNIDADE_SELECIONADA,
      numero_documento: valor('#lnf-doc') || null,
      fornecedor_id: valor('#lnf-fornecedor') ? parseInt(valor('#lnf-fornecedor'), 10) : null,
      data: valor('#lnf-data') || null,
      sessao_inventario_id: vinculoInventario(),
      itens: validos,
    });
    mensagem(`Compra lançada: ${resultado.movimentos_criados} item(ns), R$ ${resultado.valor_total.toFixed(2).replace('.', ',')}.`, 'sucesso');
    itensNF = [{}];
    renderItensNF();
    aplicarTrava();
    atualizarTelaAtual();
  }

  async function salvarContagem() {
    const qtd = parseFloat(valor('#li-qtd'));
    if (isNaN(qtd)) throw new Error('Informe a quantidade contada.');

    const codigo = valor('#li-codigo');
    const produto = produtoPorCodigo(codigo) || produtoPorId(valor('#li-produto'));
    if (!produto) throw new Error('Informe um código de produto válido.');
    if (foraDoEscopo(produto)) {
      throw new Error(
        `${produto.codigo} — ${produto.nome} não faz parte do inventário ` +
        `nº ${inventarioAtivo.numero_documento} (${escopoDoInventario()}).`);
    }

    // Grava direto na linha do inventário (servicos/contagem.py no backend),
    // e não como movimento solto — é isso que faz o valor aparecer no PDF.
    const r = await api.post('/inventario/contagem', {
      sessao_id: inventarioAtivo.id,
      produto_id: produto.id,
      quantidade: qtd,
      origem: 'WEB',
    });

    mensagem(r.mensagem, 'sucesso');
    janela.querySelector('#li-qtd').value = '';
    janela.querySelector('#li-codigo').value = '';
    janela.querySelector('#li-un').value = '';
    atualizarTelaAtual();
  }

  /* Mostra o saldo do item escolhido, para quem requisita saber o que há
     disponível antes de pedir. Não bloqueia — só informa. */
  async function mostrarSaldoRequisicao() {
    const aviso = janela.querySelector('#lr-saldo');
    if (!aviso) return;
    const p = produtoPorCodigo(valor('#lr-codigo')) || produtoPorId(valor('#lr-produto'));
    if (!p) { aviso.hidden = true; return; }
    try {
      const est = await api.get(`/estoque?unidade_id=${UNIDADE_SELECIONADA}&busca=${encodeURIComponent(p.codigo || p.nome)}`);
      const item = (est.itens || []).find((i) => i.produto_id === p.id);
      if (!item) { aviso.hidden = true; return; }
      aviso.hidden = false;
      aviso.textContent = `Saldo em estoque: ${item.quantidade}${p.unidade_medida ? ' ' + p.unidade_medida : ''}.`;
    } catch (e) { aviso.hidden = true; }
  }

  async function mostrarSaldoPerda() {
    const aviso = janela.querySelector('#lp-saldo');
    if (!aviso) return;
    const p = produtoPorCodigo(valor('#lp-codigo')) || produtoPorId(valor('#lp-produto'));
    if (!p) { aviso.hidden = true; return; }
    try {
      const est = await api.get(`/estoque?unidade_id=${UNIDADE_SELECIONADA}&busca=${encodeURIComponent(p.codigo || p.nome)}`);
      const item = (est.itens || []).find((i) => i.produto_id === p.id);
      if (!item) { aviso.hidden = true; return; }
      aviso.hidden = false;
      aviso.textContent = `Saldo em estoque: ${item.quantidade}${p.unidade_medida ? ' ' + p.unidade_medida : ''}.`;
    } catch (e) { aviso.hidden = true; }
  }

  async function salvarPerda() {
    const qtd = parseFloat(valor('#lp-qtd'));
    if (isNaN(qtd) || qtd <= 0) throw new Error('Informe uma quantidade maior que zero.');

    const produto = produtoPorCodigo(valor('#lp-codigo')) || produtoPorId(valor('#lp-produto'));
    if (!produto) throw new Error('Informe um código de produto válido.');

    const motivo = valor('#lp-motivo');
    if (!motivo) throw new Error('Escolha o motivo da perda.');
    const obs = valor('#lp-obs');
    if (motivo === 'OUTRO' && !obs) {
      throw new Error('Motivo "Outro" exige uma observação explicando o que houve.');
    }

    const r = await api.post('/perdas', {
      unidade_id: UNIDADE_SELECIONADA,
      produto_id: produto.id,
      quantidade: qtd,
      motivo,
      data: valor('#lp-data') || null,
      observacao: obs || null,
    });

    const valorPerda = r.perda.custo_total
      ? ` — R$ ${Number(r.perda.custo_total).toFixed(2).replace('.', ',')}`
      : '';
    mensagem(`Perda ${r.perda.numero_documento} registrada${valorPerda}. `
      + `Saldo de ${produto.nome}: ${r.saldo_anterior} → ${r.saldo_atual}.`,
      r.saldo_atual < 0 ? 'erro' : 'sucesso');

    ['#lp-qtd', '#lp-codigo', '#lp-un', '#lp-obs'].forEach((s) => { janela.querySelector(s).value = ''; });
    const aviso = janela.querySelector('#lp-saldo');
    if (aviso) aviso.hidden = true;
    atualizarTelaAtual();
  }

  async function salvarRequisicao() {
    const qtd = parseFloat(valor('#lr-qtd'));
    if (isNaN(qtd) || qtd <= 0) throw new Error('Informe uma quantidade maior que zero.');

    const produto = produtoPorCodigo(valor('#lr-codigo')) || produtoPorId(valor('#lr-produto'));
    if (!produto) throw new Error('Informe um código de produto válido.');

    const r = await api.post('/requisicoes/item', {
      requisicao_id: requisicaoAtiva.id,
      produto_id: produto.id,
      quantidade: qtd,
      observacao: valor('#lr-obs') || null,
      origem: 'WEB',
    });

    mensagem(r.mensagem, r.saldo_disponivel < qtd ? 'erro' : 'sucesso');
    ['#lr-qtd', '#lr-codigo', '#lr-un', '#lr-obs'].forEach((s) => { janela.querySelector(s).value = ''; });
    const aviso = janela.querySelector('#lr-saldo');
    if (aviso) aviso.hidden = true;
    atualizarTelaAtual();
  }

  async function salvarVenda() {
    const inicio = valor('#lv-inicio');
    const fim = valor('#lv-fim');
    const total = parseFloat(valor('#lv-total'));
    if (!inicio || !fim) throw new Error('Informe o início e o fim do período.');
    if (fim < inicio) throw new Error('O fim do período não pode ser antes do início.');
    if (isNaN(total)) throw new Error('Informe o faturamento total do período.');
    if (total < 0) throw new Error('O faturamento não pode ser negativo.');

    const comida = valor('#lv-comida');
    const bebida = valor('#lv-bebida');
    await api.post('/vendas', {
      unidade_id: UNIDADE_SELECIONADA,
      data_inicio: inicio,
      data_fim: fim,
      faturamento_total: total,
      faturamento_comida: comida ? parseFloat(comida) : null,
      faturamento_bebida: bebida ? parseFloat(bebida) : null,
      observacao: valor('#lv-obs') || null,
    });
    mensagem(`Venda lançada: R$ ${total.toFixed(2).replace('.', ',')} (${inicio.split('-').reverse().join('/')} a ${fim.split('-').reverse().join('/')}).`, 'sucesso');
    ['#lv-total', '#lv-comida', '#lv-bebida', '#lv-obs'].forEach((s) => { janela.querySelector(s).value = ''; });
    const aviso = janela.querySelector('#lv-aviso');
    if (aviso) aviso.hidden = true;
    atualizarTelaAtual();
  }

  function atualizarTelaAtual() {
    const rota = (location.hash || '').replace('#', '').split('/')[0] || 'dashboard';
    if (['dashboard', 'movimentos', 'inventario', 'vendas', 'estoque', 'requisicoes'].includes(rota) && window.roteador) {
      window.roteador.rerenderizar();
    }
  }

  function mensagem(texto, tipo) {
    const el = janela.querySelector('#lancador-msg');
    el.textContent = texto;
    el.className = 'lancador-msg ' + (tipo || '');
  }
  function limparMensagem() { mensagem('', ''); }

  function trocarAba(nome) {
    abaAtiva = nome;
    janela.querySelectorAll('.lancador-aba').forEach((b) => {
      b.classList.toggle('ativa', b.dataset.aba === nome);
    });

    // Cada aba tem o seu documento: o campo mostra o que já estiver validado
    const ctx = contextoDaAba();
    const campo = janela.querySelector('#inv-num');
    const desc = janela.querySelector('#inv-descricao');
    if (ctx) {
      const doc = ctx.obter();
      campo.value = doc ? ctx.numeroDe(doc) : '';
      desc.value = doc ? (doc.descricao || '(sem descrição)') : '';
      mostrarEstadoDocumento('', '');
      carregarSugestoes();
    }

    renderAba();
  }

  function atualizarUnidade() {
    const el = janela && janela.querySelector('#lancador-unidade');
    if (!el) return;
    const u = (UNIDADES_DISPONIVEIS || []).find((x) => x.id === UNIDADE_SELECIONADA);
    el.textContent = u ? u.nome : '';
    // Inventário e requisição são por unidade: trocar de unidade invalida
    // o documento que estava validado.
    const desatualizado = (d) => d && d.unidade_id !== UNIDADE_SELECIONADA;
    if (desatualizado(inventarioAtivo) || desatualizado(requisicaoAtiva)) {
      inventarioAtivo = null;
      requisicaoAtiva = null;
      janela.querySelector('#inv-num').value = '';
      janela.querySelector('#inv-descricao').value = '';
      mostrarEstadoDocumento('A unidade mudou — valide o documento novamente.', 'erro');
      aplicarTrava();
      carregarSugestoes();
    }
  }

  // ---------- API pública ----------
  async function abrir() {
    if (!janela) criarJanela();
    janela.classList.add('visible');
    if (posicaoValida()) {
      janela.style.left = posicao.left + 'px';
      janela.style.top = posicao.top + 'px';
    } else {
      requestAnimationFrame(centralizar);
    }
    atualizarUnidade();
    const permitidas = abasPermitidas().map((a) => a.chave);
    if (!permitidas.includes(abaAtiva)) abaAtiva = permitidas[0];
    try {
      await carregarDados();
      trocarAba(abaAtiva);
      carregarSugestoes();
    } catch (erro) {
      janela.querySelector('#lancador-corpo').innerHTML =
        `<div class="estado-vazio">Não foi possível carregar produtos e fornecedores: ${erro.message}</div>`;
    }
  }

  function fechar() {
    if (janela) janela.classList.remove('visible');
  }

  function estaAberto() { return !!janela && janela.classList.contains('visible'); }
  function alternar() { estaAberto() ? fechar() : abrir(); }

  return { abrir, fechar, alternar, estaAberto, atualizarUnidade };
})();
