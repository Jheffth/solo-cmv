/* ============================================================
   USUÁRIOS — administrar quem já entrou.

   ESTA TELA NÃO CRIA CONTA. Conta nasce de um convite.

   Antes ela criava: um administrador digitava nome, login, SENHA e papel.
   Quem entrava pela primeira vez não tinha senha — tinha um segredo
   compartilhado com quem cadastrou. E ninguém troca senha no primeiro
   acesso quando o sistema não obriga.

   O convite separa as duas metades pela raiz: quem emite decide papel e
   lojas, quem aceita escolhe a própria senha, e as duas nunca se cruzam.
   De quebra fica o registro de quem autorizou a entrada de quem.

   O que sobra aqui é rotina de administração:
     · alterar o acesso (lojas e Regional)
     · ativar e desativar

   Não existe apagar. O histórico de quem lançou cada compra e cada contagem
   precisa continuar apontando para alguém — conta apagada deixa movimento
   órfão. Desativar tira o acesso e preserva a história.
   ============================================================ */
window.Paginas = window.Paginas || {};

const ROTULO_PAPEL = {
  ARQUITETO: 'Arquiteto', DIRETOR: 'Diretor', ADMIN: 'Administrador',
  GERENTE: 'Gerente', OPERADOR: 'Operador',
};

// Papéis que enxergam tudo por definição — não faz sentido pedir escopo
const IRRESTRITOS = ['ARQUITETO', 'DIRETOR'];

