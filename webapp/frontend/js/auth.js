/* Login, sessão e usuário atual.

   ESTADO COMPARTILHADO VAI EM `window`, NÃO EM `let`
   --------------------------------------------------
   `let X` no topo de um script cria um binding no escopo léxico global,
   que NÃO é acessível como `window.X`. Os outros scripts leem o
   identificador solto e funcionam, mas qualquer código que precise
   alcançar o estado por referência (teste, futuro módulo, console) não
   enxerga nada. Declarando em `window` os dois caminhos funcionam. */
window.USUARIO_ATUAL = null;
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
  USUARIO_ATUAL = await api.get('/auth/me');
  return USUARIO_ATUAL;
}

async function carregarSessaoExistente() {
  if (!getToken()) return false;
  try {
    USUARIO_ATUAL = await api.get('/auth/me');
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
  const escopo = await api.get('/unidades/escopo');
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
