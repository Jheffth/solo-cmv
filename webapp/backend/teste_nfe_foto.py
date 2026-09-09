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
print('\n[3b] A COLUNA DIZ QUEM É QUEM')
# ==============================================================================
# O problema que motivou esta parte: os números apareciam legíveis na tela e
# os campos ficavam vazios, porque nada dizia qual número era quantidade e
# qual era base de cálculo do ICMS. A DANFE diz — em coluna.

# Armadilha real da nota de referência: na primeira linha a BC do ICMS é
# IGUAL ao valor do item (129,90 nas duas), então a multiplicação fecha com
# as DUAS colunas. Quem desempata é a soma da coluna contra o total impresso.
grade = [
    #  q      vu       total     BC ICMS   ICMS
    [[10.0], [12.99], [129.90], [129.90], [23.98]],
    [[9.9],  [29.99], [296.90], [103.92], [20.78]],
]
trio = danfe_itens._escolher_colunas(grade, 446.80)
ok(trio == (0, 1, 2),
   f'a coluna de totais ganha da BC do ICMS pela soma ({trio})')

# E sem essa trava a coluna errada passa: se o total impresso não for
# conhecido, o empate fica de pé — então o desempate TEM que vir do total.
ok(danfe_itens._escolher_colunas(grade, 949.70) != (0, 1, 3),
   'e a coluna de BC nunca é eleita coluna de valor')

# 296,90 / 39,55 = 7,507 fecha no centavo tão bem quanto 296,90 / 29,99 = 9,9.
# Fornecedor de alimento não vende 7,507 caixas: a quantidade mais redonda é
# a que revela qual dos dois preços o OCR leu certo.
ok(danfe_itens._quantidade_mais_simples(296.90, 29.99) == (9.9, 1),
   '29,99 dá quantidade de uma casa (9,9)')
q_torta, casas_tortas = danfe_itens._quantidade_mais_simples(296.90, 39.55)
ok(casas_tortas > 1,
   f'39,55 só fecha com {casas_tortas} casas ({q_torta}) — e por isso perde')

# A subtração só é permitida para UMA linha. Duas incógnitas numa equação é
# palpite, e palpite aqui vira estoque.
duas = [LinhaLida(texto='', descricao='a', candidatos=[]),
        LinhaLida(texto='', descricao='b', candidatos=[]),
        LinhaLida(texto='', descricao='c', candidatos=[])]
duas[0].valor_total = 100.0
ok(not danfe_itens._fechar_o_que_falta(duas, 300.0),
   'com duas linhas em branco a subtração se recusa a chutar')
duas[1].valor_total = 150.0
ok(danfe_itens._fechar_o_que_falta(duas, 300.0) and duas[2].valor_total == 50.0,
   'com uma só, o resto da soma é aritmética e não chute (50,00)')
ok(duas[2].precisa_conferir,
   'e mesmo assim ela continua marcada para conferir')

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

    # O que não fechou sozinho vem PREENCHIDO pela coluna e MARCADO. Campo
    # vazio obriga a digitar tudo de novo olhando o papel; campo preenchido e
    # marcado pede só a conferência. O que não pode é preenchido e calado.
    abertas = [l for l in r.linhas if not l.quantidade_confirmada]
    ok(all(l.precisa_conferir for l in abertas),
       f'as outras {len(abertas)} ficam marcadas para conferir')
    ok(all(not l.quantidade_confirmada for l in abertas),
       'nenhuma delas é dada por confirmada')

    # E o preenchimento tem que estar CERTO — é o ponto do exercício. Estes
    # doze números vieram da nota de papel, conferidos contra o XML.
    ESPERADO = [(10.0, 12.99, 129.90), (9.9, 29.99, 296.90),
                (15.1, 30.99, 467.95), (5.0, 10.99, 54.95)]
    lido = [(l.quantidade, l.valor_unitario, l.valor_total) for l in r.linhas]
    for i, (esperado, obtido) in enumerate(zip(ESPERADO, lido), 1):
        ok(all(a is not None and abs(a - b) < 0.011
               for a, b in zip(obtido, esperado)),
           f'linha {i}: {obtido[0]} x {obtido[1]} = {obtido[2]} '
           f'(nota: {esperado[0]} x {esperado[1]} = {esperado[2]})')

    ok(r.soma_confere,
       'e a coluna de valores soma exatamente o total impresso')

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

