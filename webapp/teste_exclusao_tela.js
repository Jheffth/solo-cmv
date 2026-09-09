/* A seleção que tira lançamento do estoque (jsdom).

   O QUE ESTA SUÍTE PROTEGE
   Esta é a única tela do sistema onde um clique apaga número de estoque e de
   CMV. Três coisas precisam continuar verdadeiras, e nenhuma delas é óbvia
   olhando o código:

     1. A caixinha só existe para quem o SERVIDOR disse que pode. Não há
        conferência de papel escrita aqui — se houvesse, seria uma segunda
        régua de permissão, e as duas concordariam até o dia em que uma
        mudasse.

     2. A linha que o servidor marcou como travada não pode ser selecionada,
        e o motivo dele fica à vista. "Selecionar todos" respeita a trava —
        senão marcaria o travado só para o lote inteiro ser recusado depois,
        que é uma armadilha com cara de atalho.

     3. A confirmação NOMEIA o que vai sair. "Excluir 3 lançamentos?" não é
        uma pergunta que alguém consiga responder; é um pedido de coragem.
*/
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('/tmp/jt/node_modules/jsdom');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';

const PRODUTOS = [
  { id: 1, nome: 'Batata Doce', codigo: '111008' },
  { id: 2, nome: 'Costela bovina', codigo: '222001' },
];
const FORNECEDORES = [{ id: 3, nome: 'SUINOAVES ALIMENTOS LTDA' }];

// Como o servidor devolve: `travado_para_excluir` já vem calculado pela
// MESMA função que recusa no POST.
const MOVIMENTOS = [
  { id: 10, unidade_id: 1, produto_id: 1, tipo: 'COMPRA', quantidade: 10,
    custo_unitario: 12.99, custo_total: 129.9, fornecedor_id: 3,
    documento: 'NF 427795', numero_documento: 'NF 427795', data: '2026-09-08',
    travado_para_excluir: null },
  { id: 11, unidade_id: 1, produto_id: 2, tipo: 'COMPRA', quantidade: 15.1,
    custo_unitario: 30.99, custo_total: 467.95, fornecedor_id: 3,
    documento: 'NF 427795', numero_documento: 'NF 427795', data: '2026-09-08',
    travado_para_excluir: null },
  { id: 12, unidade_id: 1, produto_id: 1, tipo: 'CONTAGEM_FINAL', quantidade: 4,
    custo_unitario: null, custo_total: null, documento: 'INV-03',
    data: '2026-09-01',
    travado_para_excluir: 'Este é o ajuste de um inventário. Apagar a linha '
      + 'deixaria o inventário fechado apontando um número que o estoque não '
      + 'tem — desfaça pelo inventário.' },
];

function janela(capacidades) {
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="conteudo"></div></body></html>',
    { url: 'http://localhost:8095/', runScripts: 'outside-only' });
  const w = dom.window;
  const pedidos = [];
  const perguntas = [];
  w.CAPACIDADES = new Set(capacidades);
  w.pode = (c) => w.CAPACIDADES.has(c);
  w.icone = (n) => `<svg data-i="${n}"></svg>`;
  w.UNIDADE_SELECIONADA = 1;
  w.emRegional = () => false;
  /* O sistema não usa mais as caixas do navegador: o Antigravity as trocou
     por `window.Dialogo`, que devolve promessa. O dublê responde igual — e
     `prompt` distingue null (cancelou) de não-definido (sem resposta
     combinada), porque cancelar no meio é justamente um dos casos. */
  w.Dialogo = {
    async confirm(texto) { perguntas.push(texto); return w.RESPOSTA !== false; },
    async prompt(texto) {
      perguntas.push(texto);
      return w.MOTIVO === undefined ? 'engano' : w.MOTIVO;
    },
    async alert(texto) { perguntas.push(texto); },
  };
  w.RESPOSTA = true;
  w.api = {
    async get(url) {
      pedidos.push(['GET', url]);
      if (url.startsWith('/produtos')) return PRODUTOS;
      if (url.startsWith('/fornecedores')) return FORNECEDORES;
      if (url.startsWith('/movimentos')) return w.LISTA || MOVIMENTOS;
      return [];
    },
    async post(url, corpo) {
      pedidos.push(['POST', url, corpo]);
      return { excluidos: (corpo.ids || []).length,
               avisos: ['A nota 427795 saiu inteira do estoque.'] };
    },
  };
  dom.window.eval(fs.readFileSync(
    path.join(BASE, 'js/pages/movimentos.js'), 'utf8'));
  return { dom, w, pedidos, perguntas,
           alvo: w.document.getElementById('conteudo') };
}

const espera = (ms = 30) => new Promise((r) => setTimeout(r, ms));

