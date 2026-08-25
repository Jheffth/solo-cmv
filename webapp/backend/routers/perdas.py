"""
Perdas — o que saiu do estoque e não virou venda.

A regra vive em servicos/perda.py; aqui só entra a tradução HTTP, para que
um bot do Telegram possa lançar perda pelo mesmo caminho sem duplicar nada.

A perda já está dentro do CMV (consumiu estoque sem gerar receita). Registrá-la
separadamente não muda o total — muda o diagnóstico: sem isso, "CMV subiu 3
pontos" e "jogamos fora R$ 4.000 de hortifruti vencido" são o mesmo número.
"""
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Movimento, TipoMovimento, MotivoPerda, PapelUsuario
from schemas import (
    PerdaLancamento, PerdaOut, PerdaResultado, PerdaResumo, PerdaResumoMotivo,
)
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer, ve_dinheiro
from servicos.perda import (
    ErroPerda, registrar as servico_registrar, estornar as servico_estornar,
    ROTULOS_MOTIVO, ORIGEM_WEB,
)

router = APIRouter(prefix="/perdas", tags=["perdas"])


def _saida(mov: Movimento) -> PerdaOut:
    p = mov.produto
    return PerdaOut(
        id=mov.id,
        unidade_id=mov.unidade_id,
        produto_id=mov.produto_id,
        produto=p.nome if p else f"#{mov.produto_id}",
        codigo=p.codigo if p else None,
        categoria=(p.categoria.nome.replace("Família - ", "")
                   if p and p.categoria else None),
        quantidade=mov.quantidade,
        unidade_medida=p.unidade_medida if p else None,
        custo_unitario=mov.custo_unitario,
        custo_total=mov.custo_total,
        motivo=mov.motivo or MotivoPerda.OUTRO,
        motivo_rotulo=ROTULOS_MOTIVO.get(mov.motivo, "—"),
        observacao=mov.observacao,
        numero_documento=mov.numero_documento,
        data=mov.data,
    )


@router.get("/motivos")
def listar_motivos(usuario=Depends(get_current_user)):
    """Motivos disponíveis, para o front montar a lista sem hardcode."""
    return [{"valor": m.value, "rotulo": ROTULOS_MOTIVO[m]} for m in MotivoPerda]


@router.get("", response_model=List[PerdaOut])
def listar(unidade_id: int,
           motivo: Optional[MotivoPerda] = None,
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    query = db.query(Movimento).filter(
        Movimento.unidade_id == unidade_id,
        Movimento.tipo == TipoMovimento.PERDA,
    )
    if motivo:
        query = query.filter(Movimento.motivo == motivo)
    if data_inicio:
        query = query.filter(Movimento.data >= data_inicio)
    if data_fim:
        query = query.filter(Movimento.data <= data_fim)

    movs = query.order_by(Movimento.data.desc(), Movimento.id.desc()).limit(500).all()
    return [_saida(m) for m in movs]


@router.get("/resumo", response_model=PerdaResumo)
def resumo(unidade_id: int,
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           db: Session = Depends(get_db),
           usuario=Depends(requer(Capacidade.VER_DINHEIRO))):
    """Perda agrupada por motivo — é aqui que a informação vira ação.

    Agregado, e por isso fechado para quem não vê dinheiro. Registrar a
    perda de 3 kg continua sendo do operador; saber que a casa jogou fora
    R$ 4.000 de hortifruti no mês é leitura de quem decide o que fazer a
    respeito.
    """
    query = db.query(Movimento).filter(
        Movimento.unidade_id == unidade_id,
        Movimento.tipo == TipoMovimento.PERDA,
    )
    if data_inicio:
        query = query.filter(Movimento.data >= data_inicio)
    if data_fim:
        query = query.filter(Movimento.data <= data_fim)

    movs = query.all()
    agrupado = {}
    for m in movs:
        chave = m.motivo or MotivoPerda.OUTRO
        alvo = agrupado.setdefault(chave, {"ocorrencias": 0, "quantidade": 0.0, "valor": 0.0})
        alvo["ocorrencias"] += 1
        alvo["quantidade"] += m.quantidade
        alvo["valor"] += m.custo_total or 0.0

    por_motivo = [
        PerdaResumoMotivo(
            motivo=k, rotulo=ROTULOS_MOTIVO.get(k, "—"),
            ocorrencias=v["ocorrencias"],
            quantidade=round(v["quantidade"], 3),
            valor=round(v["valor"], 2),
        )
        for k, v in sorted(agrupado.items(), key=lambda kv: -kv[1]["valor"])
    ]

    return PerdaResumo(
        total_ocorrencias=len(movs),
        valor_total=round(sum(m.custo_total or 0 for m in movs), 2),
        por_motivo=por_motivo,
    )


@router.post("", response_model=PerdaResultado, status_code=201)
def lancar(dados: PerdaLancamento, db: Session = Depends(get_db),
           usuario=Depends(requer(Capacidade.LANCAR_PERDA))):
    try:
        r = servico_registrar(
            db,
            unidade_id=dados.unidade_id,
            quantidade=dados.quantidade,
            motivo=dados.motivo,
            produto_id=dados.produto_id,
            codigo_produto=dados.codigo_produto,
            data=dados.data,
            observacao=dados.observacao,
            custo_unitario=dados.custo_unitario,
            usuario_id=usuario.id,
            empresa_id=getattr(usuario, "empresa_id", None),
            origem=ORIGEM_WEB,
        )
    except ErroPerda as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)

    return PerdaResultado(
        perda=_saida(r.movimento),
        saldo_anterior=r.saldo_anterior,
        saldo_atual=r.saldo_atual,
    )


@router.delete("/{perda_id}", status_code=204)
def estornar(perda_id: int, db: Session = Depends(get_db),
             usuario=Depends(requer(Capacidade.ESTORNAR_PERDA))):
    """Apaga uma perda lançada por engano e devolve a quantidade ao estoque."""
    try:
        servico_estornar(db, perda_id)
    except ErroPerda as e:
        raise HTTPException(status_code=e.http, detail=e.mensagem)
