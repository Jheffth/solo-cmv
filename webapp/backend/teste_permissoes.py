"""
A régua de capacidades — e a varredura que impede o dinheiro de vazar.

O QUE ESTA SUÍTE PROTEGE
    "Funcionário de base não vê faturamento" não existia em lugar nenhum. As
    ESCRITAS estavam guardadas e as LEITURAS não: POST /vendas exigia Gerente,
    GET /vendas exigia só estar logado. A assimetria não é descuido de quem
    escreveu — gravar assusta, ler não.

O TESTE QUE IMPORTA É A VARREDURA (seção 6)
    Testar rota por rota prova o hoje. O risco é o amanhã: alguém acrescenta
    "valor_total" a uma resposta que o operador lê, e nenhum teste de lista
    fixa percebe.

    Então a seção 6 faz o contrário — pega tudo que o operador consegue ler e
    procura QUALQUER chave com cara de dinheiro, recursivamente. Rota nova
    com dinheiro dentro cai aqui sem ninguém ter que lembrar de escrever um
    teste para ela.
"""
import os
import shutil
import sys
import tempfile

BACKEND = '/sessions/peaceful-youthful-lovelace/mnt/SOLO CMV/webapp/backend'
sys.path.insert(0, BACKEND)

_copia = os.path.join(tempfile.mkdtemp(), 'perm.db')
if os.environ.get('DATABASE_URL_TESTE'):
    os.environ['DATABASE_URL'] = os.environ['DATABASE_URL_TESTE']
else:
    shutil.copy(os.path.join(BACKEND, 'solo_cmv.db'), _copia)
    os.environ['DATABASE_URL'] = 'sqlite:///' + _copia

from fastapi.testclient import TestClient                  # noqa: E402
from database import SessionLocal, criar_tabelas           # noqa: E402
from migracoes import aplicar_migracoes                    # noqa: E402
from models import (PapelUsuario, SessaoInventario,        # noqa: E402
                    StatusSessaoInventario, Unidade, Usuario)
from auth.security import hash_senha                       # noqa: E402
from servicos import permissoes                            # noqa: E402
from servicos.permissoes import Capacidade                 # noqa: E402
from main import app                                       # noqa: E402

criar_tabelas()
aplicar_migracoes()

SENHA = 'Teste@2026'
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


db = SessionLocal()
_uni = db.query(Unidade).order_by(Unidade.id).first()
UNI_ID, EMPRESA = _uni.id, _uni.empresa_id

PERFIS = {'pm_ope': PapelUsuario.OPERADOR, 'pm_ger': PapelUsuario.GERENTE,
          'pm_dir': PapelUsuario.DIRETOR}
ids = {}
for login, papel in PERFIS.items():
    antigo = db.query(Usuario).filter(Usuario.login == login).first()
    if antigo:
        db.delete(antigo)
        db.commit()
    u = Usuario(nome=login, login=login, senha_hash=hash_senha(SENHA),
                papel=papel, ativo=True, empresa_id=EMPRESA)
    u.unidades = [_uni]
    db.add(u)
    db.commit()
    ids[login] = u.id

# Um inventário que ACEITA CONTAGEM precisa existir, e não pode depender de o
# banco de desenvolvimento ter um. Sem ele a varredura não chega no detalhe do
# inventário — que é justamente onde há custo por item —, e a suíte passaria
# verde sem ter olhado onde mais importa.
_sessao = db.query(SessaoInventario).filter(
    SessaoInventario.unidade_id == UNI_ID,
    SessaoInventario.status.in_((StatusSessaoInventario.CONGELADO,
                                 StatusSessaoInventario.EM_CONTAGEM))).first()
if not _sessao:
    _sessao = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == UNI_ID).order_by(
            SessaoInventario.id.desc()).first()
    if _sessao:
        _sessao.status = StatusSessaoInventario.CONGELADO
        db.commit()
SESSAO_ID = _sessao.id if _sessao else None
QUALQUER_ID = SESSAO_ID
db.close()

cliente = TestClient(app)


def entrar(login):
    r = cliente.post('/api/auth/login', json={'login': login, 'senha': SENHA})
    assert r.status_code == 200, f'login {login}: {r.status_code} {r.text[:150]}'
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


OPE, GER, DIR = entrar('pm_ope'), entrar('pm_ger'), entrar('pm_dir')


# ==============================================================================
print('\n[1] A RÉGUA RESPONDE SEM ALVO — e nega o que não conhece')
# ==============================================================================
class _Fake:
    def __init__(self, papel):
        self.papel = papel


ope, ger, dirq = (_Fake(PapelUsuario.OPERADOR), _Fake(PapelUsuario.GERENTE),
                  _Fake(PapelUsuario.DIRETOR))