# ==============================================================================
print('\n[7] O CABEÇALHO — E A CHAVE MANDANDO NELE')
# ==============================================================================
# Doze números conferidos sem fornecedor, sem número de nota e sem data não
# são uma compra: são uma lista de coisas.
from servicos import chave_nfe, danfe_cabecalho                # noqa: E402

CHAVE_REAL = '53260903425088000181550010004277951006747382'
_chave = chave_nfe.validar(CHAVE_REAL)

if os.path.exists(FOTO):
    cab = danfe_cabecalho.ler(open(FOTO, 'rb').read(), _chave,
                              valor_produtos=949.70)
    ok(cab.emitente_nome == 'SUINOAVES ALIMENTOS LTDA',
       f'o fornecedor sai do canhoto: {cab.emitente_nome!r}')
    ok(cab.numero == '427795' and cab.serie == '1',
       f'número e série vêm da chave: {cab.numero}/{cab.serie}')
    ok(cab.data_emissao and cab.data_emissao.isoformat() == '2026-09-08',
       f'a data de emissão é a do papel: {cab.data_emissao}')
    ok(cab.valor_nota == 959.47,
       f'e o total da nota, com frete e imposto: {cab.valor_nota}')
    ok('JOSEFINA' in cab.destinatario_nome.upper(),
       f'o destinatário é lido para conferir a loja: {cab.destinatario_nome!r}')

    # A prova de que a chave manda: o quadro impresso diz 03.415.088/0001-81
    # (o OCR lê o 2 como 1) e a chave diz 03.425.088/0001-81. Um dígito. É
    # esse dígito que vira um segundo cadastro do mesmo fornecedor.
    ok(cab.emitente_cnpj == '03425088000181',
       f'o CNPJ vem da chave, não da leitura: {cab.emitente_cnpj}')
    ok(cab.origem.get('emitente_cnpj') == 'chave',
       'e a tela recebe de onde ele veio, para não pedir conferência à toa')

    # Sem chave, o CNPJ fica VAZIO em vez de errado. Campo vazio é pergunta;
    # CNPJ errado gravado no cadastro é dano silencioso.
    sozinho = danfe_cabecalho.ler(open(FOTO, 'rb').read(), None,
                                  valor_produtos=949.70)
    ok(sozinho.emitente_cnpj == '',
       'sem a chave, nenhum CNPJ é chutado a partir da foto')
    ok(sozinho.emitente_nome == 'SUINOAVES ALIMENTOS LTDA',
       'mas o nome continua saindo — ele não precisa de dígito verificador')

# ==============================================================================
print('\n[8] O FORNECEDOR DA NOTA VIRA O FORNECEDOR DO CADASTRO')
# ==============================================================================
r = nfe_importacao.candidatos_de_fornecedor(
    _db2 := SessionLocal(), 'SUINOAVES ALIMENTOS LTDA', '', EMPRESA)
ok(r['sugerido'] is not None,
   f"o nome lido acha o cadastro: {[c['nome'] for c in r['candidatos'][:1]]}")

# O empate por palavra genérica é o erro que quebra relatório por fornecedor:
# "COMERCIO", "DISTRIBUIDORA" e "LTDA" estão em metade do cadastro.
r = nfe_importacao.candidatos_de_fornecedor(
    _db2, 'XPTO COMERCIO DE ALIMENTOS LTDA', '', EMPRESA)
ok(r['sugerido'] is None,
   'fornecedor desconhecido NÃO é casado por palavra genérica')

# CNPJ não concorre com nome: ele encerra a discussão.
_alvo = _db2.query(__import__('models').Fornecedor).filter_by(
    empresa_id=EMPRESA).first()
