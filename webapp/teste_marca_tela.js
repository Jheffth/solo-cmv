/* As telas de entrada, e a marca nelas (jsdom).

   O QUE ESTA SUÍTE PROTEGE
   Design tem uma forma própria de quebrar: nada estoura, nada aparece no
   log, e a tela só fica errada. Um `placeholder=" "` removido numa limpeza
   de código faz TODO rótulo flutuante travar em cima do texto — e quem fez
   a limpeza não tem por que desconfiar de um espaço em branco.

   Então o que se testa aqui não é "está bonito", que é opinião. É o que
   sustenta o bonito: as cores são as do manual, o logo herda cor em vez de
   ser uma foto, e os campos têm o que o CSS precisa para funcionar.
*/
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('/tmp/jt/node_modules/jsdom');

const BASE = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/frontend';
const html = fs.readFileSync(path.join(BASE, 'index.html'), 'utf8');
const css = fs.readFileSync(path.join(BASE, 'css/marca.css'), 'utf8');
const svg = fs.readFileSync(path.join(BASE, 'assets/logos/casa-josefina.svg'), 'utf8');

const falhas = [];
const ok = (c, m) => { if (!c) falhas.push(m); console.log((c ? '  ok  ' : '  XX  ') + m); };

const dom = new JSDOM(html, { url: 'http://localhost:8095/' });
const doc = dom.window.document;

// ============================================================================
console.log('\n[1] AS CORES SÃO AS DO MANUAL, E SÓ ELAS');
// ============================================================================
// Amostradas do PDF pixel a pixel. Um "quase igual" na tela de login é a
// primeira rachadura na consistência da marca — e ninguém consegue apontar
// o que mudou, só sente que ficou errado.
const PALETA = {
  '--cj-carmim': '#A6183B', '--cj-vinho': '#64111C', '--cj-tijolo': '#B63421',
  '--cj-terra': '#753017', '--cj-coral': '#EC6E45', '--cj-creme': '#EED5B4',
  '--cj-petroleo': '#466178', '--cj-azul': '#83ABC1',
};
for (const [nome, hex] of Object.entries(PALETA)) {
  ok(new RegExp(`${nome}:\\s*${hex}`, 'i').test(css), `${nome} = ${hex}`);
}

// Nenhuma cor do tema antigo pode ter sobrado nas telas de entrada.
const ANTIGAS = ['#1F3B57', '#16293e', '#B08D3E'];
const sobrou = ANTIGAS.filter((c) => css.toUpperCase().includes(c.toUpperCase()));
ok(sobrou.length === 0, `nenhuma cor do tema antigo sobrou (${sobrou})`);

// ============================================================================
console.log('\n[2] O LOGO É VETOR E HERDA A COR');
// ============================================================================
// Um JPG serviria para uma cor só, e traria fundo branco em cima do vinho.
// Como SVG com currentColor, a MESMA arte vira creme no painel e carmim no
// celular — e escala sem borrar em tela de retina.
ok(svg.includes('<svg'), 'o arquivo é SVG de verdade');
ok(svg.includes('fill="currentColor"'), 'e pinta por currentColor');
ok(!/fill:\s*rgb\(/.test(svg), 'sem nenhuma cor fixa presa dentro dele');
ok((svg.match(/<path/g) || []).length > 20,
   `com as curvas do logotipo (${(svg.match(/<path/g) || []).length} caminhos)`);
ok(/viewBox="[^"]+"/.test(svg) && !/\swidth="/.test(svg.split('>')[0]),
   'sem largura fixa — quem dimensiona é o CSS');