ok(permissoes.pode(ope, Capacidade.CONTAR), 'Operador conta')
ok(not permissoes.pode(ope, Capacidade.CONGELAR_INVENTARIO),
   'Operador NÃO congela')
ok(not permissoes.pode(ope, Capacidade.ABRIR_INVENTARIO),
   'Operador NÃO abre inventário')
ok(not permissoes.pode(ope, Capacidade.VER_DINHEIRO), 'Operador NÃO vê R$')
ok(permissoes.pode(ope, Capacidade.LANCAR_COMPRA),
   'mas lança compra — a nota está na mão dele')
ok(permissoes.pode(ger, Capacidade.CONGELAR_INVENTARIO), 'Gerente congela')
ok(not permissoes.pode(ger, Capacidade.DEFINIR_META),
   'Gerente NÃO define meta')
ok(permissoes.pode(dirq, Capacidade.DEFINIR_META), 'Diretor define meta')


class _Desconhecida:
    value = 'CAPACIDADE_QUE_NAO_EXISTE'


ok(not permissoes.pode(dirq, _Desconhecida()),
   'capacidade não registrada é NEGADA, mesmo para o Diretor — '
   'liberar o desconhecido é como buraco entra em produção')

# Toda capacidade tem piso e frase. Sem isto, uma nova entraria mostrando o
# nome cru numa mensagem de erro.
sem_piso = [c.value for c in Capacidade if c not in permissoes.PISO]
sem_frase = [c.value for c in Capacidade if c not in permissoes.DESCRICAO]
ok(not sem_piso, f'toda capacidade tem piso ({sem_piso})')
ok(not sem_frase, f'toda capacidade tem frase legível ({sem_frase})')


# ==============================================================================
print('\n[2] O OPERADOR É RECUSADO ONDE DEVE — e sabe a quem pedir')
# ==============================================================================
RECUSAS = [
    ('post', f'/api/inventario/sessoes/{QUALQUER_ID}/congelar', 'congelar'),
    ('post', '/api/inventario/sessoes/abrir', 'abrir inventário'),
    ('get',  f'/api/vendas?unidade_id={UNI_ID}', 'ver faturamento'),
    ('post', '/api/vendas', 'lançar faturamento'),
    ('get',  f'/api/cmv/apuracao?unidade_id={UNI_ID}'
             '&data_inicio=2026-08-01&data_fim=2026-08-31', 'apurar CMV'),
    ('get',  '/api/relatorios', 'listar relatórios'),
    ('get',  f'/api/relatorios/fechamento?unidade_id={UNI_ID}', 'abrir relatório'),
    ('get',  f'/api/metas/painel?unidade_id={UNI_ID}', 'painel de metas'),
    ('get',  f'/api/perdas/resumo?unidade_id={UNI_ID}', 'resumo de perdas'),
]
for metodo, rota, oque in RECUSAS:
    extra = {'json': {}} if metodo == 'post' else {}
    r = getattr(cliente, metodo)(rota, headers=OPE, **extra)
    ok(r.status_code == 403, f'{oque}: {r.status_code}')
    if r.status_code == 403:
        texto = r.json().get('detail', '')
        ok('para cima' in texto or 'Gerente' in texto or 'Diretor' in texto,
           f'   e a recusa diz a quem pedir: "{texto[:70]}"')


# ==============================================================================
print('\n[3] E LIBERADO ONDE DEVE — recusa demais também é defeito')
# ==============================================================================
LIBERADAS = [
    (f'/api/estoque?unidade_id={UNI_ID}', 'ver o estoque (saldo)'),
    (f'/api/inventario/sessoes?unidade_id={UNI_ID}', 'listar inventários'),
    (f'/api/requisicoes?unidade_id={UNI_ID}', 'listar requisições'),
    ('/api/perdas/motivos', 'ver os motivos de perda'),
    ('/api/produtos', 'ver produtos'),
    (f'/api/dashboard/painel?unidade_id={UNI_ID}', 'abrir a tela inicial'),
    ('/api/sessao', 'abrir o sistema'),
]
for rota, oque in LIBERADAS:
    r = cliente.get(rota, headers=OPE)
    ok(r.status_code == 200, f'{oque}: {r.status_code}')


# ==============================================================================
print('\n[4] O ESTOQUE VEM SEM R$, MAS COM SALDO')
# ==============================================================================
# Filtrar, não recusar: pedir 20 kg de um item que tem 12 é erro que só
# aparece na hora de atender. Um 403 aqui tiraria dele a informação de que
# ele mais precisa, para proteger uma que não é dele.
e_ope = cliente.get(f'/api/estoque?unidade_id={UNI_ID}', headers=OPE).json()
e_ger = cliente.get(f'/api/estoque?unidade_id={UNI_ID}', headers=GER).json()

