"""
Requisições — retirada de itens do estoque com destino à produção.

CICLO DE VIDA
-------------
    ABERTA ──iniciar──> INICIADA ──atender──> ATENDIDA
       └──────────── CANCELADA <──────┘

Regras:
  * Numeração sequencial própria, por unidade (01, 02…), sem reaproveitar
    número de cancelada — ela segue consultável.
  * Sem escopo por família: o requisitante pede qualquer item cadastrado.
  * ABERTA não recebe itens; é preciso iniciar (mesma lógica do congelamento
    no inventário: separa "criar o documento" de "começar a preencher").
  * Lançar item não mexe no estoque. A baixa acontece no atendimento, de uma
    vez, gerando um movimento de REQUISICAO por item.

Toda a regra vive em servicos/requisicao.py, para que um bot do Telegram
possa lançar requisições sem reimplementar nada.
"""
from datetime import datetime, date, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Requisicao, RequisicaoItem, StatusRequisicao, PapelUsuario
from schemas import (
    RequisicaoOut, RequisicaoAbrir, RequisicaoDetalheOut, RequisicaoItemOut,
    RequisicaoItemLancamento, RequisicaoItemResultado,
)
from auth.deps import get_current_user, exigir_papeis
from servicos import escopo as _escopo
from calculo_estoque import saldos_por_produto, ultimos_custos
from servicos.requisicao import (
    ErroRequisicao, proximo_numero, lancar_item, remover_item,
    iniciar as servico_iniciar, atender as servico_atender,
    cancelar as servico_cancelar, resumo_requisicao, ORIGEM_WEB,
    STATUS_ACEITA_ITENS,
)
from servicos.permissoes import Capacidade, requer

router = APIRouter(prefix="/requisicoes", tags=["requisições"])


# ==============================================================================
# HELPERS
# ==============================================================================
def _buscar(db: Session, requisicao_id: int) -> Requisicao:
    req = db.query(Requisicao).filter(Requisicao.id == requisicao_id).first()
    if not req:
        raise HTTPException(status_code=404, detail="Requisição não encontrada.")
    return req


def _item_out(item: RequisicaoItem, saldo_atual: Optional[float] = None,
              custo_atual: Optional[float] = None) -> RequisicaoItemOut:
    p = item.produto
    custo = item.custo_unitario if item.custo_unitario is not None else custo_atual
    return RequisicaoItemOut(
        id=item.id,
        produto_id=item.produto_id,
        codigo=p.codigo if p else None,
        produto=p.nome if p else None,
        categoria=p.categoria.nome if (p and p.categoria) else None,
        unidade_medida=p.unidade_medida if p else None,
        quantidade=item.quantidade,
        custo_unitario=custo,
        saldo_no_pedido=item.saldo_no_pedido,
        saldo_atual=saldo_atual,
        valor_total=round(item.quantidade * (custo or 0), 2),
        observacao=item.observacao,
    )


def _itens_out(db: Session, req: Requisicao) -> List[RequisicaoItemOut]:
    ids = [i.produto_id for i in req.itens]
    saldos = saldos_por_produto(db, req.unidade_id, ids) if ids else {}
    custos = ultimos_custos(db, req.unidade_id)
    saida = [_item_out(i, saldos.get(i.produto_id, 0.0), custos.get(i.produto_id)) for i in req.itens]
    saida.sort(key=lambda i: (i.produto or ""))
    return saida


