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
from typing import Dict, Optional, Iterable

from sqlalchemy.orm import Session

from models import Movimento, HistoricoCusto, TipoMovimento

TIPOS_CONTAGEM = (TipoMovimento.CONTAGEM_INICIAL, TipoMovimento.CONTAGEM_FINAL)
TIPOS_SAIDA = (TipoMovimento.REQUISICAO, TipoMovimento.PERDA)


def saldos_por_produto(db: Session, unidade_id: int,
                       produto_ids: Optional[Iterable[int]] = None) -> Dict[int, float]:
    """Saldo atual de cada produto na unidade. Chave = produto_id."""
    query = db.query(Movimento).filter(Movimento.unidade_id == unidade_id)
    if produto_ids is not None:
        ids = list(produto_ids)
        if not ids:
            return {}
        query = query.filter(Movimento.produto_id.in_(ids))

    por_produto: Dict[int, list] = {}
    for m in query.all():
        por_produto.setdefault(m.produto_id, []).append(m)

    saldos: Dict[int, float] = {}
    for produto_id, movs in por_produto.items():
        contagens = [m for m in movs if m.tipo in TIPOS_CONTAGEM]
        ultima = max(contagens, key=lambda m: (m.data, m.id)) if contagens else None

        def posterior(m):
            """Movimento que aconteceu depois da última contagem."""
            return ultima is None or (m.data, m.id) > (ultima.data, ultima.id)

        entradas = sum(m.quantidade for m in movs
                       if m.tipo == TipoMovimento.COMPRA and posterior(m))
        saidas = sum(m.quantidade for m in movs
                     if m.tipo in TIPOS_SAIDA and posterior(m))

        base = ultima.quantidade if ultima else 0
        saldos[produto_id] = round(base + entradas - saidas, 3)

    return saldos


def data_ultima_contagem(db: Session, unidade_id: int) -> Dict[int, object]:
    """Data da última contagem de cada produto (para exibição)."""
    resultado: Dict[int, object] = {}
    movs = db.query(Movimento).filter(
        Movimento.unidade_id == unidade_id,
        Movimento.tipo.in_(TIPOS_CONTAGEM),
    ).all()
    for m in movs:
        atual = resultado.get(m.produto_id)
        if atual is None or m.data > atual:
            resultado[m.produto_id] = m.data
    return resultado


def ultimos_custos(db: Session, unidade_id: int) -> Dict[int, float]:
    """Último custo pago por produto na unidade (equivalente à aba UCustoInfo)."""
    custos: Dict[int, float] = {}
    for h in (db.query(HistoricoCusto)
              .filter(HistoricoCusto.unidade_id == unidade_id)
              .order_by(HistoricoCusto.data.asc(), HistoricoCusto.id.asc()).all()):
        custos[h.produto_id] = h.custo
    return custos
