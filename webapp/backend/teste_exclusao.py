"""
Tirar um lançamento do estoque — e provar que ele saiu de TODAS as contas.

O QUE ESTA SUÍTE PROTEGE
------------------------
A exclusão é a única operação do sistema que apaga número de estoque e de
CMV. Ela erra de dois jeitos, e os dois são silenciosos:

  1. TIRA DA TELA E NÃO DA CONTA. É o que aconteceria com uma coluna
     `excluido_em`: vinte e quatro consultas leem `movimentos`, e a que
     esquecesse de filtrar continuaria somando no CMV um movimento que a
     tela mostra como excluído. Ninguém veria — o número sairia plausível.
     Por isso a linha SAI da tabela, e por isso o teste central aqui compara
     a apuração antes e depois.

  2. DEIXA O DOCUMENTO MENTINDO. Apagar o ajuste de um inventário fechado
     deixa o inventário apontando um número que o estoque não tem. Esses
     movimentos são recusados, e a recusa é testada.

E A EXCLUSÃO PARCIAL É PIOR QUE A RECUSA
----------------------------------------
Excluir sete de oito e avisar depois é a forma mais rápida de alguém achar
que excluiu os oito. Lote com um item travado não exclui nada.
"""
import os
import sys
from datetime import date, timedelta

BACKEND = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BACKEND)
os.environ.setdefault("DATABASE_URL",
                      "sqlite:///" + os.path.join(BACKEND, "solo_cmv.db"))

from database import SessionLocal, engine                      # noqa: E402
from models import (Base, Movimento, MovimentoExcluido,        # noqa: E402
                    NotaFiscalImportada, PapelUsuario, Produto,
                    SessaoInventario, StatusNotaFiscal, TipoMovimento,
                    Unidade, Usuario)
from servicos import exclusao as servico_exclusao              # noqa: E402
from servicos.permissoes import Capacidade, pode               # noqa: E402

Base.metadata.create_all(engine)

falhas = []


def ok(condicao, mensagem):
    if not condicao:
        falhas.append(mensagem)
    print(("  ok  " if condicao else "  XX  ") + mensagem)


db = SessionLocal()
eu = db.query(Usuario).filter(Usuario.ativo.is_(True)).first()
loja = db.query(Unidade).first()
produto = db.query(Produto).filter(Produto.ativo.is_(True)).first()
criados = []


def novo_movimento(tipo=TipoMovimento.COMPRA, quantidade=7.0, custo=10.0,
                   documento="NF 999999", **extra):
    movimento = Movimento(
        unidade_id=loja.id, produto_id=produto.id, tipo=tipo,
        quantidade=quantidade, custo_unitario=custo,
        custo_total=round(quantidade * custo, 2),
        numero_documento=documento, data=date.today(),
        usuario_id=eu.id, **extra)
    db.add(movimento)
    db.commit()
    criados.append(movimento.id)
    return movimento


# ==============================================================================
print('\n[1] QUEM PODE — E POR QUE SÃO DUAS PERMISSÕES')
# ==============================================================================
# Anular a nota é operação do negócio: documento e estoque saem juntos, nada
# fica mentindo. Excluir linha avulsa é manutenção, e deixa o documento de
# origem dizendo uma coisa que o estoque não confirma.
class _Falso:
    def __init__(self, papel):
        self.papel = papel


for papel, anular, excluir in (
        (PapelUsuario.OPERADOR, False, False),
        (PapelUsuario.GERENTE, False, False),
        (PapelUsuario.ADMIN, False, False),
        (PapelUsuario.DIRETOR, True, False),
        (PapelUsuario.ARQUITETO, True, True)):
    u = _Falso(papel)
    ok(pode(u, Capacidade.ANULAR_NOTA) is anular
       and pode(u, Capacidade.EXCLUIR_MOVIMENTO) is excluir,
       f'{papel.value:<9} anula nota: {anular} | exclui avulso: {excluir}')

# ==============================================================================
print('\n[2] O QUE NÃO SE EXCLUI POR AQUI')
# ==============================================================================
sessao = db.query(SessaoInventario).first()
contagem = novo_movimento(tipo=TipoMovimento.CONTAGEM_FINAL, documento=None,
                          sessao_inventario_id=sessao.id if sessao else None)
