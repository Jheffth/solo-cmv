"""
O bot inteiro, sem tocar na rede.

COMO ISTO RODA SEM TELEGRAM E SEM SERVIDOR
    · o Telegram vira uma classe que guarda as mensagens numa lista
    · a API vira o TestClient do FastAPI, falando com o app de verdade

Ou seja: nada é simulado do lado que importa. As permissões, o inventário, a
contagem e a idempotência são os de produção. O que se troca é só o canal —
que é exatamente a parte que não tem regra nenhuma.

Foi para isso que `telegram_api.py` não usa python-telegram-bot: sem
biblioteca com loop próprio, trocar o canal é trocar um objeto.

O QUE ESTA SUÍTE PROTEGE
    1. reentrega não duplica lançamento (o risco mais provável e o mais
       silencioso — contagem duplicada não dá erro, só estraga o inventário)
    2. quem não vê dinheiro não vê dinheiro tampouco pelo chat
    3. vínculo revogado para de valer NA HORA, não no vencimento do token
    4. o /ajuda não lista nada que dê 403 — a ajuda não pode mentir
    5. as três ações irreversíveis não existem por este canal, e a recusa
       está no BACKEND, não na boa vontade do bot
"""
import os
import shutil
import sys
import tempfile

BACKEND = os.path.dirname(os.path.abspath(__file__))
BOT = os.path.join(os.path.dirname(BACKEND), 'bot')
sys.path.insert(0, BACKEND)
sys.path.insert(0, BOT)

SEGREDO = 'segredo-de-teste-do-bot-1234567890'
os.environ['BOT_SEGREDO'] = SEGREDO

_copia = os.path.join(tempfile.mkdtemp(), 'bot.db')
if os.environ.get('DATABASE_URL_TESTE'):
    os.environ['DATABASE_URL'] = os.environ['DATABASE_URL_TESTE']
else:
    src_db = os.path.join(BACKEND, 'solo_cmv.db')
    if os.path.exists(src_db):
        shutil.copy(src_db, _copia)
    os.environ['DATABASE_URL'] = 'sqlite:///' + _copia

from fastapi.testclient import TestClient                  # noqa: E402
from database import SessionLocal, criar_tabelas           # noqa: E402
from migracoes import aplicar_migracoes                    # noqa: E402
from models import (PapelUsuario, SessaoInventario,        # noqa: E402
                    StatusSessaoInventario, TentativaVinculo, Unidade, Usuario)
from auth.security import hash_senha, criar_access_token   # noqa: E402
from main import app                                       # noqa: E402

criar_tabelas()
aplicar_migracoes()

SENHA = 'Teste@2026'
falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


# ==============================================================================
# CENÁRIO
# ==============================================================================
db = SessionLocal()
_uni = db.query(Unidade).order_by(Unidade.id).first()
UNI_ID, EMPRESA = _uni.id, _uni.empresa_id

ids = {}
for login, papel in (('bot_ope', PapelUsuario.OPERADOR),
                     ('bot_ger', PapelUsuario.GERENTE)):
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

# Um inventário que aceita contagem — o cenário do operador na câmara fria
sessao_inv = db.query(SessaoInventario).filter(
    SessaoInventario.unidade_id == UNI_ID,
    SessaoInventario.status.in_((StatusSessaoInventario.CONGELADO,
                                 StatusSessaoInventario.EM_CONTAGEM))).first()
if not sessao_inv:
    sessao_inv = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == UNI_ID).order_by(
            SessaoInventario.id.desc()).first()
    if sessao_inv:
        sessao_inv.status = StatusSessaoInventario.CONGELADO
        db.commit()
INV_ID = sessao_inv.id if sessao_inv else None
INV_NUM = sessao_inv.numero_documento if sessao_inv else None
db.close()

cliente = TestClient(app)

# Banco recém-preparado (PostgreSQL limpo) não tem inventário nenhum. Criar
# um pelo CAMINHO REAL — abrir e congelar como gerente, pela API — em vez de
# inserir linha na marra: se a abertura mudar de regra, este teste sente.
if INV_ID is None:
    _cab = {'Authorization': 'Bearer ' + cliente.post(
        '/api/auth/login',
        json={'login': 'bot_ger', 'senha': SENHA}).json()['access_token']}
    _r = cliente.post('/api/inventario/sessoes/abrir', headers=_cab,
                      json={'unidade_id': UNI_ID, 'geral': True,
                            'categoria_ids': [], 'descricao': 'teste do bot'})
    assert _r.status_code == 201, f'abrir inventário: {_r.status_code} {_r.text[:200]}'
    INV_ID = _r.json()['id']
    INV_NUM = _r.json()['numero_documento']
    _r = cliente.post(f'/api/inventario/sessoes/{INV_ID}/congelar', headers=_cab)
    assert _r.status_code == 200, f'congelar: {_r.status_code} {_r.text[:200]}'


