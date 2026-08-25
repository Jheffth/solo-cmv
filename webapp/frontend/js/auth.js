/* Login, sessão e usuário atual.

   ESTADO COMPARTILHADO VAI EM `window`, NÃO EM `let`
   --------------------------------------------------
   `let X` no topo de um script cria um binding no escopo léxico global,
   que NÃO é acessível como `window.X`. Os outros scripts leem o
   identificador solto e funcionam, mas qualquer código que precise
   alcançar o estado por referência (teste, futuro módulo, console) não
   enxerga nada. Declarando em `window` os dois caminhos funcionam. */
window.USUARIO_ATUAL = null;

/* Preenchidas pela abertura (/sessao). Vazias até lá, e o `pode()` abaixo
   trata isso negando: antes de saber, não se mostra. Um menu que aparece
   completo e encolhe meio segundo depois ensina a não confiar na tela. */
window.CAPACIDADES = new Set();
window.VE_DINHEIRO = true;

/* A pergunta única do frontend sobre permissão. */
window.pode = function (capacidade) {
  return window.CAPACIDADES.has(capacidade);
};
window.UNIDADES_DISPONIVEIS = [];
window.UNIDADE_SELECIONADA = null;

function mostrarTelaLogin() {
  document.getElementById('app').hidden = true;
  document.getElementById('tela-login').hidden = false;
  USUARIO_ATUAL = null;
}

function mostrarApp() {
  document.getElementById('tela-login').hidden = true;
  document.getElementById('app').hidden = false;
}

async function tentarLogin(login, senha) {
  const resposta = await api.post('/auth/login', { login, senha });
  setToken(resposta.access_token);
  // Mesma rota de abertura usada quando já há sessão: quem acabou de entrar
  // não deve esperar mais viagens do que quem só atualizou a página.
  await carregarSessaoExistente();
  return USUARIO_ATUAL;
}

/* O que a rota /sessao já trouxe, para as etapas seguintes não pedirem de
   novo. Cada campo é consumido uma vez e apagado: é adiantamento da
   abertura, não cache — a segunda vez que a tela precisar do dado, ele tem
   que vir fresco do servidor. */
window.ABERTURA = { escopo: null, painel: null, unidade: null };

/* Abre o sistema numa viagem só.

   Eram três pedidos em fila — /auth/me, /unidades/escopo e
   /dashboard/painel — e cada um custa ~250 ms de distância até o servidor,
   medidos. O trabalho do servidor é o mesmo; o que se economiza são duas
   idas e voltas antes de a tela aparecer.

   A unidade lembrada vai como `preferida` (e não `unidade_id`): se a pessoa
   perdeu o acesso àquela loja, o servidor ignora e abre na primeira
   permitida, em vez de recusar a abertura inteira. */
async function carregarSessaoExistente() {
  if (!getToken()) return false;
  try {
    const params = new URLSearchParams();
    const lembrada = localStorage.getItem(CHAVE_UNIDADE);
    if (lembrada) params.set('preferida', lembrada);

    // Só vale trazer o painel se for o painel que vai abrir. Entrando
    // direto em #estoque, seria trabalho do servidor jogado fora.
    const destino = (location.hash || '').replace('#', '').split('/')[0];
    if (!destino || destino === 'dashboard') params.set('com_painel', 'true');

    const dados = await api.get('/sessao?' + params.toString());
    USUARIO_ATUAL = dados.usuario;
    // O que esta pessoa pode fazer, dito pelo servidor. O menu se monta
    // daqui em vez de repetir a régua em JavaScript — cópia da regra é
    // regra que diverge, e a do navegador é a que mente primeiro porque
    // ninguém a testa.
    window.CAPACIDADES = new Set(dados.capacidades || []);
    window.VE_DINHEIRO = dados.ve_dinheiro !== false;
    ABERTURA.escopo = dados.escopo;
    ABERTURA.painel = dados.painel;
    ABERTURA.unidade = dados.unidade;
    return true;
  } catch (e) {
    limparToken();
    return false;
  }
}

function fazerLogout() {
  limparToken();
  mostrarTelaLogin();
}

const CHAVE_UNIDADE = 'solo_cmv_unidade';

