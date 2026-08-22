/* Aceite de convite — a única tela do sistema que existe sem usuário.

   Chega-se aqui por um link: /#convite/SOLO-XXXX-XXXX

   Roda ANTES da checagem de sessão, no app.js. Se dependesse do login, a
   pessoa precisaria de uma conta para criar a conta.

   O QUE ESTA TELA MOSTRA, E POR QUÊ
   Antes de pedir senha, ela mostra o que o convite concede: papel, lojas,
   quem convidou. Aceitar sem saber o que se está aceitando não é aceitar —
   e quem recebe um convite errado descobre aqui, não depois de descobrir
   que não enxerga a própria loja. */
(function () {
  const PREFIXO = 'convite';

  function codigoDaUrl() {
    const hash = (location.hash || '').replace('#', '').trim();
    if (!hash.startsWith(PREFIXO + '/')) return null;
    return decodeURIComponent(hash.slice(PREFIXO.length + 1)).trim().toUpperCase();
  }

  function esconderTudo() {
    ['tela-login', 'app'].forEach((id) => {
      const el = document.getElementById(id);
      if (el) el.hidden = true;
    });
    document.getElementById('tela-convite').hidden = false;
  }

  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  function alvo() {
    return document.getElementById('convite-conteudo');
  }

  function recusar(motivo) {
    alvo().innerHTML = `
      <img class="login-logo" src="/assets/logos/josefina-logo.jpg" alt="">
      <h1>Convite indisponível</h1>
      <p class="convite-motivo">${escapar(motivo)}</p>
      <p class="login-subtitulo">Peça um convite novo a quem administra o sistema.</p>
      <a class="btn btn-login" href="/#dashboard" onclick="location.reload()">Ir para o login</a>`;
  }

  function desenhar(d) {
    // "Todas as lojas" é regra, não lista: dizer só os nomes de hoje esconderia
    // que as futuras entram sozinhas. A diferença aparece meses depois.
    const lojas = d.todas_as_unidades
      ? '<strong>Todas as lojas</strong>, inclusive as que forem abertas depois'
      : (d.unidades || []).map((u) => escapar(u.nome)).join(', ') || '—';

    alvo().innerHTML = `
      <img class="login-logo" src="/assets/logos/josefina-logo.jpg" alt="">
      <h1>Você foi convidado</h1>
      <p class="login-subtitulo">
        ${d.convidado_por ? escapar(d.convidado_por) + ' criou um acesso para você' : 'Crie seu acesso'}
        ${d.empresa ? ' — ' + escapar(d.empresa) : ''}
      </p>

      <div class="convite-resumo">
        <div class="convite-linha"><span>Cargo</span><strong>${escapar(d.papel)}</strong></div>
        <div class="convite-linha"><span>Lojas</span><strong>${lojas}</strong></div>
        ${d.acesso_regional
          ? '<div class="convite-linha"><span>Regional</span><strong>Vê o consolidado da rede</strong></div>'
          : ''}
        ${d.nota ? `<div class="convite-linha"><span>Recado</span><strong>${escapar(d.nota)}</strong></div>` : ''}
      </div>

      <form id="form-convite">
        <div class="form-group">
          <label for="convite-nome">Seu nome</label>
          <input id="convite-nome" type="text" autocomplete="name" required>
        </div>
        <div class="form-group">
          <label for="convite-login">Usuário para entrar</label>
          <input id="convite-login" type="text" autocomplete="username" required
                 pattern="[A-Za-z0-9._-]{3,60}"
                 title="De 3 a 60 caracteres: letras, números, ponto, hífen ou sublinhado">
        </div>
        <div class="form-group">
          <label for="convite-senha">Senha</label>
          <input id="convite-senha" type="password" autocomplete="new-password" required
                 minlength="${d.senha_minima || 10}">
          <small class="form-dica">Ao menos ${d.senha_minima || 10} caracteres.</small>
        </div>
        <button type="submit" class="btn btn-login" id="convite-enviar">Criar meu acesso</button>
        <p id="convite-erro" class="login-erro" hidden></p>
      </form>`;

    document.getElementById('form-convite').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const erroEl = document.getElementById('convite-erro');
      const botao = document.getElementById('convite-enviar');
      erroEl.hidden = true;
      botao.disabled = true;
      botao.textContent = 'Criando…';
      try {
        // Só isto viaja. Cargo, lojas e empresa saem do convite, no servidor —
        // mandá-los daqui não adiantaria nada, e é exatamente o que o backend
        // ignora de propósito. Ver servicos/convites.py.
        await api.post('/convites/aceitar', {
          codigo: d.codigo,
          nome: document.getElementById('convite-nome').value.trim(),
          login: document.getElementById('convite-login').value.trim(),
          senha: document.getElementById('convite-senha').value,
        });
        sucesso(document.getElementById('convite-login').value.trim());
      } catch (erro) {
        erroEl.textContent = erro.message || 'Não foi possível criar o acesso.';
        erroEl.hidden = false;
        botao.disabled = false;
        botao.textContent = 'Criar meu acesso';
      }
    });
  }

  function sucesso(login) {
    alvo().innerHTML = `
      <img class="login-logo" src="/assets/logos/josefina-logo.jpg" alt="">
      <h1>Acesso criado</h1>
      <p class="login-subtitulo">Entre com <strong>${escapar(login)}</strong> e a senha que você escolheu.</p>
      <a class="btn btn-login" href="/" id="convite-ir-login">Entrar agora</a>`;
    // Recarrega em vez de trocar o hash: assim a página volta limpa, sem o
    // código do convite na barra de endereço.
    document.getElementById('convite-ir-login')
      .addEventListener('click', () => { location.href = '/'; });
  }

  async function abrir() {
    const codigo = codigoDaUrl();
    if (!codigo) return false;
    esconderTudo();
    alvo().innerHTML = '<p class="login-subtitulo">Conferindo o convite…</p>';
    try {
      const d = await api.get('/convites/validar/' + encodeURIComponent(codigo));
      if (d && d.valido) desenhar(d);
      else recusar((d && d.motivo) || 'Este convite não pode ser usado.');
    } catch (erro) {
      recusar(erro.message || 'Não foi possível conferir o convite agora.');
    }
    return true;
  }

  window.AceitarConvite = { abrir, codigoDaUrl };
})();