# ==============================================================================
# OS DOIS DUBLÊS
# ==============================================================================
class TelegramFalso:
    """Guarda o que seria enviado. É todo o Telegram de que o teste precisa."""

    def __init__(self):
        self.enviadas = []
        self.botoes_respondidos = []

    def enviar(self, chat_id, texto, botoes=None):
        self.enviadas.append({'chat': chat_id, 'texto': texto, 'botoes': botoes})
        return {'ok': True}

    def responder_botao(self, callback_id, texto=''):
        self.botoes_respondidos.append(callback_id)

    # ---- ajudas de leitura
    @property
    def ultima(self):
        return self.enviadas[-1]['texto'] if self.enviadas else ''

    def tudo(self):
        return '\n'.join(m['texto'] for m in self.enviadas)

    def botoes_da_ultima(self):
        b = self.enviadas[-1]['botoes'] if self.enviadas else None
        return [x['callback_data'] for linha in (b or []) for x in linha]

    def limpar(self):
        self.enviadas.clear()


class APIdeTeste:
    """O SoloAPI, mas por TestClient — o app de verdade, sem soquete."""

    def __init__(self, token=None, segredo=None):
        self.token = token
        self.segredo = segredo

    def como(self, token):
        return APIdeTeste(token, self.segredo)

    def _cabecalhos(self):
        h = {}
        if self.token:
            h['Authorization'] = 'Bearer ' + self.token
        if self.segredo:
            h['X-Bot-Segredo'] = self.segredo
        return h

    def _tratar(self, r):
        if r.status_code >= 400:
            detalhe = r.json().get('detail') if r.headers.get(
                'content-type', '').startswith('application/json') else r.text
            if isinstance(detalhe, list) and detalhe:
                detalhe = detalhe[0].get('msg', str(detalhe))
            raise ErroAPI(r.status_code, str(detalhe))
        return r.json() if r.text else None

    def get(self, caminho, **p):
        limpos = {k: v for k, v in p.items() if v is not None}
        return self._tratar(cliente.get(caminho, params=limpos,
                                        headers=self._cabecalhos()))

    def post(self, caminho, dados=None, **p):
        limpos = {k: v for k, v in p.items() if v is not None}
        return self._tratar(cliente.post(caminho, json=dados or {}, params=limpos,
                                         headers=self._cabecalhos()))

    def put(self, caminho, dados=None, **p):
        return self._tratar(cliente.put(caminho, json=dados or {},
                                        headers=self._cabecalhos()))

    def delete(self, caminho, **p):
        return self._tratar(cliente.delete(caminho, headers=self._cabecalhos()))


from solo_api import ErroAPI                               # noqa: E402
from conversa import Conversa, ler_quantidade, separar_nome_e_numero  # noqa: E402
from principal import rodar                                # noqa: E402


def entrar(login):
    r = cliente.post('/api/auth/login', json={'login': login, 'senha': SENHA})
    assert r.status_code == 200, f'login {login}: {r.status_code} {r.text[:120]}'
    return {'Authorization': 'Bearer ' + r.json()['access_token']}


def vincular(login, chat_id):
    """Faz o caminho inteiro: a pessoa pede o código na tela e digita no bot."""
    cabecalho = entrar(login)
    codigo = cliente.post('/api/telegram/codigo', headers=cabecalho).json()['codigo']
    tg = TelegramFalso()
    conversa = Conversa(tg, APIdeTeste(segredo=SEGREDO), SEGREDO)
    conversa.atender(chat_id, f'/vincular {codigo}')
    return tg, conversa


CHAT_OPE, CHAT_GER = 900001, 900002

# Um Arquiteto, para separar "não pode" de "não por este canal".
#
# Criado aqui em vez de entrar como o Arquiteto do seed, e a diferença não é
# de estilo: fazer login exigiria a senha real escrita neste arquivo, e este
# arquivo mora num repositório. Senha em arquivo versionado é senha pública.
#
# O token sai direto de `criar_access_token` porque o que se testa abaixo é o
# CANAL, não o login — passar pela porta da frente aqui só acrescentaria uma
# senha para vazar.
db = SessionLocal()
_arq = db.query(Usuario).filter(Usuario.login == 'bot_arq').first()
if _arq:
    db.delete(_arq)
    db.commit()
_arq = Usuario(nome='bot_arq', login='bot_arq', senha_hash=hash_senha(SENHA),
               papel=PapelUsuario.ARQUITETO, ativo=True, empresa_id=EMPRESA)
_arq.unidades = [db.query(Unidade).filter(Unidade.id == UNI_ID).first()]
db.add(_arq)
db.commit()
ARQ_ID = _arq.id
db.close()
H_ARQ = {'Authorization': 'Bearer ' + criar_access_token({'sub': str(ARQ_ID)})}


# ==============================================================================
print('\n[1] LEITURA DO QUE A PESSOA DIGITA')
# ==============================================================================
for entrada, esperado in (('12,5', 12.5), ('12.5', 12.5), ('8', 8.0),
                          ('12,5 kg', 12.5), ('0', 0.0), ('1.234,5', 1234.5)):
    ok(ler_quantidade(entrada) == esperado,
       f'"{entrada}" vira {esperado} (veio {ler_quantidade(entrada)})')