window.Paginas.usuarios = (function () {
  let unidades = [];
  let euPossoTodas = false;   // só quem enxerga todas as lojas pode conceder

  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function caixasDeUnidade(marcadas = []) {
    if (!unidades.length) {
      return `<p class="nota-formula">Nenhuma unidade disponível para vincular.</p>`;
    }
    return unidades.map((u) => `
      <label class="escopo-opcao">
        <input type="checkbox" class="esc-unidade" value="${u.id}"
               ${marcadas.includes(u.id) ? 'checked' : ''}>
        <span>${escapar(u.nome)}</span>
      </label>`).join('');
  }

  function escopoDoUsuario(u) {
    if (IRRESTRITOS.includes(u.papel)) {
      return `<span class="tag">todas · ${u.papel === 'ARQUITETO'
        ? 'acesso irrestrito' : 'toda a empresa'}</span>`;
    }
    // "Todas as lojas" é regra, não lista: mostrar os nomes de hoje esconderia
    // que as futuras entram sozinhas.
    if (u.escopo_unidades === 'TODAS') {
      return `<span class="tag regional">todas as lojas</span>`
        + (u.acesso_regional ? ` <span class="tag regional">Regional</span>` : '');
    }
    const nomes = (u.unidades || []).map((x) => x.nome);
    if (!nomes.length && !u.acesso_regional) {
      return `<span class="tag alerta">sem acesso a nenhuma unidade</span>`;
    }
    return [
      ...nomes.map((n) => `<span class="tag">${escapar(n)}</span>`),
      u.acesso_regional ? `<span class="tag regional">Regional</span>` : '',
    ].join(' ');
  }

  function abrirEscopo(usuario) {
    const marcadas = (usuario.unidades || []).map((u) => u.id);
    const todas = usuario.escopo_unidades === 'TODAS';
    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa" role="dialog" aria-label="Acesso do usuário">
        <div class="modal-cabecalho">
          <h3>Acesso de ${escapar(usuario.nome)}</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x')}</button>
        </div>
        <div class="modal-corpo">
          <label>Quais lojas pode ver</label>

          ${euPossoTodas ? `
          <label class="escopo-opcao destaque">
            <input type="radio" name="esc-modo" value="TODAS" id="esc-todas"
                   ${todas ? 'checked' : ''}>
            <span><strong>Todas as lojas</strong>
              <small>inclusive as que forem abertas depois</small></span>
          </label>` : ''}

          <label class="escopo-opcao destaque">
            <input type="radio" name="esc-modo" value="LISTA" id="esc-lista"
                   ${todas ? '' : 'checked'}>
            <span><strong>Escolher lojas</strong>
              <small>só as marcadas abaixo; loja nova não entra sozinha</small></span>
          </label>

          <div class="escopo-lista" id="esc-unidades">${caixasDeUnidade(marcadas)}</div>

          <label style="margin-top:.9rem">Visão consolidada</label>
          <label class="escopo-opcao destaque">
            <input type="checkbox" id="esc-regional" ${usuario.acesso_regional ? 'checked' : ''}>
            <span>Pode ver a <strong>Regional</strong>
              <small>a soma de todas as unidades — permissão à parte de ver
                     várias lojas</small></span>
          </label>
          <div class="modal-mensagem" id="esc-msg" hidden></div>
        </div>
        <div class="modal-rodape">
          <button class="btn secundario" type="button" data-fechar>Cancelar</button>
          <button class="btn" type="button" id="esc-salvar">Salvar acesso</button>
        </div>
      </div>`;
    document.body.appendChild(fundo);

    const fechar = () => fundo.remove();
    fundo.querySelectorAll('[data-fechar]').forEach((b) => b.addEventListener('click', fechar));
    fundo.addEventListener('click', (ev) => { if (ev.target === fundo) fechar(); });

    // Com "todas as lojas", a lista fica visível mas apagada: some a ação,
    // não a informação — quem olha ainda vê quais lojas existem hoje.
    const lista = fundo.querySelector('#esc-unidades');
    const ajustar = () => {
      const porLista = fundo.querySelector('#esc-lista').checked;
      lista.classList.toggle('desabilitada', !porLista);
    };
    fundo.querySelectorAll('input[name="esc-modo"]')
      .forEach((r) => r.addEventListener('change', ajustar));
    ajustar();

    fundo.querySelector('#esc-salvar').addEventListener('click', async () => {
      const msg = fundo.querySelector('#esc-msg');
      msg.hidden = true;
      const modo = fundo.querySelector('input[name="esc-modo"]:checked').value;
      const ids = [...fundo.querySelectorAll('.esc-unidade:checked')]
        .map((c) => parseInt(c.value, 10));

      if (modo === 'LISTA' && !ids.length) {
        msg.hidden = false;
        msg.textContent = 'Escolha ao menos uma loja — sem isso a pessoa entra '
          + 'e não enxerga nada.';
        return;
      }

      try {
        await api.put(`/usuarios/${usuario.id}/escopo`, {
          escopo_unidades: modo,
          unidade_ids: modo === 'LISTA' ? ids : [],
          acesso_regional: fundo.querySelector('#esc-regional').checked,
        });
        fechar();
        window.roteador.rerenderizar();
      } catch (erro) {
        msg.hidden = false;
        msg.textContent = erro.message || 'Não foi possível salvar.';
      }
    });
  }

  return {
    async render(container) {
      const [usuarios, lista, escopo] = await Promise.all([
        api.get('/usuarios'),
        api.get('/unidades').catch(() => []),
        api.get('/unidades/escopo').catch(() => ({})),
      ]);
      unidades = lista;
      // Conceder "todas as lojas" exige enxergar todas. O backend recusa de
      // qualquer forma; esconder a opção evita oferecer o que vai ser negado.
      euPossoTodas = !!(escopo.irrestrito
        || (window.USUARIO_ATUAL && IRRESTRITOS.includes(USUARIO_ATUAL.papel)));

      const meuId = window.USUARIO_ATUAL ? USUARIO_ATUAL.id : null;

      container.innerHTML = `
        <div class="card card-aviso">
          <div>
            <h2 style="margin:0 0 .3rem">Conta nova entra por convite</h2>
            <p class="nota-formula" style="margin:0">
              Gere um link em <strong>Convites</strong> e envie para a pessoa.
              Ela escolhe a própria senha — ninguém mais precisa conhecê-la.
              Aqui você administra quem já entrou.
            </p>
          </div>
          <button class="btn" type="button" id="ir-convites">Ir para Convites</button>
        </div>

        <div class="card">
          <div class="card-header"><h2>Usuários (${usuarios.length})</h2></div>
          <div class="tabela-rolavel">
            <table class="tabela-simples">
              <thead><tr><th>Nome</th><th>Login</th><th>Papel</th>
                <th>Acesso</th><th>Status</th><th></th></tr></thead>
              <tbody>
                ${usuarios.map((u) => `
                  <tr class="${u.ativo ? '' : 'linha-inativa'}">
                    <td>${escapar(u.nome)}</td>
                    <td>${escapar(u.login)}</td>
                    <td><span class="badge-role">${ROTULO_PAPEL[u.papel] || u.papel}</span></td>
                    <td class="celula-escopo">${escopoDoUsuario(u)}</td>
                    <td>${u.ativo
                      ? '<span class="status-badge status-aberto">ativo</span>'
                      : '<span class="status-badge status-cancelado">inativo</span>'}</td>
                    <td class="acoes">
                      ${IRRESTRITOS.includes(u.papel) ? ''
                        : `<button class="btn-acao" type="button" data-escopo="${u.id}">
                             Alterar acesso</button>`}
                      ${u.id === meuId ? ''
                        : `<button class="btn-acao ${u.ativo ? 'btn-perigo' : ''}"
                                   type="button" data-ativo="${u.id}"
                                   data-valor="${u.ativo ? 'false' : 'true'}">
                             ${u.ativo ? 'Desativar' : 'Reativar'}</button>`}
                    </td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>
          <p class="nota-formula">
            Não existe apagar usuário: o histórico de quem lançou cada compra e
            cada contagem precisa continuar apontando para alguém. Desativar
            tira o acesso e preserva a história.
          </p>
        </div>
      `;

      container.querySelector('#ir-convites')
        .addEventListener('click', () => { location.hash = 'convites'; });

      container.querySelectorAll('[data-escopo]').forEach((b) => {
        b.addEventListener('click', () => {
          const alvo = usuarios.find((u) => u.id === parseInt(b.dataset.escopo, 10));
          if (alvo) abrirEscopo(alvo);
        });
      });

      container.querySelectorAll('[data-ativo]').forEach((b) => {
        b.addEventListener('click', async () => {
          const ativar = b.dataset.valor === 'true';
          if (!ativar && !confirm('Desativar este usuário? Ele perde o acesso '
                                  + 'na hora, mas o histórico dele fica.')) return;
          await api.put(`/usuarios/${b.dataset.ativo}/ativo`, { ativo: ativar });
          window.roteador.rerenderizar();
        });
      });
    },
  };
})();
