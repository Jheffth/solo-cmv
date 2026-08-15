"""
Serviço de requisição — regra de negócio em um lugar só.

Mesma ideia do serviço de contagem: a requisição pode chegar pela tela web
e, no futuro, por um bot do Telegram ou coletor. A regra fica aqui; cada
canal só traduz a entrada e trata `ErroRequisicao` do seu jeito.

O QUE A REQUISIÇÃO FAZ
----------------------
Ela retira itens do estoque com destino à produção. Diferente do inventário,
não tem escopo por família: o requisitante escolhe qualquer item cadastrado.

Lançar um item NÃO baixa o estoque — a baixa acontece de uma vez no
atendimento. Isso permite montar o pedido com calma, conferir e só então
efetivar.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional, List

from sqlalchemy.orm import Session

from models import (
    Requisicao, RequisicaoItem, StatusRequisicao, Produto, Movimento, TipoMovimento,
)
from calculo_estoque import saldos_por_produto, ultimos_custos

ORIGEM_WEB = "WEB"
ORIGEM_TELEGRAM = "TELEGRAM"
ORIGEM_API = "API"

# Status em que a requisição aceita o lançamento de itens
STATUS_ACEITA_ITENS = (StatusRequisicao.INICIADA,)
# Status em que a requisição ainda está "viva"
STATUS_ATIVOS = (StatusRequisicao.ABERTA, StatusRequisicao.INICIADA)

ROTULOS = {
    StatusRequisicao.ABERTA: "aberta",
    StatusRequisicao.INICIADA: "iniciada",
    StatusRequisicao.ATENDIDA: "atendida",
    StatusRequisicao.CANCELADA: "cancelada",
}

TRANSICOES = {
    StatusRequisicao.ABERTA: {StatusRequisicao.INICIADA, StatusRequisicao.CANCELADA},
    StatusRequisicao.INICIADA: {StatusRequisicao.ATENDIDA, StatusRequisicao.CANCELADA},
    StatusRequisicao.ATENDIDA: set(),
    StatusRequisicao.CANCELADA: set(),
}


class ErroRequisicao(Exception):
    def __init__(self, mensagem: str, codigo: str = "INVALIDO", http: int = 409):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.http = http


@dataclass
class ResultadoItem:
    item: RequisicaoItem
    requisicao: Requisicao
    produto: Produto
    substituiu: bool
    quantidade_anterior: Optional[float]
    saldo_disponivel: float


# ==============================================================================
# NUMERAÇÃO
# ==============================================================================
def proximo_numero(db: Session, unidade_id: int) -> str:
    """Sequência própria da requisição, por unidade, com 2 dígitos no mínimo.

    Considera todas as requisições já abertas (inclusive canceladas) — número
    consumido não volta, porque a requisição cancelada segue consultável.
    """
    numeros = [
        int(r.numero)
        for r in db.query(Requisicao).filter(Requisicao.unidade_id == unidade_id).all()
        if str(r.numero).strip().isdigit()
    ]
    return f"{(max(numeros) + 1) if numeros else 1:02d}"


# ==============================================================================
# LOCALIZAÇÃO
# ==============================================================================
def localizar_requisicao(db: Session, *, requisicao_id: Optional[int] = None,
                         numero: Optional[str] = None,
                         unidade_id: Optional[int] = None) -> Requisicao:
    if requisicao_id:
        req = db.query(Requisicao).filter(Requisicao.id == requisicao_id).first()
        if not req:
            raise ErroRequisicao("Requisição não encontrada.", "NAO_ENCONTRADA", 404)
        return req

    if numero and unidade_id:
        req = db.query(Requisicao).filter(
            Requisicao.unidade_id == unidade_id,
            Requisicao.numero == str(numero).strip(),
        ).first()
        if not req:
            raise ErroRequisicao(
                f"Requisição nº {numero} não encontrada nesta unidade.", "NAO_ENCONTRADA", 404)
        return req

    raise ErroRequisicao("Informe a requisição (id, ou número junto da unidade).",
                         "NAO_INFORMADA", 400)


def localizar_produto(db: Session, *, produto_id: Optional[int] = None,
                      codigo: Optional[str] = None,
                      empresa_id: Optional[int] = None) -> Produto:
    query = db.query(Produto)
    if empresa_id:
        query = query.filter(Produto.empresa_id == empresa_id)

    if produto_id:
        produto = query.filter(Produto.id == produto_id).first()
        if not produto:
            raise ErroRequisicao("Produto não encontrado.", "PRODUTO_NAO_ENCONTRADO", 404)
        return produto
    if codigo:
        produto = query.filter(Produto.codigo == str(codigo).strip()).first()
        if not produto:
            raise ErroRequisicao(f"Nenhum produto com o código {codigo}.",
                                 "PRODUTO_NAO_ENCONTRADO", 404)
        return produto
    raise ErroRequisicao("Informe o produto (id ou código).", "PRODUTO_NAO_INFORMADO", 400)


# ==============================================================================
# VALIDAÇÕES
# ==============================================================================
def validar_aceita_itens(req: Requisicao) -> None:
    if req.status in STATUS_ACEITA_ITENS:
        return
    if req.status == StatusRequisicao.ABERTA:
        raise ErroRequisicao(
            f"Requisição nº {req.numero} está apenas aberta. "
            f"Inicie a requisição para poder lançar itens.",
            "NAO_INICIADA",
        )
    raise ErroRequisicao(
        f"Requisição nº {req.numero} está {ROTULOS.get(req.status, req.status.value)} "
        f"e não aceita mais itens.",
        "ENCERRADA",
    )


def validar_quantidade(quantidade) -> float:
    try:
        valor = float(quantidade)
    except (TypeError, ValueError):
        raise ErroRequisicao("Quantidade inválida.", "QUANTIDADE_INVALIDA", 400)
    if valor <= 0:
        raise ErroRequisicao("A quantidade requisitada deve ser maior que zero.",
                             "QUANTIDADE_INVALIDA", 400)
    return valor


# ==============================================================================
# LANÇAMENTO DE ITEM
# ==============================================================================
def lancar_item(
    db: Session,
    *,
    quantidade,
    requisicao_id: Optional[int] = None,
    numero_requisicao: Optional[str] = None,
    unidade_id: Optional[int] = None,
    produto_id: Optional[int] = None,
    codigo_produto: Optional[str] = None,
    observacao: Optional[str] = None,
    usuario_id: Optional[int] = None,
    empresa_id: Optional[int] = None,
    origem: str = ORIGEM_WEB,
) -> ResultadoItem:
    """Adiciona (ou corrige) um item da requisição.

    Não baixa o estoque — isso acontece no atendimento. O saldo disponível é
    guardado junto para dar contexto a quem for atender depois.
    """
    req = localizar_requisicao(db, requisicao_id=requisicao_id,
                               numero=numero_requisicao, unidade_id=unidade_id)
    validar_aceita_itens(req)

    produto = localizar_produto(db, produto_id=produto_id, codigo=codigo_produto,
                                empresa_id=empresa_id)
    valor = validar_quantidade(quantidade)

    saldo = saldos_por_produto(db, req.unidade_id, [produto.id]).get(produto.id, 0.0)

    item = db.query(RequisicaoItem).filter(
        RequisicaoItem.requisicao_id == req.id,
        RequisicaoItem.produto_id == produto.id,
    ).first()

    substituiu = item is not None
    anterior = item.quantidade if item else None

    if item is None:
        item = RequisicaoItem(requisicao_id=req.id, produto_id=produto.id)
        db.add(item)

    item.quantidade = valor
    item.saldo_no_pedido = saldo
    item.observacao = (observacao or "").strip() or None
    item.lancado_em = datetime.utcnow()
    item.usuario_id = usuario_id
    item.origem = origem

    db.commit()
    db.refresh(item)

    return ResultadoItem(item=item, requisicao=req, produto=produto,
                         substituiu=substituiu, quantidade_anterior=anterior,
                         saldo_disponivel=saldo)


def remover_item(db: Session, requisicao_id: int, item_id: int) -> Requisicao:
    req = localizar_requisicao(db, requisicao_id=requisicao_id)
    validar_aceita_itens(req)
    item = db.query(RequisicaoItem).filter(
        RequisicaoItem.id == item_id,
        RequisicaoItem.requisicao_id == req.id,
    ).first()
    if not item:
        raise ErroRequisicao("Item não encontrado nesta requisição.", "ITEM_NAO_ENCONTRADO", 404)
    db.delete(item)
    db.commit()
    db.refresh(req)
    return req


# ==============================================================================
# MUDANÇAS DE STATUS
# ==============================================================================
def iniciar(db: Session, requisicao_id: int) -> Requisicao:
    req = localizar_requisicao(db, requisicao_id=requisicao_id)
    if req.status != StatusRequisicao.ABERTA:
        raise ErroRequisicao(
            f"Só é possível iniciar uma requisição aberta "
            f"(esta está {ROTULOS.get(req.status, req.status.value)}).",
            "STATUS_INVALIDO",
        )
    req.status = StatusRequisicao.INICIADA
    req.data_inicio = datetime.utcnow()
    db.commit()
    db.refresh(req)
    return req


def atender(db: Session, requisicao_id: int, usuario_id: Optional[int] = None,
            permitir_saldo_negativo: bool = True) -> Requisicao:
    """Efetiva a requisição: baixa os itens do estoque.

    Cada item vira um movimento de REQUISICAO, que o cálculo de estoque
    subtrai. O custo é congelado no momento do atendimento, para o valor da
    saída não mudar depois.

    `permitir_saldo_negativo` fica ligado por padrão porque, na prática, o
    estoque teórico costuma estar defasado e travar a produção seria pior do
    que registrar o negativo — que aliás é sinal de que falta inventário.
    """
    req = localizar_requisicao(db, requisicao_id=requisicao_id)
    if req.status != StatusRequisicao.INICIADA:
        raise ErroRequisicao(
            f"Só é possível atender uma requisição iniciada "
            f"(esta está {ROTULOS.get(req.status, req.status.value)}).",
            "STATUS_INVALIDO",
        )
    if not req.itens:
        raise ErroRequisicao("A requisição não tem nenhum item lançado.", "SEM_ITENS", 400)

    ids = [i.produto_id for i in req.itens]
    saldos = saldos_por_produto(db, req.unidade_id, ids)
    custos = ultimos_custos(db, req.unidade_id)

    if not permitir_saldo_negativo:
        faltas = [i for i in req.itens if saldos.get(i.produto_id, 0) < i.quantidade]
        if faltas:
            nomes = ", ".join(f"{f.produto.nome} (saldo {saldos.get(f.produto_id, 0)})" for f in faltas)
            raise ErroRequisicao(f"Saldo insuficiente para: {nomes}.", "SALDO_INSUFICIENTE")

    hoje = (req.data_producao or datetime.utcnow().date())
    for item in req.itens:
        custo = custos.get(item.produto_id)
        item.custo_unitario = custo
        db.add(Movimento(
            unidade_id=req.unidade_id,
            produto_id=item.produto_id,
            tipo=TipoMovimento.REQUISICAO,
            quantidade=item.quantidade,
            custo_unitario=custo,
            custo_total=round((custo or 0) * item.quantidade, 4),
            data=hoje,
            requisicao_id=req.id,
            numero_documento=f"REQ-{req.numero}",
            usuario_id=usuario_id,
        ))

    req.status = StatusRequisicao.ATENDIDA
    req.data_atendimento = datetime.utcnow()
    req.usuario_atendimento_id = usuario_id
    db.commit()
    db.refresh(req)
    return req


def cancelar(db: Session, requisicao_id: int, usuario_id: Optional[int] = None) -> Requisicao:
    req = localizar_requisicao(db, requisicao_id=requisicao_id)
    if req.status not in STATUS_ATIVOS:
        raise ErroRequisicao(
            f"Requisição já está {ROTULOS.get(req.status, req.status.value)}.",
            "STATUS_INVALIDO",
        )
    req.status = StatusRequisicao.CANCELADA
    req.usuario_atendimento_id = usuario_id
    db.commit()
    db.refresh(req)
    return req


# ==============================================================================
# RESUMO
# ==============================================================================
def resumo_requisicao(db: Session, req: Requisicao) -> dict:
    ids = [i.produto_id for i in req.itens]
    saldos = saldos_por_produto(db, req.unidade_id, ids) if ids else {}
    custos = ultimos_custos(db, req.unidade_id)

    valor = 0.0
    sem_saldo = 0
    for item in req.itens:
        custo = item.custo_unitario if item.custo_unitario is not None else custos.get(item.produto_id)
        valor += (custo or 0) * item.quantidade
        if saldos.get(item.produto_id, 0) < item.quantidade:
            sem_saldo += 1

    return {
        "total_itens": len(req.itens),
        "quantidade_total": round(sum(i.quantidade for i in req.itens), 3),
        "valor_total": round(valor, 2),
        "itens_sem_saldo": sem_saldo,
    }