ok(ler_quantidade('batata') is None, '"batata" não é quantidade')
ok(ler_quantidade('-3') is None, 'negativo é recusado')

nome, qtd = separar_nome_e_numero('gengibre 8')
ok(nome == 'gengibre' and qtd == 8.0, 'gengibre 8 → (gengibre, 8)')
nome, qtd = separar_nome_e_numero('batata doce')
ok(nome == 'batata doce' and qtd is None, 'sem número, fica só o nome')


# ==============================================================================
print('\n[2] SEM VÍNCULO, O BOT NÃO FAZ NADA — e explica o caminho')
# ==============================================================================
tg = TelegramFalso()
conversa = Conversa(tg, APIdeTeste(segredo=SEGREDO), SEGREDO)
conversa.atender(999999, 'oi')
ok('não está ligado' in tg.ultima, 'diz que o Telegram não está vinculado')
ok('Perfil' in tg.ultima and 'vincular' in tg.ultima.lower(),
   'e diz exatamente onde pegar o código')
ok('senha' in tg.ultima.lower(),
   'e avisa para nunca mandar a senha pelo chat')

conversa.atender(999999, '/contar')
ok('não está ligado' in tg.ultima, '/contar de desconhecido também é recusado')

tg.limpar()
conversa.atender(999999, '/vincular 000000')
ok('código' in tg.ultima.lower(),
   f'código inventado é recusado: "{tg.ultima[:60]}"')


# ==============================================================================
print('\n[3] O VÍNCULO PELO CÓDIGO')
# ==============================================================================
tg_ope, conv_ope = vincular('bot_ope', CHAT_OPE)
ok('Operador' in tg_ope.ultima, f'operador conectado: "{tg_ope.ultima[:50]}"')

tg_ger, conv_ger = vincular('bot_ger', CHAT_GER)
ok('Gerente' in tg_ger.ultima, 'gerente conectado')

# Código serve UMA vez. Dois chats VIRGENS de propósito: usar o CHAT_OPE
# aqui não queimaria o código (ele já está vinculado, cai noutro caminho) e
# a segunda tentativa moveria o vínculo dele para outro chat — foi o que
# aconteceu na primeira versão deste teste, e derrubou tudo daqui para baixo
# com "ok" falsos pelo caminho.
cab = entrar('bot_ope')
codigo = cliente.post('/api/telegram/codigo', headers=cab).json()['codigo']
tg2 = TelegramFalso()
c2 = Conversa(tg2, APIdeTeste(segredo=SEGREDO), SEGREDO)
c2.atender(700001, f'/vincular {codigo}')
ok('conectado' in tg2.ultima.lower(), 'o código funciona uma vez')
tg2.limpar()
c2.atender(700002, f'/vincular {codigo}')
ok('já foi usado' in tg2.ultima,
   f'e não serve de novo: "{tg2.ultima[:60]}"')

# E quem já está vinculado não fica com um código solto na mão
tg2.limpar()
c2.atender(700001, '/vincular 123456')
ok('já está ligado' in tg2.ultima,
   'chat já vinculado recebe o estado atual, não a ajuda genérica')

# Devolve o operador ao chat dele — o passo acima moveu o vínculo
tg_ope, conv_ope = vincular('bot_ope', CHAT_OPE)


# ==============================================================================
print('\n[4] O /AJUDA NÃO PODE MENTIR')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/ajuda')
ajuda_ope = tg_ope.ultima
ok('/contar' in ajuda_ope, 'operador vê /contar')
ok('/perda' in ajuda_ope, 'e /perda')
ok('/cmv' not in ajuda_ope, 'e NÃO vê /cmv')
ok('/congelar' not in ajuda_ope, 'nem /congelar')
ok('/faturamento' not in ajuda_ope, 'nem /faturamento')
ok('Fora do seu acesso' in ajuda_ope,
   'mas sabe que existe mais, e a quem pedir')
ok(ajuda_ope.count('\n') < 25,
   f'e cabe na tela do celular ({ajuda_ope.count(chr(10)) + 1} linhas)')

tg_ger.limpar()
conv_ger.atender(CHAT_GER, '/ajuda')
ok('/congelar' in tg_ger.ultima and '/cmv' in tg_ger.ultima,
   'o gerente vê congelar e CMV')

# A prova que importa: NADA listado pode dar 403. Percorre a ajuda de cada
# papel contra a própria API — se um comando mudar de piso e a ajuda não
# acompanhar, cai aqui.
from servicos import comandos as reg                       # noqa: E402
db = SessionLocal()
for login, chat in (('bot_ope', CHAT_OPE), ('bot_ger', CHAT_GER)):
    u = db.query(Usuario).filter(Usuario.login == login).first()
    listados = {c.nome for c in reg.disponiveis(u)}
    permitidos = {c.nome for c in reg.COMANDOS if reg.permitido(u, c.nome)}
    ok(listados == permitidos,
       f'{login}: a ajuda lista exatamente o que o despachante aceita')
db.close()


# ==============================================================================
print('\n[5] CONTAGEM — quatro caminhos, nenhum pede número de inventário')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/contar')
texto = tg_ope.tudo()
ok(f'Inventário {INV_NUM}' in texto or 'Inventário' in texto,
   f'entra no inventário sem perguntar o número: "{texto[:70]}"')
