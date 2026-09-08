/* ============================================================
   NOTAS FISCAIS — da chave ao estoque, com conferência no meio.

   TRÊS PORTAS, UM CORREDOR
   A nota chega de três jeitos: digitada, fotografada ou como arquivo. O que
   muda é só a entrada — da conferência em diante é tudo igual, e por isso
   `desenharNota` é uma função só.

   O CAMPO DA CHAVE CONFERE ENQUANTO SE DIGITA
   Os 44 dígitos têm um verificador embutido. Conferir no navegador, antes
   de qualquer botão, é o que transforma "digitei errado e não sei onde" em
   um aviso na hora — e evita ir buscar a nota de OUTRA empresa, que é o
   erro caro: ele não dá mensagem nenhuma, só lança compra errada.
   ============================================================ */
window.Paginas = window.Paginas || {};

window.Paginas.nfe = (function () {
  let notaAtual = null;
  let produtos = [];

  const brl = (v) => (v == null ? '—' : 'R$ ' + Number(v).toLocaleString(
    'pt-BR', { minimumFractionDigits: 2, maximumFractionDigits: 2 }));
  const num = (v) => Number(v || 0).toLocaleString('pt-BR', { maximumFractionDigits: 4 });
  const escapar = (t) => String(t == null ? '' : t)
    .replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');

  /* O MESMO módulo 11 do backend, e a repetição é deliberada.

     Regra duplicada costuma ser defeito; aqui não é, porque as duas cópias
     respondem a perguntas diferentes: esta dá resposta INSTANTÂNEA enquanto
     a pessoa digita, sem viagem à rede. A do servidor é quem decide — se as
     duas discordarem, vale a dele, e o pior que acontece é um aviso a mais
     na tela. É a única duplicação aceitável do projeto, e o motivo está
     aqui para quem for tentar "limpar" isto depois. */
  function chaveValida(bruta) {
    const d = (bruta || '').replace(/\D/g, '');
    if (d.length !== 44) return false;
    let soma = 0, peso = 2;
    for (let i = 42; i >= 0; i--) {
      soma += Number(d[i]) * peso;
      peso = peso === 9 ? 2 : peso + 1;
    }
    const resto = soma % 11;
    return String(resto < 2 ? 0 : 11 - resto) === d[43];
  }

  const formatarChave = (bruta) =>
    ((bruta || '').replace(/\D/g, '').slice(0, 44).match(/.{1,4}/g) || []).join(' ');

  // ---------------------------------------------------------------- entrada
  function html() {
    return `
      <div class="pagina-cabecalho">
        <h2>Notas fiscais</h2>
        <p class="subtitulo">Importe uma compra a partir da nota do fornecedor.</p>
      </div>

      <div class="card nfe-entrada">
        <div class="nfe-abas">
          <button class="nfe-aba ativa" data-aba="chave" type="button">Digitar a chave</button>
          <button class="nfe-aba" data-aba="foto" type="button">Foto da nota</button>
          <button class="nfe-aba" data-aba="xml" type="button">Arquivo XML</button>
        </div>

        <div class="nfe-painel" data-painel="chave">
          <label for="nfe-chave">Chave de acesso — os 44 números embaixo do código de barras</label>
          <input id="nfe-chave" class="nfe-campo-chave" type="text" inputmode="numeric"
                 autocomplete="off" spellcheck="false"
                 placeholder="0000 0000 0000 0000 0000 0000 0000 0000 0000 0000 0000">
          <div id="nfe-chave-retorno" class="nfe-retorno"></div>
          <div class="nfe-acoes">
            <button class="btn btn-primario" id="nfe-consultar" type="button" disabled>
              Consultar</button>
          </div>
        </div>

        <div class="nfe-painel" data-painel="foto" hidden>
          <p class="nfe-dica">Fotografe o código de barras de perto, com a nota
             esticada. Se não der, digite os números à mão.</p>
          <input id="nfe-foto" type="file" accept="image/*" capture="environment">
          <div id="nfe-foto-retorno" class="nfe-retorno"></div>
        </div>

        <div class="nfe-painel" data-painel="xml" hidden>
          <p class="nfe-dica">O arquivo que o contador manda. É o caminho que
             traz os itens com valor e imposto — sem depender de certificado.</p>
          <input id="nfe-xml" type="file" accept=".xml,text/xml,application/xml">
          <div id="nfe-xml-retorno" class="nfe-retorno"></div>
        </div>
      </div>

      <div id="nfe-conferencia"></div>

      <div class="card">
        <h3 class="card-titulo">Últimas notas</h3>
        <div id="nfe-lista"><p class="estado-vazio">Carregando…</p></div>
      </div>`;
  }

  // ------------------------------------------------------------- conferência
  function linhaItem(item) {
    const opcoes = produtos.map((p) =>
      `<option value="${p.id}"${p.id === item.produto_id ? ' selected' : ''}>
         ${escapar(p.nome)}${p.unidade_medida ? ' (' + escapar(p.unidade_medida) + ')' : ''}
       </option>`).join('');

    // O acréscimo ganha destaque porque é a informação que ninguém espera:
    // o custo real acima do valor impresso na nota.
    const extra = item.acrescimos > 0
      ? `<span class="nfe-acrescimo" title="ICMS ST, frete e outras despesas que entram no custo">
           +${brl(item.acrescimos)}</span>` : '';

    return `
      <tr class="${item.ignorar ? 'nfe-ignorado' : ''}" data-item="${item.id}">
        <td>
          <strong>${escapar(item.descricao)}</strong>
          <small class="nfe-codigo">cód. ${escapar(item.codigo_fornecedor || '—')}</small>
        </td>
        <td class="num">${num(item.quantidade_nota)} ${escapar(item.unidade_nota || '')}</td>
        <td class="num">${brl(item.valor_unitario_nota)}${extra}</td>
        <td>
          <select class="nfe-produto" data-item="${item.id}">
            <option value="">— escolher produto —</option>
            ${opcoes}
          </select>
        </td>
        <td class="num">
          <input class="nfe-fator" type="number" step="0.0001" min="0.0001"
                 value="${item.fator_conversao}" data-item="${item.id}"
                 title="Quantas unidades nossas cabem numa unidade da nota">
        </td>
        <td class="num nfe-final">
          ${item.produto_id
            ? `<strong>${num(item.quantidade_final)}</strong> ${escapar(item.produto_unidade || '')}
               <small>${brl(item.custo_final)} / un</small>`
            : '<span class="zerado">—</span>'}
        </td>
        <td class="num">
          <button class="btn-acao nfe-ignorar" data-item="${item.id}" type="button">
            ${item.ignorar ? 'Considerar' : 'Ignorar'}</button>
        </td>
      </tr>`;
  }

  function desenharNota(container, nota) {
    notaAtual = nota;
    const alvo = container.querySelector('#nfe-conferencia');
    if (!nota) { alvo.innerHTML = ''; return; }

    const avisos = (nota.avisos || []).map((a) =>
      `<p class="nfe-aviso">${escapar(a)}</p>`).join('');

    const pendencia = nota.itens_sem_produto > 0
      ? `<p class="nfe-aviso nfe-aviso--acao">${nota.itens_sem_produto} item(ns)
           ainda sem produto escolhido. Escolha ou marque para ignorar.</p>`
      : '';

    alvo.innerHTML = `
      <div class="card">
        <div class="nfe-cabecalho">
          <div>
            <h3 class="card-titulo">${escapar(nota.emitente || 'Nota')}</h3>
            <p class="subtitulo">
              Nota ${escapar(nota.numero)}/${escapar(nota.serie)} ·
              ${nota.emissao ? nota.emissao.split('-').reverse().join('/') : '—'} ·
              ${brl(nota.valor_total)}
            </p>
          </div>
          <span class="status-badge">${escapar(nota.status)}</span>
        </div>

        ${avisos}${pendencia}

        <div class="tabela-rolavel">
          <table class="tabela-simples">
            <thead><tr>
              <th>Item na nota</th><th class="num">Qtd.</th><th class="num">V. unit.</th>
              <th>Nosso produto</th><th class="num">Fator</th>
              <th class="num">Entra no estoque</th><th></th>
            </tr></thead>
            <tbody>${nota.itens.map(linhaItem).join('')}</tbody>
          </table>
        </div>

        <div class="nfe-acoes">
          <button class="btn btn-primario" id="nfe-aprovar" type="button"
                  ${nota.pronta_para_aprovar && nota.status !== 'PROCESSADA' ? '' : 'disabled'}>
            Lançar no estoque</button>
          <button class="btn" id="nfe-descartar" type="button">Descartar</button>
        </div>
      </div>`;

    ligarConferencia(container);
  }

  async function ajustar(container, itemId, corpo) {
    try {
      const nova = await api.put(`/nfe/${notaAtual.id}/item/${itemId}`, corpo);
      desenharNota(container, nova);
    } catch (erro) {
      alert(erro.message || 'Não foi possível ajustar o item.');
    }
  }

  function ligarConferencia(container) {
    container.querySelectorAll('.nfe-produto').forEach((sel) => {
      sel.addEventListener('change', () => ajustar(
        container, sel.dataset.item,
        { produto_id: sel.value ? Number(sel.value) : null }));
    });
    container.querySelectorAll('.nfe-fator').forEach((campo) => {
      campo.addEventListener('change', () => ajustar(
        container, campo.dataset.item,
        { fator_conversao: Number(campo.value) }));
    });
    container.querySelectorAll('.nfe-ignorar').forEach((botao) => {
      botao.addEventListener('click', () => {
        const item = notaAtual.itens.find((i) => String(i.id) === botao.dataset.item);
        ajustar(container, botao.dataset.item, { ignorar: !item.ignorar });
      });
    });

    const aprovar = container.querySelector('#nfe-aprovar');
    if (aprovar) {
      aprovar.addEventListener('click', async () => {
        aprovar.disabled = true;
        aprovar.textContent = 'Lançando…';
        try {
          const r = await api.post(`/nfe/${notaAtual.id}/aprovar`);
          alert(r.mensagem || 'Nota lançada.');
          notaAtual = null;
          container.querySelector('#nfe-conferencia').innerHTML = '';
          await carregarLista(container);
        } catch (erro) {
          alert(erro.message || 'Não foi possível lançar.');
          aprovar.disabled = false;
          aprovar.textContent = 'Lançar no estoque';
        }
      });
    }

    const descartar = container.querySelector('#nfe-descartar');
    if (descartar) {
      descartar.addEventListener('click', async () => {
        if (!confirm('Descartar esta nota? Ela fica no histórico, sem virar compra.')) return;
        await api.post(`/nfe/${notaAtual.id}/descartar`);
        notaAtual = null;
        container.querySelector('#nfe-conferencia').innerHTML = '';
        await carregarLista(container);
      });
    }
  }

  // ------------------------------------------------------------------- lista
  async function carregarLista(container) {
    const alvo = container.querySelector('#nfe-lista');
    const notas = await api.get('/nfe?unidade_id=' + UNIDADE_SELECIONADA);
    if (!notas.length) {
      alvo.innerHTML = '<p class="estado-vazio">Nenhuma nota importada ainda.</p>';
      return;
    }
    alvo.innerHTML = `
      <table class="tabela-simples">
        <thead><tr><th>Fornecedor</th><th>Nota</th><th>Emissão</th>
          <th class="num">Valor</th><th>Situação</th><th></th></tr></thead>
        <tbody>${notas.map((n) => `
          <tr>
            <td>${escapar(n.emitente || '—')}</td>
            <td>${escapar(n.numero || '—')}</td>
            <td>${n.emissao ? n.emissao.split('-').reverse().join('/') : '—'}</td>
            <td class="num">${brl(n.valor_total)}</td>
            <td><span class="status-badge">${escapar(n.status)}</span></td>
            <td class="num">
              <button class="btn-acao nfe-abrir" data-nota="${n.id}" type="button">Abrir</button>
            </td>
          </tr>`).join('')}</tbody>
      </table>`;

    alvo.querySelectorAll('.nfe-abrir').forEach((b) => {
      b.addEventListener('click', async () => {
        desenharNota(container, await api.get('/nfe/' + b.dataset.nota));
        container.querySelector('#nfe-conferencia').scrollIntoView({ behavior: 'smooth' });
      });
    });
  }

  // ----------------------------------------------------------------- ligação
  function ligarEntrada(container) {
    container.querySelectorAll('.nfe-aba').forEach((aba) => {
      aba.addEventListener('click', () => {
        container.querySelectorAll('.nfe-aba').forEach((a) =>
          a.classList.toggle('ativa', a === aba));
        container.querySelectorAll('.nfe-painel').forEach((p) => {
          p.hidden = p.dataset.painel !== aba.dataset.aba;
        });
      });
    });

    const campo = container.querySelector('#nfe-chave');
    const retorno = container.querySelector('#nfe-chave-retorno');
    const consultar = container.querySelector('#nfe-consultar');

    campo.addEventListener('input', () => {
      const noFim = campo.selectionStart === campo.value.length;
      campo.value = formatarChave(campo.value);
      if (noFim) campo.selectionStart = campo.selectionEnd = campo.value.length;

      const digitos = campo.value.replace(/\D/g, '');
      consultar.disabled = true;
      if (!digitos) { retorno.innerHTML = ''; return; }
      if (digitos.length < 44) {
        retorno.innerHTML = `<span class="nfe-contando">${digitos.length} de 44</span>`;
        return;
      }
      if (!chaveValida(digitos)) {
        retorno.innerHTML = `<span class="nfe-erro">Essa chave não passa na
          conferência — algum número está trocado.</span>`;
        return;
      }
      retorno.innerHTML = '<span class="nfe-contando">Conferindo…</span>';
      identificar(container, digitos);
    });

    consultar.addEventListener('click', async () => {
      consultar.disabled = true;
      consultar.textContent = 'Consultando…';
      try {
        const nota = await api.post('/nfe/consultar', {
          chave: campo.value.replace(/\D/g, ''),
          unidade_id: Number(UNIDADE_SELECIONADA),
        });
        desenharNota(container, nota);
      } catch (erro) {
        // A recusa da SEFAZ é longa e explicativa de propósito — ela diz o
        // que falta e qual caminho funciona hoje. Cortar em alert() jogaria
        // fora justamente a parte útil.
        retorno.innerHTML = `<div class="nfe-erro nfe-erro--bloco">${
          escapar(erro.message || 'Não foi possível consultar.')
            .replace(/\n\n/g, '<br><br>')}</div>`;
      } finally {
        consultar.disabled = false;
        consultar.textContent = 'Consultar';
      }
    });

    container.querySelector('#nfe-foto').addEventListener('change', async (ev) => {
      const arquivo = ev.target.files[0];
      if (!arquivo) return;
      const alvo = container.querySelector('#nfe-foto-retorno');
      alvo.innerHTML = '<span class="nfe-contando">Procurando a chave…</span>';
      const corpo = new FormData();
      corpo.append('arquivo', arquivo);
      try {
        const r = await api.postArquivo('/nfe/foto', corpo);
        if (!r.encontrada) {
          alvo.innerHTML = `<span class="nfe-erro">${escapar(r.mensagem)}<br>
            <small>${escapar(r.dica)}</small></span>`;
          return;
        }
        // Leva para a aba da chave já preenchida: a foto achou o número, e
        // daqui em diante o caminho é o mesmo de quem digitou.
        container.querySelector('.nfe-aba[data-aba="chave"]').click();
        campo.value = formatarChave(r.chave);
        campo.dispatchEvent(new Event('input'));
        alvo.innerHTML = '';
      } catch (erro) {
        alvo.innerHTML = `<span class="nfe-erro">${escapar(erro.message)}</span>`;
      }
    });

    container.querySelector('#nfe-xml').addEventListener('change', async (ev) => {
      const arquivo = ev.target.files[0];
      if (!arquivo) return;
      const alvo = container.querySelector('#nfe-xml-retorno');
      alvo.innerHTML = '<span class="nfe-contando">Lendo a nota…</span>';
      const corpo = new FormData();
      corpo.append('arquivo', arquivo);
      try {
        const nota = await api.postArquivo(
          `/nfe/xml?unidade_id=${UNIDADE_SELECIONADA}`, corpo);
        alvo.innerHTML = '';
        desenharNota(container, nota);
        container.querySelector('#nfe-conferencia')
          .scrollIntoView({ behavior: 'smooth' });
        await carregarLista(container);
      } catch (erro) {
        alvo.innerHTML = `<span class="nfe-erro">${escapar(erro.message)}</span>`;
      }
    });
  }

  async function identificar(container, digitos) {
    const retorno = container.querySelector('#nfe-chave-retorno');
    try {
      const d = await api.post('/nfe/chave', { chave: digitos });
      // Mostrar CNPJ e número ANTES de qualquer consulta é o que deixa a
      // pessoa perceber que digitou a nota errada — enquanto isso ainda
      // custa uma tecla, e não um lançamento no estoque.
      retorno.innerHTML = `
        <div class="nfe-identificada">
          <strong>Nota ${escapar(String(d.numero))}</strong>
          série ${escapar(d.serie)} · ${escapar(d.uf)} · ${escapar(d.competencia)}<br>
          <small>Emitente ${escapar(d.cnpj_formatado)}</small><br>
          <small class="nfe-proximo">${escapar(d.proximo_passo)}</small>
        </div>`;
      container.querySelector('#nfe-consultar').disabled = false;
    } catch (erro) {
      retorno.innerHTML = `<span class="nfe-erro">${escapar(erro.message)}</span>`;
    }
  }

  return {
    async render(container) {
      container.innerHTML = html();
      produtos = await api.get('/produtos');
      ligarEntrada(container);
      await carregarLista(container);
    },
  };
})();