_guardado = _alvo.cnpj
_alvo.cnpj = '99999999000191'
r = nfe_importacao.candidatos_de_fornecedor(
    _db2, 'NOME COMPLETAMENTE DIFERENTE SA', '99999999000191', EMPRESA)
ok(r['sugerido'] == _alvo.id,
   'com o CNPJ batendo, o nome não importa mais')

# E o CNPJ da chave é gravado no cadastro — é isso que faz o casamento
# virar exato daqui para a frente.
_alvo.cnpj = None
ok(nfe_importacao.fixar_cnpj(_alvo, '03425088000181') is None
   and _alvo.cnpj == '03425088000181',
   'cadastro sem CNPJ recebe o da chave')
conflito = nfe_importacao.fixar_cnpj(_alvo, '11111111000191')
ok(conflito and _alvo.cnpj == '03425088000181',
   'e um CNPJ DIFERENTE não sobrescreve: vira aviso')
ok('confira' in (conflito or '').lower(),
   'porque isso é sinal de nota casada com o fornecedor errado')
_alvo.cnpj = _guardado
_db2.rollback()
_db2.close()

# ==============================================================================
print('\n[9] A CONFERÊNCIA DA LOJA')
# ==============================================================================
# Compra entra em UMA loja, e a loja errada estraga duas apurações de CMV de
# uma vez: sobra onde não entrou e falta onde entrou. A nota sabe para quem
# foi vendida.
from routers.nfe import _conferir_a_loja                       # noqa: E402
from models import Unidade                                     # noqa: E402

_db3 = SessionLocal()
_lojas = _db3.query(Unidade).all()
_por_nome = {l.nome.lower(): l for l in _lojas}
_josefina = next((l for l in _lojas if l.nome.lower() == 'josefina'), None)
_casa = next((l for l in _lojas if 'casa' in l.nome.lower()), None)

if _josefina and _casa:
    aviso = _conferir_a_loja(_db3, 'DESTINATARIO CASA JOSEFINA LTDA',
                             _casa.id, _casa.empresa_id)
    ok(aviso is None, 'nota da Casa Josefina lançada na Casa Josefina: silêncio')

    # O alarme é conservador de propósito. "Josefina" está DENTRO de "Casa
    # Josefina", então as duas casam com o texto — e alarme que dispara à toa
    # é desligado pela pessoa em uma semana, e aí não avisa nem quando importa.
    aviso = _conferir_a_loja(_db3, 'DESTINATARIO CASA JOSEFINA LTDA',
                             _josefina.id, _josefina.empresa_id)
    ok(aviso is None,
       'com os dois nomes casando no texto, também fica calado')

# Quando a loja escolhida NÃO aparece no destinatário e outra aparece, aí
# fala. Com nomes que se contêm ("Josefina" dentro de "Casa Josefina") isso
# nunca acontece, então o caso é montado com duas lojas de nomes distintos —
# que é o desenho para o qual a conferência foi feita.
_empresa = _lojas[0].empresa_id if _lojas else None
if _empresa:
    _a = Unidade(empresa_id=_empresa, nome='Asa Norte')
    _b = Unidade(empresa_id=_empresa, nome='Taguatinga')
    _db3.add_all([_a, _b])
    _db3.flush()
    aviso = _conferir_a_loja(_db3, 'DESTINATARIO REDE TAGUATINGA LTDA',
                             _a.id, _empresa)
    ok(aviso is not None,
       'nota endereçada a outra loja com nome distinto DISPARA o aviso')
    ok(aviso and 'CMV' in aviso,
       'e o aviso diz o que quebra — o CMV das duas lojas')
    ok(_conferir_a_loja(_db3, 'DESTINATARIO REDE TAGUATINGA LTDA',
                        _b.id, _empresa) is None,
       'na loja certa, silêncio')
    _db3.rollback()

ok(_conferir_a_loja(_db3, '', 1, None) is None,
   'sem destinatário legível não há conferência, e não há alarme falso')