ok('Responda só a quantidade' in texto, 'e explica que basta o número')
ok('/' in tg_ope.ultima and 'em ' in tg_ope.ultima,
   f'já pergunta o primeiro item com a unidade de medida:\n      '
   f'{tg_ope.ultima!r}')
ok('pular' in str(tg_ope.botoes_da_ultima()),
   'com os botões de pular e não tem')

# A pessoa responde SÓ o número — o caminho de menor esforço que existe
primeiro = tg_ope.ultima
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '12,5')
ok(tg_ope.enviadas and tg_ope.enviadas[0]['texto'].startswith('✓'),
   f'a contagem entra: "{tg_ope.enviadas[0]["texto"] if tg_ope.enviadas else ""}"')
ok('12,5' in tg_ope.enviadas[0]['texto'],
   'a confirmação repete a quantidade')
ok(len(tg_ope.enviadas) >= 2, 'e já pergunta o próximo item')

# Busca por nome, fora de ordem
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, 'batata')
resposta = tg_ope.ultima
achou = ('Qual deles' in resposta or 'quanto tem' in resposta.lower()
         or 'Não achei' in resposta)
ok(achou, f'nome solto é entendido como busca: "{resposta[:60]}"')

# Sem acento nem caixa
from servicos import busca as servico_busca                # noqa: E402
db = SessionLocal()
for termo in ('BATATA', 'batata'):
    r = servico_busca.buscar(db, termo, empresa_id=EMPRESA)
    ok(len(r) > 0, f'"{termo}" acha produto ({len(r)} candidatos)')
sem_acento = servico_busca.normalizar('Muçarela Fatiada')
ok(sem_acento == 'mucarela fatiada',
   f'"Muçarela" normaliza para "{sem_acento}"')
ok(servico_busca.normalizar('AGRIÃO') == 'agriao', 'e "AGRIÃO" para "agriao"')
db.close()


# ==============================================================================
print('\n[6] REENTREGA NÃO DUPLICA — o risco mais silencioso')
# ==============================================================================
class TelegramComFila(TelegramFalso):
    def __init__(self, updates):
        super().__init__()
        self.filas = list(updates)

    def receber(self, desde=None):
        return self.filas.pop(0) if self.filas else []


db = SessionLocal()
inv = db.query(SessaoInventario).filter(SessaoInventario.id == INV_ID).first()
alvo = next(i for i in inv.itens)
PRODUTO_ID = alvo.produto_id
db.close()

# O mesmo update, entregue duas vezes — que é o que o Telegram faz quando o
# servidor não confirma.
update = {'update_id': 555001,
          'message': {'chat': {'id': CHAT_OPE}, 'from': {'username': 'ope'},
                      'text': '7'}}
tg_fila = TelegramComFila([[update], [update], []])

# Deixa um item aguardando quantidade
conv_ope.atender(CHAT_OPE, '/contar')
api_bot = APIdeTeste(segredo=SEGREDO)
rodar(tg_fila, api_bot, SEGREDO, limite_de_voltas=3)

confirmacoes = [m for m in tg_fila.enviadas if m['texto'].startswith('✓')]
ok(len(confirmacoes) == 1,
   f'o update repetido virou UMA confirmação, não duas ({len(confirmacoes)})')

r = cliente.post('/api/telegram/update', json={'update_id': 555001},
                 headers={'X-Bot-Segredo': SEGREDO}).json()
ok(r['novo'] is False, 'e a API continua dizendo que ele não é novo')
r = cliente.post('/api/telegram/update', json={'update_id': 555002},
                 headers={'X-Bot-Segredo': SEGREDO}).json()
ok(r['novo'] is True, 'enquanto um update inédito é aceito')


# ==============================================================================
print('\n[7] O OPERADOR NÃO VÊ DINHEIRO PELO CHAT')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/estoque batata')
ok('R$' not in tg_ope.tudo(),
   f'o /estoque dele vem sem R$: "{tg_ope.ultima[:70]}"')
ok(any(c.isdigit() for c in tg_ope.ultima), 'mas com o saldo')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/resumo')
ok('R$' not in tg_ope.tudo(), 'o /resumo da contagem também')

# Para o gerente, o que se prova é que o CANAL entrega os valores — e não
# que existam. Num banco recém-criado não há compra, logo não há custo, e
# procurar "R$" no texto acusaria o código por falta de dado. O que a regra
# promete é `com_valores`, e é isso que se checa.
tg_ger.limpar()
conv_ger.atender(CHAT_GER, '/estoque batata')
api_ger = APIdeTeste(segredo=SEGREDO).como(
    cliente.post('/api/telegram/sessao', json={'chat_id': CHAT_GER},
                 headers={'X-Bot-Segredo': SEGREDO}).json()['token'])
e_ger = api_ger.get('/api/estoque', unidade_id=UNI_ID, busca='batata')
ok(e_ger.get('com_valores') is not False,
   'o estoque do gerente vem COM valores')
