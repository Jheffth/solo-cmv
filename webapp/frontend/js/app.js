/* Bootstrap da aplicação: monta o menu lateral, liga os formulários e decide
   se mostra a tela de login ou o painel, ao carregar a página. */
window.NAV_ITEMS = [
  { chave: 'dashboard',   rotulo: 'Painel',              icone: 'dashboard',   emBreve: false },
  // "acao" em vez de rota: abre a janela flutuante do Lançador, sem trocar de página
  { chave: 'lancador',    rotulo: 'Lançador',            icone: 'lancador',    emBreve: false, acao: 'abrirLancador' },
  // Produtos e Categorias ficam em abas dentro desta entrada
  { chave: 'cadastros',   rotulo: 'Cadastros',            icone: 'cadastros',   emBreve: false },
  // Fornecedores tem entrada própria: é a origem de toda compra
  { chave: 'fornecedores', rotulo: 'Fornecedores',        icone: 'fornecedores', emBreve: false },
  { chave: 'estoque',     rotulo: 'Estoque',              icone: 'estoque',     emBreve: false },
  { chave: 'movimentos',  rotulo: 'Movimentações',        icone: 'movimentos',  emBreve: false },
  { chave: 'inventario',  rotulo: 'Inventários',          icone: 'inventario',  emBreve: false },
  { chave: 'requisicoes', rotulo: 'Requisições',          icone: 'requisicoes', emBreve: false },
  { chave: 'vendas',      rotulo: 'Faturamento por Período', icone: 'vendas',   emBreve: false },
  { chave: 'cmv',         rotulo: 'Motor de CMV',         icone: 'cmv',         emBreve: false },
  // Quem define o alvo é a diretoria; os demais papéis veem a meta nas telas
  { chave: 'metas',       rotulo: 'Metas',                icone: 'metas',       emBreve: false, papeis: ['ARQUITETO', 'DIRETOR'] },
  { chave: 'relatorios',  rotulo: 'Relatórios',           icone: 'relatorios', emBreve: false },
  { chave: 'nfe',         rotulo: 'Notas Fiscais (NF-e)',  icone: 'nfe',        emBreve: true },
  { chave: 'unidades',    rotulo: 'Unidades',             icone: 'unidades',    emBreve: false, papeis: ['ARQUITETO', 'ADMIN'] },
  { chave: 'usuarios',    rotulo: 'Usuários',             icone: 'usuarios',    emBreve: false, papeis: ['ARQUITETO', 'ADMIN'] },
];

function montarMenuLateral() {
  const menu = document.getElementById('menu-lateral');
  const papel = USUARIO_ATUAL ? USUARIO_ATUAL.papel : null;

  // ARQUITETO e DIRETOR são os níveis irrestritos — a mesma regra que o
  // backend aplica em exigir_papeis(), para menu e API não discordarem.
  const irrestrito = papel === 'ARQUITETO' || papel === 'DIRETOR';
  const visiveis = window.NAV_ITEMS
    .filter(item => !item.papeis || irrestrito || item.papeis.includes(papel));

  menu.innerHTML = visiveis.map(item => `
      <button class="nav-item" data-pagina="${item.chave}"${item.acao ? ` data-acao="${item.acao}"` : ''}>
        ${icone(item.icone)}
        <span>${item.rotulo}</span>
        ${item.emBreve ? `<span class="badge-soon">Em breve</span>` : ''}
      </button>
    `).join('');

  menu.querySelectorAll('.nav-item').forEach(botao => {
    botao.addEventListener('click', () => {
      fecharMenuLateral();   // em telas pequenas, a gaveta some ao escolher
      if (botao.dataset.acao === 'abrirLancador') {
        window.Lancador.abrir();   // abre a janela sem sair da página atual
        return;
      }
      const destino = botao.dataset.pagina;
      const atual = (location.hash || '').replace('#', '').split('/')[0];
      if (atual === destino) {
        // Já estamos nela: mudar o hash não dispararia evento nenhum, então
        // recarrega na mão (clicar no menu da página atual = atualizar).
        window.roteador.rerenderizar();
      } else {
        location.hash = destino;
      }
    });
  });
}

/* ---------- Menu lateral em telas pequenas (gaveta) ---------- */
function abrirMenuLateral() {
  document.getElementById('sidebar').classList.add('aberta');
  document.getElementById('menu-overlay').classList.add('visivel');
}
function fecharMenuLateral() {
  document.getElementById('sidebar').classList.remove('aberta');
  document.getElementById('menu-overlay').classList.remove('visivel');
}
function ligarMenuLateral() {
  const botao = document.getElementById('btn-menu');
  botao.innerHTML = icone('menu');
  botao.addEventListener('click', () => {
    const aberta = document.getElementById('sidebar').classList.contains('aberta');
    aberta ? fecharMenuLateral() : abrirMenuLateral();
  });
  document.getElementById('menu-overlay').addEventListener('click', fecharMenuLateral);
  // Voltando para tela grande, a gaveta não deve continuar "aberta"
  window.addEventListener('resize', () => {
    if (window.innerWidth > 900) fecharMenuLateral();
  });
}

function preencherTopbarUsuario() {
  document.getElementById('nome-usuario').textContent = USUARIO_ATUAL.nome;
  document.getElementById('badge-papel').textContent = USUARIO_ATUAL.papel;
  document.getElementById('btn-logout').innerHTML = icone('logout');
}

async function iniciarApp() {
  mostrarApp();
  preencherTopbarUsuario();
  ligarMenuLateral();
  montarMenuLateral();
  await carregarUnidades();
  window.roteador.iniciar();
}

document.getElementById('form-login').addEventListener('submit', async (ev) => {
  ev.preventDefault();
  const erroEl = document.getElementById('login-erro');
  erroEl.hidden = true;
  const login = document.getElementById('input-login').value.trim();
  const senha = document.getElementById('input-senha').value;
  try {
    await tentarLogin(login, senha);
    await iniciarApp();
  } catch (erro) {
    erroEl.textContent = erro.message || 'Não foi possível entrar.';
    erroEl.hidden = false;
  }
});

document.getElementById('btn-logout').addEventListener('click', fazerLogout);

(async function bootstrap() {
  const autenticado = await carregarSessaoExistente();
  if (autenticado) {
    await iniciarApp();
  } else {
    mostrarTelaLogin();
  }
})();