ok(e_ope['com_valores'] is False, 'a resposta DECLARA que veio sem valores')
ok(e_ger['com_valores'] is True, 'e para o gerente, que veio com')
ok(len(e_ope['itens']) == len(e_ger['itens']),
   f"mesmo número de itens para os dois ({len(e_ope['itens'])})")
if e_ope['itens']:
    ok('quantidade' in e_ope['itens'][0], 'o saldo está lá')
    ok('ultimo_custo' not in e_ope['itens'][0], 'o custo não')
ok('valor_total' not in e_ope['resumo'], 'nem o valor total')
ok('valor_total' in e_ger['resumo'], 'que o gerente continua vendo')


# ==============================================================================
print('\n[5] A TELA INICIAL DO OPERADOR É A FILA DELE')
# ==============================================================================
p_ope = cliente.get(f'/api/dashboard/painel?unidade_id={UNI_ID}', headers=OPE).json()
p_ger = cliente.get(f'/api/dashboard/painel?unidade_id={UNI_ID}', headers=GER).json()
ok(p_ope.get('operacional') is True,
   'ele recebe o painel operacional, não o de CMV com os números apagados')
ok('tarefas' in p_ope, 'com as tarefas que esperam por ele')
ok('kpis' not in p_ope, 'e sem os KPIs')
ok(not p_ger.get('operacional'), 'o gerente recebe o painel completo')
ok('kpis' in p_ger, 'com os KPIs')

s = cliente.get('/api/sessao', headers=OPE).json()
ok(s['ve_dinheiro'] is False, 'a abertura já diz que ele não vê dinheiro')
ok('CONTAR' in s['capacidades'], 'e lista o que ele pode: CONTAR')
ok('CONGELAR_INVENTARIO' not in s['capacidades'],
   'e omite o que não pode — menu se monta daqui, sem régua em JavaScript')


# ==============================================================================
print('\n[6] A VARREDURA — nenhuma chave de dinheiro no que o operador lê')
# ==============================================================================
# O teste que pega o amanhã. Qualquer chave nova com cara de dinheiro numa
# resposta que o operador alcança falha aqui, sem ninguém lembrar de escrever
# um teste para ela.
PALAVRAS = ('custo', 'valor', 'faturamento', 'cmv', 'preco', 'preço',
            'receita', 'lucro', 'margem')

# O nome da chave sozinho não basta, e descobri isso vendo o teste acusar
# código correto. Neste projeto "valor" tem dois sentidos: dinheiro e "o
# valor desta opção" — `/perdas/motivos` devolve {"valor": "QUEBRA"} e
# `/usuarios/poderes` devolve {"valor": "DIRETOR"}. Nenhum é dinheiro.
#
# O que separa os dois é o TIPO. Dinheiro é número. Marcar pelo nome faria a
# suíte gritar em toda lista de opções do sistema, e uma suíte que grita à
# toa é uma suíte que se aprende a ignorar — aí ela deixa de proteger.


