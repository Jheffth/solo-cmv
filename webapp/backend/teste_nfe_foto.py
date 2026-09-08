"""
Ler a tabela de itens de uma foto — e não deixar erro passar calado.

O CASO É A FOTO REAL
    A nota da Suinoaves fotografada em cima da mesa, torta, com a borda
    rasgada e sombra do teclado. É o pior caso realista, e é o único que
    prova alguma coisa: OCR testado com scan limpo não diz nada sobre o
    celular do estoquista.

O QUE ESTA SUÍTE PROTEGE
    A promessa inteira desta via é "o erro não passa calado". Se um dia
    alguém afrouxar a conferência para "melhorar a taxa de leitura", estes
    testes caem — e é para isso que existem.

    A medição que motivou o desenho: o OCR leu 296,90 como 396,90 (R$ 100 a
    mais numa linha), 15,1000 como 1S,1000, e 5,0000 como $,0000. Nenhum
    desses erros dá mensagem; todos entrariam no estoque parecendo normais.
"""
import os
import sys

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

FOTO = os.path.join(os.path.dirname(BACKEND), '..', 'uploads',
                    'WhatsApp Image 2026-09-08 at 15.58.17.jpeg')
if not os.path.exists(FOTO):
    FOTO = ('/sessions/peaceful-youthful-lovelace/mnt/uploads/'
            'WhatsApp Image 2026-09-08 at 15.58.17.jpeg')

from servicos import danfe_itens                            # noqa: E402
from servicos.danfe_itens import LinhaLida                  # noqa: E402

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


# ==============================================================================
print('\n[1] A ARITMÉTICA RECUSA O QUE NÃO FECHA')
# ==============================================================================
# O coração da defesa, e testável sem imagem nenhuma: a linha só é dada por
# confirmada quando três números dela concordam numa multiplicação.
linha = LinhaLida(texto='', descricao='EMBUTIDO',
                  candidatos=[129.9, 12.99, 10.0, 23.98])
ok(danfe_itens._fechar_por_multiplicacao(linha),
   '10 x 12,99 = 129,90 fecha e a linha é confirmada')
ok(linha.quantidade == 10.0 and linha.valor_unitario == 12.99,
   f'com quantidade {linha.quantidade} e preço {linha.valor_unitario}')
ok(linha.quantidade_confirmada, 'e a linha fica marcada como provada')

# O erro real medido: 296,90 lido como 396,90. Nada na linha fecha com ele.
ruim = LinhaLida(texto='', descricao='COSTELA',
                 candidatos=[396.9, 29.99, 9.9, 103.92])
ok(not danfe_itens._fechar_por_multiplicacao(ruim),
   '9,9 x 29,99 NÃO dá 396,90 — a linha NÃO é confirmada')
ok(not ruim.quantidade_confirmada,
   'e nada é preenchido como se estivesse certo')

# ==============================================================================
print('\n[2] NENHUM NÚMERO SOLTO DA PÁGINA VIRA "TOTAL"')
# ==============================================================================
# Falha real da primeira versão: a busca fechou em 40,00 somando 20 + 20, e
# 40,00 era o PESO BRUTO, lido do bloco de transporte. Um total inventado que
# fecha a conta é o pior resultado possível — confirma o que ninguém conferiu.
linhas = [
    LinhaLida(texto='', descricao='a', candidatos=[129.9, 20.0, 10.0]),
    LinhaLida(texto='', descricao='b', candidatos=[467.95, 20.0, 15.1]),
]
alvo, valores = danfe_itens._achar_total_que_fecha(linhas, [949.7, 40.0, 20.0])
ok(alvo != 40.0,
   f'40,00 (peso bruto) não é aceito como total ({alvo})')
ok(danfe_itens._total_plausivel(linhas, [40.0, 9.77]) is None,
   'e nenhum número menor que o maior item vira total')

# ==============================================================================
print('\n[3] AMBIGUIDADE NÃO É CONFIRMAÇÃO')
# ==============================================================================
# Se duas combinações diferentes fecham no mesmo total, não há o que
# confirmar: escolher uma seria sorteio disfarçado de conferência.
ambiguas = [
    LinhaLida(texto='', descricao='a', candidatos=[10.0, 20.0]),
    LinhaLida(texto='', descricao='b', candidatos=[10.0, 20.0]),
]
ok(danfe_itens._combinar_para_o_total(ambiguas, 30.0) is None,
   '10+20 e 20+10 fecham nos mesmos 30 — nada é confirmado')

