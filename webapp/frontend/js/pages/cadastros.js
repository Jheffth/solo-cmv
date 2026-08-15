/* ============================================================
   CADASTROS — reúne Produtos e Categorias em abas, numa única
   entrada do menu lateral.

   Fornecedores saiu daqui e ganhou entrada própria: é a origem
   de toda compra, então é consultado com outra frequência.

   Não duplica lógica: cada aba delega para o módulo já existente
   (Paginas.produtos / Paginas.categorias), renderizando dentro
   de um container próprio.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.cadastros = (function () {
  const ABAS = [
    { chave: 'produtos',     rotulo: 'Produtos',     icone: 'produtos',     endpoint: '/produtos' },
    { chave: 'categorias',   rotulo: 'Categorias',   icone: 'categorias',   endpoint: '/categorias' },
  ];

  let abaAtiva = 'produtos';

  // Permite abrir já numa aba específica: #cadastros/fornecedores
  function lerAbaDaRota() {
    const partes = (location.hash || '').replace('#', '').split('/');
    if (partes[1] && ABAS.some((a) => a.chave === partes[1])) abaAtiva = partes[1];
  }

  async function contarRegistros() {
    const contagens = {};
    await Promise.all(ABAS.map(async (a) => {
      try {
        const lista = await api.get(a.endpoint);
        contagens[a.chave] = Array.isArray(lista) ? lista.length : null;
      } catch (e) {
        contagens[a.chave] = null;
      }
    }));
    return contagens;
  }

  function montarAbas(contagens) {
    return ABAS.map((a) => {
      const n = contagens[a.chave];
      return `
        <button class="aba-pagina${a.chave === abaAtiva ? ' ativa' : ''}" data-aba="${a.chave}" type="button">
          ${icone(a.icone)}
          <span>${a.rotulo}</span>
          ${n !== null && n !== undefined ? `<span class="contador">${n}</span>` : ''}
        </button>`;
    }).join('');
  }

  async function renderConteudoAba(container) {
    const modulo = window.Paginas[abaAtiva];
    if (!modulo) {
      container.innerHTML = `<div class="estado-vazio">Seção "${abaAtiva}" não encontrada.</div>`;
      return;
    }
    container.innerHTML = `<div class="estado-vazio">Carregando…</div>`;
    try {
      await modulo.render(container);
    } catch (erro) {
      container.innerHTML = `<div class="estado-vazio">Não foi possível carregar: ${erro.message}</div>`;
    }
  }

  return {
    async render(container) {
      lerAbaDaRota();
      const contagens = await contarRegistros();

      container.innerHTML = `
        <div class="abas-pagina" id="cadastros-abas">${montarAbas(contagens)}</div>
        <div id="cadastros-conteudo"></div>
      `;

      const conteudo = container.querySelector('#cadastros-conteudo');
      container.querySelectorAll('.aba-pagina').forEach((botao) => {
        botao.addEventListener('click', async () => {
          abaAtiva = botao.dataset.aba;
          container.querySelectorAll('.aba-pagina').forEach((b) => {
            b.classList.toggle('ativa', b.dataset.aba === abaAtiva);
          });
          // Mantém a aba na URL, para poder recarregar/compartilhar o link
          history.replaceState(null, '', `#cadastros/${abaAtiva}`);
          await renderConteudoAba(conteudo);
        });
      });

      await renderConteudoAba(conteudo);
    },
  };
})();
