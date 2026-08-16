/* Abertura em uma viagem só (jsdom).

   O ganho é real só se DUAS coisas forem verdade ao mesmo tempo:
     · a abertura faz um pedido, não três
     · o dado adiantado é usado UMA vez, e nunca no lugar errado

   A segunda é a que assusta. Reaproveitar o painel de outra unidade ou de
   outro mês mostraria número errado com cara de certo — pior do que lento.
   Metade dos casos abaixo existe para provar que isso não acontece. */
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('/tmp/jt/node_modules/jsdom');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';

/* Mesma forma que a rota devolve de verdade. `marca` distingue de onde o
   painel veio — é o que permite provar qual caminho a tela usou. */
const kpi = (valor, extra = {}) => ({
  valor, valor_anterior: null, formato: 'MOEDA', meta: null,
  dentro_da_meta: null, variacao: null, direcao: null, serie: [],
  detalhe: null, ...extra,
});
const PAINEL = (marca) => ({
  periodo: {
    rotulo: 'Agosto/2026', data_inicio: '2026-08-03', data_fim: '2026-08-10',
    inventario_abertura: '1002', inventario_fechamento: '1003',
    encaixado_no_ciclo: true, sem_ciclo: false,
  },
  pendencias: [],
  kpis: {
    cmv_percentual: kpi(0.284, { formato: 'PERCENTUAL', meta: 0.29, dentro_da_meta: true }),
    cmv_valor: kpi(37544.98, { detalhe: marca }),
    faturamento: kpi(96500),
    perdas: kpi(812),
    estoque: kpi(12155.06),
  },
  historico: [],
  composicao: {
    comida: { cmv: 30000, cmv_percentual: 0.341, faturamento: 67600 },
    bebida: { cmv: 7544.98, cmv_percentual: 0.187, faturamento: 28900 },
  },
  top_itens: [],
  perdas: { valor_total: 812, por_motivo: [] },
  estoque: { total_itens: 244, itens_com_saldo: 58, itens_sem_custo: 187, valor_total: 12155.06 },
  estoque_parado: [],
  atividade: [],
  avisos: [],
});

function ambiente({ hash = '', lembrada = null, sessao = null } = {}) {
  const dom = new JSDOM(`<!doctype html><html><body>
    <div id="app"><select id="seletor-unidade"></select><div id="conteudo"></div></div>
    </body></html>`, { url: 'http://localhost:8095/' + hash, runScripts: 'outside-only' });
  const w = dom.window;
  const pedidos = [];
  w.requestAnimationFrame = (f) => setTimeout(f, 0);
  w.getToken = () => 'token-de-teste';
  w.limparToken = () => {};
  w.setToken = () => {};
  w.mostrarApp = () => {};
  w.mostrarTelaLogin = () => {};
  w.roteador = { rerenderizar() {}, iniciar() {} };
  w.icone = (n) => `<svg data-i="${n}"></svg>`;
  w.Chart = undefined;
  w.localStorage.clear();
  if (lembrada) w.localStorage.setItem('solo_cmv_unidade', lembrada);

  w.api = {
    async get(url) {
      pedidos.push(url);
      if (url.startsWith('/sessao')) {
        return sessao || {
          usuario: { id: 1, nome: 'Jefferson', papel: 'DIRETOR' },
          escopo: {
            unidades: [{ id: 1, nome: 'Josefina' }, { id: 2, nome: 'Casa Josefina' }],
            regional: true, papel: 'DIRETOR', irrestrito: true,
          },
          unidade: 1,
          painel: url.includes('com_painel') ? PAINEL('adiantado') : null,
        };
      }
      if (url === '/unidades/escopo') {
        return { unidades: [{ id: 1, nome: 'Josefina' }, { id: 2, nome: 'Casa Josefina' }],
                 regional: true, papel: 'DIRETOR', irrestrito: true };
      }
      if (url.startsWith('/dashboard/painel')) return PAINEL('do-servidor');
      return [];
    },
    async post() { return { access_token: 'x' }; },
  };
  return { w, pedidos };
}

const carregar = (w, arquivos) =>
  arquivos.forEach((f) => w.eval(fs.readFileSync(path.join(BASE, 'js', f), 'utf8')));

