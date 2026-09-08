"""
Importação de nota fiscal — da foto ao movimento de compra.

O CASO DE TESTE É UMA NOTA DE VERDADE
    NF-e 427.795 da Suinoaves para a Casa Josefina, 08/09/2026. A foto é a
    que o Jefferson tirou em cima da mesa, torta e com a borda rasgada; o
    XML é a reconstrução fiel dela. Testar contra papel real é o que impede
    a suíte de provar só que o código concorda consigo mesmo.

O QUE ESTA SUÍTE PROTEGE
    1. O CUSTO NÃO É O VALOR UNITÁRIO DA NOTA. O ICMS ST entra. Nesta nota
       são 7,5% no embutido — some numa planilha e reaparece como "o CMV
       subiu e não sei por quê".
    2. A UNIDADE DA NOTA NÃO É A DO ESTOQUE. Dez bandejas de 500 g são 5 kg.
    3. NADA VIRA ESTOQUE SEM ALGUÉM CONFERIR. "PANCETA FOOD - 3VL" não é o
       nome de produto nenhum, e adivinhar errado cria compra errada que
       ninguém percebe, porque o total fecha.
"""
import os
import shutil
import sys
import tempfile

BACKEND = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/backend'
FOTO = '/sessions/peaceful-youthful-lovelace/mnt/uploads/WhatsApp Image 2026-09-08 at 15.58.17.jpeg'
sys.path.insert(0, BACKEND)

_copia = os.path.join(tempfile.mkdtemp(), 'nfe.db')
if os.environ.get('DATABASE_URL_TESTE'):
    os.environ['DATABASE_URL'] = os.environ['DATABASE_URL_TESTE']
else:
    shutil.copy(os.path.join(BACKEND, 'solo_cmv.db'), _copia)
    os.environ['DATABASE_URL'] = 'sqlite:///' + _copia

from fastapi.testclient import TestClient                  # noqa: E402
from database import SessionLocal, criar_tabelas           # noqa: E402
from migracoes import aplicar_migracoes                    # noqa: E402
from models import (Movimento, PapelUsuario, Produto,      # noqa: E402
                    SinonimoProduto, TipoMovimento, Unidade, Usuario)
from auth.security import hash_senha                       # noqa: E402
from servicos import chave_nfe, danfe, nfe_xml, sefaz      # noqa: E402
from main import app                                       # noqa: E402

criar_tabelas()
aplicar_migracoes()

SENHA = 'Teste@2026'
CHAVE = '53260903425088000181550010004277951006747382'
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


db = SessionLocal()
_uni = db.query(Unidade).order_by(Unidade.id).first()
UNI_ID, EMPRESA = _uni.id, _uni.empresa_id
for login, papel in (('nf_ope', PapelUsuario.OPERADOR),
                     ('nf_ger', PapelUsuario.GERENTE)):
    antigo = db.query(Usuario).filter(Usuario.login == login).first()
    if antigo:
        db.delete(antigo)
        db.commit()
    u = Usuario(nome=login, login=login, senha_hash=hash_senha(SENHA),
                papel=papel, ativo=True, empresa_id=EMPRESA)
    u.unidades = [_uni]
    db.add(u)
db.commit()
db.close()

cliente = TestClient(app)


def entrar(login):
    r = cliente.post('/api/auth/login', json={'login': login, 'senha': SENHA})
    assert r.status_code == 200, f'login {login}: {r.status_code}'
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


H = entrar('nf_ger')
XML = open(os.path.join(BACKEND, 'exemplos/nfe_suinoaves.xml'),
           encoding='utf-8').read()


# ==============================================================================
print('\n[1] A CHAVE SE EXPLICA SOZINHA — sem rede, sem certificado')
# ==============================================================================
r = cliente.post('/api/nfe/chave', headers=H, json={'chave': CHAVE})
ok(r.status_code == 200, f'chave aceita ({r.status_code})')
d = r.json()
ok(d['uf'] == 'DF', f"UF sai da chave: {d['uf']}")
ok(d['cnpj_formatado'] == '03.425.088/0001-81',
   f"e o CNPJ do emitente: {d['cnpj_formatado']}")
