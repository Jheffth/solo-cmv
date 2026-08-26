/* Bootstrap da aplicação: monta o menu lateral, liga os formulários e decide
   se mostra a tela de login ou o painel, ao carregar a página. */
/* `exige` é uma CAPACIDADE, não uma lista de papéis.

   Antes cada item carregava `papeis: ['ARQUITETO', 'DIRETOR']` — uma cópia
   da régua do backend, escrita em JavaScript e nunca testada contra ela. As
   duas concordavam até o dia em que uma mudasse; e a que muda por último é
   sempre esta, porque quem mexe na permissão mexe no servidor.

   Agora o servidor manda a lista do que a pessoa pode (em /sessao) e o menu
   só consulta. Uma capacidade nova aparece no menu sozinha; uma que troque
   de piso acompanha sem ninguém tocar aqui. */
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
  { chave: 'vendas',      rotulo: 'Faturamento por Período', icone: 'vendas',   emBreve: false, exige: 'VER_FATURAMENTO' },
  { chave: 'cmv',         rotulo: 'Motor de CMV',         icone: 'cmv',         emBreve: false, exige: 'VER_CMV' },
  // Quem define o alvo é a diretoria; os demais papéis veem a meta nas telas
  { chave: 'metas',       rotulo: 'Metas',                icone: 'metas',       emBreve: false, exige: 'DEFINIR_META' },
  // Convidar, promover, rebaixar, suspender e excluir num lugar só.
  { chave: 'equipe',      rotulo: 'Equipe',               icone: 'usuarios',    emBreve: false, exige: 'ADMINISTRAR_ACESSO' },
  { chave: 'relatorios',  rotulo: 'Relatórios',           icone: 'relatorios', emBreve: false, exige: 'VER_CMV' },
  { chave: 'nfe',         rotulo: 'Notas Fiscais (NF-e)',  icone: 'nfe',        emBreve: true },
  { chave: 'unidades',    rotulo: 'Unidades',             icone: 'unidades',    emBreve: false, exige: 'CRIAR_UNIDADE' },
];

function montarMenuLateral() {
  const menu = document.getElementById('menu-lateral');
  const visiveis = window.NAV_ITEMS
    .filter(item => !item.exige || window.pode(item.exige));

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
  if (!USUARIO_ATUAL) return;
  const nomeEl = document.getElementById('nome-usuario');
  const papelEl = document.getElementById('badge-papel');
  const logoutBtn = document.getElementById('btn-logout');
  const avatarEl = document.getElementById('sidebar-avatar');

  // Apelido ganha do nome completo: é como a pessoa pediu para ser
  // chamada, e a barra lateral é o lugar mais pessoal da tela.
  if (nomeEl) nomeEl.textContent = USUARIO_ATUAL.apelido || USUARIO_ATUAL.nome;
  if (papelEl) papelEl.textContent = USUARIO_ATUAL.papel;
  if (logoutBtn) logoutBtn.innerHTML = icone('logout');

  if (avatarEl) {
    if (USUARIO_ATUAL.avatar_url) {
      avatarEl.innerHTML = `<img src="${USUARIO_ATUAL.avatar_url}" alt="Avatar">`;
    } else {
      const inicial = (USUARIO_ATUAL.nome || 'U').trim().charAt(0).toUpperCase();
      avatarEl.textContent = inicial;
    }
  }
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

(function ligarToggleSenhaLogin() {
  const btn = document.getElementById('btn-toggle-senha');
  const input = document.getElementById('input-senha');
  const olhoAberto = document.getElementById('icone-olho-aberto');
  const olhoFechado = document.getElementById('icone-olho-fechado');
  if (!btn || !input) return;

  btn.addEventListener('click', () => {
    const ehPassword = input.type === 'password';
    input.type = ehPassword ? 'text' : 'password';
    if (olhoAberto && olhoFechado) {
      olhoAberto.style.display = ehPassword ? 'none' : 'block';
      olhoFechado.style.display = ehPassword ? 'block' : 'none';
    }
  });
})();

/* O card do usuário na barra lateral abre o perfil. É onde a pessoa já olha
   quando quer trocar a foto — pedir que ela procure no menu seria fazer com
   que o lugar óbvio não funcionasse. O botão de sair fica de fora do clique,
   senão sair e editar o perfil virariam a mesma ação. */
(function ligarAtalhoDoPerfil() {
  const card = document.getElementById('sidebar-user');
  if (!card) return;
  card.style.cursor = 'pointer';
  card.title = 'Ver e editar meu perfil';
  card.addEventListener('click', (ev) => {
    if (ev.target.closest('#btn-logout')) return;
    location.hash = 'perfil';
  });
})();

(async function bootstrap() {
  // O aceite de convite vem ANTES de tudo. É a única tela que existe sem
  // usuário: exigir sessão para criar a primeira sessão seria um círculo.
  // Se a URL não for de convite, `abrir()` devolve false e a vida segue.
  if (window.AceitarConvite && await window.AceitarConvite.abrir()) return;

  const autenticado = await carregarSessaoExistente();
  if (autenticado) {
    await iniciarApp();
  } else {
    mostrarTelaLogin();
  }
})();
