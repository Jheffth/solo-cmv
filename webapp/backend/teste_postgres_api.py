"""
Verificação da API inteira contra o banco apontado por DATABASE_URL.

Roda igual em SQLite e PostgreSQL — é essa a prova de que a migração não
mudou comportamento. Os números conferidos são os mesmos nos dois bancos.
"""
import os
import shutil
import sys
import tempfile
import time

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)

# A suíte GRAVA (cria fornecedor, meta e nota fiscal) — então nunca roda
# contra o banco de trabalho. No SQLite, trabalha numa cópia; no PostgreSQL,
# quem chama já aponta DATABASE_URL para um banco descartável.
if not os.environ.get('DATABASE_URL', '').startswith('postgresql'):
    _copia = os.path.join(tempfile.mkdtemp(), 'teste_api.db')
    shutil.copy(os.path.join(BACKEND, 'solo_cmv.db'), _copia)
    os.environ['DATABASE_URL'] = 'sqlite:///' + _copia

from database import criar_tabelas, engine       # noqa: E402
from migracoes import aplicar_migracoes          # noqa: E402

criar_tabelas()
aplicar_migracoes()

from fastapi.testclient import TestClient        # noqa: E402
from main import app                             # noqa: E402

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(('  ok  ' if condicao else '  XX  ') + mensagem)


print(f'\nDIALETO: {engine.dialect.name}')

# Credenciais vêm do ambiente: este arquivo é versionado, e senha em
# arquivo versionado é senha pública.
#   set TESTE_LOGIN=... & set TESTE_SENHA=...     (Windows)
#   export TESTE_LOGIN=... TESTE_SENHA=...        (Linux)
LOGIN = os.environ.get('TESTE_LOGIN', 'Jh3ffth')
SENHA = os.environ.get('TESTE_SENHA')
if not SENHA:
    sys.exit('Defina TESTE_SENHA com a senha do usuário Arquiteto para rodar este teste.')

cliente = TestClient(app)
resposta = cliente.post('/api/auth/login', json={'login': LOGIN, 'senha': SENHA})
if resposta.status_code != 200:
    sys.exit(f'Login falhou ({resposta.status_code}). Confira TESTE_LOGIN e TESTE_SENHA.')
H = {'Authorization': 'Bearer ' + resposta.json()['access_token']}

print('\n[1] TODAS AS ROTAS RESPONDEM')
ROTAS = [
    '/api/unidades', '/api/unidades/escopo',
    '/api/dashboard/painel?unidade_id=1', '/api/dashboard/painel?unidade_id=REGIONAL',
    '/api/dashboard/resumo?unidade_id=1',
    '/api/metas/painel?unidade_id=1', '/api/metas/historico?unidade_id=1',
    '/api/metas/previa-distribuicao?meta_geral=0.29&unidade_id=1'
    '&data_inicio=2026-08-03&data_fim=2026-08-10',
    '/api/relatorios',
    '/api/relatorios/fechamento?unidade_id=1',
    '/api/relatorios/fechamento?unidade_id=REGIONAL',
    '/api/relatorios/curva-abc?unidade_id=REGIONAL',
    '/api/relatorios/familias?unidade_id=REGIONAL',
    '/api/relatorios/comparativo?unidade_id=REGIONAL',
    '/api/cmv/apuracao?unidade_id=1&data_inicio=2026-08-03&data_fim=2026-08-10',
    '/api/cmv/configuracao?unidade_id=1',
    '/api/estoque?unidade_id=1', '/api/estoque?unidade_id=REGIONAL',
    '/api/movimentos?unidade_id=1', '/api/movimentos?unidade_id=REGIONAL',
    '/api/inventario/sessoes?unidade_id=1',
    '/api/inventario/sessoes?unidade_id=REGIONAL',
    '/api/requisicoes?unidade_id=REGIONAL',
    '/api/produtos', '/api/produtos/unidades-medida', '/api/fornecedores',
    '/api/perdas/motivos', '/api/vendas?unidade_id=1', '/api/categorias',
    '/api/usuarios',
]
ruins = []
inicio = time.perf_counter()
for rota in ROTAS:
    r = cliente.get(rota, headers=H)
    if r.status_code != 200:
        ruins.append(f'{r.status_code} {rota} — {str(r.json())[:100]}')
duracao = (time.perf_counter() - inicio) * 1000
for erro in ruins:
    print('     ' + erro)
