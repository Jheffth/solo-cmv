/* A tela de quem não vê dinheiro (jsdom).

   O QUE ESTA SUÍTE PROTEGE
   O menu e as abas do Lançador filtravam por PAPEL, numa lista escrita em
   JavaScript — uma segunda régua, paralela à do backend e nunca testada
   contra ela. As duas concordavam até o dia em que uma mudasse, e a que muda
   por último é sempre a do navegador, porque quem mexe em permissão mexe no
   servidor.

   Agora as duas leem a mesma lista, que vem em /sessao. O teste abaixo
   monta um operador e um gerente e confere o que cada um enxerga — e, mais
   importante, que a tela NÃO decide nada sozinha: ela desenha o que chegou.
*/
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('/tmp/jt/node_modules/jsdom');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';

// As capacidades do Operador, exatamente como servicos/permissoes.py devolve
const CAP_OPERADOR = ['CONTAR', 'LANCAR_COMPRA', 'LANCAR_PERDA',
                      'ABRIR_REQUISICAO', 'CADASTRAR'];
const CAP_GERENTE = CAP_OPERADOR.concat([
  'VER_DINHEIRO', 'VER_CMV', 'VER_FATURAMENTO', 'LANCAR_FATURAMENTO',
  'CONFIGURAR_CMV', 'ABRIR_INVENTARIO', 'CONGELAR_INVENTARIO',
  'FINALIZAR_INVENTARIO', 'ESTORNAR_PERDA', 'ATENDER_REQUISICAO',
  'ADMINISTRAR_ACESSO']);

const PAINEL_OPERACIONAL = {
  operacional: true,
  periodo: { rotulo: 'agosto/2026' },
  tarefas: [
    { chave: 'contagem', rota: 'inventario', id: 5, titulo: 'Inventário 03',
      detalhe: '38 de 42 itens sem contagem', gravidade: 'atencao', quantidade: 38 },
    { chave: 'requisicao', rota: 'requisicoes', id: 7, titulo: 'Requisição REQ-07',
      detalhe: 'aberta — inicie para lançar itens', gravidade: 'atencao', quantidade: null },
  ],
  aguardando_congelamento: [{ numero: '05', dias: 2 }],
};

const ESTOQUE_SEM_VALORES = {
  regional: false, escopo: 'Josefina', com_valores: false,
  itens: [
    { produto_id: 1, codigo: '111008', nome: 'Batata Doce', unidade_medida: 'Kg',
      categoria_id: 1, categoria: 'Hortifruti', quantidade: 165.2,
      ultima_contagem: '2026-08-10', unidade_id: 1, unidade_nome: 'Josefina' },
  ],
  por_unidade: [{ unidade_id: 1, unidade: 'Josefina', itens_com_saldo: 58 }],
  resumo: { total_itens: 244, itens_com_saldo: 58, itens_zerados: 186, unidades: 1 },
};