ok(d['numero'] == 427795, f"e o número da nota: {d['numero']}")
ok(d['competencia'] == '09/2026', f"e a competência: {d['competencia']}")
ok(d['formatada'].startswith('5326 0903'),
   'formatada em blocos de quatro, como vem impressa')

# Digitar 44 números erra. O verificador é o que pega o erro antes de
# qualquer viagem à rede — e antes de importar a nota de OUTRA empresa.
trocado = CHAVE[:20] + ('8' if CHAVE[20] != '8' else '7') + CHAVE[21:]
r = cliente.post('/api/nfe/chave', headers=H, json={'chave': trocado})
ok(r.status_code == 400, f'um dígito trocado é recusado ({r.status_code})')
ok('conferência' in r.json()['detail'] or 'trocado' in r.json()['detail'],
   f"e a recusa explica: \"{r.json()['detail'][:60]}\"")

r = cliente.post('/api/nfe/chave', headers=H, json={'chave': CHAVE[:40]})
ok(r.status_code == 400 and 'Faltam 4' in r.json()['detail'],
   f"chave curta diz QUANTOS faltam: \"{r.json()['detail'][:50]}\"")

# Espaços e pontos coladas da mensagem do fornecedor não podem atrapalhar.
r = cliente.post('/api/nfe/chave', headers=H,
                 json={'chave': chave_nfe.validar(CHAVE).formatada})
ok(r.status_code == 200, 'colada com espaços funciona igual')


# ==============================================================================
print('\n[2] A FOTO REAL, TIRADA EM CIMA DA MESA')
# ==============================================================================
if os.path.exists(FOTO):
    with open(FOTO, 'rb') as f:
        r = cliente.post('/api/nfe/foto', headers=H,
                         files={'arquivo': ('nota.jpg', f, 'image/jpeg')})
    ok(r.status_code == 200, f'foto aceita ({r.status_code})')
    d = r.json()
    ok(d.get('encontrada') is True, 'a chave foi encontrada na foto')
    ok(d.get('chave') == CHAVE, f"e é a chave certa: {d.get('chave')}")
    ok(d.get('origem') == 'CODIGO_BARRAS',
       f"lida do código de barras, não por OCR ({d.get('origem')})")
    ok(d.get('dados', {}).get('numero') == 427795,
       'e já vem decodificada, com o número da nota')
else:
    ok(False, 'a foto de referência sumiu do lugar')

# Arquivo que não é imagem não pode estourar exceção crua na cara do usuário.
r = cliente.post('/api/nfe/foto', headers=H,
                 files={'arquivo': ('x.txt', b'nao sou imagem', 'text/plain')})
ok(r.status_code == 400, f'arquivo que não é imagem é recusado ({r.status_code})')


# ==============================================================================
print('\n[3] O CUSTO NÃO É O VALOR UNITÁRIO — o ICMS ST entra')
# ==============================================================================
nota = nfe_xml.ler(XML)
ok(round(nota.valor_produtos, 2) == 949.70, 'produtos: 949,70 como na nota')
ok(round(nota.valor_nota, 2) == 959.47, 'total da nota: 959,47')
ok(nota.soma_dos_custos == 959.47,
   f'a soma dos nossos custos FECHA no total ({nota.soma_dos_custos})')

embutido = nota.itens[0]
ok(embutido.valor_unitario_comercial == 12.99, 'a nota diz R$ 12,99 a bandeja')
ok(round(embutido.custo_unitario, 2) == 13.97,
   f'mas o custo real é R$ {embutido.custo_unitario:.4f} — o ST de 9,77 é dele')
ok(embutido.acrescimos == 9.77, 'e o acréscimo aparece separado, para conferir')

# Os outros três não têm ST: o custo tem que continuar igual ao da nota.
for item in nota.itens[1:]:
    ok(abs(item.custo_unitario - item.valor_unitario_comercial) < 0.01,
       f'{item.descricao[:22]}: sem ST, custo = valor da nota')

