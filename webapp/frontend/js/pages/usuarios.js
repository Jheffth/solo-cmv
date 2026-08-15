/* ============================================================
   USUÁRIOS — quem entra, com qual papel e enxergando o quê.

   O escopo faz parte do cadastro, não é um detalhe posterior. Criar
   alguém sem dizer quais unidades ele vê o deixaria sem acesso a nada —
   ou, pior, com acesso a tudo por omissão.

   Duas dimensões independentes:
     · PAPEL  — o que pode fazer (lançar, aprovar, administrar)
     · ESCOPO — onde pode fazer (unidade A, B, e/ou a Regional)

   Ver duas lojas não dá acesso ao número da rede: a Regional é marca
   própria, porque somar as lojas é informação de diretoria.
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

  function caixasDeUnidade(marcadas = [], prefixo = 'usr') {
    if (!unidades.length) {
      return `<p class="nota-formula">Nenhuma unidade disponível para vincular.</p>`;
    }
    return unidades.map((u) => `
      <label class="escopo-opcao">
        <input type="checkbox" class="${prefixo}-unidade" value="${u.id}"
               ${marcadas.includes(u.id) ? 'checked' : ''}>
        <span>${u.nome}</span>
      </label>`).join('');
  }

  function escopoDoUsuario(u) {
    if (IRRESTRITOS.includes(u.papel)) {
      return `<span class="tag">todas · ${u.papel === 'ARQUITETO'
        ? 'acesso irrestrito' : 'toda a empresa'}</span>`;
    }
    const nomes = (u.unidades || []).map((x) => x.nome);
    if (!nomes.length && !u.acesso_regional) {
      return `<span class="tag alerta">sem acesso a nenhuma unidade</span>`;
    }
    return [
      ...nomes.map((n) => `<span class="tag">${n}</span>`),
      u.acesso_regional ? `<span class="tag regional">Regional</span>` : '',
    ].join(' ');
  }

  function abrirEscopo(usuario) {
    const marcadas = (usuario.unidades || []).map((u) => u.id);
    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa" role="dialog" aria-label="Acesso do usuário">
        <div class="modal-cabecalho">
          <h3>Acesso de ${usuario.nome}</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x')}</button>
        </div>
        <div class="modal-corpo">
          <label>Unidades que pode ver</label>
          <div class="escopo-lista">${caixasDeUnidade(marcadas, 'esc')}</div>

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

    fundo.querySelector('#esc-salvar').addEventListener('click', async () => {
      const msg = fundo.querySelector('#esc-msg');
      const ids = [...fundo.querySelectorAll('.esc-unidade:checked')]
        .map((c) => parseInt(c.value, 10));
      try {
        await api.put(`/usuarios/${usuario.id}/escopo`, {
          unidade_ids: ids,
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
      const [usuarios, lista] = await Promise.all([
        api.get('/usuarios'),
        api.get('/unidades').catch(() => []),
      ]);
      unidades = lista;

      container.innerHTML = `
        <div class="card">
          <div class="card-header"><h2>Novo usuário</h2></div>
          <form id="form-usuario">
            <div class="form-inline">
              <div class="form-group">
                <label for="usr-nome">Nome</label>
                <input id="usr-nome" required>
              </div>
              <div class="form-group">
                <label for="usr-login">Login</label>
                <input id="usr-login" required autocomplete="off">
              </div>
              <div class="form-group">
                <label for="usr-senha">Senha</label>
                <input id="usr-senha" type="password" required autocomplete="new-password">
              </div>
              <div class="form-group">
                <label for="usr-papel">Papel</label>
                <select id="usr-papel">
                  <option value="OPERADOR">Operador</option>
                  <option value="GERENTE">Gerente</option>
                  <option value="ADMIN">Administrador</option>
                  <option value="DIRETOR">Diretor</option>
                </select>
              </div>
            </div>

            <div class="escopo-bloco" id="usr-escopo">
              <div>
                <label>Unidades que pode ver</label>
                <div class="escopo-lista">${caixasDeUnidade()}</div>
              </div>
              <div>
                <label>Visão consolidada</label>
                <label class="escopo-opcao destaque">
                  <input type="checkbox" id="usr-regional">
                  <span>Pode ver a <strong>Regional</strong>
                    <small>a soma de todas as unidades</small></span>
                </label>
              </div>
            </div>

            <p class="nota-formula" id="usr-nota-irrestrito" hidden>
              Diretor enxerga todas as unidades da empresa e a Regional por
              definição do papel — não é preciso escolher.
            </p>

            <button class="btn" type="submit">Criar usuário</button>
            <div class="modal-mensagem" id="usr-msg" hidden></div>
          </form>
        </div>

        <div class="card">
          <div class="card-header"><h2>Usuários (${usuarios.length})</h2></div>
          <div class="tabela-rolavel">
            <table class="tabela-simples">
              <thead><tr><th>Nome</th><th>Login</th><th>Papel</th>
                <th>Acesso</th><th>Status</th><th></th></tr></thead>
              <tbody>
                ${usuarios.map((u) => `
                  <tr>
                    <td>${u.nome}</td>
                    <td>${u.login}</td>
                    <td><span class="badge-role">${ROTULO_PAPEL[u.papel] || u.papel}</span></td>
                    <td class="celula-escopo">${escopoDoUsuario(u)}</td>
                    <td>${u.ativo
                      ? '<span class="status-badge status-aberto">ativo</span>'
                      : '<span class="status-badge status-cancelado">inativo</span>'}</td>
                    <td>${IRRESTRITOS.includes(u.papel) ? ''
                      : `<button class="btn-acao" type="button" data-escopo="${u.id}">
                           Alterar acesso</button>`}</td>
                  </tr>`).join('')}
              </tbody>
            </table>
          </div>
        </div>
      `;

      // Papel irrestrito dispensa a escolha de escopo
      const papel = container.querySelector('#usr-papel');
      const bloco = container.querySelector('#usr-escopo');
      const nota = container.querySelector('#usr-nota-irrestrito');
      const ajustarEscopo = () => {
        const irrestrito = IRRESTRITOS.includes(papel.value);
        bloco.hidden = irrestrito;
        nota.hidden = !irrestrito;
      };
      papel.addEventListener('change', ajustarEscopo);
      ajustarEscopo();

      container.querySelectorAll('[data-escopo]').forEach((b) => {
        b.addEventListener('click', () => {
          const alvo = usuarios.find((u) => u.id === parseInt(b.dataset.escopo, 10));
          if (alvo) abrirEscopo(alvo);
        });
      });

      container.querySelector('#form-usuario').addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const msg = container.querySelector('#usr-msg');
        msg.hidden = true;
        const irrestrito = IRRESTRITOS.includes(papel.value);
        const ids = [...container.querySelectorAll('.usr-unidade:checked')]
          .map((c) => parseInt(c.value, 10));

        if (!irrestrito && !ids.length) {
          msg.hidden = false;
          msg.textContent = 'Escolha ao menos uma unidade — sem isso o usuário '
            + 'entra e não enxerga nada.';
          return;
        }

        try {
          await api.post('/usuarios', {
            nome: container.querySelector('#usr-nome').value.trim(),
            login: container.querySelector('#usr-login').value.trim(),
            senha: container.querySelector('#usr-senha').value,
            papel: papel.value,
            unidade_ids: ids,
            acesso_regional: container.querySelector('#usr-regional').checked,
          });
          window.roteador.rerenderizar();
        } catch (erro) {
          msg.hidden = false;
          msg.textContent = erro.message || 'Não foi possível criar o usuário.';
        }
      });
    },
  };
})();
