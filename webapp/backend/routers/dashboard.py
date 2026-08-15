"""
Indicadores gerenciais do painel.

A rota que importa é /dashboard/painel: ela devolve, numa chamada só, tudo
que a tela inicial mostra — período encaixado no ciclo de inventário,
pendências, KPIs com variação, série histórica, composição do CMV, itens que
mais custam, perdas por motivo, estoque parado e atividade recente.

A regra vive em servicos/painel.py, que apenas compõe o que os outros
serviços já calculam. Aqui só entra a tradução HTTP.

/dashboard/resumo continua existindo para não quebrar integrações antigas,
mas não alimenta mais a tela.
"""
from datetime import date as date_type
from typing import Optional
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Produto, Fornecedor, Categoria, Unidade, Movimento, VendaPeriodo,
    SessaoInventario, StatusSessaoInventario, PapelUsuario,
)
from auth.deps import get_current_user
from servicos import painel as servico_painel
from servicos import regional as servico_regional
from servicos import escopo as servico_escopo

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

PAPEIS_COM_METAS = (PapelUsuario.ARQUITETO, PapelUsuario.DIRETOR)


@router.get("/painel")
def painel(unidade_id: Optional[str] = Query(
               None, description='Id da unidade ou "REGIONAL" para o consolidado'),
           referencia: Optional[str] = Query(None, description="Mês no formato 2026-08"),
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           historico: int = Query(5, ge=0, le=12),
           db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Painel de uma unidade, ou da rede inteira quando unidade_id=REGIONAL."""
    recorte = servico_escopo.resolver(db, usuario, unidade_id)

    if recorte.regional:
        return servico_regional.painel(
            db, recorte.unidades, referencia=referencia,
            data_inicio=data_inicio, data_fim=data_fim, historico=historico,
            empresa_id=usuario.empresa_id)

    try:
        return servico_painel.montar(
            db, unidade_id=recorte.unidade_id, referencia=referencia,
            data_inicio=data_inicio, data_fim=data_fim, historico=historico,
            empresa_id=usuario.empresa_id,
            pode_ver_metas=usuario.papel in PAPEIS_COM_METAS,
        )
    except ValueError as erro:
        raise HTTPException(400, str(erro))


@router.get("/resumo")
def resumo(unidade_id: Optional[int] = None, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    empresa_id = usuario.empresa_id

    q_produtos = db.query(Produto)
    q_fornecedores = db.query(Fornecedor)
    q_categorias = db.query(Categoria)
    q_unidades = db.query(Unidade)
    if empresa_id:
        q_produtos = q_produtos.filter(Produto.empresa_id == empresa_id)
        q_fornecedores = q_fornecedores.filter(Fornecedor.empresa_id == empresa_id)
        q_categorias = q_categorias.filter(Categoria.empresa_id == empresa_id)
        q_unidades = q_unidades.filter(Unidade.empresa_id == empresa_id)

    q_movimentos = db.query(Movimento)
    q_vendas = db.query(VendaPeriodo)
    q_sessoes_abertas = db.query(SessaoInventario).filter(
        SessaoInventario.status.in_((
            StatusSessaoInventario.ABERTO,
            StatusSessaoInventario.CONGELADO,
            StatusSessaoInventario.EM_CONTAGEM,
        ))
    )
    if unidade_id:
        q_movimentos = q_movimentos.filter(Movimento.unidade_id == unidade_id)
        q_vendas = q_vendas.filter(VendaPeriodo.unidade_id == unidade_id)
        q_sessoes_abertas = q_sessoes_abertas.filter(SessaoInventario.unidade_id == unidade_id)

    return {
        "cadastros": {
            "produtos": q_produtos.count(),
            "fornecedores": q_fornecedores.count(),
            "categorias": q_categorias.count(),
            "unidades": q_unidades.count(),
        },
        "operacao": {
            "movimentos_lancados": q_movimentos.count(),
            "periodos_venda_informados": q_vendas.count(),
            "sessoes_inventario_abertas": q_sessoes_abertas.count(),
        },
        "cmv": {
            "implementado": True,
            "mensagem": "Motor de CMV em operação. O painel completo está em "
                        "/dashboard/painel.",
        },
    }
