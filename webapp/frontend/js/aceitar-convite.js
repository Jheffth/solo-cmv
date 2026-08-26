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

  /* Três situações, e a do meio é a que costuma faltar:

       #convite/SOLO-XXXX-XXXX  → veio pelo link, confere direto
       #convite                 → veio pelo botão do login, precisa digitar
       qualquer outra coisa     → não é assunto nosso

     O caso do meio existe porque o link quebra. O código é feito para ser
     ditado por telefone e colado de WhatsApp — por isso o alfabeto não tem
     0/O nem 1/I/L. Sem um lugar para digitar, todo esse cuidado seria
     inútil: quem tem só o código ficaria de fora. */
  function situacao() {
    const hash = (location.hash || '').replace('#', '').trim();
    if (hash === PREFIXO) return { nossa: true, codigo: null };
    if (hash.startsWith(PREFIXO + '/')) {
      const codigo = decodeURIComponent(hash.slice(PREFIXO.length + 1))
        .trim().toUpperCase();
      return { nossa: true, codigo: codigo || null };
    }
    return { nossa: false, codigo: null };
  }

  function codigoDaUrl() {
    return situacao().codigo;
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
      <img class="auth-logo-topo" src="/assets/logos/casa-josefina.svg" alt="">
      <h1>Convite indisponível</h1>
      <p class="auth-erro">${escapar(motivo)}</p>
      <p class="auth-sub">Confira o código ou peça um convite novo a quem
         administra o sistema.</p>
      <button class="btn-marca" type="button" id="tentar-outro">Digitar outro código</button>
      <p class="auth-sub" style="margin-top:1rem">
        <a href="/" id="voltar-login">Voltar para o login</a>
      </p>`;
    // Errar o código é o caso comum — dar só a saída para o login obrigaria a
    // recomeçar do zero por causa de uma letra.
    document.getElementById('tentar-outro')
      .addEventListener('click', () => { location.hash = PREFIXO; pedirCodigo(); });
    document.getElementById('voltar-login')
      .addEventListener('click', (ev) => { ev.preventDefault(); location.href = '/'; });
  }

  function desenhar(d) {
    // "Todas as lojas" é regra, não lista: dizer só os nomes de hoje esconderia
    // que as futuras entram sozinhas. A diferença aparece meses depois.
    const lojas = d.todas_as_unidades
      ? '<strong>Todas as lojas</strong>, inclusive as que forem abertas depois'
      : (d.unidades || []).map((u) => escapar(u.nome)).join(', ') || '—';

    alvo().innerHTML = `
      <img class="auth-logo-topo" src="/assets/logos/casa-josefina.svg" alt="">
      <h1>Você foi convidado</h1>
      <p class="auth-sub">
        ${d.convidado_por ? escapar(d.convidado_por) + ' criou um acesso para você' : 'Crie seu acesso'}
        ${d.empresa ? ' — ' + escapar(d.empresa) : ''}
      </p>

      <div class="convite-resumo">
        <div class="convite-linha"><span>Cargo</span><strong class="selo-cargo">${escapar(d.papel)}</strong></div>
        <div class="convite-linha"><span>Lojas</span><strong>${lojas}</strong></div>
        ${d.acesso_regional
          ? '<div class="convite-linha"><span>Regional</span><strong>Vê o consolidado da rede</strong></div>'
          : ''}
        ${d.nota ? `<div class="convite-linha"><span>Recado</span><strong>${escapar(d.nota)}</strong></div>` : ''}
      </div>

      <form id="form-convite">
        <div class="campo">
          <input id="convite-nome" type="text" autocomplete="name" placeholder=" " required>
          <label for="convite-nome">Seu nome</label>
        </div>
        <div class="campo">
          <input id="convite-login" type="text" autocomplete="username" placeholder=" " required
                 pattern="[A-Za-z0-9._-]{3,60}"
                 title="De 3 a 60 caracteres: letras, números, ponto, hífen ou sublinhado">
          <label for="convite-login">Usuário para entrar</label>
        </div>
        <div class="campo">
          <input id="convite-senha" type="password" autocomplete="new-password" placeholder=" " required
                 minlength="${d.senha_minima || 10}">
          <label for="convite-senha">Senha</label>
        </div>
        <small class="form-dica">Ao menos ${d.senha_minima || 10} caracteres.</small>
        <button type="submit" class="btn-marca" id="convite-enviar">Criar meu acesso</button>
        <p id="convite-erro" class="auth-erro" hidden></p>
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
      <img class="auth-logo-topo" src="/assets/logos/casa-josefina.svg" alt="">
      <h1>Acesso criado</h1>
      <p class="auth-sub">Entre com <strong>${escapar(login)}</strong> e a senha que você escolheu.</p>
      <a class="btn-marca" href="/" id="convite-ir-login">Entrar agora</a>`;
    // Recarrega em vez de trocar o hash: assim a página volta limpa, sem o
    // código do convite na barra de endereço.
    document.getElementById('convite-ir-login')
      .addEventListener('click', () => { location.href = '/'; });
  }

  /* Formata enquanto digita: SOLOK3M9P7QR vira SOLO-K3M9-P7QR.
     Quem copia de uma mensagem cola de qualquer jeito, e recusar por causa
     de um hífen faltando seria implicância. */
  function normalizar(bruto) {
    const limpo = (bruto || '').toUpperCase().replace(/[^A-Z0-9]/g, '')
      .replace(/^SOLO/, '').slice(0, 8);
    if (!limpo) return '';
    const partes = ['SOLO'];
    if (limpo.length > 0) partes.push(limpo.slice(0, 4));
    if (limpo.length > 4) partes.push(limpo.slice(4, 8));
    return partes.join('-');
  }

  function pedirCodigo(erro) {
    alvo().innerHTML = `
      <img class="auth-logo-topo" src="/assets/logos/casa-josefina.svg" alt="">
      <h1>Tenho um convite</h1>
      <p class="auth-sub">Digite o código que você recebeu.</p>
      <form id="form-codigo">
        <div class="campo">
          <input id="convite-codigo" type="text" inputmode="latin"
                 autocomplete="off" autocapitalize="characters" spellcheck="false"
                 placeholder="SOLO-XXXX-XXXX" class="campo-codigo" required>
        </div>
        <button type="submit" class="btn-marca" id="codigo-enviar">Continuar</button>
        <p id="codigo-erro" class="auth-erro"${erro ? '' : ' hidden'}>${escapar(erro || '')}</p>
        <p class="auth-sub" style="margin-top:1rem">
          <a href="/" id="voltar-login">Voltar para o login</a>
        </p>
      </form>`;

    const campo = document.getElementById('convite-codigo');
    campo.addEventListener('input', () => {
      const posicaoNoFim = campo.selectionStart === campo.value.length;
      campo.value = normalizar(campo.value);
      if (posicaoNoFim) campo.selectionStart = campo.selectionEnd = campo.value.length;
    });
    campo.focus();

    document.getElementById('voltar-login')
      .addEventListener('click', (ev) => { ev.preventDefault(); location.href = '/'; });

    document.getElementById('form-codigo').addEventListener('submit', (ev) => {
      ev.preventDefault();
      const codigo = normalizar(campo.value);
      if (codigo.length !== 14) {
        const el = document.getElementById('codigo-erro');
        el.textContent = 'O código tem o formato SOLO-XXXX-XXXX.';
        el.hidden = false;
        return;
      }
      // Vai pela URL, e não direto para a conferência: assim a pessoa pode
      // recarregar a página, e o link fica igual ao que teria recebido.
      location.hash = PREFIXO + '/' + codigo;
      conferir(codigo);
    });
  }

  async function conferir(codigo) {
    alvo().innerHTML = '<p class="auth-sub">Conferindo o convite…</p>';
    try {
      const d = await api.get('/convites/validar/' + encodeURIComponent(codigo));
      if (d && d.valido) desenhar(d);
      else recusar((d && d.motivo) || 'Este convite não pode ser usado.');
    } catch (erro) {
      recusar(erro.message || 'Não foi possível conferir o convite agora.');
    }
  }

  async function abrir() {
    const { nossa, codigo } = situacao();
    if (!nossa) return false;
    esconderTudo();
    if (codigo) await conferir(codigo);
    else pedirCodigo();
    return true;
  }

  /* O link "Criar meu acesso" na tela de login só muda o hash. Nesse momento
     o roteador do app ainda não existe — ele só começa depois do login —,
     então ninguém estaria ouvindo. Sem isto, o link não faria nada. */
  window.addEventListener('hashchange', () => {
    const { nossa } = situacao();
    const telaConvite = document.getElementById('tela-convite');
    if (nossa) {
      // Já estando na tela com um código conferido, não redesenhar por cima.
      if (telaConvite && !telaConvite.hidden && document.getElementById('form-convite')) return;
      abrir();
    } else if (telaConvite && !telaConvite.hidden) {
      // Saiu do convite sem ter entrado: volta para o login limpo.
      location.reload();
    }
  });

  window.AceitarConvite = { abrir, codigoDaUrl, normalizar, pedirCodigo };
})();
