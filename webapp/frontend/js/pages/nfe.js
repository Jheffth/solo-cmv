window.Paginas = window.Paginas || {};

window.Paginas.nfe = {
  async render(container) {
    container.innerHTML = `
      <div class="placeholder-em-construcao">
        ${icone('soon')}
        <h2>Notas Fiscais (NF-e)</h2>
        <p>Espaço reservado para a importação automática de notas fiscais de compra via certificado digital (A1/A3), lendo o XML direto da SEFAZ e gerando os lançamentos de Compra sem digitação manual.</p>
        <p>As tabelas de Certificado Digital e Nota Fiscal Importada já existem no banco de dados, prontas para receber esta integração.</p>
        <span class="fase-tag">Fase 10 do plano de migração — evolução pós-lançamento</span>
      </div>
    `;
  },
};
