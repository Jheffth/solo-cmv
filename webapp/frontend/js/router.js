/* Roteador simples baseado em hash (#/pagina). Cada módulo de página deve
   registrar-se em window.Paginas["chave"] = { render(container) {...} }. */
window.Paginas = window.Paginas || {};

const ROTA_PADRAO = 'dashboard';

// Produtos e Categorias vivem em abas dentro de Cadastros.
// Fornecedores voltou a ter entrada própria (é a origem das compras).
// Links antigos continuam funcionando, abrindo direto na aba correspondente.
const ROTAS_MOVIDAS = {
  produtos: 'cadastros/produtos',
  categorias: 'cadastros/categorias',
  'cadastros/fornecedores': 'fornecedores',
};

function paginaAtualChave() {
  const hash = (location.hash || '').replace('#', '').trim();
  // Só a primeira parte é a página; o resto é parâmetro (ex.: cadastros/produtos)
  return (hash || ROTA_PADRAO).split('/')[0];
}

async function renderizarRota() {
  const hashCompleto = (location.hash || '').replace('#', '').trim();
  if (ROTAS_MOVIDAS[hashCompleto]) {
    location.hash = ROTAS_MOVIDAS[hashCompleto];   // dispara hashchange e re-renderiza
    return;
  }

  const chave = paginaAtualChave();
  const container = document.getElementById('conteudo');
  const pagina = window.Paginas[chave];

  document.querySelectorAll('.nav-item').forEach(el => {
    el.classList.toggle('ativo', el.dataset.pagina === chave);
  });
  const titulo = document.getElementById('titulo-pagina');
  const itemNav = (window.NAV_ITEMS || []).find(i => i.chave === chave);
  titulo.textContent = itemNav ? itemNav.rotulo : 'Solo CMV';

  if (!pagina) {
    container.innerHTML = `<div class="estado-vazio">Seção não encontrada.</div>`;
    return;
  }

  // A Regional é uma soma, não um lugar: telas de lançamento e de operação
  // não existem nela. Dizer isso é melhor que renderizar uma tela vazia.
  if (typeof emRegional === 'function' && emRegional()
      && window.PAGINAS_SEM_REGIONAL && window.PAGINAS_SEM_REGIONAL.has(chave)) {
    container.innerHTML = `
      <div class="card">
        <div class="estado-vazio">
          ${icone('cadeado')}
          <p style="margin:.6rem 0 .2rem"><strong>${itemNav ? itemNav.rotulo : 'Esta seção'}
            não existe na Regional</strong></p>
          <p>A Regional consolida o que já aconteceu nas unidades — ela soma,
             não opera. Escolha uma unidade na barra de topo para lançar,
             contar ou consultar movimento.</p>
        </div>
      </div>`;
    return;
  }

  container.innerHTML = `<div class="estado-vazio">Carregando…</div>`;
  // Quem rola agora é o #conteudo, não a janela. Sem isto, sair de uma
  // página longa rolada até o fim abriria a próxima já no meio dela.
  container.scrollTop = 0;
  try {
    await pagina.render(container);
  } catch (erro) {
    container.innerHTML = `<div class="estado-vazio">Não foi possível carregar esta seção: ${erro.message}</div>`;
  }
}

window.roteador = {
  iniciar() {
    window.addEventListener('hashchange', renderizarRota);
    renderizarRota();
  },
  rerenderizar() { renderizarRota(); },
};