_db3.close()

# ==============================================================================
print('\n[10] A ROTA INTEIRA, COM A NOTA DE VERDADE')
# ==============================================================================
# Os pedaços passando não provam que a compra sai lançável. Esta seção sobe
# a aplicação e faz o caminho que a pessoa faz.
import models                                                  # noqa: E402
from database import engine                                    # noqa: E402
models.Base.metadata.create_all(engine)

from fastapi.testclient import TestClient                      # noqa: E402
from auth.deps import get_current_user                         # noqa: E402
import main                                                    # noqa: E402

CHAVE_REAL = '53260903425088000181550010004277951006747382'
_db4 = SessionLocal()
_eu = _db4.query(models.Usuario).filter(models.Usuario.ativo.is_(True)).first()
_loja = _db4.query(Unidade).filter(
    Unidade.empresa_id == _eu.empresa_id).first() if _eu else None

if _eu and _loja:
    main.app.dependency_overrides[get_current_user] = lambda: _eu
    cliente = TestClient(main.app)

    if os.path.exists(FOTO):
        resposta = cliente.post(
            '/api/nfe/foto/itens',
            files={'arquivo': ('nota.jpg', open(FOTO, 'rb').read(), 'image/jpeg')},
            data={'chave': CHAVE_REAL, 'unidade_id': str(_loja.id)})
        ok(resposta.status_code == 200,
           f'a foto + chave voltam a nota inteira ({resposta.status_code})')
        corpo = resposta.json()
        cabecalho = corpo.get('cabecalho') or {}
        ok(cabecalho.get('numero') == '427795'
           and cabecalho.get('data_emissao') == '2026-09-08',
           'com número e data no cabeçalho')
        ok((cabecalho.get('fornecedor') or {}).get('sugerido') is not None,
           'e com o fornecedor do cadastro já apontado')

    _forn = _db4.query(models.Fornecedor).filter(
        models.Fornecedor.nome == 'SUINOAVES ALIMENTOS LTDA').first()
    if _forn:
        _forn.cnpj = None
        _db4.commit()
        criada = cliente.post('/api/nfe/manual', json={
            'unidade_id': _loja.id, 'chave': CHAVE_REAL,
            'numero': '427795', 'serie': '1',
            'data_emissao': '2026-09-08', 'valor_nota': 959.47,
            'emitente_nome': 'SUINOAVES ALIMENTOS LTDA',
            'emitente_cnpj': '03425088000181',
            'fornecedor_id': _forn.id,
            'itens': [
                {'descricao': 'Linguiça de Frango Fina', 'quantidade': 10,
                 'valor_unitario': 12.99, 'valor_total': 129.90},
                {'descricao': 'Costelinha salgada', 'quantidade': 9.9,
                 'valor_unitario': 29.99, 'valor_total': 296.90},
                {'descricao': 'Panceta kg', 'quantidade': 15.1,
                 'valor_unitario': 30.99, 'valor_total': 467.95},
                {'descricao': 'Pe Salgado kg', 'quantidade': 5.0,
                 'valor_unitario': 10.99, 'valor_total': 54.95}],
        })
        ok(criada.status_code == 200,
           f'a nota conferida vira registro ({criada.status_code})')
        if criada.status_code == 200:
            nota = criada.json()
            ok(nota.get('fornecedor') == 'SUINOAVES ALIMENTOS LTDA',
               f"com o fornecedor do cadastro: {nota.get('fornecedor')}")
            ok(nota.get('numero') == '427795' and nota.get('serie') == '1',
               f"com número e série: {nota.get('numero')}/{nota.get('serie')}")
            ok(nota.get('emissao') == '2026-09-08',
               f"com a data de emissão: {nota.get('emissao')}")
            ok(nota.get('valor_produtos') == 949.70,
               f"e os produtos somando o da nota: {nota.get('valor_produtos')}")

            # O total da nota (959,47) é MAIOR que os produtos (949,70). A
            # diferença de 9,77 é o ICMS ST, que não entra no custo por esta
            # via — e a pessoa precisa ser avisada, senão o custo parece
            # completo e não está.
            ok(any('9.77' in a or '9,77' in a for a in nota.get('avisos', [])),
               'e a diferença de R$ 9,77 é explicada como frete e imposto')

            _db4.expire_all()
            ok(_db4.get(models.Fornecedor, _forn.id).cnpj == '03425088000181',
               'o CNPJ da chave fica gravado no cadastro do fornecedor')

            # Não deixar lixo no banco de desenvolvimento.
            registro = _db4.get(models.NotaFiscalImportada, nota['id'])
            if registro:
                _db4.delete(registro)
                _db4.commit()

    main.app.dependency_overrides.pop(get_current_user, None)
