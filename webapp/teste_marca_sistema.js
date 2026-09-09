/* A paleta do sistema — e a trava que impede a quinta de nascer.

   O QUE ESTA SUÍTE PROTEGE
   Antes dela o projeto tinha 77 cores literais e quatro paletas convivendo:
   a da marca (só no login), uma azul/dourada inventada, uma colada do Solo
   Rotinas com !important em 89 linhas, e a do Tailwind entrando pelas telas
   novas. Nenhuma nasceu de uma decisão — cada uma nasceu de alguém precisar
   de um tom e não ter onde pegar.

   Consistência que depende de as pessoas lembrarem não é consistência. Estes
   testes são o "onde pegar": eles falham quando um literal aparece fora de
   `tokens.css`, quando um token some, e quando o contraste de um par de
   texto cai abaixo de AA.

   E O CONTRASTE É CALCULADO, NÃO CONFERIDO A OLHO
   A fórmula é a da WCAG. Cor bonita que ninguém lê no celular, no meio do
   serviço, com a tela suja de gordura, é cor errada — e isso não se percebe
   olhando no monitor de quem escolheu.
*/
const fs = require('fs');
const path = require('path');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';
const CSS = path.join(BASE, 'css');

const falhas = [];
const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

const ler = (f) => fs.readFileSync(path.join(CSS, f), 'utf8');
/* Comentário não é regra. Ler a prosa junto faria este arquivo acusar a si
   mesmo — os comentários explicam a história citando os hexes antigos, e é
   exatamente essa explicação que impede alguém de reintroduzi-los. */
const codigo = (f) => ler(f).replace(/\/\*[\s\S]*?\*\//g, '');
const arquivos = fs.readdirSync(CSS).filter((f) => f.endsWith('.css'));
const tokens = ler('tokens.css');

function luminancia(hex) {
  const h = hex.replace('#', '');
  const c = [0, 2, 4].map((i) => parseInt(h.slice(i, i + 2), 16) / 255)
    .map((v) => (v <= 0.03928 ? v / 12.92 : ((v + 0.055) / 1.055) ** 2.4));
  return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2];
}
function contraste(a, b) {
  const [x, y] = [luminancia(a), luminancia(b)].sort((p, q) => q - p);
  return (x + 0.05) / (y + 0.05);
}
function valorDoToken(nome) {
  const direto = tokens.match(new RegExp(`\\${nome}:\\s*(#[0-9a-fA-F]{6})`));
  if (direto) return direto[1];
  const indireto = tokens.match(new RegExp(`\\${nome}:\\s*var\\((--[\\w-]+)\\)`));
  return indireto ? valorDoToken(indireto[1]) : null;
}