ok(not ruins, f'{len(ROTAS) - len(ruins)}/{len(ROTAS)} rotas em {duracao:.0f} ms')

print('\n[2] OS NÚMEROS SÃO OS MESMOS (independentes do banco)')
d = cliente.get('/api/cmv/apuracao?unidade_id=1&data_inicio=2026-08-03&data_fim=2026-08-10',
                headers=H).json()
print(f"     CMV {d['geral']['cmv']} · faturamento {d['geral']['faturamento']} "
      f"· meta {d['meta']}")
ok(abs(d['geral']['cmv'] - 37544.98) < 0.05, f"CMV do período: {d['geral']['cmv']}")
ok(abs(d['geral']['faturamento'] - 96500.0) < 0.05, 'faturamento do período')
ok(d['total_linhas'] == 65, f"65 itens apurados ({d['total_linhas']})")

reg = cliente.get('/api/dashboard/painel?unidade_id=REGIONAL&referencia=2026-08',
                  headers=H).json()
print(f"     Regional: CMV {reg['geral']['cmv']} · "
      f"{reg['geral']['cmv_percentual'] * 100:.2f}%")
ok(abs(reg['geral']['cmv'] - 39044.98) < 0.05, 'CMV consolidado da rede')
ok(abs(reg['geral']['cmv_percentual'] - 0.350179) < 1e-5, 'percentual recalculado')

est = cliente.get('/api/estoque?unidade_id=1', headers=H).json()
ok(abs(est['resumo']['valor_total'] - 12155.06) < 0.05,
   f"valor em estoque: {est['resumo']['valor_total']}")

print('\n[3] ENUMS GUARDADOS COMO TEXTO')
movs = cliente.get('/api/movimentos?unidade_id=1', headers=H).json()
tipos = {m['tipo'] for m in movs}
ok(tipos <= {'COMPRA', 'CONTAGEM_INICIAL', 'CONTAGEM_FINAL', 'REQUISICAO', 'PERDA'},
   f'tipos de movimento legíveis: {sorted(tipos)}')
usuarios = cliente.get('/api/usuarios', headers=H).json()
ok(all(u['papel'] in ('ARQUITETO', 'DIRETOR', 'ADMIN', 'GERENTE', 'OPERADOR')
       for u in usuarios), 'papéis legíveis')

print('\n[4] ESCRITA — a sequência foi reposicionada?')
antes = len(cliente.get('/api/fornecedores', headers=H).json())
r = cliente.post('/api/fornecedores', headers=H,
                 json={'nome': f'TESTE SEQUENCIA {time.time():.0f}'})
ok(r.status_code == 201, f'cria fornecedor ({r.status_code})')
novo_id = r.json().get('id')
ok(novo_id and novo_id > antes,
   f'id novo não colide com os importados (id {novo_id}, havia {antes})')

r = cliente.post('/api/metas', headers=H, json={
    'unidade_id': 1, 'tipo': 'CMV_GERAL', 'valor': 0.28,
    'formato': 'PERCENTUAL', 'observacao': 'smoke'})
ok(r.status_code == 201, f'cria meta ({r.status_code})')

r = cliente.post('/api/movimentos/nota-fiscal', headers=H, json={
    'unidade_id': 1, 'numero_documento': 'SMOKE-1', 'data': '2026-08-14',
    'itens': [{'produto_id': 1, 'quantidade': 2, 'custo_unitario': 3.5}]})
ok(r.status_code == 201, f'lança nota fiscal ({r.status_code})')

print('\n[5] PDFs')
for chave in ('fechamento', 'comparativo', 'curva-abc', 'familias'):
    r = cliente.get(f'/api/relatorios/{chave}?unidade_id=1&referencia=2026-08&formato=pdf',
                    headers=H)
    ok(r.status_code == 200 and r.content[:5] == b'%PDF-',
       f'{chave}: {len(r.content)} bytes')
r = cliente.get('/api/relatorios/fechamento?unidade_id=REGIONAL&referencia=2026-08'
                '&formato=pdf', headers=H)
ok(r.status_code == 200 and r.content[:5] == b'%PDF-',
   f'fechamento regional: {len(r.content)} bytes')

print('\n[6] FRONTEIRA DE UNIDADE CONTINUA DE PÉ')
r = cliente.get('/api/estoque?unidade_id=9999', headers=H)
ok(r.status_code == 403, f'unidade inexistente devolve 403 ({r.status_code})')

print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