if e_ger.get('itens'):
    ok('ultimo_custo' in e_ger['itens'][0],
       'com a coluna de custo presente')

api_ope_tok = cliente.post('/api/telegram/sessao', json={'chat_id': CHAT_OPE},
                           headers={'X-Bot-Segredo': SEGREDO}).json()['token']
e_ope = APIdeTeste(segredo=SEGREDO).como(api_ope_tok).get(
    '/api/estoque', unidade_id=UNI_ID, busca='batata')
ok(e_ope.get('com_valores') is False, 'e o do operador, sem')

# A asserção original aceitava "não conheço" — e é justamente a resposta
# ERRADA aqui. "Não conheço /cmv" é mentira: o comando existe, só não é
# dele. Quem lê isso conclui que digitou errado e tenta variações, em vez
# de falar com o gerente.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/cmv')
ok('não está no seu acesso' in tg_ope.ultima,
   f'/cmv é recusado pelo motivo certo: "{tg_ope.ultima[:60]}"')
ok('gerente' in tg_ope.ultima.lower(), 'e diz a quem pedir')
ok('Não conheço' not in tg_ope.ultima,
   'sem fingir que o comando não existe — ele existe, só não é dele')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/contagem')
ok('Não conheço' in tg_ope.ultima and '/contar' in tg_ope.ultima,
   'já um comando que não existe devolve a lista, com o certo dentro')


# ==============================================================================
print('\n[8] AS TRÊS AÇÕES IRREVERSÍVEIS NÃO EXISTEM POR AQUI')
# ==============================================================================
# E a recusa é do BACKEND: mesmo chamando a rota direto com o token do canal,
# como faria um segundo bot ou um script, ela é negada.
from auth.security import criar_token_telegram             # noqa: E402
tok_ger = {'Authorization': 'Bearer ' + criar_token_telegram(ids['bot_ger'])}

r = cliente.post(f'/api/inventario/sessoes/{INV_ID}/finalizar', headers=tok_ger)
ok(r.status_code == 403, f'finalizar inventário: {r.status_code}')
ok('tela' in r.json()['detail'], 'e a recusa manda abrir o navegador')

r = cliente.post(f'/api/inventario/sessoes/{INV_ID}/cancelar', headers=tok_ger)
ok(r.status_code == 403, f'cancelar inventário: {r.status_code}')

r = cliente.post('/api/metas', headers=tok_ger, json={})
ok(r.status_code == 403, f'definir meta: {r.status_code}')

# O contraste que prova que a recusa é do CANAL e não do papel: um Diretor,
# que PODE definir meta, também é barrado quando o token é de Telegram — e
# passa quando é da web. Sem este par, o 403 acima poderia ser só a
# capacidade faltando, e o teste não provaria nada sobre o canal.
# O Arquiteto precisa estar VINCULADO para o token de canal sequer ser
# aceito — sem chat_id, a recusa vem antes, com 401. Foi o que a primeira
# versão deste teste pegou, e o 401 estava certo: é o desvínculo funcionando.
db = SessionLocal()
db.query(Usuario).filter(Usuario.id == ARQ_ID).update(
    {'telegram_chat_id': 900009})
db.commit()
db.close()
tok_dir_tg = {'Authorization': 'Bearer ' + criar_token_telegram(ARQ_ID)}
r = cliente.post('/api/metas', headers=tok_dir_tg, json={})
ok(r.status_code == 403 and 'tela' in r.json()['detail'],
   f'o Arquiteto pelo Telegram também é barrado ({r.status_code})')

r = cliente.post('/api/metas', headers=H_ARQ, json={})
ok(r.status_code != 403,
   f'e o MESMO Arquiteto pela web passa pelo canal ({r.status_code})')


# ==============================================================================
print('\n[9] DESVINCULAR VALE NA HORA')
# ==============================================================================
tok_ope = criar_token_telegram(ids['bot_ope'])
antes = cliente.get('/api/usuarios/poderes',
                    headers={'Authorization': 'Bearer ' + tok_ope})
ok(antes.status_code == 200, 'antes de desvincular, o token do bot funciona')

cliente.delete('/api/telegram/vinculo', headers=entrar('bot_ope'))
depois = cliente.get('/api/usuarios/poderes',
                     headers={'Authorization': 'Bearer ' + tok_ope})
ok(depois.status_code == 401,
   f'o MESMO token para de valer na hora ({depois.status_code}) — '
   f'não espera os 180 dias vencerem')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/contar')
ok('não está ligado' in tg_ope.ultima,
   'e o bot volta a tratá-lo como desconhecido')


# ==============================================================================
print('\n[10] O SEGREDO DO BOT É EXIGIDO')
# ==============================================================================
r = cliente.post('/api/telegram/sessao', json={'chat_id': CHAT_GER})
ok(r.status_code == 401, f'sem o segredo, a rota de sessão recusa ({r.status_code})')
r = cliente.post('/api/telegram/sessao', json={'chat_id': CHAT_GER},
                 headers={'X-Bot-Segredo': 'chute'})
