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

  /* O código aparece NA TELA e some sozinho. Não vai por e-mail nem por
     mensagem: um código de vínculo encaminhado é um vínculo entregue a
     outra pessoa. Ele vale 10 minutos porque essa é a janela em que alguém
     está com o celular na mão, olhando para esta tela. */
  function telegramHtml() {
    const t = dados.telegram || {};
    if (t.vinculado) {
      const desde = t.desde ? t.desde.slice(0, 10).split('-').reverse().join('/') : '';
      return `
        <div class="card">
          <h3 class="card-titulo">Telegram</h3>
          <div class="perfil-acesso">
            <div><span>Situação</span><strong>conectado${t.username ? ' · @' + escapar(t.username) : ''}</strong></div>
            ${desde ? `<div><span>Desde</span><strong>${desde}</strong></div>` : ''}
          </div>
          <p class="card-sub">Perdeu o celular? Desvincular corta o acesso do
             bot agora — não quando a sessão vencer.</p>
          <button type="button" class="btn-acao btn-perigo" id="tg-desvincular">
            Desvincular
          </button>
        </div>`;
    }
    return `
      <div class="card">
        <h3 class="card-titulo">Telegram</h3>
        <p class="card-sub">Conte inventário, registre perda e peça itens pelo
           celular, sem abrir o sistema.</p>
        <div id="tg-codigo-area"></div>
        <button type="button" class="btn secundario" id="tg-vincular">
          Vincular Telegram
        </button>
      </div>`;
  }

  function whatsappHtml() {
    const w = dados.whatsapp || {};
    const papel = dados.acesso ? dados.acesso.papel : '';
    const ehGestor = papel === 'ARQUITETO' || papel === 'DIRETOR';

    let corpo = '';
    if (w.vinculado) {
      const desde = w.desde ? w.desde.slice(0, 10).split('-').reverse().join('/') : '';
      corpo = `
        <div class="perfil-acesso">
          <div><span>Situação</span><strong>conectado · +${escapar(w.numero)}</strong></div>
          ${desde ? `<div><span>Desde</span><strong>${desde}</strong></div>` : ''}
        </div>
        <p class="card-sub">Perdeu o celular? Desvincular corta o acesso do bot agora.</p>
        <button type="button" class="btn-acao btn-perigo" id="wpp-desvincular">
          Desvincular WhatsApp
        </button>
      `;
    } else {
      corpo = `
        <p class="card-sub">Receba alertas, lance perdas, requisições e consulte CMV direto no WhatsApp.</p>
        <div id="wpp-codigo-area"></div>
        <button type="button" class="btn secundario" id="wpp-vincular">
          Vincular WhatsApp
        </button>
      `;
    }

    let qrSecao = '';
    if (ehGestor) {
      qrSecao = `
        <div style="margin-top: 1.2rem; padding-top: 1rem; border-top: 1px solid var(--borda, #e5e7eb);">
          <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:.5rem;">
            <small class="form-dica">
              WhatsApp Central da Empresa: <strong id="wpp-badge-status">${w.instancia_conectada ? '🟢 Conectado' : '🔴 Desconectado'}</strong>
            </small>
            <button type="button" class="btn-acao" id="wpp-abrir-qrcode">
              ${w.instancia_conectada ? 'Reconectar / QR Code' : 'Escanear QR Code do Sistema'}
            </button>
          </div>
          <div id="wpp-qrcode-container" hidden></div>
        </div>
      `;
    }

    return `
      <div class="card">
        <h3 class="card-titulo">WhatsApp (Evolution API)</h3>
        ${corpo}
        ${qrSecao}
      </div>`;
  }

  function ligarWhatsapp(container) {
    const pedir = container.querySelector('#wpp-vincular');
    if (pedir) {
      pedir.addEventListener('click', async () => {
        pedir.disabled = true;
        try {
          const r = await api.post('/whatsapp/codigo');
          container.querySelector('#wpp-codigo-area').innerHTML = `
            <div class="wpp-codigo">
              <strong>${r.codigo}</strong>
              <p>No WhatsApp da empresa, envie:<br>
                 <code>/vincular ${r.codigo}</code></p>
              <small>Vale ${r.minutos} minutos e serve uma vez só.</small>
            </div>`;
          pedir.textContent = 'Gerar outro código';
        } finally {
          pedir.disabled = false;
        }
      });
    }

    const cortar = container.querySelector('#wpp-desvincular');
    if (cortar) {
      cortar.addEventListener('click', async () => {
        if (!confirm('Desvincular o WhatsApp? O bot para de responder agora.')) return;
        await api.del('/whatsapp/vinculo');
        await window.Paginas.perfil.render(container);
      });
    }

    const badgeStatus = container.querySelector('#wpp-badge-status');
    const pollerStatusGeral = setInterval(async () => {
      if (!document.body.contains(container)) {
        clearInterval(pollerStatusGeral);
        return;
      }
      try {
        const st = await api.get('/whatsapp/status');
        if (badgeStatus) {
          badgeStatus.textContent = st.instancia_conectada ? '🟢 Conectado' : '🔴 Desconectado';
        }
        if (st.vinculado !== (dados.whatsapp && dados.whatsapp.vinculado)) {
          clearInterval(pollerStatusGeral);
          await window.Paginas.perfil.render(container);
        }
      } catch (_) {}
    }, 4000);

    let intervaloQr = null;

    const abrirQr = container.querySelector('#wpp-abrir-qrcode');
    if (abrirQr) {
      abrirQr.addEventListener('click', async () => {
        const qrc = container.querySelector('#wpp-qrcode-container');
        if (!qrc.hidden && intervaloQr) {
          clearInterval(intervaloQr);
          intervaloQr = null;
          qrc.hidden = true;
          return;
        }

        let containerEstruturado = false;

        qrc.hidden = false;
        qrc.innerHTML = `
          <div class="qrcode-box" id="wpp-box-content">
            <p id="wpp-box-instrucao" style="margin-bottom:.8rem; font-weight:600;">Abra o WhatsApp no celular › Aparelhos conectados › Conectar aparelho:</p>
            
            <div id="wpp-img-wrapper" style="min-height: 290px; display: flex; align-items: center; justify-content: center;">
              <p id="wpp-loading-txt" style="color: #6b7280;">Carregando QR Code da Evolution API...</p>
              <img id="wpp-qrcode-img" alt="QR Code WhatsApp" style="display:none; max-width:320px; width:100%; margin:0 auto; padding:14px; background:#ffffff; border:2px solid #cbd5e1; border-radius:12px; box-shadow: 0 10px 15px -3px rgba(0,0,0,.1);">
            </div>
            
            <div style="display:flex; justify-content:center; gap:.5rem; margin-top:.8rem;">
              <button type="button" class="btn-acao" id="wpp-btn-manual-refresh" style="font-size:.82rem; padding:.3rem .7rem;">
                🔄 Atualizar QR Code
              </button>
            </div>

            <div style="margin-top:1.2rem; padding-top:1rem; border-top:1px dashed #e5e7eb;">
              <p style="font-size:.85rem; margin-bottom:.5rem;"><strong>Prefere conectar por código no celular sem câmera?</strong></p>
              <div style="display:flex; gap:.5rem; justify-content:center; max-width:320px; margin:0 auto;">
                <input type="tel" id="wpp-input-tel-bot" placeholder="55 + DDD + Número" style="padding:.4rem .6rem; font-size:.85rem; border:1px solid #ccc; border-radius:6px; flex:1;">
                <button type="button" class="btn-acao" id="wpp-btn-gerar-pairing">Gerar Código</button>
              </div>
              <div id="wpp-pairing-box" style="margin-top:.6rem;"></div>
            </div>
          </div>`;

        const imgEl = qrc.querySelector('#wpp-qrcode-img');
        const loadTxt = qrc.querySelector('#wpp-loading-txt');
        const btnManual = qrc.querySelector('#wpp-btn-manual-refresh');
        const btnPairing = qrc.querySelector('#wpp-btn-gerar-pairing');
        const inTel = qrc.querySelector('#wpp-input-tel-bot');
        const pairBox = qrc.querySelector('#wpp-pairing-box');

        let intervaloStatus = null;

        if (btnManual) {
          btnManual.addEventListener('click', async () => {
            btnManual.disabled = true;
            btnManual.textContent = 'Atualizando...';
            await api.post('/whatsapp/reiniciar').catch(() => {});
            await carregarQr();
            btnManual.disabled = false;
            btnManual.textContent = '🔄 Atualizar QR Code';
          });
        }

        if (btnPairing && inTel) {
          btnPairing.addEventListener('click', async () => {
            const num = inTel.value.trim().replace(/\D/g, '');
            if (!num || num.length < 10) {
              pairBox.innerHTML = '<span style="color:red; font-size:.82rem;">Digite o número com DDD (ex: 5561999998888)</span>';
              return;
            }
            
            // Pausa imediatamente qualquer atualização de QR Code para não sobrescrever o código
            if (intervaloQr) {
              clearInterval(intervaloQr);
              intervaloQr = null;
            }

            btnPairing.disabled = true;
            btnPairing.textContent = 'Gerando...';
            pairBox.innerHTML = '<p style="color:#6b7280; font-size:.85rem; margin-top:.4rem;">Solicitando código de 8 dígitos ao WhatsApp...</p>';

            try {
              const rCode = await api.get(`/whatsapp/qrcode?numero=${num}`);
              const codRaw = (rCode.pairing_code || rCode.code || '').trim();
              if (codRaw) {
                // Formata o código com espaço ou hífen para facilitar leitura (ex: ABCD-1234)
                let codFormatado = codRaw;
                if (codRaw.length === 8 && !codRaw.includes('-')) {
                  codFormatado = codRaw.slice(0, 4) + ' - ' + codRaw.slice(4);
                }

                pairBox.innerHTML = `
                  <div style="background:#f0fdf4; border:2px solid #10b981; border-radius:8px; padding:1rem; margin-top:.6rem; text-align:center;">
                    <p style="font-size:.9rem; margin:0 0 .5rem; color:#065f46; font-weight:600;">
                      No celular: <em>Aparelhos conectados › Conectar com número de telefone</em>
                    </p>
                    <div style="font-size:1.8rem; font-weight:bold; letter-spacing:.2em; color:#047857; font-family:monospace; margin:.5rem 0; padding:.5rem; background:#fff; border:1px dashed #10b981; border-radius:6px; user-select:all;">
                      ${escapar(codFormatado)}
                    </div>
                    <p style="font-size:.8rem; color:#4b5563; margin:0;">
                      ⏳ O código fica fixo aqui. Digite no WhatsApp do celular com calma.
                    </p>
                  </div>`;

                // Monitora apenas o status silenciosamente até o WhatsApp conectar
                if (intervaloStatus) clearInterval(intervaloStatus);
                intervaloStatus = setInterval(async () => {
                  try {
                    const st = await api.get('/whatsapp/status');
                    if (st.instancia_conectada) {
                      clearInterval(intervaloStatus);
                      await window.Paginas.perfil.render(container);
                    }
                  } catch (_) {}
                }, 4000);

              } else {
                pairBox.innerHTML = '<span style="color:red; font-size:.82rem;">Não foi possível gerar o código. Verifique se o número está correto (ex: 5561999998888).</span>';
              }
            } catch (ePair) {
              pairBox.innerHTML = `<span style="color:red; font-size:.82rem;">${ePair.message || 'Erro ao gerar código.'}</span>`;
            } finally {
              btnPairing.disabled = false;
              btnPairing.textContent = 'Gerar Código';
            }
          });
        }

        async function carregarQr() {
          try {
            const res = await api.get('/whatsapp/qrcode');
            if (res.base64) {
              const srcImg = res.base64.startsWith('data:') ? res.base64 : 'data:image/png;base64,' + res.base64;
              imgEl.src = srcImg;
              imgEl.style.display = 'block';
              loadTxt.style.display = 'none';
            }
            if (res.estado === 'open' || res.conectado) {
              if (intervaloQr) clearInterval(intervaloQr);
              if (intervaloStatus) clearInterval(intervaloStatus);
              await window.Paginas.perfil.render(container);
            }
          } catch (e) {
            if (!imgEl.src) {
              loadTxt.textContent = e.message || 'Tentando carregar conexão...';
            }
          }
        }

        // DE 10 EM 10 SEGUNDOS, e não de 30 em 30.
        //
        // O QR do WhatsApp vive ~20 segundos. Buscando a cada 30, o código na
        // tela já nasce vencido — e escanear um vencido não dá erro nenhum:
        // o celular lê, aceita, e o servidor descartou a vaga. Foi por isso
        // que "aparece mas não conecta" resistiu a mexer em tamanho e
        // contraste da imagem. O problema nunca esteve na imagem.
        await carregarQr();
        intervaloQr = setInterval(carregarQr, 10000);
      });
    }
  }

  function ligarTelegram(container) {
    const pedir = container.querySelector('#tg-vincular');
    if (pedir) {
      pedir.addEventListener('click', async () => {
        pedir.disabled = true;
        try {
          const r = await api.post('/telegram/codigo');
          container.querySelector('#tg-codigo-area').innerHTML = `
            <div class="tg-codigo">
              <strong>${r.codigo}</strong>
              <p>No Telegram, mande para o bot:<br>
                 <code>/vincular ${r.codigo}</code></p>
              <small>Vale ${r.minutos} minutos e serve uma vez.
                Nunca mande sua senha pelo chat — nem para o bot.</small>
            </div>`;
          pedir.textContent = 'Gerar outro código';
        } finally {
          pedir.disabled = false;
        }
      });
    }

    const cortar = container.querySelector('#tg-desvincular');
    if (cortar) {
      cortar.addEventListener('click', async () => {
        // Confirmação porque é destrutivo e silencioso: sem ela, um toque
        // errado tira o acesso e a pessoa só descobre na câmara fria.
        if (!confirm('Desvincular o Telegram? O bot para de responder agora.')) return;
        await api.del('/telegram/vinculo');
        await window.Paginas.perfil.render(container);
      });
    }
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
      ${telegramHtml()}
      ${whatsappHtml()}

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
      // Três chamadas em paralelo, não em fila: são independentes
      const [perfil, telegram, whatsapp] = await Promise.all([
        api.get('/perfil'),
        api.get('/telegram/status').catch(() => ({ vinculado: false })),
        api.get('/whatsapp/status').catch(() => ({ vinculado: false, instancia_conectada: false })),
      ]);
      dados = perfil;
      dados.telegram = telegram;
      dados.whatsapp = whatsapp;
      render(container);
      ligarTelegram(container);
      ligarWhatsapp(container);
    },
  };
})();