_db4.close()

# ==============================================================================
print('\n[11] O RELÓGIO — porque a lentidão volta calada')
# ==============================================================================
# A primeira versão levava 28 segundos para ler uma foto, e nada no código
# dizia por quê: o tratamento de imagem inteiro respondia por 0,1 deles, e o
# resto era configuração do Tesseract que ninguém tinha medido.
#
# Estas verificações existem porque a lentidão não dá erro. Quem remover uma
# das linhas abaixo não vê nada quebrar — só a importação volta a demorar
# meio minuto, e demora assim para sempre, porque ninguém liga lentidão a um
# `-c` que sumiu de uma string.
import time                                                    # noqa: E402
from servicos import danfe                                     # noqa: E402

ok('tessedit_do_invert=0' in danfe.CONFIG_OCR,
   'o OCR não refaz a leitura na imagem invertida (a nossa já é preto no '
   'branco) — vale 40% do tempo')
ok(os.environ.get('OMP_THREAD_LIMIT') == '1',
   'e o Tesseract roda com uma thread: paralelizar página pequena custa '
   'mais que rende (3,67s -> 1,63s)')

# Paralelo de verdade, não concorrência de mentira: o pytesseract chama outro
# processo, e essa espera solta a GIL. Se um dia isto virar sequencial, o
# tempo da foto dobra sem nenhum sinal.
def _dorme():
    time.sleep(0.35)
    return True

_inicio = time.time()
_r = danfe.em_paralelo([_dorme, _dorme])
_gasto = time.time() - _inicio
ok(_r == [True, True] and _gasto < 0.6,
   f'duas leituras rodam JUNTAS ({_gasto:.2f}s para duas de 0,35s)')

# Uma passada que estoura não pode derrubar as outras: perder uma leitura
# degrada o resultado, perder todas o inviabiliza.
def _quebra():
    raise RuntimeError('faixa ilegível')

ok(danfe.em_paralelo([_quebra, lambda: 'ok']) == [None, 'ok'],
   'e a que falha vira None sem levar as outras junto')

# O orçamento. Generoso de propósito — três vezes o medido — para não piscar
# em máquina ocupada, e apertado o bastante para pegar a volta dos 28s.
if os.path.exists(FOTO):
    _bytes = open(FOTO, 'rb').read()
    _inicio = time.time()
    danfe_itens.ler(_bytes)
    danfe_cabecalho.transcrever(_bytes, _chave)
    _gasto = time.time() - _inicio
    ok(_gasto < 20,
       f'a foto inteira é lida em {_gasto:.1f}s (orçamento: 20s; já foi 28s)')

# ==============================================================================
print('\n[12] O CÓDIGO DO FORNECEDOR — o ciclo que faz a segunda nota ser fácil')
# ==============================================================================
# A descrição o fornecedor reescreve; o código dele não muda. Na primeira
# nota a pessoa escolhe o produto e o sistema aprende "cód. 1077 = Panceta";
# da segunda em diante ele lê o código e já sabe.
#
# O QUE ESTA SEÇÃO PROTEGE: que o código NÃO seja aceito por ter sido lido.
# A coluna sai suja — junto dos quatro códigos certos vieram "05", "0", "8",
# "077". Confiar na leitura trocaria um erro visível (campo vazio) por um
# invisível (produto errado com cara de conciliado).
from models import SinonimoProduto                             # noqa: E402