ok(r.status_code == 401, 'com segredo errado também')
r = cliente.post('/api/telegram/sessao', json={'chat_id': CHAT_GER},
                 headers={'X-Bot-Segredo': SEGREDO})
ok(r.status_code == 200 and r.json()['vinculado'] is True,
   'e com o certo devolve a sessão')
ok('token' in r.json(), 'com um token novo — nenhum fica guardado em disco')

# A rota de VÍNCULO também. Ela nascia aberta, com o argumento de que o token
# ainda não existe — verdade, mas o bot já carrega o segredo para as rotas
# acima, e sem ele /vincular ficava na internet aceitando palpites.
r = cliente.post('/api/telegram/vincular',
                 json={'codigo': '000000', 'chat_id': 800001})
ok(r.status_code == 401,
   f'/vincular sem o segredo recusa antes de olhar o código ({r.status_code})')


# ==============================================================================
print('\n[11] PERDA — três formatos, e o motivo é obrigatório')
# ==============================================================================
# A seção 9 desvinculou o operador de propósito. Sem religar aqui, TODA
# asserção daqui para baixo recebe "este Telegram não está ligado" — e as
# que procuram texto genérico passariam em verde sem ter exercitado nada.
# Foi o que aconteceu na primeira versão desta suíte.
tg_ope, conv_ope = vincular('bot_ope', CHAT_OPE)
ok('conectado' in tg_ope.ultima.lower(),
   'operador religado para as seções seguintes')

# Perda é o lançamento que a operação mais deixa de fazer, e por um motivo
# mecânico: dá trabalho parar e abrir o sistema. Se o bot não cobrir os três
# jeitos de dizer a mesma coisa, ele reintroduz o atrito que veio tirar.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/sair')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/perda batata doce 3 validade')
ok('Perda registrada' in tg_ope.tudo(),
   f'uma linha só resolve: "{tg_ope.ultima[:70]}"')
ok('Vencimento' in tg_ope.tudo() or 'validade' in tg_ope.tudo().lower(),
   'e a confirmação repete o motivo')
ok('Saldo' in tg_ope.tudo(),
   'com o saldo antes e depois — "3 kg" não dá noção de tamanho, "168 → 165" dá')

# Guiado: sem nada, o bot pergunta.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/perda')
ok('item' in tg_ope.ultima.lower(), 'sem argumento, ele conduz')
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, 'batata doce')
ok('quanto' in tg_ope.ultima.lower(), 'pergunta a quantidade')
ok('em ' in tg_ope.ultima.lower(),
   f'dizendo a unidade de medida: "{tg_ope.ultima[:60]}"')
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '2')
botoes = tg_ope.botoes_da_ultima()
ok(any(b.startswith('mot:') for b in botoes),
   f'e oferece os motivos em botões ({len(botoes)})')
ok('Por quê' in tg_ope.ultima, 'perguntando o porquê')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '', callback='mot:QUEBRA')
ok('Perda registrada' in tg_ope.tudo(), 'o botão fecha o lançamento')

# Perda de zero não é perda
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/perda')
conv_ope.atender(CHAT_OPE, 'batata doce')
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '0')
ok('zero não é perda' in tg_ope.ultima.lower(),
   f'zero é recusado — criaria movimento vazio: "{tg_ope.ultima[:50]}"')
conv_ope.atender(CHAT_OPE, '/sair')


# ==============================================================================
print('\n[12] REQUISIÇÃO — abre, lança e avisa quando vai faltar')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/requisicao')
ok('quisi' in tg_ope.ultima.lower(),
   f'abre uma requisição sem pedir número: "{tg_ope.ultima[:60]}"')
ok('/atender' in tg_ope.ultima, 'e diz como terminar')

tg_ope.limpar()
conv_ope.atender(CHAT_OPE, 'batata doce 2')
ok('✓' in tg_ope.ultima, f'lança pelo nome: "{tg_ope.ultima[:60]}"')

# Pedir mais do que existe: o aviso tem que vir AGORA, não na hora de
# atender, quando a produção já está parada esperando.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, 'batata doce 999999')
ok('faltar' in tg_ope.ultima.lower() or '⚠' in tg_ope.ultima,
   f'pedir além do saldo avisa na hora: "{tg_ope.ultima[:80]}"')

# O operador ABRE e LANÇA, mas não ATENDE — atender baixa o estoque.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/atender')
ok('não está no seu acesso' in tg_ope.ultima,
   f'/atender é do gerente para cima: "{tg_ope.ultima[:60]}"')

# E o gerente atende a mesma requisição
tg_ger.limpar()
conv_ger.atender(CHAT_GER, '/atender')
ok('atendida' in tg_ger.ultima.lower() or 'Qual requisição' in tg_ger.ultima,
   f'o gerente consegue: "{tg_ger.ultima[:70]}"')
conv_ope.atender(CHAT_OPE, '/sair')


# ==============================================================================
print('\n[13] CONGELAR — existe no bot; finalizar continua fora')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/congelar')
ok('não está no seu acesso' in tg_ope.ultima,
   'o operador não congela — é ele quem conta')

