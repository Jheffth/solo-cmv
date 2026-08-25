/* ============================================================
   PERFIL — o que a própria pessoa mantém sobre si.

   Identidade aqui; poder na tela de Equipe. Papel, lojas e Regional
   aparecem, mas só para leitura: mudar a própria autoridade seria a
   hierarquia inteira virando decoração.

   A FOTO É REDUZIDA NO NAVEGADOR, ANTES DE SUBIR
   Uma foto de celular tem 3 a 5 MB. Subir isso para virar um círculo de
   40 pixels na barra lateral seria desperdício em três lugares: no envio
   (numa linha a 250 ms de distância), no banco, e em toda abertura de
   tela depois. O canvas corta no quadrado central e reduz a 256×256 —
   sobram uns 25 KB.

   Cortar pelo centro é escolha: a alternativa seria espremer a imagem, e
   rosto espremido fica estranho de um jeito que ninguém sabe nomear.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.perfil = (function () {
  const LADO = 256;
  let dados = null;
  let fotoNova = null;          // data URL escolhida nesta sessão de edição

  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  const iniciais = (nome) => (nome || '?').trim().split(/\s+/).slice(0, 2)
    .map((p) => p[0]).join('').toUpperCase();

  /* Reduz e corta no quadrado central. Devolve data URL JPEG. */
  function reduzir(arquivo) {
    return new Promise((resolve, reject) => {
      const leitor = new FileReader();
      leitor.onerror = () => reject(new Error('Não foi possível ler o arquivo.'));
      leitor.onload = () => {
        const img = new Image();
        img.onerror = () => reject(new Error('Este arquivo não é uma imagem.'));
        img.onload = () => {
          const lado = Math.min(img.width, img.height);
          const tela = document.createElement('canvas');
          tela.width = tela.height = LADO;
          tela.getContext('2d').drawImage(
            img,
            (img.width - lado) / 2, (img.height - lado) / 2, lado, lado,
            0, 0, LADO, LADO);
          // 0.82 é o joelho da curva: acima disso o arquivo cresce rápido
          // e a diferença não aparece num círculo de 40 pixels.
          resolve(tela.toDataURL('image/jpeg', 0.82));
        };
        img.src = leitor.result;
      };
      leitor.readAsDataURL(arquivo);
    });
  }

  function avatarHtml() {
    const foto = fotoNova || dados.avatar_url;
    if (foto) {
      return `<img src="${foto}" alt="Sua foto" class="perfil-foto">`;
    }
    return `<div class="perfil-foto perfil-foto--vazia">${escapar(iniciais(dados.nome))}</div>`;
  }

  function acessoHtml() {
    const a = dados.acesso;
    const lojas = a.todas_as_unidades
      ? '<span class="tag regional">todas as lojas</span>'
      : (a.unidades || []).map((u) => `<span class="tag">${escapar(u.nome)}</span>`).join(' ')
        || '<span class="tag alerta">nenhuma</span>';
    return `
      <div class="card">
        <h3 class="card-titulo">Seu acesso</h3>
        <p class="card-sub">Isto não se edita aqui. Cargo e lojas são definidos
           por quem administra a equipe.</p>
        <div class="perfil-acesso">
          <div><span>Cargo</span><strong>${escapar(a.papel_rotulo)}</strong></div>
          <div><span>Lojas</span><span class="celula-escopo">${lojas}</span></div>
          <div><span>Regional</span><strong>${a.acesso_regional ? 'sim' : 'não'}</strong></div>
        </div>
      </div>`;
  }

  function render(container) {
    container.innerHTML = `
      <p id="perfil-aviso" hidden></p>

      <div class="card perfil-cabecalho">
        <div class="perfil-foto-area">
          ${avatarHtml()}
          <div class="perfil-foto-acoes">
            <label class="btn secundario" for="perfil-arquivo">Escolher foto</label>
            <input type="file" id="perfil-arquivo" accept="image/*" hidden>
            ${(fotoNova || dados.avatar_url)
              ? '<button type="button" class="btn-acao btn-perigo" id="perfil-tirar-foto">Remover</button>'
              : ''}
            <small class="form-dica">A imagem é reduzida a ${LADO}×${LADO} aqui
              no navegador antes de ser enviada.</small>
          </div>
        </div>
        <div class="perfil-identidade">
          <h2>${escapar(dados.apelido || dados.nome)}</h2>
          <p class="nota-formula">
            ${escapar(dados.login)} · ${escapar(dados.acesso.papel_rotulo)}
          </p>
        </div>
      </div>

      <div class="card">
        <h3 class="card-titulo">Seus dados</h3>
        <form id="form-perfil">
          <div class="form-linha">
            <div class="form-group">
              <label for="perfil-nome">Nome completo</label>
              <input id="perfil-nome" type="text" required maxlength="120"
                     value="${escapar(dados.nome)}">
            </div>
            <div class="form-group">
              <label for="perfil-apelido">Como quer ser chamado</label>
              <input id="perfil-apelido" type="text" maxlength="60"
                     placeholder="opcional" value="${escapar(dados.apelido || '')}">
            </div>
          </div>
          <div class="form-linha">
            <div class="form-group">
              <label for="perfil-telefone">Telefone</label>
              <input id="perfil-telefone" type="tel" maxlength="30"
                     placeholder="(61) 99999-0000" value="${escapar(dados.telefone || '')}">
            </div>
            <div class="form-group">
              <label>Usuário</label>
              <input type="text" value="${escapar(dados.login)}" disabled
                     title="O usuário não muda: ele identifica você no histórico
                            de tudo que já lançou">
            </div>
          </div>
          <button type="submit" class="btn btn-primario" id="perfil-salvar">Salvar</button>
          <p id="perfil-erro" class="login-erro" hidden></p>
        </form>
      </div>

      ${acessoHtml()}

      <div class="card">
        <h3 class="card-titulo">Trocar senha</h3>
        <p class="card-sub">Pedimos a senha atual mesmo com você já conectado —
           sessão aberta prova que alguém entrou, não que é você agora.</p>
        <form id="form-senha">
          <div class="form-linha">
            <div class="form-group">
              <label for="senha-atual">Senha atual</label>
              <input id="senha-atual" type="password" autocomplete="current-password" required>
            </div>
            <div class="form-group">
              <label for="senha-nova">Senha nova</label>
              <input id="senha-nova" type="password" autocomplete="new-password"
                     required minlength="${dados.senha_minima}">
              <small class="form-dica">Ao menos ${dados.senha_minima} caracteres.</small>
            </div>
          </div>
          <button type="submit" class="btn" id="senha-salvar">Trocar senha</button>
          <p id="senha-erro" class="login-erro" hidden></p>
        </form>
      </div>`;

    ligar(container);
  }

  function avisar(container, texto, erro) {
    const el = container.querySelector('#perfil-aviso');
    el.textContent = texto;
    el.className = erro ? 'login-erro' : 'aviso-sucesso';
    el.hidden = false;
  }

  function ligar(container) {
    const arquivo = container.querySelector('#perfil-arquivo');
    arquivo.addEventListener('change', async () => {
      if (!arquivo.files || !arquivo.files[0]) return;
      try {
        fotoNova = await reduzir(arquivo.files[0]);
        render(container);
        avisar(container, 'Foto escolhida. Clique em Salvar para guardar.', false);
      } catch (erro) {
        avisar(container, erro.message, true);
      }
    });

    const tirar = container.querySelector('#perfil-tirar-foto');
    if (tirar) {
      tirar.addEventListener('click', async () => {
        if (fotoNova) {
          // Ainda não foi salva: basta esquecer, sem falar com o servidor.
          fotoNova = null;
          render(container);
          return;
        }
        if (!confirm('Remover sua foto?')) return;
        dados = await api.del('/perfil/foto');
        atualizarBarraLateral();
        render(container);
        avisar(container, 'Foto removida.', false);
      });
    }

    container.querySelector('#form-perfil').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const erroEl = container.querySelector('#perfil-erro');
      const botao = container.querySelector('#perfil-salvar');
      erroEl.hidden = true;
      botao.disabled = true;
      try {
        dados = await api.put('/perfil', {
          nome: container.querySelector('#perfil-nome').value.trim(),
          apelido: container.querySelector('#perfil-apelido').value.trim() || null,
          telefone: container.querySelector('#perfil-telefone').value.trim() || null,
          // Sem foto nova, manda a que já estava: o backend guarda o que
          // receber, e mandar nulo aqui apagaria a foto sem ninguém pedir.
          avatar_url: fotoNova || dados.avatar_url || null,
        });
        fotoNova = null;
        atualizarBarraLateral();
        render(container);
        avisar(container, 'Perfil salvo.', false);
      } catch (erro) {
        erroEl.textContent = erro.message || 'Não foi possível salvar.';
        erroEl.hidden = false;
        botao.disabled = false;
      }
    });

    container.querySelector('#form-senha').addEventListener('submit', async (ev) => {
      ev.preventDefault();
      const erroEl = container.querySelector('#senha-erro');
      const botao = container.querySelector('#senha-salvar');
      erroEl.hidden = true;
      botao.disabled = true;
      try {
        const r = await api.put('/perfil/senha', {
          senha_atual: container.querySelector('#senha-atual').value,
          senha_nova: container.querySelector('#senha-nova').value,
        });
        // Derrubar a própria sessão é o sinal honesto de que a troca valeu:
        // quem trocou por desconfiar de acesso indevido espera exatamente
        // que as sessões abertas caiam.
        alert(r.mensagem || 'Senha alterada. Entre de novo.');
        if (typeof fazerLogout === 'function') fazerLogout();
        else location.href = '/';
      } catch (erro) {
        erroEl.textContent = erro.message || 'Não foi possível trocar a senha.';
        erroEl.hidden = false;
        botao.disabled = false;
      }
    });
  }

  /* A barra lateral mostra nome e foto. Sem isto, salvar o perfil só
     apareceria depois de recarregar a página — e a pessoa acharia que
     não salvou. */
  function atualizarBarraLateral() {
    if (!window.USUARIO_ATUAL) return;
    USUARIO_ATUAL.nome = dados.nome;
    USUARIO_ATUAL.apelido = dados.apelido;
    USUARIO_ATUAL.avatar_url = dados.avatar_url;
    if (typeof preencherTopbarUsuario === 'function') preencherTopbarUsuario();
  }

  return {
    async render(container) {
      fotoNova = null;
      dados = await api.get('/perfil');
      render(container);
    },
  };
})();