# ==============================================================================
# LISTAGEM E CONSULTA
# ==============================================================================
@router.get("", response_model=List[RequisicaoOut])
def listar(
    unidade_id: Optional[str] = None,
    status: Optional[StatusRequisicao] = None,
    aceita_itens: bool = False,
    busca: Optional[str] = None,
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    limite: int = 200,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    # Aceita "REGIONAL": o histórico de requisições de todas as lojas. Abrir,
    # iniciar e atender continua sendo ato de uma unidade — só a CONSULTA
    # é consolidada.
    recorte = _escopo.resolver(db, usuario, unidade_id)
    query = db.query(Requisicao).filter(Requisicao.unidade_id.in_(recorte.ids))
    # Filtro por significado — "onde eu posso lançar itens agora". Ver a
    # explicação em routers/inventario.py::listar_sessoes: a lista de status
    # que serve mora no serviço, que é quem recusa.
    if aceita_itens:
        query = query.filter(Requisicao.status.in_(STATUS_ACEITA_ITENS))
    if status:
        query = query.filter(Requisicao.status == status)
    if busca:
        termo = f"%{busca.strip()}%"
        query = query.filter(
            (Requisicao.numero.ilike(termo))
            | (Requisicao.descricao.ilike(termo))
            | (Requisicao.solicitante.ilike(termo))
        )
    if data_inicio:
        query = query.filter(Requisicao.data_abertura >= datetime.combine(data_inicio, time.min))
    if data_fim:
        query = query.filter(Requisicao.data_abertura <= datetime.combine(data_fim, time.max))

    requisicoes = query.order_by(Requisicao.data_abertura.desc()).limit(
        max(1, min(limite, 1000))).all()

    # Requisição nº 01 existe em toda loja: sem a unidade, a lista da
    # Regional teria vários "REQ-01" indistinguíveis.
    nomes = {u.id: u.nome for u in recorte.unidades}
    for r in requisicoes:
        r.unidade_nome = nomes.get(r.unidade_id)
    return requisicoes


@router.get("/buscar", response_model=RequisicaoOut)
def buscar_por_numero(numero: str, unidade_id: int,
                      db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Valida um número de requisição digitado no Lançador."""
    req = db.query(Requisicao).filter(
        Requisicao.unidade_id == unidade_id,
        Requisicao.numero == numero.strip(),
    ).first()
    if not req:
        raise HTTPException(status_code=404, detail=f"Requisição nº {numero} não encontrada nesta unidade.")

    if req.status == StatusRequisicao.ABERTA:
        raise HTTPException(
            status_code=409,
            detail=f"Requisição nº {numero} está apenas aberta. Inicie a requisição para lançar itens.",
        )
    if req.status != StatusRequisicao.INICIADA:
        rotulos = {StatusRequisicao.ATENDIDA: "atendida", StatusRequisicao.CANCELADA: "cancelada"}
        raise HTTPException(
            status_code=409,
            detail=f"Requisição nº {numero} está {rotulos.get(req.status, req.status.value)} "
                   f"e não aceita mais itens.",
        )
    return req


@router.get("/{requisicao_id}", response_model=RequisicaoDetalheOut)
def detalhe(requisicao_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    req = _buscar(db, requisicao_id)
    return RequisicaoDetalheOut(requisicao=req, itens=_itens_out(db, req),
                                resumo=resumo_requisicao(db, req))


# ==============================================================================
# ABERTURA E CICLO DE VIDA
# ==============================================================================
@router.post("", response_model=RequisicaoOut, status_code=201)
def abrir(dados: RequisicaoAbrir, db: Session = Depends(get_db),
          usuario=Depends(requer(Capacidade.ABRIR_REQUISICAO))):
    req = Requisicao(
        unidade_id=dados.unidade_id,
        numero=proximo_numero(db, dados.unidade_id),
        descricao=(dados.descricao or "").strip() or None,
        solicitante=(dados.solicitante or "").strip() or None,
        data_producao=dados.data_producao,
        observacao=(dados.observacao or "").strip() or None,
        usuario_abertura_id=usuario.id,
        status=StatusRequisicao.ABERTA,
    )
    db.add(req)
    db.commit()
    db.refresh(req)
    return req


@router.post("/{requisicao_id}/iniciar", response_model=RequisicaoOut)
def iniciar(requisicao_id: int, db: Session = Depends(get_db),
            usuario=Depends(requer(Capacidade.ABRIR_REQUISICAO))):
    try:
        return servico_iniciar(db, requisicao_id)
    except ErroRequisicao as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)


@router.post("/{requisicao_id}/atender", response_model=RequisicaoDetalheOut)
def atender(requisicao_id: int, db: Session = Depends(get_db),
            usuario=Depends(requer(Capacidade.ATENDER_REQUISICAO))):
    """Efetiva a requisição: os itens saem do estoque e vão para a produção."""
    try:
        req = servico_atender(db, requisicao_id, usuario_id=usuario.id)
    except ErroRequisicao as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)
    return RequisicaoDetalheOut(requisicao=req, itens=_itens_out(db, req),
                                resumo=resumo_requisicao(db, req))


@router.post("/{requisicao_id}/cancelar", response_model=RequisicaoOut)
def cancelar(requisicao_id: int, db: Session = Depends(get_db),
             usuario=Depends(requer(Capacidade.ATENDER_REQUISICAO))):
    try:
        return servico_cancelar(db, requisicao_id, usuario_id=usuario.id)
    except ErroRequisicao as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)


# ==============================================================================
# ITENS
# ==============================================================================
@router.post("/item", response_model=RequisicaoItemResultado)
def lancar(dados: RequisicaoItemLancamento, db: Session = Depends(get_db),
           usuario=Depends(requer(Capacidade.ABRIR_REQUISICAO))):
    """Lança um item na requisição.

    Identificação flexível (requisição por id ou número + unidade; produto por
    id ou código) para servir também ao futuro bot do Telegram.
    """
    try:
        r = lancar_item(
            db,
            quantidade=dados.quantidade,
            requisicao_id=dados.requisicao_id,
            numero_requisicao=dados.numero_requisicao,
            unidade_id=dados.unidade_id,
            produto_id=dados.produto_id,
            codigo_produto=dados.codigo_produto,
            observacao=dados.observacao,
            usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
            origem=dados.origem or ORIGEM_WEB,
        )
    except ErroRequisicao as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)

    if r.substituiu:
        msg = (f"Item atualizado: {r.produto.nome} = {r.item.quantidade} "
               f"(antes era {r.quantidade_anterior}).")
    else:
        msg = f"Item adicionado: {r.produto.nome} = {r.item.quantidade}."
    if r.saldo_disponivel < r.item.quantidade:
        msg += f" Atenção: saldo em estoque é {r.saldo_disponivel}."

    return RequisicaoItemResultado(
        item=_item_out(r.item, r.saldo_disponivel),
        numero_requisicao=r.requisicao.numero,
        status_requisicao=r.requisicao.status,
        substituiu=r.substituiu,
        quantidade_anterior=r.quantidade_anterior,
        saldo_disponivel=r.saldo_disponivel,
        mensagem=msg,
    )


@router.delete("/{requisicao_id}/item/{item_id}", response_model=RequisicaoDetalheOut)
def remover(requisicao_id: int, item_id: int, db: Session = Depends(get_db),
            usuario=Depends(requer(Capacidade.ABRIR_REQUISICAO))):
    try:
        req = remover_item(db, requisicao_id, item_id)
    except ErroRequisicao as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)
    return RequisicaoDetalheOut(requisicao=req, itens=_itens_out(db, req),
                                resumo=resumo_requisicao(db, req))