(async () => {
  const falhas = [];
  const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

  // ==========================================================================
  console.log('\n[1] A CAIXINHA É UMA PERMISSÃO DO SERVIDOR');
  // ==========================================================================
  const semPoder = janela(['LANCAR_COMPRA', 'VER_DINHEIRO', 'VER_CMV']);
  await semPoder.w.Paginas.movimentos.render(semPoder.alvo);
  await espera();
  ok(semPoder.alvo.querySelectorAll('.mov-marca').length === 0,
     'sem a capacidade, não existe caixinha nenhuma na tabela');
  ok(!semPoder.alvo.querySelector('#mov-acoes'),
     'nem a barra de excluir');
  ok(semPoder.alvo.querySelectorAll('tbody tr').length === 3,
     'e a tela continua servindo para consultar (3 linhas)');

  const t = janela(['EXCLUIR_MOVIMENTO', 'ANULAR_NOTA', 'VER_DINHEIRO']);
  await t.w.Paginas.movimentos.render(t.alvo);
  await espera();
  const caixas = t.alvo.querySelectorAll('.mov-marca');
  ok(caixas.length === 3, `com a capacidade, cada linha ganha a caixinha (${caixas.length})`);

  // ==========================================================================
  console.log('\n[2] O QUE O SERVIDOR TRAVOU, A TELA NÃO OFERECE');
  // ==========================================================================
  const daContagem = [...caixas].find((c) => c.dataset.id === '12');
  ok(daContagem && daContagem.disabled,
     'a linha do ajuste de inventário não pode ser marcada');
  ok(daContagem && /desfaça pelo inventário/.test(daContagem.title),
     'e o motivo do servidor está no title, palavra por palavra');
  ok([...caixas].filter((c) => !c.disabled).length === 2,
     'as duas compras continuam selecionáveis');

  // "Selecionar todos" que marcasse o travado só para o lote ser recusado
  // depois seria uma armadilha com cara de atalho.
  const todos = t.alvo.querySelector('#mov-todos');
  todos.checked = true;
  todos.dispatchEvent(new t.w.Event('change'));
  await espera(10);
  const marcadas = [...t.alvo.querySelectorAll('.mov-marca')].filter((c) => c.checked);
  ok(marcadas.length === 2,
     `"todos" marca só os que podem (${marcadas.length} de 3)`);
  ok(t.alvo.querySelector('#mov-selecionados').textContent === '2 selecionado(s)',
     'e o contador diz quantos são');
  ok(!t.alvo.querySelector('#mov-acoes').hidden,
     'a barra de ação aparece só agora, com algo marcado');

  // ==========================================================================
  console.log('\n[3] A CONFIRMAÇÃO NOMEIA O QUE VAI SAIR');
  // ==========================================================================
  t.w.MOTIVO = 'lançado em duplicidade';
  t.alvo.querySelector('#mov-excluir').click();
  await espera(60);

  const pergunta = t.perguntas[0] || '';
  ok(/Batata Doce/.test(pergunta) && /Costela bovina/.test(pergunta),
     'a confirmação lista os produtos, não só a quantidade de linhas');
  ok(/597,85/.test(pergunta),
     `com o total em R$ que sai do estoque (${(pergunta.match(/Total: [^\n]+/) || [''])[0]})`);
  ok(/CMV/.test(pergunta),
     'e avisa que o CMV do período muda — quem só queria "arrumar a lista" precisa saber');
  ok(/NF 427795/.test(pergunta),
     'dizendo qual nota volta a poder ser lançada');
  ok(/quem excluiu/.test(pergunta),
     'e que fica registrado quem excluiu');

  const enviado = t.pedidos.find((p) => p[1] === '/movimentos/excluir');
  ok(!!enviado, 'só depois de confirmar é que o pedido sai');
  ok(enviado && enviado[2].ids.length === 2
     && !enviado[2].ids.includes(12),
     `e vão só os selecionáveis (${enviado && enviado[2].ids})`);
  ok(enviado && enviado[2].motivo === 'lançado em duplicidade',
     'com o motivo digitado junto');

  // ==========================================================================
  console.log('\n[4] DESISTIR NO MEIO NÃO EXCLUI NADA');
  // ==========================================================================
  const d = janela(['EXCLUIR_MOVIMENTO', 'VER_DINHEIRO']);
  await d.w.Paginas.movimentos.render(d.alvo);
  await espera();
  d.alvo.querySelector('.mov-marca').click();
  d.alvo.querySelector('.mov-marca').dispatchEvent(new d.w.Event('change'));
  await espera(10);
  d.w.RESPOSTA = false;                       // diz "não" na confirmação
  d.alvo.querySelector('#mov-excluir').click();
  await espera(40);
  ok(!d.pedidos.some((p) => p[1] === '/movimentos/excluir'),
     'dizendo não na confirmação, nenhum pedido é enviado');

  d.w.RESPOSTA = true;
  d.w.MOTIVO = null;                          // cancela na hora do motivo
  d.alvo.querySelector('#mov-excluir').click();
  await espera(40);
  ok(!d.pedidos.some((p) => p[1] === '/movimentos/excluir'),
     'e cancelando na pergunta do motivo, também não');

  console.log('\n' + (falhas.length
    ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
  process.exit(falhas.length ? 1 : 0);
})();