(async () => {
  const falhas = [];
  const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

  console.log('\n[1] A ABERTURA FAZ UM PEDIDO, NÃO TRÊS');
  const a = ambiente({ lembrada: '1' });
  carregar(a.w, ['auth.js']);
  await a.w.carregarSessaoExistente();
  await a.w.carregarUnidades();
  carregar(a.w, ['pages/dashboard.js']);
  a.w.UNIDADE_SELECIONADA = 1;
  await a.w.Paginas.dashboard.render(a.w.document.getElementById('conteudo'));
  await new Promise((r) => setTimeout(r, 60));

  console.log('     pedidos:', a.pedidos.join(' | ') || '(nenhum)');
  ok(a.pedidos.length === 1, `um pedido para abrir a tela (foram ${a.pedidos.length})`);
  ok(a.pedidos[0].startsWith('/sessao'), 'e é a rota de abertura');
  ok(!a.pedidos.some((p) => p.startsWith('/auth/me')), '/auth/me não é mais chamado à parte');
  ok(!a.pedidos.some((p) => p === '/unidades/escopo'), '/unidades/escopo veio junto');
  ok(!a.pedidos.some((p) => p.startsWith('/dashboard/painel')), 'o painel veio junto');

  console.log('\n[2] A UNIDADE LEMBRADA VIAJA COMO "preferida", NUNCA "unidade_id"');
  ok(/[?&]preferida=1\b/.test(a.pedidos[0]), 'manda a unidade lembrada como preferência');
  ok(!/unidade_id=/.test(a.pedidos[0]),
     'não usa unidade_id — o guarda devolveria 403 e trancaria a pessoa fora');

  console.log('\n[3] O DADO ADIANTADO É USADO UMA VEZ SÓ');
  const alvo = a.w.document.getElementById('conteudo');
  ok(/adiantado/.test(alvo.textContent), 'a tela pintou com o dado que veio na abertura');
  ok(a.w.ABERTURA.painel === null, 'o adiantamento foi descartado depois de usado');
  ok(a.w.ABERTURA.escopo === null, 'o escopo também');

  await a.w.Paginas.dashboard.render(alvo);
  await new Promise((r) => setTimeout(r, 60));
  ok(a.pedidos.some((p) => p.startsWith('/dashboard/painel')),
     'a segunda pintura busca do servidor — dado velho não se repete');
  ok(/do-servidor/.test(alvo.textContent), 'e mostra o que o servidor devolveu agora');

  console.log('\n[4] NÃO REAPROVEITA O PAINEL DE OUTRA UNIDADE');
  const b = ambiente({ lembrada: '1' });
  carregar(b.w, ['auth.js']);
  await b.w.carregarSessaoExistente();
  await b.w.carregarUnidades();
  carregar(b.w, ['pages/dashboard.js']);
  b.w.UNIDADE_SELECIONADA = 2;              // trocou de loja antes de pintar
  const alvoB = b.w.document.getElementById('conteudo');
  await b.w.Paginas.dashboard.render(alvoB);
  await new Promise((r) => setTimeout(r, 60));
  ok(b.pedidos.some((p) => p.startsWith('/dashboard/painel')),
     'unidade diferente da adiantada obriga a buscar de novo');
  ok(/unidade_id=2/.test(b.pedidos.join(' ')), 'e pede a unidade certa');
  ok(!/adiantado/.test(alvoB.textContent),
     'o número da outra loja não vai para a tela');

  console.log('\n[5] ENTRANDO DIRETO EM OUTRA PÁGINA, NÃO PEDE O PAINEL');
  const c = ambiente({ hash: '#estoque', lembrada: '1' });
  carregar(c.w, ['auth.js']);
  await c.w.carregarSessaoExistente();
  ok(!/com_painel/.test(c.pedidos[0]),
     'sem com_painel: o servidor não calcula um painel que ninguém vai ver');

  console.log('\n[6] PREFERÊNCIA INVÁLIDA NÃO TRANCA NINGUÉM DO LADO DE FORA');
  const d = ambiente({
    lembrada: '99',
    sessao: {
      usuario: { id: 2, nome: 'Contador', papel: 'OPERADOR' },
      escopo: { unidades: [{ id: 2, nome: 'Casa Josefina' }], regional: false,
                papel: 'OPERADOR', irrestrito: false },
      unidade: 2,          // o servidor ignorou a preferência e escolheu por ele
      painel: PAINEL('adiantado'),
    },
  });
  carregar(d.w, ['auth.js']);
  const entrou = await d.w.carregarSessaoExistente();
  await d.w.carregarUnidades();
  ok(entrou === true, 'a sessão abre mesmo com unidade lembrada que não existe mais');
  ok(d.w.UNIDADE_SELECIONADA === 2, `caiu na unidade permitida (${d.w.UNIDADE_SELECIONADA})`);
  const opcoes = [...d.w.document.getElementById('seletor-unidade').options].map((o) => o.value);
  ok(!opcoes.includes('REGIONAL'), 'e sem acesso regional a opção não aparece');

  console.log('\n[7] SEM TOKEN, NEM TENTA');
  const e = ambiente();
  e.w.getToken = () => null;
  carregar(e.w, ['auth.js']);
  e.w.getToken = () => null;
  const semToken = await e.w.carregarSessaoExistente();
  ok(semToken === false && e.pedidos.length === 0,
     'sem token não há pedido nenhum');

  console.log('\n' + (falhas.length ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
  process.exit(falhas.length ? 1 : 0);
})();