ok(any('ICMS ST' in a for a in nota.avisos),
   'e a nota avisa por que o custo ficou maior')


# ==============================================================================
print('\n[4] DEZ BANDEJAS DE 500 G SÃO CINCO QUILOS')
# ==============================================================================
# O próprio XML informa: uCom=BD/qCom=10 e uTrib=KG/qTrib=5. O fator sai de
# graça, do emitente, sem ninguém cadastrar nada.
ok(embutido.fator_para_tributavel == 0.5,
   f'o fator vem do próprio XML: {embutido.fator_para_tributavel}')
ok(nota.itens[1].fator_para_tributavel is None,
   'item vendido e tributado em KG não sugere conversão nenhuma')


# ==============================================================================
print('\n[5] A IMPORTAÇÃO NÃO MEXE NO ESTOQUE ANTES DE ALGUÉM CONFERIR')
# ==============================================================================
antes = SessionLocal()
movimentos_antes = antes.query(Movimento).filter(
    Movimento.tipo == TipoMovimento.COMPRA).count()
antes.close()

r = cliente.post(f'/api/nfe/xml?unidade_id={UNI_ID}', headers=H,
                 files={'arquivo': ('nota.xml', XML.encode(), 'text/xml')})
ok(r.status_code == 200, f'XML importado ({r.status_code}) {r.text[:120]}')
nf = r.json()
NOTA_ID = nf['id']
ok(nf['status'] == 'CONFERINDO', f"status: {nf['status']} — ainda não é compra")
ok(len(nf['itens']) == 4, f"quatro itens ({len(nf['itens'])})")
ok(nf['emitente'] == 'SUINOAVES ALIMENTOS LTDA', 'com o emitente identificado')

depois = SessionLocal()
ok(depois.query(Movimento).filter(
    Movimento.tipo == TipoMovimento.COMPRA).count() == movimentos_antes,
   'e NENHUM movimento de compra foi criado ainda')
depois.close()

# Aprovar com item sem produto tem que recusar — e dizer QUAIS.
r = cliente.post(f'/api/nfe/{NOTA_ID}/aprovar', headers=H)
ok(r.status_code == 409, f'aprovar sem casar produto é recusado ({r.status_code})')
ok('sem produto escolhido' in r.json()['detail'],
   'e a recusa nomeia os itens que faltam')


# ==============================================================================
print('\n[6] A CONFERÊNCIA, E O QUE ELA MUDA NO NÚMERO')
# ==============================================================================
_db = SessionLocal()
produtos = _db.query(Produto).filter(Produto.ativo == True).limit(4).all()  # noqa: E712
alvo = produtos[0]
ALVO_ID, ALVO_NOME = alvo.id, alvo.nome
_db.close()

r = cliente.put(f'/api/nfe/{NOTA_ID}/item/{nf["itens"][0]["id"]}', headers=H,
                json={'produto_id': ALVO_ID, 'fator_conversao': 0.5})
ok(r.status_code == 200, f'item casado com um produto ({r.status_code})')
item = r.json()['itens'][0]
ok(item['quantidade_final'] == 5.0,
   f"10 BD viram {item['quantidade_final']} na nossa unidade")
ok(round(item['custo_final'], 2) == 27.93,
   f"e o custo por unidade nossa vira R$ {item['custo_final']:.2f} "
   f"(139,67 / 5), não os 12,99 da nota")

# Os três restantes: um casado, dois ignorados — para provar que ignorar
# funciona sem travar a aprovação.
for i, linha in enumerate(nf['itens'][1:], start=1):
    corpo = ({'produto_id': produtos[i].id} if i == 1 else {'ignorar': True})
    cliente.put(f'/api/nfe/{NOTA_ID}/item/{linha["id"]}', headers=H, json=corpo)

r = cliente.get(f'/api/nfe/{NOTA_ID}', headers=H)
ok(r.json()['pronta_para_aprovar'] is True,
   'com tudo casado ou ignorado, a nota fica pronta')


