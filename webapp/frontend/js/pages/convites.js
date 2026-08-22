/* Convites — quem entra no sistema, e com o quê.

   Só Arquiteto e Diretor chegam aqui. A tela não decide nada: pergunta ao
   backend o que este usuário pode oferecer (`/convites/opcoes`) e desenha a
   partir disso. Repetir a regra em JavaScript criaria uma segunda verdade,
   que diverge na primeira mudança — e a do navegador é só decoração, porque
   quem recusa de fato é o servidor. */
window.Paginas = window.Paginas || {};

window.Paginas.convites = (function () {
  let opcoes = null;

  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const ROTULO_ESTADO = {
    DISPONIVEL: 'Aguardando',
    USADO: 'Aceito',
    EXPIRADO: 'Vencido',
    REVOGADO: 'Cancelado',
  };

  function dataCurta(iso) {
    if (!iso) return '—';
    const d = new Date(iso);
    return d.toLocaleDateString('pt-BR', { day: '2-digit', month: '2-digit' });
  }

  function linkCompleto(codigo) {
    return `${location.origin}/#convite/${codigo}`;
  }

  // ------------------------------------------------------------- formulário
  function formulario() {
    if (!opcoes.pode_convidar) return '';

    const papeis = opcoes.papeis.map((p) =>
      `<option value="${p}"${p === 'OPERADOR' ? ' selected' : ''}>${p}</option>`).join('');

    const unidades = opcoes.unidades.map((u) => `
      <label class="check-linha">
        <input type="checkbox" name="unidade" value="${u.id}">
        <span>${escapar(u.nome)}</span>
      </label>`).join('');

    return `
    <div class="card">
      <h3 class="card-titulo">Novo convite</h3>
      <p class="card-sub">Quem aceitar entra já com o cargo e as lojas definidos aqui.
         Nada disso é escolhido por quem recebe.</p>

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

        ${opcoes.precisa_escolher_empresa ? `
        <div class="form-group">
          <label for="conv-empresa">Empresa</label>
          <input id="conv-empresa" type="number" placeholder="id da empresa" required>
          <small class="form-dica">O Arquiteto não pertence a uma empresa, então o
            convite precisa dizer para qual ele vale.</small>
        </div>` : ''}

        <div class="form-group">
          <label>Acesso às lojas</label>
          <label class="check-linha check-destaque">
            <input type="radio" name="escopo" value="TODAS" id="conv-todas">
            <span><strong>Todas as lojas</strong> — inclusive as que forem abertas depois</span>
          </label>
          <label class="check-linha check-destaque">
            <input type="radio" name="escopo" value="LISTA" id="conv-lista" checked>
            <span><strong>Escolher lojas</strong> — só as marcadas abaixo</span>
          </label>
          <div class="lista-unidades" id="conv-unidades">${unidades}</div>
        </div>

        ${opcoes.pode_regional ? `
        <label class="check-linha">
          <input type="checkbox" id="conv-regional">
          <span>Pode ver o consolidado da rede (Regional)</span>
        </label>` : ''}

        <div class="form-group">
          <label for="conv-nota">Recado (opcional)</label>
          <input id="conv-nota" type="text" maxlength="200" placeholder="para a Maria, do estoque">
        </div>

        <button type="submit" class="btn btn-primario" id="conv-enviar">Gerar convite</button>
        <p id="conv-erro" class="login-erro" hidden></p>
      </form>
    </div>`;
  }

  function tabela(dados) {
    if (!dados.convites.length) {
      return `<div class="card"><div class="estado-vazio">
                Nenhum convite ainda.</div></div>`;
    }
    const linhas = dados.convites.map((c) => {
      const lojas = c.todas_as_unidades
        ? 'Todas'
        : (c.unidades || []).map((u) => escapar(u.nome)).join(', ') || '—';
      const podeRevogar = c.estado === 'DISPONIVEL';
      return `
      <tr class="estado-${c.estado.toLowerCase()}">
        <td><code class="codigo-convite">${c.codigo}</code></td>
        <td><span class="badge-estado badge-${c.estado.toLowerCase()}">
              ${ROTULO_ESTADO[c.estado] || c.estado}</span></td>
        <td>${escapar(c.papel)}</td>
        <td>${lojas}${c.acesso_regional ? ' <small>+ Regional</small>' : ''}</td>
        <td>${c.usado_por ? escapar(c.usado_por.nome) : (escapar(c.nota) || '—')}</td>
        <td>${dataCurta(c.expira_em)}</td>
        <td class="acoes">
          ${podeRevogar ? `
            <button class="btn-icone" data-copiar="${c.codigo}" title="Copiar link">
              ${icone('copiar') || '🔗'}</button>
            <button class="btn-icone btn-perigo" data-revogar="${c.id}" title="Cancelar">
              ${icone('lixeira') || '✕'}</button>` : ''}
        </td>
      </tr>`;
    }).join('');

    return `
    <div class="card">
      <h3 class="card-titulo">Convites emitidos</h3>
      <p class="card-sub">${dados.resumo.disponiveis} aguardando ·
         ${dados.resumo.usados} aceitos · ${dados.resumo.total} no total</p>
      <div class="tabela-wrap">
        <table class="tabela">
          <thead><tr>
            <th>Código</th><th>Estado</th><th>Cargo</th><th>Lojas</th>
            <th>Para</th><th>Vence</th><th></th>
          </tr></thead>
          <tbody>${linhas}</tbody>
        </table>
      </div>
    </div>`;
  }

  // ------------------------------------------------------------------ ações
  async function copiar(codigo, botao) {
    const texto = linkCompleto(codigo);
    try {
      await navigator.clipboard.writeText(texto);
    } catch (e) {
      // Sem permissão de área de transferência, mostrar o link ainda resolve:
      // a pessoa copia à mão. Falhar em silêncio seria pior.
      window.prompt('Copie o link do convite:', texto);
    }
    if (botao) {
      const antes = botao.innerHTML;
      botao.innerHTML = '✓';
      setTimeout(() => { botao.innerHTML = antes; }, 1200);
    }
  }

  function ligarEventos(container) {
    const form = container.querySelector('#form-convite-novo');
    if (form) {
      const marcarLista = () => {
        const lista = container.querySelector('#conv-lista');
        const caixas = container.querySelector('#conv-unidades');
        if (caixas) caixas.classList.toggle('desabilitada', !lista.checked);
      };
      container.querySelectorAll('input[name="escopo"]')
        .forEach((r) => r.addEventListener('change', marcarLista));
      marcarLista();

      form.addEventListener('submit', async (ev) => {
        ev.preventDefault();
        const erroEl = container.querySelector('#conv-erro');
        const botao = container.querySelector('#conv-enviar');
        erroEl.hidden = true;
        botao.disabled = true;

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

        try {
          const criado = await api.post('/convites', corpo);
          await copiar(criado.codigo, null);
          await render(container);
          const aviso = container.querySelector('#conv-aviso');
          if (aviso) {
            aviso.textContent = `Convite ${criado.codigo} criado — o link já está na área de transferência.`;
            aviso.hidden = false;
          }
        } catch (erro) {
          erroEl.textContent = erro.message || 'Não foi possível gerar o convite.';
          erroEl.hidden = false;
          botao.disabled = false;
        }
      });
    }

    container.querySelectorAll('[data-copiar]').forEach((b) => {
      b.addEventListener('click', () => copiar(b.dataset.copiar, b));
    });
    container.querySelectorAll('[data-revogar]').forEach((b) => {
      b.addEventListener('click', async () => {
        if (!confirm('Cancelar este convite? Quem tiver o link não poderá mais usá-lo.')) return;
        await api.del('/convites/' + b.dataset.revogar);
        await render(container);
      });
    });
  }

  async function render(container) {
    const [ops, dados] = await Promise.all([
      api.get('/convites/opcoes'),
      api.get('/convites'),
    ]);
    opcoes = ops;

    if (!opcoes.pode_convidar) {
      container.innerHTML = `<div class="card"><div class="estado-vazio">
        Somente Diretor e Arquiteto emitem convites.</div></div>`;
      return;
    }

    container.innerHTML = `
      <p id="conv-aviso" class="aviso-sucesso" hidden></p>
      ${formulario()}
      ${tabela(dados)}`;
    ligarEventos(container);
  }

  return { render };
})();