# O gerente abre um inventário pela tela e congela pelo chat
_cab_ger = entrar('bot_ger')
_r = cliente.post('/api/inventario/sessoes/abrir', headers=_cab_ger,
                  json={'unidade_id': UNI_ID, 'geral': False,
                        'categoria_ids': [], 'descricao': 'para congelar'})
if _r.status_code == 201:
    tg_ger.limpar()
    conv_ger.atender(CHAT_GER, '/congelar')
    ok('congelado' in tg_ger.tudo().lower() or 'Qual inventário' in tg_ger.ultima,
       f'o gerente congela pelo chat: "{tg_ger.ultima[:70]}"')
else:
    # Sem família livre não dá para abrir outro — o conflito de escopo é
    # regra do sistema, não falha do bot. Confere que a recusa EXPLICA, e
    # segue: exigir um código específico aqui seria testar o inventário,
    # que já tem suíte própria.
    ok(_r.status_code in (400, 409) and len(_r.json().get('detail', '')) > 20,
       f'abrir esbarrou numa regra e disse qual ({_r.status_code}: '
       f'{_r.json().get("detail", "")[:60]})')


# ==============================================================================
print('\n[14] COMPRA — o custo aparece porque a nota está na mão dele')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/compra')
botoes = tg_ope.botoes_da_ultima()
ok(any(b.startswith('forn:') for b in botoes),
   f'oferece os fornecedores, não pede id ({len(botoes)} botões)')

if botoes:
    tg_ope.limpar()
    conv_ope.atender(CHAT_OPE, '', callback=botoes[0])
    ok('nota' in tg_ope.ultima.lower(), 'depois pergunta o número da nota')

    tg_ope.limpar()
    conv_ope.atender(CHAT_OPE, '1500')
    ok('quantidade' in tg_ope.ultima.lower() and 'custo' in tg_ope.ultima.lower(),
       'e ensina o formato da linha, com exemplo')

    tg_ope.limpar()
    conv_ope.atender(CHAT_OPE, 'batata doce 50 10,48')
    ok('R$' in tg_ope.ultima and '524' in tg_ope.ultima,
       f'lança e mostra o total: "{tg_ope.ultima[:70]}"')

    tg_ope.limpar()
    conv_ope.atender(CHAT_OPE, '/fechar')
    ok('encerrada' in tg_ope.ultima.lower(),
       f'e fecha com o total da nota: "{tg_ope.ultima[:70]}"')


# ==============================================================================
print('\n[15] CONSULTA — cada um vê o que é dele')
# ==============================================================================
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/cmv')
ok('não está no seu acesso' in tg_ope.ultima,
   f'/cmv não é do operador: "{tg_ope.ultima[:60]}"')

tg_ger.limpar()
conv_ger.atender(CHAT_GER, '/cmv')
ok('CMV' in tg_ger.ultima or 'inventário' in tg_ger.ultima.lower(),
   f'o gerente recebe o CMV ou o motivo de não haver: "{tg_ger.ultima[:70]}"')

# /painel NÃO é recusado ao operador — ele recebe outra coisa, que é a fila
# de trabalho dele. Negar o comando de "e agora, o que eu faço?" justamente
# a quem executa deixaria a pergunta mais útil do bot sem dono.
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/painel')
ok('não está no seu acesso' not in tg_ope.ultima,
   f'/painel serve ao operador: "{tg_ope.ultima[:60]}"')
ok('R$' not in tg_ope.ultima, 'sem nenhum R$ para ele')

tg_ger.limpar()
conv_ger.atender(CHAT_GER, '/painel')
ok(len(tg_ger.ultima) > 10, 'e o gerente recebe o painel com números')


# ==============================================================================
print('\n[16] TODO COMANDO DA AJUDA TEM DONO')
# ==============================================================================
# O teste que fecha o ciclo: a ajuda anuncia comandos, e até agora oito deles
# não tinham handler nenhum — caíam em "não conheço". A ajuda mentia, e
# nenhum teste percebia porque cada um olhava só o comando que testava.
import re as _re                                             # noqa: E402

for chat, conv, tg, quem in ((CHAT_OPE, conv_ope, tg_ope, 'operador'),
                             (CHAT_GER, conv_ger, tg_ger, 'gerente')):
    conv.atender(chat, '/sair')
    tg.limpar()
    conv.atender(chat, '/ajuda')
    anunciados = set(_re.findall(r'/[a-zà-ú]+', tg.ultima))
    orfaos = []
    for cmd in sorted(anunciados):
        if cmd in ('/ajuda', '/sair', '/vincular'):
            continue
        tg.limpar()
        conv.atender(chat, cmd)
        if 'Não conheço' in tg.ultima:
            orfaos.append(cmd)
        conv.atender(chat, '/sair')
    ok(not orfaos,
       f'{quem}: nenhum comando anunciado cai em "não conheço" ({orfaos})')


# ==============================================================================
print('\n[17] O BOT APRENDE COMO A CASA CHAMA AS COISAS')
# ==============================================================================
# A tabela de apelidos existia e nada a preenchia: o sistema oferecia as
# mesmas três opções toda vez, para sempre. O laço só fecha quando a ESCOLHA
# vira conhecimento.
from models import SinonimoProduto                          # noqa: E402

