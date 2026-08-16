"""
Cálculo do saldo de estoque — usado pela tela de Estoque e pelo congelamento
do inventário (que precisa fotografar o saldo do momento).

REGRA
-----
O saldo é o **saldo teórico desde a última contagem física**:

    saldo = última contagem + compras posteriores − saídas posteriores

Saída é tudo que tira do estoque sem passar pela contagem:
  · REQUISICAO — foi para a produção e vira venda
  · PERDA      — quebrou, venceu, sumiu; não vira venda nenhuma

As planilhas de origem não registravam saída alguma (o consumo era implícito:
Estoque Inicial + Compras − Estoque Final), então perda e consumo normal
ficavam misturados num número só. Separar os dois é o que permite dizer *onde*
o CMV está subindo.

Sem nenhuma contagem, o saldo é compras − saídas — que dá 0 para item
recém-cadastrado.
"""
from typing import Dict, Iterable, NamedTuple, Optional

from sqlalchemy.orm import Session

from models import Movimento, HistoricoCusto, TipoMovimento

TIPOS_CONTAGEM = (TipoMovimento.CONTAGEM_INICIAL, TipoMovimento.CONTAGEM_FINAL)
TIPOS_SAIDA = (TipoMovimento.REQUISICAO, TipoMovimento.PERDA)


class _Mov(NamedTuple):
    """Um movimento reduzido ao que o cálculo de saldo precisa.

    Buscamos colunas soltas em vez de objetos Movimento inteiros: o ORM
    monta um objeto com dezenas de atributos e o registra na sessão, e aqui
    são milhares de linhas para somar quatro campos.

    São campos NOMEADOS de propósito. A versão anterior guardava tuplas
    anônimas e lia `m[4]` para pegar a quantidade — índice que existia na
    consulta (onde produto_id é a coluna 0) mas não na tupla guardada (onde
    produto_id virou a chave do dicionário). Resultado: IndexError em toda
    tela que mostra saldo. Com nome, esse erro não tem como acontecer.
    """
    tipo: object
    data: object
    id: int
    quantidade: float

    @property
    def ordem(self):
        """Critério de "veio depois": data, e o id para desempatar no mesmo dia."""
        return (self.data, self.id)


def saldos_por_produto(db: Session, unidade_id: int,
                       produto_ids: Optional[Iterable[int]] = None) -> Dict[int, float]:
    """Saldo atual de cada produto na unidade. Chave = produto_id."""
    query = db.query(
        Movimento.produto_id,
        Movimento.tipo,
        Movimento.data,
        Movimento.id,
        Movimento.quantidade,
    ).filter(Movimento.unidade_id == unidade_id)

    if produto_ids is not None:
        ids = list(produto_ids)
        if not ids:
            return {}
        query = query.filter(Movimento.produto_id.in_(ids))

    por_produto: Dict[int, list] = {}
    for pid, tipo, data, mid, qtde in query.all():
        por_produto.setdefault(pid, []).append(_Mov(tipo, data, mid, qtde or 0))

    saldos: Dict[int, float] = {}
    for produto_id, movs in por_produto.items():
        contagens = [m for m in movs if m.tipo in TIPOS_CONTAGEM]
        ultima = max(contagens, key=lambda m: m.ordem) if contagens else None
        corte = ultima.ordem if ultima else None

        entradas = 0.0
        saidas = 0.0
        for m in movs:
            if corte is not None and m.ordem <= corte:
                continue          # já está embutido na contagem
            if m.tipo == TipoMovimento.COMPRA:
                entradas += m.quantidade
            elif m.tipo in TIPOS_SAIDA:
                saidas += m.quantidade

        base = ultima.quantidade if ultima else 0.0
        saldos[produto_id] = round(base + entradas - saidas, 3)

    return saldos


def data_ultima_contagem(db: Session, unidade_id: int) -> Dict[int, object]:
    """Data da última contagem de cada produto (para exibição)."""
    resultado: Dict[int, object] = {}
    movs = db.query(Movimento.produto_id, Movimento.data).filter(
        Movimento.unidade_id == unidade_id,
        Movimento.tipo.in_(TIPOS_CONTAGEM),
    ).all()
    for pid, data in movs:
        atual = resultado.get(pid)
        if atual is None or data > atual:
            resultado[pid] = data
    return resultado


def ultimos_custos(db: Session, unidade_id: int) -> Dict[int, float]:
    """Último custo pago por produto na unidade (equivalente à aba UCustoInfo)."""
    custos: Dict[int, float] = {}
    for pid, custo in (db.query(HistoricoCusto.produto_id, HistoricoCusto.custo)
              .filter(HistoricoCusto.unidade_id == unidade_id)
              .order_by(HistoricoCusto.data.asc(), HistoricoCusto.id.asc()).all()):
        custos[pid] = custo
    return custos