# ==============================================================================
print('\n[4] A FOTO DE VERDADE')
# ==============================================================================
if not os.path.exists(FOTO):
    ok(False, 'a foto de referência não está no lugar')
else:
    r = danfe_itens.ler(open(FOTO, 'rb').read())

    ok(len(r.linhas) == 4, f'os quatro itens da nota são separados ({len(r.linhas)})')
    ok(r.total_produtos == 949.70,
       f'o total impresso é lido do rodapé: {r.total_produtos}')

    provadas = [l for l in r.linhas if l.quantidade_confirmada]
    ok(len(provadas) >= 1,
       f'{len(provadas)} linha(s) fecham sozinhas na multiplicação')
    if provadas:
        p = provadas[0]
        ok(p.quantidade == 10.0 and p.valor_unitario == 12.99
           and p.valor_total == 129.90,
           f'e a que fecha está CERTA: {p.quantidade} x {p.valor_unitario} '
           f'= {p.valor_total}')

    # O que não fechou tem que ficar vazio e marcado, não preenchido com
    # palpite. Campo vazio é uma pergunta; palpite errado é uma armadilha.
    abertas = [l for l in r.linhas if not l.quantidade_confirmada]
    ok(all(l.precisa_conferir for l in abertas),
       f'as outras {len(abertas)} ficam marcadas para conferir')
    ok(all(not l.quantidade_confirmada for l in abertas),
       'nenhuma delas é dada por confirmada')

    # As descrições servem para a pessoa RECONHECER o item na hora de casar
    # com o produto. Não precisam estar perfeitas; precisam ser legíveis.
    reconheciveis = sum(1 for l in r.linhas
                        for termo in ('EMBUTIDO', 'COSTELA', 'PANCETA', 'SALGADO')
                        if termo in l.descricao.upper())
    ok(reconheciveis >= 3,
       f'{reconheciveis} de 4 descrições dão para reconhecer o item')

    ok(any('949' in a for a in r.avisos),
       'e a tela recebe o total impresso para conferir a soma')

# ==============================================================================
print('\n[5] O CUSTO POR ESTA VIA NÃO TEM ICMS ST — e isso é dito')
# ==============================================================================
# Limitação honesta: o ST não é legível numa foto de celular com confiança.
# Pela foto, o embutido entra a R$ 12,99; pelo XML, a R$ 13,97. Quem usa
# esta via precisa saber que o custo é o de tabela.
import inspect                                              # noqa: E402
from routers import nfe as router_nfe                       # noqa: E402

doc = inspect.getdoc(router_nfe.nota_conferida) or ''
ok('ICMS ST' in doc and 'XML' in doc,
   'a rota da nota conferida avisa que o ST fica de fora')

# ==============================================================================
print('\n[6] O NOME LIDO VIRA PRODUTO DO CADASTRO')
# ==============================================================================
# A descrição crua do OCR não serve para ninguém escolher nada. O que serve
# é o produto que ela provavelmente é — e, quando dois empatam, a escolha.
import os as _os                                            # noqa: E402
_os.environ.setdefault('DATABASE_URL', 'sqlite:///' + _os.path.join(BACKEND, 'solo_cmv.db'))
from database import SessionLocal                           # noqa: E402
from models import Produto                                  # noqa: E402
from servicos import nfe_importacao                         # noqa: E402

_db = SessionLocal()
_p = _db.query(Produto).first()
EMPRESA = _p.empresa_id if _p else None

def achar(texto):
    return nfe_importacao.candidatos_para_texto(_db, texto, EMPRESA)

r = achar('PANCETA FOOD -3\u00a5L')
ok(r['sugerido'] is not None,
   f"texto sujo com um só parecido vem escolhido: {r['candidatos'][:1]}")

r = achar('eee) COSTELA SALGADA - 2VL')
nomes = [c['nome'] for c in r['candidatos'][:2]]
ok(len(r['candidatos']) >= 2, f'costela acha mais de um: {nomes}')
ok(r['sugerido'] is None,
   'e com empate NÃO escolhe sozinho — a decisão é de quem tem a nota')

r = achar('ere PE SALGADO \u00ab BVL 0" <5 EPSON oF SST a6"')
ok(r['candidatos'] and 'salgado' in r['candidatos'][0]['nome'].lower(),
   f"lixo em volta não atrapalha: {r['candidatos'][:1]}")

r = achar('xyzqwk 999')
ok(not r['candidatos'] or r['sugerido'] is None,
   'texto que não é nada não vira sugestão')
_db.close()

print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