function janela(capacidades, veDinheiro) {
  // app.js liga ouvintes na carga; sem estes nós ele estoura antes de
  // chegar no menu, que é o que se quer testar.
  const dom = new JSDOM(
    `<!doctype html><html><body>
       <aside id="sidebar"><div id="sidebar-user">
         <img id="sidebar-avatar"><span id="nome-usuario"></span>
         <span id="badge-papel"></span>
       </div></aside>
       <div id="menu-lateral"></div><div id="menu-overlay"></div>
       <button id="btn-menu"></button><button id="btn-logout"></button>
       <form id="form-login">
         <input id="input-login"><input id="input-senha">
         <div id="login-erro"></div>
       </form>
       <div id="conteudo"></div>
     </body></html>`,
    { url: 'http://localhost:8095/', runScripts: 'outside-only' });
  const w = dom.window;
  w.CAPACIDADES = new Set(capacidades);
  w.VE_DINHEIRO = veDinheiro;
  w.pode = (c) => w.CAPACIDADES.has(c);
  w.icone = (n) => `<svg data-i="${n}"></svg>`;
  w.roteador = { rerenderizar() {}, iniciar() {} };
  w.UNIDADE_SELECIONADA = 1;
  // app.js espera auth.js já carregado. Só o mínimo para ele ligar os
  // ouvintes sem estourar — o alvo do teste é o menu.
  w.fazerLogout = () => {};
  w.tentarLogin = async () => {};
  w.carregarSessaoExistente = async () => true;
  w.mostrarTelaLogin = () => {};
  w.mostrarApp = () => {};
  w.carregarUnidades = async () => {};
  w.USUARIO_ATUAL = { nome: 'Teste', papel: 'OPERADOR' };
  // jsdom não tem rAF; o Lançador usa para centralizar a janela.
  w.requestAnimationFrame = (fn) => setTimeout(fn, 0);
  w.UNIDADES_DISPONIVEIS = [{ id: 1, nome: 'Josefina' }];
  w.emRegional = () => false;
  w.api = { async get() { return []; }, async post() { return {}; } };
  return dom;
}