// ==========================================================================
console.log('\n[1] UMA FONTE DE COR, E UMA SÓ');
// ==========================================================================
// A regra inteira em uma linha: literal de cor só em tokens.css. Se este
// teste falhar, alguém precisou de um tom e inventou em vez de nomear.
const infratores = [];
arquivos.filter((f) => f !== 'tokens.css').forEach((f) => {
  const texto = codigo(f);
  const achados = (texto.match(/#[0-9a-fA-F]{6}\b|#[0-9a-fA-F]{3}\b/g) || [])
    .filter((h) => !/^#(fff|ffffff)$/i.test(h));
  if (achados.length) infratores.push(`${f}: ${[...new Set(achados)].join(' ')}`);
});
ok(infratores.length === 0,
   `nenhuma cor literal fora de tokens.css${infratores.length ? ' -> ' + infratores.join(' | ') : ''}`);

// O branco puro é a exceção deliberada: superfície de cartão e texto sobre
// cor forte. Ele não é "uma cor da paleta", é a ausência de uma.
ok(/--superficie:\s*#FFFFFF/.test(tokens),
   'e o branco tem nome próprio, para quem quiser trocar a superfície');

// ==========================================================================
console.log('\n[2] A MARCA NÃO PARA MAIS NO LOGIN');
// ==========================================================================
// O achado que motivou tudo: a pessoa entrava numa tela vinho e o sistema a
// recebia em azul. A troca era perceptível e não significava nada.
const main = ler('main.css');
ok(/\.sidebar\s*{[^}]*background:\s*var\(--marca-fundo\)/.test(main),
   'a barra lateral usa o vinho da marca, continuando a tela de login');
ok(/h1, h2, h3[^}]*color:\s*var\(--marca-fundo\)/.test(main),
   'e os títulos também');
ok(/button\.btn\s*{[^}]*background:\s*var\(--marca\)/.test(main),
   'o botão de ação é carmim — a cor do logotipo');

// O manual JÁ tinha um azul (petróleo) e um realce (coral). O app tinha
// inventado #1F3B57 e #B08D3E para os mesmos papéis.
ok(!/#1F3B57|#B08D3E/i.test(arquivos.map(codigo).join('')),
   'o azul e o dourado inventados não existem mais em lugar nenhum');

// ==========================================================================
console.log('\n[3] O BLOCO COLADO DE OUTRO PROJETO');
// ==========================================================================
// 89 !important numa lateral que ninguém conseguia retematizar, e o dourado
// do Solo Rotinas no meio do vinho da Casa Josefina.
const importantes = (codigo('main.css').match(/!important/g) || []).length;
ok(importantes <= 1,
   `main.css tem ${importantes} !important (eram 89; sobra o do [hidden])`);
ok(!/d4af37|997519|0b1521|f87171/i.test(arquivos.map(codigo).join('')),
   'e nenhuma cor do Solo Rotinas sobrou');

// ==========================================================================
console.log('\n[4] CADA ESTADO TEM TRÊS TONS, E SÓ TRÊS');
// ==========================================================================
// Foi a falta do trio que multiplicou os tons: quem precisava de um fundo
// claro para o vermelho inventava um, porque não havia onde pegar.
['perigo', 'atencao', 'sucesso', 'info'].forEach((estado) => {
  const trio = ['', '-fundo', '-linha']
    .every((sufixo) => tokens.includes(`--${estado}${sufixo}:`));
  ok(trio, `--${estado} tem texto, fundo e linha`);
});

// ==========================================================================
console.log('\n[5] CONTRASTE — CALCULADO, NÃO ESTIMADO');
// ==========================================================================
const PAPEL = valorDoToken('--papel');
const VINHO = valorDoToken('--marca-fundo');
const pares = [
  ['--tinta', PAPEL, 'texto sobre o papel', 4.5],
  ['--tinta-2', PAPEL, 'rótulo sobre o papel', 4.5],
  ['--marca-fundo', PAPEL, 'título sobre o papel', 4.5],
  ['--perigo', PAPEL, 'perda sobre o papel', 4.5],
  ['--atencao', PAPEL, 'conferir sobre o papel', 4.5],
  ['--sucesso', PAPEL, 'fechou sobre o papel', 4.5],
  ['--info', PAPEL, 'neutro sobre o papel', 4.5],
  ['--cj-creme', VINHO, 'menu sobre o vinho', 4.5],
  // O coral é FILETE e contorno, nunca texto pequeno: sobre vinho dá 4,20.
  // Componente de interface pede 3:1, e é essa a régua que se aplica a ele.
  ['--acento', VINHO, 'filete do item ativo sobre o vinho', 3],
];
pares.forEach(([tokenNome, fundo, rotulo, minimo]) => {
  const cor = valorDoToken(tokenNome);
  const r = cor && fundo ? contraste(cor, fundo) : 0;
  ok(r >= minimo, `${rotulo}: ${r.toFixed(2)}:1 (mínimo ${minimo})`);
});

// O botão principal carrega texto branco. Se alguém escurecer o carmim ou
// clarear demais, isto acusa antes de virar um botão ilegível.
ok(contraste('#FFFFFF', valorDoToken('--marca')) >= 4.5,
   `branco sobre o botão principal: ${contraste('#FFFFFF', valorDoToken('--marca')).toFixed(2)}:1`);

// ==========================================================================
console.log('\n[6] FORMA — TRÊS RAIOS, DUAS SOMBRAS');
// ==========================================================================
// Havia catorze raios e oito sombras. Ninguém escolheu catorze: cada tela
// escolheu um, e a soma virou ruído.
const raiosCrus = arquivos.filter((f) => f !== 'tokens.css')
  .flatMap((f) => codigo(f).match(/border-radius:\s*\d+px/g) || []);
const distintos = [...new Set(raiosCrus.map((r) => r.match(/\d+/)[0]))];
ok(distintos.length <= 3,
   `raios em px fora dos tokens: ${distintos.length} (${distintos.join(', ') || 'nenhum'})`);
ok(['--raio-p', '--raio', '--raio-g', '--raio-pilula']
   .every((t) => tokens.includes(t + ':')),
   'e os quatro raios nomeados existem');

// ==========================================================================
console.log('\n[7] OS NOMES ANTIGOS AINDA RESPONDEM');
// ==========================================================================
// A migração acontece tela a tela. Enquanto ela não termina, uma regra que
// ainda diga `var(--navy)` precisa pintar a cor certa — senão o commit que
// troca a paleta teria que trocar mil linhas de uma vez, e um descuido
// deixaria uma tela para trás sem ninguém ver.
['--navy', '--gold', '--red', '--bg', '--card', '--border', '--text', '--muted']
  .forEach((antigo) => {
    ok(new RegExp(`\\${antigo}:\\s*var\\(--`).test(tokens),
       `${antigo} aponta para um token novo`);
  });

// ==========================================================================
console.log('\n[8] OS DIÁLOGOS TAMBÉM');
// ==========================================================================
// As caixas de confirmação são estilo em JavaScript, fora do alcance do CSS
// — e por isso o lugar mais fácil de uma paleta antiga sobreviver sem
// ninguém notar. Elas aparecem justamente nos momentos que importam:
// excluir do estoque, anular uma nota.
const dialogos = fs.readFileSync(path.join(BASE, 'js/dialogos.js'), 'utf8');
ok(!/var\(--navy|var\(--red\b|var\(--bg\b|var\(--muted/.test(dialogos),
   'os diálogos usam os tokens novos, não os apelidos de compatibilidade');
ok(/var\(--marca,/.test(dialogos),
   'confirmar é ação: carmim, a mesma cor do botão da aplicação');
ok(/var\(--perigo,/.test(dialogos),
   'e o destrutivo é o mesmo vermelho de perda do resto do sistema');

// A reserva existe para o caso de o CSS não ter carregado. Se ela apontar
// para a cor ANTIGA, o diálogo aparece na paleta velha justamente quando
// algo já deu errado — que é quando ninguém está com paciência de
// investigar por que a tela ficou azul.
ok(!/#1F3B57|#A6231F|#F3F4F7|#E3E6EA|#6B7280/.test(dialogos),
   'e as cores de reserva são as novas, não as que foram substituídas');

console.log('\n' + (falhas.length
  ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
process.exit(falhas.length ? 1 : 0);