def eh_numero(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def varrer(no, caminho=''):
    achados = []
    if isinstance(no, dict):
        for k, v in no.items():
            aqui = f'{caminho}.{k}'
            suspeita = any(p in k.lower() for p in PALAVRAS)
            if suspeita and (eh_numero(v)
                             or (isinstance(v, str) and 'R$' in v)):
                achados.append(f'{aqui}={v}')
            achados += varrer(v, aqui)
    elif isinstance(no, list):
        for i, v in enumerate(no[:3]):     # 3 amostras bastam: a forma repete
            achados += varrer(v, f'{caminho}[{i}]')
    return achados


# Duas exceções, declaradas em voz alta para que sejam decisão e não descuido:
# o operador vê o dinheiro do FATO QUE ELE MESMO LANÇOU. A nota fiscal estava
# na mão dele; esconder o número impresso seria teatro. O que ele não vê é o
# agregado, que só o sistema sabe somar.
ISENTAS = {
    '/api/movimentos': 'livro-razão: a nota que ele digitou',
    '/api/perdas': 'a perda que ele mesmo registrou',
}

A_VARRER = [
    f'/api/estoque?unidade_id={UNI_ID}',
    f'/api/dashboard/painel?unidade_id={UNI_ID}',
    '/api/dashboard/resumo',
    '/api/sessao',
    f'/api/inventario/sessoes?unidade_id={UNI_ID}',
    f'/api/inventario/sessoes?unidade_id={UNI_ID}&aceita_contagem=true',
    f'/api/requisicoes?unidade_id={UNI_ID}',
    '/api/produtos',
    '/api/categorias',
    '/api/fornecedores',
    '/api/perdas/motivos',
    '/api/usuarios/poderes',
    '/api/perfil',
    # Rotas do canal Telegram. Entraram aqui porque a checagem de cobertura
    # as acusou — que é o serviço que ela presta: rota nova não passa
    # despercebida, vira decisão.
    '/api/telegram/status',
    '/api/telegram/comandos',
]
if SESSAO_ID:
    A_VARRER.append(f'/api/inventario/sessoes/{SESSAO_ID}')

# A busca de produto devolve nome, código e unidade — nunca custo. Vai na
# varredura com um termo real, senão a lista viria vazia e não provaria nada.
A_VARRER.append('/api/produtos/buscar?termo=batata')

for rota in A_VARRER:
    r = cliente.get(rota, headers=OPE)
    if r.status_code != 200:
        continue
    achados = varrer(r.json())
    ok(not achados,
       f'{rota.split("?")[0]}: {len(achados)} chave(s) de dinheiro'
       + (f' → {achados[:4]}' if achados else ''))

# A varredura só vale se cobrir o que existe. Rota GET nova e não listada
# aparece aqui — para virar decisão, e não esquecimento.
registradas = {
    r.path for r in app.routes
    if getattr(r, 'methods', None) and 'GET' in r.methods
    and r.path.startswith('/api/') and '{' not in r.path
}
cobertas = {p.split('?')[0] for p in A_VARRER} | set(ISENTAS)
# O que é reconhecidamente sem dinheiro ou fora do alcance do operador
FORA = {'/api/docs', '/api/redoc', '/api/openapi.json',
        '/api/health', '/api/versao/', '/api/auth/me', '/api/nfe/status',
        '/api/unidades', '/api/unidades/escopo', '/api/produtos/unidades-medida',
        '/api/vendas', '/api/relatorios', '/api/metas/painel', '/api/metas',
        '/api/metas/historico', '/api/metas/previa-distribuicao',
        '/api/cmv/apuracao', '/api/cmv/configuracao', '/api/perdas/resumo',
        '/api/despesas', '/api/usuarios', '/api/convites', '/api/convites/opcoes',
        '/api/inventario/sessoes/buscar', '/api/requisicoes/buscar'}
descobertas = sorted(registradas - cobertas - FORA)
ok(not descobertas,
   f'nenhuma rota GET fora da varredura ({len(descobertas)}): {descobertas[:6]}')

# A resposta de quem LANÇA também é leitura. O operador manda contagem
# dezenas de vezes por inventário: se a confirmação devolver o custo do item,
# o dinheiro sai pela porta que ele mais usa — e nenhuma varredura de GET
# olharia para lá.
if SESSAO_ID:
    _d = cliente.get(f'/api/inventario/sessoes/{SESSAO_ID}', headers=GER).json()
    _itens = _d.get('itens') or []
    if _itens:
        corpo = {'sessao_id': SESSAO_ID, 'produto_id': _itens[0]['produto_id'],
                 'quantidade': 7}
        r = cliente.post(f'/api/inventario/sessoes/{SESSAO_ID}/contagem',
                         headers=OPE, json=corpo)
        if r.status_code == 200:
            achados = varrer(r.json())
            ok(not achados,
               f'a confirmação da contagem volta sem R$ ({achados[:3]})')
        else:
            ok(False, f'contagem do operador falhou: {r.status_code} {r.text[:120]}')


# ==============================================================================
print('\n[7] O GERENTE CONTINUA VENDO TUDO — a trava não pode ter passado do ponto')
# ==============================================================================
for metodo, rota, oque in RECUSAS:
    if metodo != 'get':
        continue
    r = cliente.get(rota, headers=GER)
    ok(r.status_code != 403, f'gerente {oque}: {r.status_code}')

r = cliente.get(f'/api/metas/painel?unidade_id={UNI_ID}', headers=DIR)
ok(r.status_code == 200, f'e o diretor idem ({r.status_code})')


# ==============================================================================
print('\n[8] FILTRO POR SIGNIFICADO — sem cópia da regra no cliente')
# ==============================================================================
from servicos.contagem import STATUS_ACEITA_CONTAGEM          # noqa: E402
import routers.inventario as router_inv                       # noqa: E402

ok(router_inv.STATUS_ACEITA_CONTAGEM is STATUS_ACEITA_CONTAGEM,
   'o router usa a lista do serviço — havia uma cópia idêntica, '
   'idêntica até o dia em que não fosse')

todas = cliente.get(f'/api/inventario/sessoes?unidade_id={UNI_ID}',
                    headers=OPE).json()
prontas = cliente.get(f'/api/inventario/sessoes?unidade_id={UNI_ID}'
                      '&aceita_contagem=true', headers=OPE).json()
rotulos = {s['status'] for s in prontas}
esperados = {s.value for s in STATUS_ACEITA_CONTAGEM}
ok(rotulos <= esperados,
   f'só volta o que aceita contagem: {rotulos or "nenhum"}')
ok(len(prontas) <= len(todas),
   f'{len(prontas)} de {len(todas)} inventários servem para contar')

shutil.rmtree(os.path.dirname(_copia), ignore_errors=True)
print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
