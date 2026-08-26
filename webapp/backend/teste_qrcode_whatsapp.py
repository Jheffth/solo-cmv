"""
Por que o QR Code aparecia e não conectava.

O SINTOMA ENGANA
    A imagem carregava, bonita, no tamanho certo. Escanear não fazia nada —
    e nada é a palavra exata: o celular LÊ o código, aceita, e o servidor do
    WhatsApp já descartou a vaga. Não há erro no aparelho, não há erro no
    log, não há nada para investigar.

    Por isso a busca foi parar em tamanho e contraste da imagem (dois commits
    nisso). O problema nunca esteve na imagem: estava na IDADE dela.

AS DUAS CAUSAS, QUE SE SOMAVAM
    1. O QR do WhatsApp vive ~20 segundos. O cache do backend segurava por
       30 e a tela buscava a cada 30 — o código exibido podia ter 60.
    2. O webhook ia no formato da Evolution v1 (`webhook` como string). A v2
       espera um objeto, aceita a criação e IGNORA o webhook em silêncio.
       Sem ele, o evento QRCODE_UPDATED nunca chegava, e o caminho
       "instantâneo" que existia no código nunca rodava uma única vez.

    Cada uma sozinha já quebrava. Juntas, não havia janela em que
    funcionasse.

COMO ISTO RODA SEM A EVOLUTION API
    A Evolution vira um dublê que grava o que recebeu. O que se testa aqui é
    o que MANDAMOS e QUANDO — que é exatamente onde estavam os dois erros.
"""
import os
import re
import pathlib
import sys
import time
from datetime import datetime, timedelta

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

from servicos import evolution_cliente as ec                 # noqa: E402
from servicos import whatsapp as servico                     # noqa: E402

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


class EvolutionFalsa:
    """Grava cada chamada. É toda a Evolution de que o teste precisa."""

    def __init__(self, estado='close'):
        self.chamadas = []
        self.estado = estado

    def __call__(self, metodo, caminho, payload=None, timeout=10):
        self.chamadas.append({'metodo': metodo, 'caminho': caminho,
                              'payload': payload})
        if caminho.startswith('/instance/connectionState'):
            return {'status_code': 200,
                    'dados': {'instance': {'state': self.estado}}}
        if caminho.startswith('/instance/connect'):
            return {'status_code': 200,
                    'dados': {'base64': 'QRFALSO', 'code': 'codigo-qr'}}
        return {'status_code': 201, 'dados': {}}

    def de(self, caminho_parcial):
        return [c for c in self.chamadas if caminho_parcial in c['caminho']]


def montar(estado='close'):
    cliente = ec.EvolutionCliente(base_url='http://falso', api_key='k',
                                  instancia='solo_cmv')
    falsa = EvolutionFalsa(estado)
    cliente._fazer_requisicao = falsa
    return cliente, falsa


# ==============================================================================
print('\n[1] O WEBHOOK VAI NO FORMATO DA v2')
# ==============================================================================
cliente, falsa = montar()
cliente.criar_instancia_se_necessario()

criacao = falsa.de('/instance/create')
ok(len(criacao) == 1, f'a instância é criada uma vez ({len(criacao)})')

corpo = criacao[0]['payload']
webhook = corpo.get('webhook')
ok(isinstance(webhook, dict),
   f'`webhook` é um OBJETO, não uma string ({type(webhook).__name__})')
ok(webhook.get('url'), 'com a url dentro dele')
ok(webhook.get('base64') is True,
   'e base64=True — sem isso o evento avisa que há QR novo e não manda o QR')
ok('QRCODE_UPDATED' in (webhook.get('events') or []),
   'inscrito em QRCODE_UPDATED, que é o evento inteiro do problema')

# Os campos da v1 não podem sobrar: a v2 ignora, mas quem ler o código depois
# vai achar que o webhook está configurado em dois lugares.
ok('webhook_by_events' not in corpo and 'events' not in corpo,
   'e nada do formato v1 sobrou no primeiro nível')


# ==============================================================================
print('\n[2] INSTÂNCIA QUE JÁ EXISTIA TAMBÉM GANHA O WEBHOOK')
# ==============================================================================
# Este é o caso do servidor agora: a instância foi criada ANTES da correção,
# nasceu sem webhook, e nunca mais seria recriada — porque ninguém cria de
# novo o que já existe. Sem este caminho, corrigir o código não corrigiria
# o servidor.
cliente, falsa = montar()
falsa_original = falsa.__call__


def responder_403(metodo, caminho, payload=None, timeout=10):
    falsa.chamadas.append({'metodo': metodo, 'caminho': caminho,
                           'payload': payload})
    if caminho == '/instance/create':
        return {'status_code': 403, 'erro': 'This name is already in use'}
    return {'status_code': 201, 'dados': {}}