motivo = servico_exclusao.por_que_nao(contagem)
ok(motivo is not None, 'ajuste de inventário é recusado')
ok(motivo and 'inventário' in motivo,
   'e a recusa manda desfazer pelo inventário, que sabe cuidar dos dois lados')

compra = novo_movimento()
ok(servico_exclusao.por_que_nao(compra) is None,
   'compra avulsa pode ser excluída')

# Lote com um travado não exclui NADA. Excluir sete de oito e avisar depois é
# a forma mais rápida de alguém achar que excluiu os oito.
antes = db.query(Movimento).count()
try:
    servico_exclusao.excluir(db, [compra, contagem], eu, 'teste')
    ok(False, 'o lote misto deveria ter sido recusado')
except servico_exclusao.ErroExclusao as erro:
    ok('Nada foi excluído' in str(erro),
       'lote com um item travado não exclui NENHUM')
db.rollback()
ok(db.query(Movimento).count() == antes,
   f'e a contagem de movimentos não mudou ({antes})')

# ==============================================================================
print('\n[3] SAI DO SALDO E SAI DO CMV')
# ==============================================================================
# O teste que justifica o desenho. Não basta a linha sumir da tela: ela tem
# que sumir da apuração, que é onde o erro custaria dinheiro.
inicio = date.today() - timedelta(days=30)
fim = date.today() + timedelta(days=1)


def compras_no_periodo():
    """O valor de compras que a apuração enxerga para este produto."""
    return sum(
        m.custo_total or 0
        for m in db.query(Movimento).filter(
            Movimento.unidade_id == loja.id,
            Movimento.produto_id == produto.id,
            Movimento.tipo == TipoMovimento.COMPRA,
            Movimento.data >= inicio, Movimento.data <= fim).all())


grande = novo_movimento(quantidade=100.0, custo=25.0, documento="NF 888888")
com_ele = compras_no_periodo()
ok(com_ele >= 2500.0,
   f'com o lançamento, a apuração vê R$ {com_ele:.2f} em compras')

quantos, avisos = servico_exclusao.excluir(db, [grande], eu,
                                           'lançado em duplicidade')
sem_ele = compras_no_periodo()
ok(quantos == 1, 'o lançamento é excluído')
ok(abs(com_ele - sem_ele - 2500.0) < 0.01,
   f'e a apuração cai exatamente os R$ 2500,00 (de {com_ele:.2f} '
   f'para {sem_ele:.2f})')
ok(db.query(Movimento).filter(Movimento.id == grande.id).first() is None,
   'a linha sai da tabela viva — nenhuma consulta precisa lembrar de filtrar')

# ==============================================================================
print('\n[4] O RASTRO')
# ==============================================================================
rastro = db.query(MovimentoExcluido).filter(
    MovimentoExcluido.movimento_id == grande.id).first()
ok(rastro is not None, 'o que saiu do estoque fica registrado')
ok(rastro and rastro.quantidade == 100.0 and rastro.custo_total == 2500.0,
   f'com a quantidade e o valor que tinha ({rastro.quantidade} / '
   f'{rastro.custo_total})')
ok(rastro and rastro.excluido_por_id == eu.id,
   'com quem excluiu')
ok(rastro and rastro.excluido_motivo == 'lançado em duplicidade',
   f'e por quê: {rastro.excluido_motivo!r}')
ok(rastro and rastro.excluido_em is not None, 'e quando')

# ==============================================================================
print('\n[5] A NOTA VOLTA A PODER SER LANÇADA')
# ==============================================================================
# O caso que motivou tudo: a compra foi lançada errada e precisa ser
# refeita. Sem isto, a única saída era lançar uma perda para compensar — o
# que tira a quantidade do estoque e DEIXA o custo dentro do CMV, escondendo
# o erro em vez de desfazê-lo.
nota = NotaFiscalImportada(
    unidade_id=loja.id, chave_acesso='9' * 44, numero='777777', serie='1',
    status=StatusNotaFiscal.PROCESSADA, origem='FOTO',
    valor_produtos=140.0, valor_total=140.0, criado_por_id=eu.id,
    data_emissao=date.today())