_db = SessionLocal()
_db.query(SinonimoProduto).delete()
_db.commit()
_db.close()

conv_ope.atender(CHAT_OPE, '/sair')
tg_ope.limpar()
conv_ope.atender(CHAT_OPE, '/perda bata')          # termo ambíguo de propósito
botoes = tg_ope.botoes_da_ultima()
ok(any(b.startswith('pperda:') for b in botoes),
   f'"bata" é ambíguo e o bot oferece as opções ({len(botoes)})')

if botoes:
    escolhido_id = int(botoes[0].split(':')[1])
    conv_ope.atender(CHAT_OPE, '', callback=botoes[0])

    _db = SessionLocal()
    aprendido = _db.query(SinonimoProduto).filter(
        SinonimoProduto.produto_id == escolhido_id,
        SinonimoProduto.termo == 'bata').first()
    _db.close()
    ok(aprendido is not None,
       'escolher no menu ensina que "bata" é aquele produto')

    # A prova que importa: na segunda vez, a MESMA digitação não pergunta.
    conv_ope.atender(CHAT_OPE, '/sair')
    tg_ope.limpar()
    conv_ope.atender(CHAT_OPE, '/perda bata')
    ok('quanto' in tg_ope.ultima.lower(),
       f'na segunda vez ele vai direto: "{tg_ope.ultima[:60]}"')
    conv_ope.atender(CHAT_OPE, '/sair')

# Aprender é ESCOLHA CONFIRMADA, nunca palpite: um termo que resolveu
# sozinho não pode virar apelido, senão o acerto de hoje vira regra amanhã
# e ninguém entende de onde saiu.
_db = SessionLocal()
antes = _db.query(SinonimoProduto).count()
_db.close()
conv_ope.atender(CHAT_OPE, '/perda batata doce 1 quebra')
_db = SessionLocal()
depois = _db.query(SinonimoProduto).count()
_db.close()
ok(depois == antes,
   f'acerto direto NÃO vira apelido ({antes} → {depois})')


# ==============================================================================
print('\n[18] ADIVINHAR O CÓDIGO NÃO PODE COMPENSAR')
# ==============================================================================
# Seis dígitos são um milhão de combinações, e isso parece bastante até
# alguém medir: sem limite, 400 palpites errados do mesmo chat levaram 1,8
# segundo. O prêmio não é pequeno — quem acertar QUALQUER código vivo recebe
# o token daquela pessoa, e escolhe a que chat amarrar.
CHAT_ATAQUE = 800002
CAB = {'X-Bot-Segredo': SEGREDO}


def palpite(codigo, chat=CHAT_ATAQUE):
    return cliente.post('/api/telegram/vincular',
                        json={'codigo': codigo, 'chat_id': chat}, headers=CAB)


respostas = [palpite(f'{9000 + i:06d}') for i in range(8)]
codigos_http = [r.status_code for r in respostas]
bloqueou_em = next((i for i, r in enumerate(respostas)
                    if 'Muitas tentativas' in r.text), None)
ok(bloqueou_em is not None and bloqueou_em <= 5,
   f'o chat é bloqueado no {bloqueou_em}º palpite ({codigos_http})')

# E o bloqueio vale mesmo para um código BOM: quem varre e acerta depois de
# esgotar as chances não pode ser premiado pela sorte.
bom = cliente.post('/api/telegram/codigo',
                   headers=entrar('bot_ger')).json()['codigo']
r = palpite(bom)
ok('Muitas tentativas' in r.text,
   'e nem um código válido passa enquanto o castigo corre')
ok(r.status_code == 400 and 'Perfil' in r.text,
   'a recusa diz o que fazer, não só que deu errado')

# Chat diferente não herda o castigo — senão um atacante trancaria a loja
# inteira só errando bastante.
r = palpite(bom, chat=800003)
ok('conectado' in r.text.lower() or r.status_code == 200,
   f'outro chat continua conseguindo vincular ({r.status_code})')

# Formato errado não gasta chance: quem manda "/vincular" sem nada não está
# adivinhando, está errando o comando.
from servicos import telegram as _stg                       # noqa: E402
from database import SessionLocal as _SL                    # noqa: E402
_db = _SL()
_db.query(TentativaVinculo).filter(
    TentativaVinculo.chat_id == 800004).delete()
_db.commit()
for _ in range(9):
    palpite('abc', chat=800004)
ok(_stg._erros_recentes(_db, 800004) == 0,
   'nove "/vincular abc" não consomem nenhuma das cinco chances')
_db.close()

# Acertar limpa o histórico: quem errou duas vezes hoje e acertou não pode
# carregar essas duas para a próxima troca de aparelho, semanas depois.
_db = _SL()
restantes = _db.query(TentativaVinculo).filter(
    TentativaVinculo.chat_id == 800003).count()
_db.close()
ok(restantes == 0, f'vínculo bem-sucedido zera o contador do chat ({restantes})')

shutil.rmtree(os.path.dirname(_copia), ignore_errors=True)
print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
