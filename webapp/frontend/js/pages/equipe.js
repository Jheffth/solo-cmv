/* ============================================================
   EQUIPE — quem entra, com qual poder, e quem pode mexer nisso.

   Um lugar só para convidar, promover, rebaixar, suspender e excluir.
   Antes eram duas telas (Usuários e Convites) que não conversavam: a de
   Convites concedia "todas as lojas" e a de Usuários nem sabia que isso
   existia.

   A TELA NÃO DECIDE NADA. Ela pergunta ao backend o que este usuário pode
   conceder (/usuarios/poderes) e o que pode fazer com cada pessoa (o campo
   `acoes` de cada linha). Repetir a hierarquia em JavaScript criaria uma
   segunda verdade — e a do navegador é decoração, porque quem recusa de
   fato é o servidor.

   Consequência boa: quando alguém não pode agir sobre uma linha, aparece o
   MOTIVO ("mesmo nível que o seu") em vez de um botão morto. Botão que não
   funciona não ensina nada.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.equipe = (function () {
  let poderes = null;
  let unidades = [];
  let opcoesConvite = null;
  let aba = 'pessoas';
  let mostrarExcluidos = false;

  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const ROTULO_PAPEL = {
    ARQUITETO: 'Arquiteto', DIRETOR: 'Diretor', ADMIN: 'Administrador',
    GERENTE: 'Gerente', OPERADOR: 'Operador',
  };

  const ROTULO_ESTADO_CONVITE = {
    DISPONIVEL: 'Aguardando', USADO: 'Aceito',
    EXPIRADO: 'Vencido', REVOGADO: 'Cancelado',
  };

  function dataCurta(iso) {
    if (!iso) return '—';
    return new Date(iso).toLocaleDateString('pt-BR',
      { day: '2-digit', month: '2-digit' });
  }

  /* ------------------------------------------------- faixa de poderes */
  function faixaPoderes() {
    const concede = poderes.papeis_que_concede.map((p) => p.rotulo).join(', ');
    const fora = poderes.papeis_fora_do_alcance.map((p) => p.rotulo).join(', ');
    return `
      <div class="card faixa-poderes">
        <div>
          <span class="badge-role badge-nivel">${escapar(poderes.rotulo)}</span>
          <p class="nota-formula" style="margin:.5rem 0 0">
            Você concede até o próprio nível: <strong>${escapar(concede)}</strong>.
            ${fora ? `Acima de você fica ${escapar(fora)} — fora do seu alcance.` : ''}
            Você altera ${escapar(poderes.mexe_em)}; quem está no seu nível não.
          </p>
        </div>
      </div>`;
  }

  /* ------------------------------------------------- pessoas */
  function acoesDaLinha(p) {
    if (!p.acoes.pode_gerenciar) {
      return `<span class="motivo-bloqueio">${escapar(p.acoes.motivo)}</span>`;
    }
    if (p.excluido) {
      return `<button class="btn-acao" data-restaurar="${p.id}">Restaurar</button>`;
    }
    const papeis = p.acoes.papeis_disponiveis.map((op) =>
      `<option value="${op.valor}"${op.valor === p.papel ? ' selected' : ''}>${op.rotulo}</option>`
    ).join('');
    return `
      <select class="sel-papel" data-papel="${p.id}" title="Promover ou rebaixar">${papeis}</select>
      <button class="btn-acao" data-escopo="${p.id}">Lojas</button>
      <button class="btn-acao" data-ativo="${p.id}" data-valor="${p.ativo ? 'false' : 'true'}">
        ${p.ativo ? 'Suspender' : 'Reativar'}</button>
      <button class="btn-acao btn-perigo" data-excluir="${p.id}">Excluir</button>`;
  }

  function escopoDe(p) {
    if (p.papel === 'ARQUITETO' || p.papel === 'DIRETOR') {
      return `<span class="tag">todas · por ser ${ROTULO_PAPEL[p.papel]}</span>`;
    }
    if (p.escopo_unidades === 'TODAS') {
      return `<span class="tag regional">todas as lojas</span>`
        + (p.acesso_regional ? ' <span class="tag regional">Regional</span>' : '');
    }
    const nomes = (p.unidades || []).map((u) => `<span class="tag">${escapar(u.nome)}</span>`);
    if (!nomes.length && !p.acesso_regional) {
      return '<span class="tag alerta">sem acesso a nenhuma loja</span>';
    }
    return nomes.join(' ')
      + (p.acesso_regional ? ' <span class="tag regional">Regional</span>' : '');
  }

  function estadoDe(p) {
    if (p.excluido) {
      return `<span class="status-badge status-cancelado">excluído</span>`;
    }
    return p.ativo
      ? '<span class="status-badge status-aberto">ativo</span>'
      : '<span class="status-badge status-pausado">suspenso</span>';
  }

  function tabelaPessoas(pessoas) {
    if (!pessoas.length) {
      return `<div class="card"><div class="estado-vazio">Ninguém por aqui ainda.</div></div>`;
    }
    return `
      <div class="card">
        <div class="card-header">
          <h2>Pessoas (${pessoas.length})</h2>
          <label class="check-linha" style="margin:0">
            <input type="checkbox" id="ver-excluidos" ${mostrarExcluidos ? 'checked' : ''}>
            <span>Mostrar acessos excluídos</span>
          </label>
        </div>
        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th>Nome</th><th>Login</th><th>Cargo</th><th>Lojas</th>
              <th>Estado</th><th></th>
            </tr></thead>
            <tbody>
              ${pessoas.map((p) => `
                <tr class="${p.excluido ? 'linha-excluida' : (p.ativo ? '' : 'linha-inativa')}">
                  <td>${escapar(p.nome)}</td>
                  <td>${escapar(p.login)}</td>
                  <td><span class="badge-role">${ROTULO_PAPEL[p.papel] || p.papel}</span></td>
                  <td class="celula-escopo">${escopoDe(p)}</td>
                  <td>${estadoDe(p)}</td>
                  <td class="acoes">${acoesDaLinha(p)}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
        <p class="nota-formula">
          <strong>Suspender</strong> é afastamento reversível.
          <strong>Excluir</strong> tira o acesso de vez — mas a pessoa continua
          aparecendo como autora das compras e contagens que lançou. Apagar de
          verdade deixaria esses lançamentos sem dono, e o passado mudaria.
        </p>
      </div>`;
  }

  /* ------------------------------------------------- convites */
  function formularioConvite() {
    const papeis = opcoesConvite.papeis.map((p) =>
      `<option value="${p}">${ROTULO_PAPEL[p] || p}</option>`).join('');
    const lojas = opcoesConvite.unidades.map((u) => `
      <label class="check-linha">
        <input type="checkbox" name="unidade" value="${u.id}">
        <span>${escapar(u.nome)}</span>
      </label>`).join('');

    return `
      <div class="card">
        <h3 class="card-titulo">Novo convite</h3>
        <p class="card-sub">Quem aceitar entra já com o cargo e as lojas
           definidos aqui — e escolhe a própria senha.</p>
        <form id="form-convite-novo" class="form-convite">
          <div class="form-linha">
            <div class="form-group">
              <label for="conv-papel">Cargo</label>
              <select id="conv-papel">${papeis}</select>
            </div>
            <div class="form-group">
              <label for="conv-validade">Vence em</label>
              <select id="conv-validade">
                <option value="7" selected>7 dias</option>
                <option value="30">30 dias</option>
                <option value="">Não vence</option>
              </select>
            </div>
          </div>
          ${/* Nesta instalação existe uma rede só — a Josefina —, então o
                servidor responde `precisa_escolher_empresa: false` e este
                campo não aparece. Pedir um id que o sistema já conhece era
                burocracia; o bloco fica porque a decisão é do backend, não
                daqui. */ ''}
          ${opcoesConvite.precisa_escolher_empresa ? `
          <div class="form-group">
            <label for="conv-empresa">Empresa</label>
            <input id="conv-empresa" type="number" placeholder="id da empresa" required>
            <small class="form-dica">Há mais de uma empresa nesta instalação;
              diga para qual o convite vale.</small>
          </div>` : ''}
          <div class="form-group">
            <label>Acesso às lojas</label>
            <label class="check-linha check-destaque">
              <input type="radio" name="escopo" value="TODAS" id="conv-todas">
              <span><strong>Todas as lojas</strong> — inclusive as abertas depois</span>
            </label>
            <label class="check-linha check-destaque">
              <input type="radio" name="escopo" value="LISTA" id="conv-lista" checked>
              <span><strong>Escolher lojas</strong> — só as marcadas abaixo</span>
            </label>
            <div class="lista-unidades" id="conv-unidades">${lojas}</div>
          </div>
          ${opcoesConvite.pode_regional ? `
          <label class="check-linha">
            <input type="checkbox" id="conv-regional">
            <span>Pode ver o consolidado da rede (Regional)</span>
          </label>` : ''}
          <div class="form-group">
            <label for="conv-nota">Recado (opcional)</label>
            <input id="conv-nota" type="text" maxlength="200"
                   placeholder="para a Maria, do estoque">
          </div>
          <button type="submit" class="btn btn-primario" id="conv-enviar">Gerar convite</button>
          <p id="conv-erro" class="login-erro" hidden></p>
        </form>
      </div>`;
  }

  function tabelaConvites(dados) {
    if (!dados.convites.length) {
      return `<div class="card"><div class="estado-vazio">Nenhum convite ainda.</div></div>`;
    }
    return `
      <div class="card">
        <h3 class="card-titulo">Convites emitidos</h3>
        <p class="card-sub">${dados.resumo.disponiveis} aguardando ·
           ${dados.resumo.usados} aceitos</p>
        <div class="tabela-wrap">
          <table class="tabela">
            <thead><tr><th>Código</th><th>Estado</th><th>Cargo</th>
              <th>Lojas</th><th>Para</th><th>Vence</th><th></th></tr></thead>
            <tbody>
              ${dados.convites.map((c) => `
                <tr class="estado-${c.estado.toLowerCase()}">
                  <td><code class="codigo-convite">${c.codigo}</code></td>
                  <td><span class="badge-estado badge-${c.estado.toLowerCase()}">
                        ${ROTULO_ESTADO_CONVITE[c.estado] || c.estado}</span></td>
                  <td>${ROTULO_PAPEL[c.papel] || c.papel}</td>
                  <td>${c.todas_as_unidades ? 'Todas'
                        : (c.unidades || []).map((u) => escapar(u.nome)).join(', ') || '—'}</td>
                  <td>${c.usado_por ? escapar(c.usado_por.nome) : (escapar(c.nota) || '—')}</td>
                  <td>${dataCurta(c.expira_em)}</td>
                  <td class="acoes">${c.estado === 'DISPONIVEL' ? `
                    <button class="btn-acao" data-copiar="${c.codigo}">Copiar link</button>
                    <button class="btn-acao btn-perigo" data-revogar="${c.id}">Cancelar</button>`
                    : ''}</td>
                </tr>`).join('')}
            </tbody>
          </table>
        </div>
      </div>`;
  }

  /* ------------------------------------------------- ações */
  async function copiarLink(codigo, botao) {
    const texto = `${location.origin}/#convite/${codigo}`;
    try {
      await navigator.clipboard.writeText(texto);
    } catch (e) {
      window.prompt('Copie o link do convite:', texto);
    }
    if (botao) {
      const antes = botao.textContent;
      botao.textContent = 'Copiado';
      setTimeout(() => { botao.textContent = antes; }, 1200);
    }
  }

  function avisar(container, texto, erro) {
    const el = container.querySelector('#equipe-aviso');
    if (!el) return;
    el.textContent = texto;
    el.className = erro ? 'login-erro' : 'aviso-sucesso';
    el.hidden = false;
  }

  async function comAviso(container, acao, mensagem) {
    try {
      await acao();
      await render(container);
      if (mensagem) avisar(container, mensagem, false);
    } catch (erro) {
      avisar(container, erro.message || 'Não foi possível concluir.', true);
    }
  }

  function ligar(container, pessoas) {
    const ver = container.querySelector('#ver-excluidos');
    if (ver) {
      ver.addEventListener('change', () => {
        mostrarExcluidos = ver.checked;
        render(container);
      });
    }

    container.querySelectorAll('.aba-equipe').forEach((b) => {
      b.addEventListener('click', () => { aba = b.dataset.aba; render(container); });
    });

    container.querySelectorAll('[data-papel]').forEach((sel) => {
      const original = sel.value;
      sel.addEventListener('change', async () => {
        const pessoa = pessoas.find((p) => p.id === parseInt(sel.dataset.papel, 10));
        const novo = sel.value;
        const subindo = pessoa && novo !== original;
        if (!subindo) return;
        if (!confirm(`Alterar ${pessoa.nome} para ${ROTULO_PAPEL[novo] || novo}?`)) {
          sel.value = original;
          return;
        }
        await comAviso(container,
          () => api.put(`/usuarios/${sel.dataset.papel}/papel`, { papel: novo }),
          `${pessoa.nome} agora é ${ROTULO_PAPEL[novo] || novo}.`);
      });
    });

    container.querySelectorAll('[data-ativo]').forEach((b) => {
      b.addEventListener('click', async () => {
        const ativar = b.dataset.valor === 'true';
        if (!ativar && !confirm('Suspender este acesso? A pessoa perde a entrada '
                                + 'agora, e você pode devolver quando quiser.')) return;
        await comAviso(container,
          () => api.put(`/usuarios/${b.dataset.ativo}/ativo`, { ativo: ativar }),
          ativar ? 'Acesso reativado.' : 'Acesso suspenso.');
      });
    });

    container.querySelectorAll('[data-excluir]').forEach((b) => {
      b.addEventListener('click', async () => {
        if (!confirm('Excluir este acesso?\n\nA pessoa não entra mais e sai da '
                     + 'lista. O que ela lançou continua no histórico, com o '
                     + 'nome dela — isso não se apaga.')) return;
        await comAviso(container, () => api.del(`/usuarios/${b.dataset.excluir}`),
                       'Acesso excluído. O histórico foi preservado.');
      });
    });

    container.querySelectorAll('[data-restaurar]').forEach((b) => {
      b.addEventListener('click', async () => {
        await comAviso(container,
          () => api.post(`/usuarios/${b.dataset.restaurar}/restaurar`, {}),
          'Acesso restaurado — e voltou suspenso. Reative quando quiser.');
      });
    });

    container.querySelectorAll('[data-escopo]').forEach((b) => {
      b.addEventListener('click', () => {
        const alvo = pessoas.find((p) => p.id === parseInt(b.dataset.escopo, 10));
        if (alvo) abrirEscopo(container, alvo);
      });
    });

    container.querySelectorAll('[data-copiar]').forEach((b) => {
      b.addEventListener('click', () => copiarLink(b.dataset.copiar, b));
    });
    container.querySelectorAll('[data-revogar]').forEach((b) => {
      b.addEventListener('click', async () => {
        if (!confirm('Cancelar este convite? Quem tiver o link não poderá usá-lo.')) return;
        await comAviso(container, () => api.del('/convites/' + b.dataset.revogar),
                       'Convite cancelado.');
      });
    });

    const form = container.querySelector('#form-convite-novo');
    if (form) {
      const ajustar = () => {
        const lista = container.querySelector('#conv-lista').checked;
        container.querySelector('#conv-unidades').classList.toggle('desabilitada', !lista);
      };
      container.querySelectorAll('input[name="escopo"]')
        .forEach((r) => r.addEventListener('change', ajustar));
      ajustar();

      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const escopo = container.querySelector('input[name="escopo"]:checked').value;
        const validade = container.querySelector('#conv-validade').value;
        const empresaEl = container.querySelector('#conv-empresa');
        const regionalEl = container.querySelector('#conv-regional');
        const corpo = {
          papel: container.querySelector('#conv-papel').value,
          escopo_unidades: escopo,
          unidade_ids: escopo === 'LISTA'
            ? [...container.querySelectorAll('input[name="unidade"]:checked')]
                .map((c) => parseInt(c.value, 10))
            : [],
          acesso_regional: regionalEl ? regionalEl.checked : false,
          nota: container.querySelector('#conv-nota').value.trim() || null,
          validade_dias: validade ? parseInt(validade, 10) : null,
        };
        if (empresaEl) corpo.empresa_id = parseInt(empresaEl.value, 10);

        const erroEl = container.querySelector('#conv-erro');
        erroEl.hidden = true;
        try {
          const criado = await api.post('/convites', corpo);
          await copiarLink(criado.codigo, null);
          await render(container);
          avisar(container, `Convite ${criado.codigo} criado — o link já está `
                          + 'na área de transferência.', false);
        } catch (erro) {
          erroEl.textContent = erro.message || 'Não foi possível gerar o convite.';
          erroEl.hidden = false;
        }
      });
    }
  }

  function abrirEscopo(container, pessoa) {
    const marcadas = (pessoa.unidades || []).map((u) => u.id);
    const todas = pessoa.escopo_unidades === 'TODAS';
    const podeTodas = poderes.papel === 'ARQUITETO' || poderes.papel === 'DIRETOR';
    const fundo = document.createElement('div');
    fundo.className = 'modal-fundo';
    fundo.innerHTML = `
      <div class="modal-caixa" role="dialog" aria-label="Lojas de ${escapar(pessoa.nome)}">
        <div class="modal-cabecalho">
          <h3>Lojas de ${escapar(pessoa.nome)}</h3>
          <button class="btn-icone" type="button" data-fechar>${icone('x') || '×'}</button>
        </div>
        <div class="modal-corpo">
          ${podeTodas ? `
          <label class="escopo-opcao destaque">
            <input type="radio" name="esc-modo" value="TODAS" id="esc-todas" ${todas ? 'checked' : ''}>
            <span><strong>Todas as lojas</strong>
              <small>inclusive as que forem abertas depois</small></span>
          </label>` : ''}
          <label class="escopo-opcao destaque">
            <input type="radio" name="esc-modo" value="LISTA" id="esc-lista" ${todas ? '' : 'checked'}>
            <span><strong>Escolher lojas</strong>
              <small>loja nova não entra sozinha</small></span>
          </label>
          <div class="escopo-lista" id="esc-unidades">
            ${unidades.map((u) => `
              <label class="escopo-opcao">
                <input type="checkbox" class="esc-unidade" value="${u.id}"
                       ${marcadas.includes(u.id) ? 'checked' : ''}>
                <span>${escapar(u.nome)}</span>
              </label>`).join('')}
          </div>
          <label class="escopo-opcao destaque" style="margin-top:.9rem">
            <input type="checkbox" id="esc-regional" ${pessoa.acesso_regional ? 'checked' : ''}>
            <span>Pode ver a <strong>Regional</strong>
              <small>a soma das lojas — permissão à parte de ver várias</small></span>
          </label>
          <div class="modal-mensagem" id="esc-msg" hidden></div>
        </div>
        <div class="modal-rodape">
          <button class="btn secundario" type="button" data-fechar>Cancelar</button>
          <button class="btn" type="button" id="esc-salvar">Salvar</button>
        </div>
      </div>`;
    document.body.appendChild(fundo);

    const fechar = () => fundo.remove();
    fundo.querySelectorAll('[data-fechar]').forEach((b) => b.addEventListener('click', fechar));
    fundo.addEventListener('click', (ev) => { if (ev.target === fundo) fechar(); });

    const ajustar = () => {
      const porLista = fundo.querySelector('#esc-lista').checked;
      fundo.querySelector('#esc-unidades').classList.toggle('desabilitada', !porLista);
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
        await api.put(`/usuarios/${pessoa.id}/escopo`, {
          escopo_unidades: modo,
          unidade_ids: modo === 'LISTA' ? ids : [],
          acesso_regional: fundo.querySelector('#esc-regional').checked,
        });
        fechar();
        await render(container);
      } catch (erro) {
        msg.hidden = false;
        msg.textContent = erro.message || 'Não foi possível salvar.';
      }
    });
  }

  /* ------------------------------------------------- render */
  async function render(container) {
    poderes = await api.get('/usuarios/poderes');

    if (!poderes.pode_convidar) {
      container.innerHTML = `<div class="card"><div class="estado-vazio">
        Você não administra acessos. Fale com quem está acima de você.</div></div>`;
      return;
    }

    const [pessoas, lista, ops, convites] = await Promise.all([
      api.get('/usuarios?incluir_excluidos=' + (mostrarExcluidos ? 'true' : 'false')),
      api.get('/unidades').catch(() => []),
      api.get('/convites/opcoes').catch(() => null),
      api.get('/convites').catch(() => ({ convites: [], resumo: {} })),
    ]);
    unidades = lista;
    opcoesConvite = ops;

    container.innerHTML = `
      <p id="equipe-aviso" hidden></p>
      ${faixaPoderes()}
      <div class="abas-equipe">
        <button class="aba-equipe ${aba === 'pessoas' ? 'ativa' : ''}" data-aba="pessoas">
          Pessoas</button>
        <button class="aba-equipe ${aba === 'convites' ? 'ativa' : ''}" data-aba="convites">
          Convites</button>
      </div>
      ${aba === 'pessoas'
        ? tabelaPessoas(pessoas)
        : (opcoesConvite ? formularioConvite() : '') + tabelaConvites(convites)}`;

    ligar(container, pessoas);
  }

  return { render };
})();
