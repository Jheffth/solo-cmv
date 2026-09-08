/* A tela de Notas Fiscais (jsdom).

   O QUE ESTA SUÍTE PROTEGE
   A tela tem uma responsabilidade que o backend não pode assumir: mostrar
   a nota ANTES de qualquer consulta, para a pessoa perceber que digitou a
   errada. Se o CNPJ e o número somem do retorno numa refatoração, nada
   quebra — só volta a ser possível importar a nota de outra empresa sem
   ninguém notar.

   E protege a conferência do módulo 11 no navegador. Ela é uma cópia
   deliberada da regra do backend (o comentário no arquivo explica por quê);
   um teste aqui garante que a cópia continua correta, que é a única coisa
   que torna a duplicação aceitável.
*/
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('/tmp/jt/node_modules/jsdom');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';
const CHAVE = '53260903425088000181550010004277951006747382';

const falhas = [];
const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

const NOTA = {
  id: 1, chave: CHAVE, numero: '427795', serie: '1',
  emitente: 'SUINOAVES ALIMENTOS LTDA', emitente_cnpj: '03425088000181',
  emissao: '2026-09-08', valor_total: 959.47, valor_produtos: 949.70,
  status: 'CONFERINDO', origem: 'XML',
  itens: [
    { id: 10, numero: 1, codigo_fornecedor: '1105',
      descricao: 'EMBUTIDO DE FRANGO FINA RESFRIADA BANDEJA 500 G - 10VL',
      unidade_nota: 'BD', quantidade_nota: 10, valor_unitario_nota: 12.99,
      acrescimos: 9.77, custo_total: 139.67, custo_unitario: 13.967,
      produto_id: null, produto_nome: null, produto_unidade: null,
      fator_conversao: 0.5, quantidade_final: 5, custo_final: 27.934,
      ignorar: false },
    { id: 11, numero: 2, codigo_fornecedor: '44',
      descricao: 'COSTELA SALGADA - 2VL',
      unidade_nota: 'KG', quantidade_nota: 9.9, valor_unitario_nota: 29.99,
      acrescimos: 0, custo_total: 296.90, custo_unitario: 29.99,
      produto_id: 7, produto_nome: 'Costela bovina', produto_unidade: 'Kg',
      fator_conversao: 1, quantidade_final: 9.9, custo_final: 29.99,
      ignorar: false },
  ],
  itens_sem_produto: 1, pronta_para_aprovar: false,
  avisos: ['Esta nota tem R$ 9.77 de ICMS ST, que ENTRA no custo dos itens.'],
};

function montar(respostas = {}) {
  const dom = new JSDOM(
    '<!doctype html><html><body><div id="conteudo"></div></body></html>',
    { url: 'http://localhost:8095/', runScripts: 'outside-only' });
  const w = dom.window;
  const pedidos = [];
  w.UNIDADE_SELECIONADA = 1;
  w.icone = (n) => `<svg data-i="${n}"></svg>`;
  w.alert = () => {};
  w.confirm = () => true;
  w.api = {
    async get(url) {
      pedidos.push(['GET', url]);
      if (url.startsWith('/produtos')) {
        return [{ id: 7, nome: 'Costela bovina', unidade_medida: 'Kg' },
                { id: 8, nome: 'Embutido de frango', unidade_medida: 'Kg' }];
      }
      if (url.startsWith('/fornecedores')) {
        return respostas.fornecedores
          || [{ id: 3, nome: 'SUINOAVES ALIMENTOS LTDA', cnpj: null },
              { id: 4, nome: 'AMBEV S A', cnpj: null }];
      }
      if (url.startsWith('/nfe/')) return respostas.detalhe || NOTA;
      return respostas.lista || [];
    },
    async post(url, corpo) {
      pedidos.push(['POST', url, corpo]);
      if (url === '/nfe/chave') {
        if (respostas.chaveErro) throw new Error(respostas.chaveErro);
        return {
          chave: CHAVE, numero: 427795, serie: '001', uf: 'DF',
          competencia: '09/2026', cnpj_formatado: '03.425.088/0001-81',
          proximo_passo: 'Agora mande o XML desta nota para trazer os itens.',
        };
      }
      if (url === '/nfe/consultar') throw new Error(respostas.sefazErro || 'sem certificado');
      return {};
    },
    async put(url, corpo) { pedidos.push(['PUT', url, corpo]); return NOTA; },
    async postArquivo(url, fd) { pedidos.push(['ARQ', url]); return respostas.arquivo || {}; },
  };
  w.eval(fs.readFileSync(path.join(BASE, 'js/pages/nfe.js'), 'utf8'));
  return { dom, w, pedidos, alvo: w.document.getElementById('conteudo') };
}

