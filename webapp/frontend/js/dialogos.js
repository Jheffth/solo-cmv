window.Dialogo = (function() {
  function criar(tipo, mensagem, opcoes = {}) {
    return new Promise((resolve) => {
      const overlay = document.createElement('div');
      overlay.style.position = 'fixed';
      overlay.style.top = '0';
      overlay.style.left = '0';
      overlay.style.width = '100vw';
      overlay.style.height = '100vh';
      overlay.style.backgroundColor = 'rgba(15, 23, 42, 0.4)';
      overlay.style.backdropFilter = 'blur(4px)';
      overlay.style.display = 'flex';
      overlay.style.alignItems = 'center';
      overlay.style.justifyContent = 'center';
      overlay.style.zIndex = '999999';
      overlay.style.opacity = '0';
      overlay.style.transition = 'opacity 0.2s ease-out';
      
      const card = document.createElement('div');
      card.className = 'card';
      card.style.maxWidth = '400px';
      card.style.width = '90%';
      card.style.padding = '24px';
      card.style.boxShadow = '0 20px 25px -5px rgba(0, 0, 0, 0.1), 0 10px 10px -5px rgba(0, 0, 0, 0.04)';
      card.style.transform = 'scale(0.95) translateY(10px)';
      card.style.transition = 'all 0.2s cubic-bezier(0.16, 1, 0.3, 1)';
      card.style.display = 'flex';
      card.style.flexDirection = 'column';
      card.style.gap = '16px';
      card.style.backgroundColor = 'var(--card, #FFFFFF)';
      card.style.borderRadius = 'var(--radius, 12px)';

      const texto = document.createElement('p');
      texto.style.margin = '0';
      texto.style.lineHeight = '1.5';
      texto.style.fontSize = '1rem';
      texto.style.color = 'var(--navy, #1F3B57)';
      texto.style.whiteSpace = 'pre-wrap';
      texto.textContent = mensagem;

      card.appendChild(texto);

      let input;
      if (tipo === 'prompt') {
        input = document.createElement('input');
        input.type = 'text';
        input.value = opcoes.padrao || '';
        input.style.width = '100%';
        input.style.padding = '10px 12px';
        input.style.border = '1px solid var(--border, #E3E6EA)';
        input.style.borderRadius = '8px';
        input.style.fontSize = '1rem';
        input.style.fontFamily = 'inherit';
        input.style.outline = 'none';
        input.style.backgroundColor = 'var(--bg, #F3F4F7)';
        input.addEventListener('focus', () => {
          input.style.borderColor = 'var(--navy, #1F3B57)';
          input.style.boxShadow = '0 0 0 2px rgba(31,59,87,0.1)';
        });
        input.addEventListener('blur', () => {
          input.style.borderColor = 'var(--border, #E3E6EA)';
          input.style.boxShadow = 'none';
        });
        card.appendChild(input);
      }

      const acoes = document.createElement('div');
      acoes.style.display = 'flex';
      acoes.style.justifyContent = 'flex-end';
      acoes.style.gap = '12px';
      acoes.style.marginTop = '8px';

      const fechar = (valor) => {
        overlay.style.opacity = '0';
        card.style.transform = 'scale(0.95) translateY(10px)';
        setTimeout(() => {
          if (document.body.contains(overlay)) document.body.removeChild(overlay);
          resolve(valor);
        }, 200);
      };

      const criarBotao = (textoBtn, primario, onClick) => {
        const btn = document.createElement('button');
        btn.textContent = textoBtn;
        btn.className = 'btn';
        btn.style.margin = '0';
        if (!primario) {
          btn.style.backgroundColor = 'transparent';
          btn.style.color = 'var(--muted, #6B7280)';
          btn.style.boxShadow = 'none';
          btn.style.padding = '0.6rem 1rem';
        } else {
          btn.style.backgroundColor = 'var(--navy, #1F3B57)';
        }
        btn.addEventListener('click', onClick);
        return btn;
      };

      if (tipo === 'alert') {
        acoes.appendChild(criarBotao('OK', true, () => fechar()));
      } else if (tipo === 'confirm') {
        acoes.appendChild(criarBotao('Cancelar', false, () => fechar(false)));
        const msgLow = mensagem.toLowerCase();
        const destrutivo = msgLow.includes('excluir') || msgLow.includes('descartar') || msgLow.includes('remover') || msgLow.includes('cancelar') || msgLow.includes('suspender') || msgLow.includes('desvincular');
        const confirma = criarBotao('Confirmar', true, () => fechar(true));
        if (destrutivo) confirma.style.backgroundColor = 'var(--red, #A6231F)';
        acoes.appendChild(confirma);
      } else if (tipo === 'prompt') {
        acoes.appendChild(criarBotao('Cancelar', false, () => fechar(null)));
        acoes.appendChild(criarBotao('Confirmar', true, () => fechar(input.value)));
      }

      card.appendChild(acoes);
      overlay.appendChild(card);
      document.body.appendChild(overlay);

      requestAnimationFrame(() => {
        overlay.style.opacity = '1';
        card.style.transform = 'scale(1) translateY(0)';
      });

      if (input) {
        setTimeout(() => input.focus(), 100);
        input.addEventListener('keydown', (e) => {
          if (e.key === 'Enter') fechar(input.value);
          if (e.key === 'Escape') fechar(null);
        });
      } else {
        const okBtn = acoes.lastChild;
        if (okBtn) {
          setTimeout(() => okBtn.focus(), 100);
          okBtn.addEventListener('keydown', (e) => {
            if (e.key === 'Escape') fechar(tipo === 'confirm' ? false : null);
          });
        }
      }
    });
  }

  return {
    alert: (msg) => criar('alert', msg),
    confirm: (msg) => criar('confirm', msg),
    prompt: (msg, def) => criar('prompt', msg, { padrao: def })
  };
})();