cliente._fazer_requisicao = responder_403
cliente.criar_instancia_se_necessario()
ok(len(falsa.de('/webhook/set')) == 1,
   'nome já em uso ainda assim registra o webhook por fora')


# ==============================================================================
print('\n[3] QR EM USO NÃO É DESTRUÍDO NO MEIO DA LEITURA')
# ==============================================================================
# `connecting` quer dizer "tem gente com o celular na mão agora". Recriar a
# instância aqui invalidaria justamente o código que a pessoa está mirando.
cliente, falsa = montar(estado='connecting')
cliente.obter_qrcode()
ok(not falsa.de('/instance/delete'),
   'estado connecting NÃO recria a instância')
ok(not falsa.de('/instance/create'),
   'nem recria por baixo — o QR na mão da pessoa continua valendo')

# E o estado travado precisa ser recriado. O código testava "closed", com D;
# a Evolution devolve "close". Nunca casava, e o ramo era morto.
cliente, falsa = montar(estado='close')
cliente.obter_qrcode()
ok(falsa.de('/instance/delete'),
   'estado close (sem D) recria — era o teste que nunca casava')


# ==============================================================================
print('\n[4] O CÓDIGO NA TELA NUNCA PASSA DA VALIDADE')
# ==============================================================================
VIDA_DO_QR = 20        # segundos, medido pelo comportamento do Baileys

ok(servico.SEGUNDOS_CACHE_QRCODE < VIDA_DO_QR,
   f'o cache ({servico.SEGUNDOS_CACHE_QRCODE}s) morre antes do QR ({VIDA_DO_QR}s)')

# A conta que importa é a SOMA: idade máxima do cache + intervalo da tela.
# Era 30 + 30 = 60, o triplo da validade. Nenhuma das duas metades parecia
# absurda sozinha, e é por isso que passou.
perfil = (pathlib.Path(__file__).resolve().parent.parent / 'frontend' / 'js' / 'pages' / 'perfil.js').read_text(encoding='utf-8')
m = re.search(r'setInterval\(carregarQr,\s*(\d+)\)', perfil)
ok(m is not None, 'a tela tem um intervalo de recarga do QR')
if m:
    intervalo = int(m.group(1)) / 1000
    pior_caso = servico.SEGUNDOS_CACHE_QRCODE + intervalo
    print(f"     cache {servico.SEGUNDOS_CACHE_QRCODE}s + tela {intervalo:.0f}s "
          f"= {pior_caso:.0f}s no pior caso (QR vive {VIDA_DO_QR}s)")
    ok(pior_caso < VIDA_DO_QR,
       f'o pior caso ({pior_caso:.0f}s) cabe dentro da validade')


# ==============================================================================
print('\n[5] O CACHE SERVE E EXPIRA COMO PROMETE')
# ==============================================================================
servico.CACHE_QRCODE.update({'base64': 'data:image/png;base64,ABC',
                             'code': 'c1', 'pairing_code': None,
                             'atualizado_em': datetime.utcnow()})
chamou = {'n': 0}


def _falso_obter(numero_telefone=None):
    chamou['n'] += 1
    return {'sucesso': True, 'base64': 'data:image/png;base64,NOVO',
            'code': 'c2', 'pairing_code': None, 'estado': 'connecting'}


_real = servico.cliente_evolution.obter_qrcode
servico.cliente_evolution.obter_qrcode = _falso_obter

r = servico.obter_qrcode_cache_ou_api()
ok(chamou['n'] == 0 and r['code'] == 'c1',
   'QR recém-buscado vem do cache, sem ir à Evolution de novo')
ok(r.get('idade_segundos') is not None,
   'e a resposta diz quantos segundos ele já tem')

# Envelhecido além do limite: tem que buscar outro
servico.CACHE_QRCODE['atualizado_em'] = (
    datetime.utcnow() - timedelta(seconds=servico.SEGUNDOS_CACHE_QRCODE + 1))
r = servico.obter_qrcode_cache_ou_api()
ok(chamou['n'] == 1 and r['code'] == 'c2',
   'passou do limite, busca um novo em vez de servir o vencido')

# Pedido com número (pairing code) nunca usa cache: o código é daquele
# telefone, e servir o de outro pedido mandaria a pessoa digitar o código
# de outra pessoa.
servico.CACHE_QRCODE['atualizado_em'] = datetime.utcnow()
r = servico.obter_qrcode_cache_ou_api(numero_telefone='5561999999999')
ok(chamou['n'] == 2, 'pedido com número ignora o cache')

servico.cliente_evolution.obter_qrcode = _real

print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