(async () => {
  const falhas = [];
  const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

  // ==========================================================================
  console.log('\n[1] O MENU SE MONTA PELA CAPACIDADE, NÃO PELO PAPEL');
  // ==========================================================================
  function menuDe(caps) {
    const dom = janela(caps, caps.includes('VER_DINHEIRO'));
    dom.window.eval(fs.readFileSync(path.join(BASE, 'js/app.js'), 'utf8'));
    dom.window.montarMenuLateral();
    return [...dom.window.document.querySelectorAll('.nav-item')]
      .map((b) => b.dataset.pagina);
  }

  const menuOpe = menuDe(CAP_OPERADOR);
  const menuGer = menuDe(CAP_GERENTE);

  for (const escondido of ['cmv', 'relatorios', 'vendas', 'metas', 'unidades', 'equipe']) {
    ok(!menuOpe.includes(escondido), `operador não vê "${escondido}" no menu`);
  }
  for (const visivel of ['dashboard', 'lancador', 'estoque', 'inventario', 'requisicoes']) {
    ok(menuOpe.includes(visivel), `mas vê "${visivel}" — o trabalho dele`);
  }
  ok(menuGer.includes('cmv') && menuGer.includes('relatorios')
     && menuGer.includes('vendas'),
     'o gerente vê CMV, relatórios e faturamento');
  ok(!menuGer.includes('metas'),
     'e ainda assim não vê Metas — é da diretoria, não de quem vê dinheiro');

  // Nenhum item do menu pode filtrar por papel: seria a régua duplicada
  // voltando pela porta dos fundos.
  const dom0 = janela(CAP_GERENTE, true);
  dom0.window.eval(fs.readFileSync(path.join(BASE, 'js/app.js'), 'utf8'));
  const comPapeis = dom0.window.NAV_ITEMS.filter((i) => i.papeis);
  ok(comPapeis.length === 0,
     `nenhum item do menu filtra por papel (${comPapeis.map((i) => i.chave)})`);

  // ==========================================================================
  console.log('\n[2] O LANÇADOR ESCONDE A ABA DE VENDAS');
  // ==========================================================================
  // Sem gancho exposto para as abas, conferimos pelo HTML montado na abertura
  const domL = janela(CAP_OPERADOR, false);
  domL.window.eval(fs.readFileSync(path.join(BASE, 'js/lancador.js'), 'utf8'));
  domL.window.Lancador.abrir();
  await new Promise((r) => setTimeout(r, 30));
  const abasOpe = [...domL.window.document.querySelectorAll('.lancador-aba')]
    .map((b) => b.dataset.aba);
  ok(abasOpe.includes('inventario') && abasOpe.includes('perda')
     && abasOpe.includes('requisicao'),
     `operador lança contagem, perda e requisição (${abasOpe.join(', ')})`);
  ok(!abasOpe.includes('vendas'), 'e não tem a aba de Vendas');

  const domLG = janela(CAP_GERENTE, true);
  domLG.window.eval(fs.readFileSync(path.join(BASE, 'js/lancador.js'), 'utf8'));
  domLG.window.Lancador.abrir();
  await new Promise((r) => setTimeout(r, 30));
  const abasGer = [...domLG.window.document.querySelectorAll('.lancador-aba')]
    .map((b) => b.dataset.aba);
  ok(abasGer.includes('vendas'), 'que o gerente tem');

  // ==========================================================================
  console.log('\n[3] A TELA INICIAL DELE É A FILA DE TRABALHO');
  // ==========================================================================
  const domP = janela(CAP_OPERADOR, false);
  domP.window.api = { async get() { return PAINEL_OPERACIONAL; } };
  domP.window.eval(fs.readFileSync(path.join(BASE, 'js/pages/dashboard.js'), 'utf8'));
  const alvo = domP.window.document.getElementById('conteudo');
  await domP.window.Paginas.dashboard.render(alvo);
  await new Promise((r) => setTimeout(r, 60));

  const cartoes = [...alvo.querySelectorAll('.cartao-tarefa')];
  ok(cartoes.length === 2, `duas tarefas esperando por ele (${cartoes.length})`);
  ok(/Inventário 03/.test(cartoes[0].textContent)
     && /38 de 42/.test(cartoes[0].textContent),
     'o cartão diz quanto falta, não só que existe');
  ok(cartoes[0].dataset.rota === 'inventario',
     'e leva direto ao lugar de fazer');
  ok(!alvo.querySelector('.kpi-card'), 'sem KPIs de CMV');
  ok(!/R\$/.test(alvo.textContent), 'e sem um único R$ na tela');

  ok(/ainda não congelado/.test(alvo.textContent),
     'o inventário 05 aparece com o motivo de não dar para contar');
  ok(/gerente/.test(alvo.textContent),
     'dizendo de quem depende — senão parece defeito do sistema');

  // ==========================================================================
  console.log('\n[4] O ESTOQUE PERDE AS COLUNAS DE R$, NÃO O SALDO');
  // ==========================================================================
  const domE = janela(CAP_OPERADOR, false);
  domE.window.api = {
    async get(url) {
      if (url.startsWith('/categorias')) return [{ id: 1, nome: 'Hortifruti' }];
      return ESTOQUE_SEM_VALORES;
    },
  };
  domE.window.emRegional = () => false;
  domE.window.eval(fs.readFileSync(path.join(BASE, 'js/pages/estoque.js'), 'utf8'));
  const alvoE = domE.window.document.getElementById('conteudo');
  await domE.window.Paginas.estoque.render(alvoE);
  await new Promise((r) => setTimeout(r, 60));

  const cabecalhos = [...alvoE.querySelectorAll('thead th')].map((t) => t.textContent.trim());
  ok(!cabecalhos.includes('Último custo'), `sem coluna de custo (${cabecalhos.join(' | ')})`);
  ok(!cabecalhos.includes('Valor em estoque'), 'sem coluna de valor');
  ok(cabecalhos.includes('Estoque'), 'mas com a coluna de saldo');
  ok(/165,2/.test(alvoE.textContent), 'e o saldo do item aparece');
  ok(!/R\$/.test(alvoE.textContent), 'nenhum R$ sobrou na tela');

  // O cartão de valor SOME. Virar "R$ 0,00" seria pior que esconder: zero
  // é uma afirmação, e uma afirmação falsa.
  const cartaoValor = alvoE.querySelector('#kpi-valor');
  const blocoValor = cartaoValor && (cartaoValor.closest('.kpi') || cartaoValor.parentElement);
  ok(!blocoValor || blocoValor.style.display === 'none',
     'o cartão de valor total some em vez de mostrar R$ 0,00');

  console.log('\n' + (falhas.length
    ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
  process.exit(falhas.length ? 1 : 0);
})();