/* Sentinela da visão consolidada. Viaja no mesmo parâmetro das unidades,
   mas é permissão à parte: ver duas lojas não dá acesso ao número da rede. */
window.REGIONAL = 'REGIONAL';
window.ACESSO_REGIONAL = false;

/* Na Regional NÃO SE OPERA — mas se CONSULTA tudo.

   Estoque, Movimentações, Inventários e Requisições existem na Regional
   como histórico consolidado das lojas, com coluna de unidade. O que não
   existe é o ato: lançar compra, abrir inventário, atender requisição.
   Essas ações pertencem a uma loja específica.

   Por isso só ficam de fora as telas que são puramente de ação. */
window.PAGINAS_SEM_REGIONAL = new Set([
  'lancador', 'vendas',
]);

/* Telas que existem na Regional em modo consulta: os botões de ação somem
   e uma coluna de unidade aparece. */
window.PAGINAS_REGIONAL_SOMENTE_LEITURA = new Set([
  'estoque', 'movimentos', 'inventario', 'requisicoes',
]);

/* Declaração de função, não `const`: assim fica acessível como
   window.emRegional para as outras telas, e não só como identificador
   solto no escopo léxico do script. */
function emRegional() {
  return String(UNIDADE_SELECIONADA) === REGIONAL;
}

function nomeDoEscopo() {
  if (emRegional()) return 'Regional';
  const u = UNIDADES_DISPONIVEIS.find((x) => String(x.id) === String(UNIDADE_SELECIONADA));
  return u ? u.nome : '—';
}

async function carregarUnidades() {
  // O backend decide o que este usuário enxerga; a tela só desenha.
  // Na abertura o escopo já veio junto com a sessão; depois disso, e em
  // qualquer recarga do seletor, vem da rota própria.
  let escopo = ABERTURA.escopo;
  ABERTURA.escopo = null;
  if (!escopo) escopo = await api.get('/unidades/escopo');
  UNIDADES_DISPONIVEIS = escopo.unidades;
  ACESSO_REGIONAL = !!escopo.regional;

  if (!UNIDADE_SELECIONADA) {
    // Lembra o último recorte usado. Sem isso o sistema abre sempre na
    // primeira unidade em ordem alfabética, que pode não ser a que a
    // pessoa trabalha — e os dados "somem" da tela sem explicação.
    const salvo = localStorage.getItem(CHAVE_UNIDADE);
    const valido = salvo === REGIONAL
      ? ACESSO_REGIONAL
      : UNIDADES_DISPONIVEIS.some((u) => String(u.id) === String(salvo));
    if (valido) {
      UNIDADE_SELECIONADA = salvo === REGIONAL ? REGIONAL : parseInt(salvo, 10);
    } else if (UNIDADES_DISPONIVEIS.length) {
      UNIDADE_SELECIONADA = UNIDADES_DISPONIVEIS[0].id;
    }
  }

  const seletor = document.getElementById('seletor-unidade');
  const opcoes = UNIDADES_DISPONIVEIS
    .map((u) => `<option value="${u.id}">${u.nome}</option>`);
  if (ACESSO_REGIONAL && UNIDADES_DISPONIVEIS.length > 1) {
    opcoes.push(`<option value="${REGIONAL}">Regional · todas as unidades</option>`);
  }
  seletor.innerHTML = opcoes.join('');
  seletor.value = UNIDADE_SELECIONADA;
  seletor.classList.toggle('regional', emRegional());

  seletor.onchange = () => {
    const valor = seletor.value;
    UNIDADE_SELECIONADA = valor === REGIONAL ? REGIONAL : parseInt(valor, 10);
    localStorage.setItem(CHAVE_UNIDADE, UNIDADE_SELECIONADA);
    seletor.classList.toggle('regional', emRegional());

    // Sair de uma tela operacional para a Regional levaria a um branco;
    // leva ao Painel, que é o lugar onde a Regional faz sentido.
    const atual = (location.hash || '').replace('#', '').split('/')[0];
    if (emRegional() && PAGINAS_SEM_REGIONAL.has(atual)) {
      location.hash = 'dashboard';
      return;
    }
    if (window.roteador) window.roteador.rerenderizar();
    // O Lançador fica aberto por cima; atualiza a unidade mostrada nele
    if (window.Lancador) window.Lancador.atualizarUnidade();
  };
}