(async () => {
  // ==========================================================================
  console.log('\n[1] A CONFERÊNCIA DA CHAVE ACONTECE NO NAVEGADOR');
  // ==========================================================================
  // Cópia deliberada do módulo 11 do backend, para a resposta ser instantânea
  // enquanto a pessoa digita. Se a cópia estiver errada, ela recusa chave boa
  // ou aceita chave ruim — e os dois casos são ruins de descobrir em produção.
  const { w, alvo, pedidos } = montar();
  await w.Paginas.nfe.render(alvo);
  await new Promise((r) => setTimeout(r, 30));

  const campo = alvo.querySelector('#nfe-chave');
  ok(campo !== null, 'a tela tem o campo da chave');

  campo.value = CHAVE;
  campo.dispatchEvent(new w.Event('input'));
  await new Promise((r) => setTimeout(r, 40));
  ok(campo.value === '5326 0903 4250 8800 0181 5500 1000 4277 9510 0674 7382',
     `formata em blocos de quatro: "${campo.value.slice(0, 24)}…"`);

  const identificou = pedidos.some(([m, u]) => m === 'POST' && u === '/nfe/chave');
  ok(identificou, 'e consulta o backend para identificar a nota');

  const retorno = alvo.querySelector('#nfe-chave-retorno').textContent;
  ok(/427795/.test(retorno), 'mostra o número da nota antes de qualquer consulta');
  ok(/03\.425\.088/.test(retorno),
     'e o CNPJ do emitente — é o que revela a nota errada a tempo');

  // ==========================================================================
  console.log('\n[2] UM DÍGITO TROCADO NÃO CHEGA A SAIR DA TELA');
  // ==========================================================================
  const t2 = montar();
  await t2.w.Paginas.nfe.render(t2.alvo);
  await new Promise((r) => setTimeout(r, 30));
  const c2 = t2.alvo.querySelector('#nfe-chave');
  const antes = t2.pedidos.filter(([m, u]) => u === '/nfe/chave').length;

  const trocado = CHAVE.slice(0, 20) + (CHAVE[20] === '8' ? '7' : '8') + CHAVE.slice(21);
  c2.value = trocado;
  c2.dispatchEvent(new t2.w.Event('input'));
  await new Promise((r) => setTimeout(r, 40));

  // textContent preserva a quebra de linha do template; o HTML colapsa ela
  // na tela. Comparar sem normalizar testaria a indentação do código-fonte,
  // não o que a pessoa lê — e foi o que esta asserção fez na primeira versão.
  const recusa = t2.alvo.querySelector('#nfe-chave-retorno')
    .textContent.replace(/\s+/g, ' ').trim();
  ok(/não passa na conferência/.test(recusa),
     `a tela recusa na hora, sem ir ao servidor: "${recusa.slice(0, 46)}…"`);
  ok(t2.pedidos.filter(([m, u]) => u === '/nfe/chave').length === antes,
     'e de fato nenhuma chamada foi feita');
  ok(t2.alvo.querySelector('#nfe-consultar').disabled,
     'o botão Consultar continua travado');

  // Chave incompleta mostra o quanto falta, em vez de "inválida".
  c2.value = CHAVE.slice(0, 30);
  c2.dispatchEvent(new t2.w.Event('input'));
  ok(/30 de 44/.test(t2.alvo.querySelector('#nfe-chave-retorno').textContent),
     'e enquanto se digita, conta quantos faltam');

  // ==========================================================================
  console.log('\n[3] A CONFERÊNCIA MOSTRA O QUE VAI ENTRAR NO ESTOQUE');
  // ==========================================================================
  const t3 = montar({ lista: [] });
  await t3.w.Paginas.nfe.render(t3.alvo);
  await new Promise((r) => setTimeout(r, 30));
  t3.w.Paginas.nfe.render;
  // desenha a nota chamando o caminho do XML
  const t3b = montar({ arquivo: NOTA, lista: [] });
  await t3b.w.Paginas.nfe.render(t3b.alvo);
  await new Promise((r) => setTimeout(r, 30));
  const entrada = t3b.alvo.querySelector('#nfe-xml');
  Object.defineProperty(entrada, 'files', {
    value: [{ name: 'nota.xml' }], configurable: true,
  });
  entrada.dispatchEvent(new t3b.w.Event('change'));
  await new Promise((r) => setTimeout(r, 60));

  const texto = t3b.alvo.querySelector('#nfe-conferencia').textContent;
  ok(/SUINOAVES/.test(texto), 'o emitente aparece no cabeçalho');
  ok(/427795/.test(texto), 'com o número da nota');

  const linhas = t3b.alvo.querySelectorAll('#nfe-conferencia tbody tr');
  ok(linhas.length === 2, `uma linha por item (${linhas.length})`);

  // O acréscimo do ST é a informação que ninguém espera. Some daqui e o
  // custo maior vira mistério.
  ok(/\+R\$\s?9,77/.test(texto.replace(/ /g, ' ')),
     'o acréscimo de ICMS ST aparece ao lado do valor unitário');
  ok(t3b.alvo.querySelector('.nfe-acrescimo') !== null,
     'com destaque próprio, não misturado ao valor da nota');

  ok(/9,9/.test(linhas[1].textContent),
     'o item já casado mostra a quantidade que entra no estoque');
  ok(/ICMS ST/.test(texto), 'e o aviso do backend é exibido, não engolido');

  ok(t3b.alvo.querySelector('#nfe-aprovar').disabled,
     'aprovar fica travado enquanto houver item sem produto');
  ok(/1 item\(ns\)\s+ainda sem produto/.test(texto.replace(/\s+/g, ' ')),
     'e a tela diz quantos faltam');

  // ==========================================================================
  console.log('\n[4] A RECUSA DA SEFAZ É LIDA INTEIRA, NÃO CORTADA');
  // ==========================================================================
  // A mensagem explica o que falta e qual caminho funciona hoje. Jogá-la num
  // alert() de uma linha jogaria fora justamente a parte que ajuda.
  const LONGA = 'A consulta automática ainda não está ligada — falta o '
    + 'certificado digital A1 da empresa (arquivo .pfx).\n\n'
    + 'Enquanto isso, use o XML: peça ao contador o arquivo da nota.';
  const t4 = montar({ sefazErro: LONGA });
  await t4.w.Paginas.nfe.render(t4.alvo);
  await new Promise((r) => setTimeout(r, 30));
  const c4 = t4.alvo.querySelector('#nfe-chave');
  c4.value = CHAVE;
  c4.dispatchEvent(new t4.w.Event('input'));
  await new Promise((r) => setTimeout(r, 40));
  t4.alvo.querySelector('#nfe-consultar').click();
  await new Promise((r) => setTimeout(r, 40));

  const bloco = t4.alvo.querySelector('.nfe-erro--bloco');
  ok(bloco !== null, 'a recusa vira um bloco na tela, não um alerta');
  ok(/certificado digital A1/.test(bloco.textContent),
     'dizendo o que falta');
  ok(/contador/.test(bloco.textContent),
     'e o caminho que funciona hoje');
  ok(bloco.innerHTML.includes('<br><br>'),
     'com os parágrafos preservados — a mensagem foi escrita para ser lida');

  // ==========================================================================
  console.log('\n[5] A FOTO LEVA PARA O CAMINHO DA CHAVE');
  // ==========================================================================
  // Achar a chave na foto não importa a nota: leva ao MESMO fluxo de quem
  // digitou. Um segundo caminho paralelo seria uma segunda coisa a manter.
  const t5 = montar({ arquivo: { encontrada: true, chave: CHAVE,
                                 origem: 'CODIGO_BARRAS' } });
  await t5.w.Paginas.nfe.render(t5.alvo);
  await new Promise((r) => setTimeout(r, 30));
  const foto = t5.alvo.querySelector('#nfe-foto');
  Object.defineProperty(foto, 'files', {
    value: [{ name: 'nota.jpg' }], configurable: true,
  });
  foto.dispatchEvent(new t5.w.Event('change'));
  await new Promise((r) => setTimeout(r, 60));

  ok(t5.pedidos.some(([m, u]) => m === 'ARQ' && u === '/nfe/foto'),
     'a foto é enviada para o motor de leitura');
  ok(t5.alvo.querySelector('#nfe-chave').value.startsWith('5326 0903'),
     'e a chave achada cai no campo, já formatada');
  ok(t5.alvo.querySelector('.nfe-aba[data-aba="chave"]').classList.contains('ativa'),
     'com a tela voltando para a aba da chave');

  // Foto ruim precisa dizer o que fazer diferente, não só "não encontrado".
  const t5b = montar({ arquivo: { encontrada: false, mensagem: 'Não achei a chave nessa foto.',
                                  dica: 'Tente uma foto só do código de barras.' } });
  await t5b.w.Paginas.nfe.render(t5b.alvo);
  await new Promise((r) => setTimeout(r, 30));
  const foto2 = t5b.alvo.querySelector('#nfe-foto');
  Object.defineProperty(foto2, 'files', { value: [{ name: 'x.jpg' }], configurable: true });
  foto2.dispatchEvent(new t5b.w.Event('change'));
  await new Promise((r) => setTimeout(r, 60));
  ok(/código de barras/.test(t5b.alvo.querySelector('#nfe-foto-retorno').textContent),
     'foto ruim recebe a dica do que mudar na próxima tentativa');

  // ==========================================================================
  console.log('\n[6] A COLUNA DO NOME É UMA ESCOLHA DE PRODUTO');
  // ==========================================================================
  // O texto do OCR não é para ser interpretado por ninguém. A coluna mostra
  // os produtos do cadastro que combinam; o lido fica embaixo, como pista.
  // O total fecha com as duas linhas (129,90 + 296,90). Assim o portão que
  // este teste examina é o do FORNECEDOR — se a soma não fechasse, o botão
  // já estaria travado por outro motivo e a asserção não provaria nada.
  const OCR = {
    total_produtos: 426.8, soma_confere: true, campos_a_conferir: 1, avisos: [],
    cabecalho: {
      emitente_nome: 'SUINOAVES ALIMENTOS LTDA',
      emitente_cnpj: '03425088000181',
      numero: '427795', serie: '1',
      data_emissao: '2026-09-08', valor_nota: 959.47,
      destinatario_nome: 'CASA JOSEFINA LTDA',
      origem: { emitente_cnpj: 'chave', numero: 'chave', serie: 'chave',
                emitente_nome: 'foto', data_emissao: 'foto', valor_nota: 'foto' },
      fornecedor: {
        sugerido: 3,
        candidatos: [{ fornecedor_id: 3, nome: 'SUINOAVES ALIMENTOS LTDA',
                       cnpj: null, pontos: 100 }],
      },
    },
    linhas: [
      { descricao: 'AOS: EMBUTIDO DE FRANGO FINA', lidos: [129.9, 12.99, 10],
        quantidade: 10, valor_unitario: 12.99, valor_total: 129.9,
        quantidade_confirmada: true, total_confirmado: true,
        produto_id: 8,
        produtos: [{ produto_id: 8, nome: 'Linguiça de Frango Fina', unidade_medida: 'und', pontos: 5 }] },
      // Preenchida pela coluna da nota, mas sem multiplicação que feche:
      // é o caso que a tela precisa mostrar como sugestão, não como dado.
      { descricao: 'eee) COSTELA SALGADA - 2VL', lidos: [296.9, 29.99],
        quantidade: 9.9, valor_unitario: 29.99, valor_total: 296.9,
        quantidade_confirmada: false, total_confirmado: true,
        produto_id: null,
        produtos: [{ produto_id: 7, nome: 'Costela bovina', unidade_medida: 'Kg', pontos: 2 },
                   { produto_id: 9, nome: 'Costelinha salgada', unidade_medida: 'kg', pontos: 2 }] },
    ],
  };
  const t6 = montar({ arquivo: OCR, lista: [] });
  await t6.w.Paginas.nfe.render(t6.alvo);
  await new Promise((r) => setTimeout(r, 30));
  t6.alvo.querySelector('#nfe-ler-itens').checked = true;
  const f6 = t6.alvo.querySelector('#nfe-foto');
  Object.defineProperty(f6, 'files', { value: [{ name: 'n.jpg' }], configurable: true });

  // a foto devolve a chave e, com a caixa marcada, também os itens
  t6.w.api.postArquivo = async (url) => (url.includes('/itens')
    ? OCR : { encontrada: true, chave: CHAVE, origem: 'CODIGO_BARRAS' });
  f6.dispatchEvent(new t6.w.Event('change'));
  await new Promise((r) => setTimeout(r, 90));

  const seletores = t6.alvo.querySelectorAll('#nfe-ocr .nfe-prod');
  ok(seletores.length === 2, `a coluna do nome virou seletor (${seletores.length})`);
  ok(seletores[0] && seletores[0].value === '8',
     'o item com um só parecido já vem escolhido');
  ok(seletores[1] && seletores[1].value === '',
     'e o que tem dois parecidos NÃO vem escolhido — a decisão é da pessoa');

  const texto6 = t6.alvo.querySelector('#nfe-ocr').textContent;
  ok(/Costela bovina/.test(texto6) && /Costelinha salgada/.test(texto6),
     'as duas opções aparecem para escolher');
  ok(/mais de um parecido/.test(texto6),
     'com o aviso de que há empate');
  ok(/lido:/.test(texto6),
     'e o texto cru do OCR fica como pista, não como campo principal');
  ok(!t6.alvo.querySelector('#nfe-ocr .nfe-desc'),
     'o campo de texto livre para o nome não existe mais');

  // Agora que a coluna preenche quase tudo, a linha entre "preenchido" e
  // "conferido" é a única coisa que segura o fluxo. Se ela sumir, um número
  // sugerido passa a parecer um número provado — e é assim que erro de OCR
  // vira estoque.
  const linhas6 = t6.alvo.querySelectorAll('#nfe-ocr tbody tr');
  const provada = linhas6[0].querySelectorAll('.nfe-n');
  const suposta = linhas6[1].querySelectorAll('.nfe-n');
  ok(suposta.length === 3 && [...suposta].every((i) => i.value !== ''),
     'a linha que não fechou vem com os três campos preenchidos');
  ok([...suposta].every((i) => i.classList.contains('nfe-sugerido')),
     'e todos marcados como sugestão, não como conferidos');
  ok([...provada].every((i) => !i.classList.contains('nfe-sugerido')),
     'a linha que fechou na conta não recebe a marca');
  ok(/confira no papel/.test(t6.alvo.querySelector('#nfe-ocr').textContent),
     'e a tela diz em palavras o que a marca significa');

  // ==========================================================================
  console.log('\n[7] O CABEÇALHO É O QUE FAZ ISSO VIRAR COMPRA');
  // ==========================================================================
  // Doze números conferidos sem fornecedor, sem número de nota e sem data não
  // são uma compra: são uma lista de coisas.
  const cab = t6.alvo.querySelector('#nfe-ocr .nfe-cabecalho-lido');
  ok(!!cab, 'a conferência abre com o cabeçalho da nota');

  const selForn = t6.alvo.querySelector('#nfe-cab-fornecedor');
  ok(selForn && selForn.value === '3',
     `o fornecedor sugerido já vem escolhido (${selForn && selForn.value})`);
  ok(/SUINOAVES/.test(cab.textContent),
     'e o nome lido da nota fica à vista para conferir com o papel');

  const numero = t6.alvo.querySelector('#nfe-cab-numero');
  ok(numero && numero.value === '427795', 'o número da nota vem preenchido');
  ok(numero && numero.hasAttribute('readonly'),
     'e não é editável, porque veio da chave e não de leitura');
  ok(/confirmado pela chave/.test(cab.textContent),
     'a tela diz de onde ele veio');

  const data = t6.alvo.querySelector('#nfe-cab-data');
  ok(data && data.value === '2026-09-08', 'a emissão vem preenchida');
  ok(!data.hasAttribute('readonly'),
     'e ESSA é editável — a chave só guarda mês e ano, o dia veio da foto');
  ok(Number(t6.alvo.querySelector('#nfe-cab-valor').value) === 959.47,
     'o total da nota, com frete e imposto, vem do rodapé');

  // Sem fornecedor não se segue. Não é rigor: é que compra sem fornecedor
  // não aparece em relatório nenhum e não casa com o pagamento depois.
  ok(!t6.alvo.querySelector('#nfe-ocr-seguir').disabled,
     'com a soma fechada e o fornecedor escolhido, dá para seguir');
  selForn.value = '';
  selForn.dispatchEvent(new t6.w.Event('change'));
  await new Promise((r) => setTimeout(r, 20));
  const botao = t6.alvo.querySelector('#nfe-ocr-seguir');
  ok(botao && botao.disabled, 'tirando o fornecedor, o botão de seguir trava');
  ok(/Escolha o\s+fornecedor/.test(t6.alvo.querySelector('#nfe-ocr').textContent),
     'e a tela diz por quê');

  // Existindo no cadastro um com o nome IGUAL, cadastrar de novo é criar
  // duplicata — e duplicata de fornecedor parte todo relatório em dois sem
  // dar erro nenhum. A saída é a lista, não um cadastro novo.
  ok(!t6.alvo.querySelector('#nfe-cab-criar'),
     'com um nome idêntico no cadastro, NÃO se oferece cadastrar outro');

  // ==========================================================================
  console.log('\n[8] FORNECEDOR QUE NÃO ESTÁ NO CADASTRO');
  // ==========================================================================
  const NOVO = JSON.parse(JSON.stringify(OCR));
  NOVO.cabecalho.emitente_nome = 'FRIGORIFICO BOA VISTA LTDA';
  NOVO.cabecalho.fornecedor = { sugerido: null, candidatos: [] };
  const t8 = montar({ arquivo: NOVO, lista: [] });
  await t8.w.Paginas.nfe.render(t8.alvo);
  await new Promise((r) => setTimeout(r, 30));
  t8.alvo.querySelector('#nfe-ler-itens').checked = true;
  const f8 = t8.alvo.querySelector('#nfe-foto');
  Object.defineProperty(f8, 'files', { value: [{ name: 'n.jpg' }], configurable: true });
  t8.w.api.postArquivo = async (url) => (url.includes('/itens')
    ? NOVO : { encontrada: true, chave: CHAVE, origem: 'CODIGO_BARRAS' });
  f8.dispatchEvent(new t8.w.Event('change'));
  await new Promise((r) => setTimeout(r, 90));

  ok(t8.alvo.querySelector('#nfe-cab-fornecedor').value === '',
     'sem parecido no cadastro, nada vem escolhido');
  ok(t8.alvo.querySelector('#nfe-ocr-seguir').disabled,
     'e o caminho fica travado');

  const criar = t8.alvo.querySelector('#nfe-cab-criar');
  ok(!!criar, 'aparece a opção de cadastrar o fornecedor da nota');
  ok(!criar.checked, 'desmarcada: cadastrar é decisão, não efeito colateral');
  ok(/FRIGORIFICO BOA VISTA/.test(
       t8.alvo.querySelector('.nfe-cabecalho-lido').textContent),
     'com o nome que veio da nota, não um campo em branco para digitar');

  criar.checked = true;
  criar.dispatchEvent(new t8.w.Event('change'));
  await new Promise((r) => setTimeout(r, 20));
  ok(!t8.alvo.querySelector('#nfe-ocr-seguir').disabled,
     'marcando para cadastrar, o caminho destrava');

  // E o que vai para o servidor tem que ser o cabeçalho, não só os itens.
  t8.alvo.querySelector('#nfe-ocr-seguir').click();
  await new Promise((r) => setTimeout(r, 40));
  const enviada = t8.pedidos.filter((p) => p[1] === '/nfe/manual').pop();
  ok(!!enviada, 'a nota é enviada para /nfe/manual');
  if (enviada) {
    const corpo = enviada[2];
    ok(corpo.criar_fornecedor === true && corpo.fornecedor_id === null,
       'com o pedido de cadastrar o fornecedor da nota');
    ok(corpo.numero === '427795' && corpo.serie === '1',
       `com número e série (${corpo.numero}/${corpo.serie})`);
    ok(corpo.data_emissao === '2026-09-08' && corpo.valor_nota === 959.47,
       'com a data de emissão e o total da nota');
    ok(corpo.emitente_cnpj === '03425088000181',
       'e com o CNPJ, que é o que vai identificar o fornecedor da próxima vez');
  }

  console.log('\n' + (falhas.length
    ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
  process.exit(falhas.length ? 1 : 0);
})();