db.add(nota)
db.commit()
a = novo_movimento(quantidade=7.0, custo=10.0, documento='NF 777777')
b = novo_movimento(quantidade=7.0, custo=10.0, documento='NF 777777')

# Excluindo SÓ UM item, a nota continua lançada — com menos itens que o papel.
# Fingir que a nota inteira saiu aqui seria mentir sobre o estoque.
quantos, avisos = servico_exclusao.excluir(db, [a], eu, 'item errado')
db.refresh(nota)
ok(nota.status == StatusNotaFiscal.PROCESSADA,
   'excluindo um item de uma nota, ela CONTINUA lançada')
ok(any('ainda tem' in x for x in avisos),
   f'e o aviso diz que a nota ficou com menos itens que o papel: {avisos}')

# Saindo o último, a nota inteira sai junto.
quantos, avisos = servico_exclusao.excluir(db, [b], eu, 'item errado')
db.refresh(nota)
ok(nota.status == StatusNotaFiscal.ANULADA,
   'saindo o último item, a nota é anulada')
ok(any('mesma chave' in x for x in avisos),
   'e o aviso diz que ela pode ser lançada de novo')
ok(nota.processado_em is None,
   'a marca de "lançada em tal dia" é limpa — senão a nota mentiria')

# ==============================================================================
print('\n[6] ANULAR A NOTA INTEIRA — o caminho da diretoria')
# ==============================================================================
nota2 = NotaFiscalImportada(
    unidade_id=loja.id, chave_acesso='8' * 44, numero='666666', serie='1',
    status=StatusNotaFiscal.PROCESSADA, origem='XML',
    valor_produtos=300.0, valor_total=300.0, criado_por_id=eu.id,
    data_emissao=date.today())
db.add(nota2)
db.commit()
novo_movimento(quantidade=10.0, custo=10.0, documento='NF 666666')
novo_movimento(quantidade=20.0, custo=10.0, documento='NF 666666')
antes_cmv = compras_no_periodo()

quantos, avisos = servico_exclusao.anular_nota(db, nota2, eu, 'preço errado')
ok(quantos == 2, f'os dois itens da nota saem juntos ({quantos})')
ok(abs(antes_cmv - compras_no_periodo() - 300.0) < 0.01,
   'e os R$ 300,00 saem da apuração')
db.refresh(nota2)
ok(nota2.status == StatusNotaFiscal.ANULADA, 'a nota fica anulada')
ok(nota2.mensagem and 'preço errado' in nota2.mensagem,
   f'com o motivo gravado nela: {nota2.mensagem!r}')

# Anular duas vezes não é idempotente por acidente — é recusado, porque a
# segunda vez quase sempre é um clique repetido em tela que não atualizou.
try:
    servico_exclusao.anular_nota(db, nota2, eu, '')
    ok(False, 'anular de novo deveria ser recusado')
except servico_exclusao.ErroExclusao as erro:
    ok('não está lançada' in str(erro),
       'anular uma nota já anulada é recusado, com o motivo')

# ==============================================================================
print('\n[7] LIMPEZA')
# ==============================================================================
for movimento_id in criados:
    movimento = db.get(Movimento, movimento_id)
    if movimento:
        db.delete(movimento)
for registro in db.query(MovimentoExcluido).filter(
        MovimentoExcluido.movimento_id.in_(criados)).all():
    db.delete(registro)
for chave in ('9' * 44, '8' * 44):
    achada = db.query(NotaFiscalImportada).filter_by(chave_acesso=chave).first()
    if achada:
        db.delete(achada)
db.commit()
ok(db.query(MovimentoExcluido).filter(
    MovimentoExcluido.movimento_id.in_(criados)).count() == 0,
   'o banco de desenvolvimento fica como estava')
db.close()

print('\n' + ('FALHAS:\n  ' + '\n  '.join(falhas) if falhas else 'Tudo certo.'))
sys.exit(1 if falhas else 0)