ok(/aria-label="Casa Josefina/.test(svg), 'e se apresenta para leitor de tela');

// ============================================================================
console.log('\n[3] A TELA DE LOGIN');
// ============================================================================
const login = doc.getElementById('tela-login');
ok(login && login.classList.contains('auth'), 'usa o palco da marca');
ok(doc.querySelector('.auth-marca'), 'tem o painel da marca');
// Escopado ao #tela-login: sem isso conta as duas telas (login e convite)
// e o número dobra — foi o que aconteceu na primeira versão desta suíte.
ok(login.querySelectorAll('.auth-paleta span').length === 6,
   `com a régua de seis cores do manual (${login.querySelectorAll('.auth-paleta span').length})`);

const logos = [...doc.querySelectorAll('#tela-login img')];
ok(logos.length === 2, `dois logos: painel e topo do celular (${logos.length})`);
ok(logos.every((i) => i.src.endsWith('.svg')),
   'os dois em SVG — nenhum JPG sobrou');
ok(logos[0].alt && logos[0].alt.length > 10,
   `o do painel tem alt descritivo: "${logos[0].alt}"`);

// ============================================================================
console.log('\n[4] O ESPAÇO QUE SEGURA O RÓTULO FLUTUANTE');
// ============================================================================
// placeholder=" " — um espaço, não vazio. É o que faz :placeholder-shown
// casar. Sem ele o rótulo não sobe e fica por cima do que a pessoa digita.
// Some numa limpeza de código sem ninguém notar, e nada quebra: só fica feio.
const campos = [...doc.querySelectorAll('#tela-login .campo input')];
ok(campos.length === 2, `dois campos (${campos.length})`);
for (const c of campos) {
  ok(c.getAttribute('placeholder') === ' ',
     `${c.id}: placeholder é UM ESPAÇO, não vazio`);
  const rot = doc.querySelector(`label[for="${c.id}"]`);
  ok(rot !== null, `${c.id}: tem rótulo ligado por for=`);
  ok(rot && rot.compareDocumentPosition(c) & 2,
     `${c.id}: o rótulo vem DEPOIS do input — o seletor + exige essa ordem`);
}
ok(css.includes(':placeholder-shown'), 'e o CSS usa :placeholder-shown');

// ============================================================================
console.log('\n[5] O QUE NÃO PODE TER MUDADO');
// ============================================================================
// Redesenho que troca ids quebra o JS em silêncio: o formulário some do ar
// e o botão "Entrar" parece não fazer nada.
for (const id of ['form-login', 'input-login', 'input-senha', 'login-erro',
                  'btn-toggle-senha', 'link-convite', 'erro-tecnico',
                  'tela-convite', 'convite-conteudo']) {
  ok(doc.getElementById(id) !== null, `#${id} continua existindo`);
}
ok(doc.getElementById('input-senha').type === 'password',
   'a senha continua escondida por padrão');
ok(doc.querySelector('#form-login button[type="submit"]'),
   'e o botão continua sendo submit — Enter no teclado tem que entrar');

// ============================================================================
console.log('\n[6] A TELA DE CONVITE USA O MESMO PALCO');
// ============================================================================
const convite = doc.getElementById('tela-convite');
ok(convite.classList.contains('auth'), 'mesma moldura do login');
ok(convite.hasAttribute('hidden'), 'e nasce escondida');
ok(convite.querySelector('.auth-marca'), 'com o painel da marca também');

const js = fs.readFileSync(path.join(BASE, 'js/aceitar-convite.js'), 'utf8');
ok(!js.includes('login-logo') && !js.includes('btn btn-login'),
   'o JS do convite não usa mais as classes antigas');
ok((js.match(/placeholder=" "/g) || []).length >= 3,
   'e os campos dele também têm o espaço no placeholder');
ok(js.includes('casa-josefina.svg'), 'usando o mesmo logo vetorial');

// ============================================================================
console.log('\n[7] CELULAR: A MARCA SAI DA FRENTE');
// ============================================================================
// Meia tela de capa empurraria o campo de senha para baixo da dobra. Quem
// abre isto no meio do serviço quer digitar, não rolar.
ok(/@media \(max-width: 860px\)/.test(css), 'tem ponto de virada no celular');
const bloco = css.split('@media (max-width: 860px)')[1].split('}\n}')[0];
ok(/\.auth-marca\s*{\s*display:\s*none/.test(bloco),
   'o painel da marca some');
ok(/\.auth-logo-topo\s*{[^}]*display:\s*block/.test(bloco),
   'e o logo reaparece no topo');
ok(/@media \(prefers-reduced-motion: reduce\)/.test(css),
   'quem pediu menos movimento recebe menos movimento');

// ============================================================================
console.log('\n[8] A FONTE DA MARCA PODE FALTAR SEM QUEBRAR NADA');
// ============================================================================
// Tanker vem de fora (Fontshare). Rede ruim no restaurante é comum, e a
// tela de login é a que MENOS pode depender de terceiro.
ok(css.includes('Tanker'), 'usa a Tanker, que é a fonte do manual');
ok(css.includes('display=swap'),
   'com swap: o texto aparece na reserva em vez de ficar invisível');
const pilha = (css.match(/font-family:\s*"Tanker"[^;]+;/) || [''])[0];
ok(/Oswald|Narrow|Condensed/.test(pilha),
   `a reserva é condensada como a Tanker — fonte larga quebraria a linha: ${pilha.slice(0, 70)}`);

console.log('\n' + (falhas.length
  ? 'FALHAS:\n  ' + falhas.join('\n  ') : 'Tudo certo.'));
process.exit(falhas.length ? 1 : 0);