_db5 = SessionLocal()
_forn = _db5.query(models.Fornecedor).filter(
    models.Fornecedor.nome == 'SUINOAVES ALIMENTOS LTDA').first() \
    if 'models' in dir() else None

if os.path.exists(FOTO) and _forn:
    _lido = danfe_itens.ler(open(FOTO, 'rb').read())
    CODIGOS = ['1105', '44', '1077', '25']     # conferidos no papel
    primeiros = [(l.codigos or [None])[0] for l in _lido.linhas]
    ok(primeiros == CODIGOS,
       f'os quatro códigos da nota são lidos e vêm em primeiro: {primeiros}')
    ok(any(len(l.codigos) > 1 for l in _lido.linhas),
       'com as leituras piores guardadas atrás, para a pessoa poder corrigir')

    # O lixo da coluna não some — e não precisa sumir. Ele não bate com nada
    # aprendido, então não custa nada.
    _produtos = _db5.query(Produto).filter_by(
        empresa_id=_forn.empresa_id).limit(2).all()
    _guardar = _db5.query(SinonimoProduto).filter_by(
        fornecedor_id=_forn.id).all()
    for _s in _guardar:
        _db5.delete(_s)
    _db5.flush()
    _db5.add(SinonimoProduto(produto_id=_produtos[0].id, termo='cod:1077',
                             fornecedor_id=_forn.id, fator_conversao=1.0))
    _db5.flush()

    achado = nfe_importacao.candidatos_para_linha(
        _db5, 'PANCETA FOOD -3VL', ['1077', '077'], _forn.id, _forn.empresa_id)
    ok(achado['sugerido'] == _produtos[0].id,
       'o código aprendido casa o item sozinho')
    ok(achado['conciliado_por'] == '1077',
       f"e a tela recebe QUAL código casou: {achado['conciliado_por']}")
    ok(achado['candidatos'][0]['origem'] == 'codigo',
       'o conciliado vem em primeiro')
    ok(any(c['origem'] == 'nome' for c in achado['candidatos'][1:])
       or len(achado['candidatos']) == 1,
       'e os parecidos por nome continuam na lista, como segunda opção')

    # Lixo de OCR não conhecido pelo de-para simplesmente não casa.
    sem_nada = nfe_importacao.candidatos_para_linha(
        _db5, 'PANCETA FOOD -3VL', ['077', '0', '8'], _forn.id,
        _forn.empresa_id)
    ok(sem_nada['conciliado_por'] is None,
       'código mal lido não casa com nada, e a linha volta para o nome')

    # DUAS leituras apontando produtos DIFERENTES é dúvida — e dúvida
    # resolvida por sorteio é como se lança compra no produto errado sem
    # ninguém notar, porque a soma da nota fecha do mesmo jeito.
    _db5.add(SinonimoProduto(produto_id=_produtos[1].id, termo='cod:077',
                             fornecedor_id=_forn.id, fator_conversao=1.0))
    _db5.flush()
    ambiguo = nfe_importacao.candidatos_para_linha(
        _db5, 'PANCETA FOOD -3VL', ['1077', '077'], _forn.id,
        _forn.empresa_id)
    ok(ambiguo['sugerido'] is None,
       'duas leituras apontando produtos diferentes NÃO escolhem sozinhas')
    ok(len([c for c in ambiguo['candidatos'] if c['origem'] == 'codigo']) == 2,
       'e as duas aparecem na lista, para a pessoa desempatar')

    # O código só vale DENTRO de um fornecedor.
    de_outro = nfe_importacao.candidatos_para_linha(
        _db5, 'PANCETA FOOD -3VL', ['1077'], None, _forn.empresa_id)
    ok(de_outro['conciliado_por'] is None,
       'sem fornecedor definido, o código não significa nada')

    _db5.rollback()
_db5.close()

print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