# ==============================================================================
print('\n[7] APROVAR VIRA COMPRA — e o sistema APRENDE o de-para')
# ==============================================================================
r = cliente.post(f'/api/nfe/{NOTA_ID}/aprovar', headers=H)
ok(r.status_code == 200, f'aprovada ({r.status_code}) {r.text[:100]}')
res = r.json()
ok(res['movimentos_criados'] == 2,
   f"dois movimentos, os dois itens casados ({res['movimentos_criados']})")

_db = SessionLocal()
mov = _db.query(Movimento).filter(
    Movimento.tipo == TipoMovimento.COMPRA,
    Movimento.produto_id == ALVO_ID).order_by(Movimento.id.desc()).first()
ok(mov is not None, 'o movimento existe no estoque')
if mov:
    ok(mov.quantidade == 5.0,
       f'com a quantidade convertida ({mov.quantidade}), não os 10 da nota')
    ok(round(mov.custo_unitario, 2) == 27.93,
       f'e o custo com ST dentro (R$ {mov.custo_unitario:.2f})')
    ok(mov.numero_documento == 'NF 427795',
       f'amarrado ao documento ({mov.numero_documento})')

# O aprendizado é o que faz a SEGUNDA nota da Suinoaves ser fácil.
aprendido = _db.query(SinonimoProduto).filter(
    SinonimoProduto.produto_id == ALVO_ID,
    SinonimoProduto.fornecedor_id.isnot(None)).count()
_db.close()
ok(aprendido >= 1,
   f'a descrição do fornecedor virou apelido daquele produto ({aprendido})')

# Importar de novo não pode duplicar compra — é o erro que ninguém percebe,
# porque cada lançamento sozinho parece certo.
r = cliente.post(f'/api/nfe/xml?unidade_id={UNI_ID}', headers=H,
                 files={'arquivo': ('nota.xml', XML.encode(), 'text/xml')})
ok(r.status_code == 409, f'reimportar nota já lançada é recusado ({r.status_code})')
ok('já foi importada' in r.json()['detail'],
   f"dizendo quando: \"{r.json()['detail'][:70]}\"")


# ==============================================================================
print('\n[8] A SEFAZ RECUSA COM EXPLICAÇÃO, E NÃO FINGE')
# ==============================================================================
# Sem certificado, a consulta pública devolve só o resumo — sem itens. Um
# `consultar` que devolvesse dados parciais fingindo estar completo seria
# pior que a ausência dele: alguém confiaria e lançaria estoque errado.
cfg = sefaz.configuracao()
ok(cfg.pronto is False, 'sem certificado configurado, como esperado')

r = cliente.post('/api/nfe/consultar', headers=H,
                 json={'chave': CHAVE, 'unidade_id': UNI_ID})
ok(r.status_code == 503, f'a consulta recusa com 503, não 500 ({r.status_code})')
detalhe = r.json()['detail']
ok('certificado' in detalhe.lower(), 'e diz o que falta')
ok('XML' in detalhe and 'contador' in detalhe.lower(),
   'e oferece o caminho que funciona hoje')

r = cliente.get('/api/nfe/status', headers=H)
d = r.json()
ok(d['implementado'] is True, 'o status não diz mais "não implementado"')
caminhos = {c['chave']: c['disponivel'] for c in d['caminhos']}
ok(caminhos['chave'] is True and caminhos['xml'] is True,
   f'chave e XML disponíveis hoje: {caminhos}')
ok(caminhos['sefaz'] is False, 'e a SEFAZ aparece como indisponível, sem esconder')


# ==============================================================================
print('\n[9] QUEM NÃO PODE LANÇAR COMPRA NÃO IMPORTA NOTA')
# ==============================================================================
# Importar nota É lançar compra. Se a régua daqui divergisse da de
# movimentos, existiria uma porta lateral para o estoque.
H_SEM = entrar('nf_ope')
r = cliente.post('/api/nfe/chave', headers=H_SEM, json={'chave': CHAVE})
ok(r.status_code == 200, 'o operador confere a chave (ele lança compra)')

shutil.rmtree(os.path.dirname(_copia), ignore_errors=True)
print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
