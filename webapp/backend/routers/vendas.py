"""
Registro manual de faturamento por unidade e período — insumo do cálculo de
CMV % enquanto não há integração com PDV/certificado digital (ver routers/nfe.py).
"""
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import VendaPeriodo, PapelUsuario
from schemas import VendaPeriodoOut, VendaPeriodoCreate
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer

router = APIRouter(prefix="/vendas", tags=["vendas"])


@router.get("", response_model=List[VendaPeriodoOut])
def listar(unidade_id: Optional[int] = None,
           db: Session = Depends(get_db),
           usuario=Depends(requer(Capacidade.VER_FATURAMENTO))):
    """Faturamento lançado por período.

    Esta rota exigia apenas estar logado enquanto o POST logo abaixo exigia
    Gerente — e era por aqui que o faturamento vazava. Guardar a escrita e
    deixar a leitura aberta é o descuido mais fácil de cometer, porque
    gravar assusta e ler não.
    """
    query = db.query(VendaPeriodo)
    if unidade_id:
        query = query.filter(VendaPeriodo.unidade_id == unidade_id)
    return query.order_by(VendaPeriodo.data_inicio.desc()).limit(200).all()


@router.post("", response_model=VendaPeriodoOut, status_code=201)
def registrar(dados: VendaPeriodoCreate, db: Session = Depends(get_db),
              usuario=Depends(requer(Capacidade.LANCAR_FATURAMENTO))):
    if dados.data_fim < dados.data_inicio:
        raise HTTPException(status_code=400, detail="A data final não pode ser anterior à inicial.")

    # Períodos sobrepostos contariam o mesmo dia duas vezes no CMV %.
    conflito = db.query(VendaPeriodo).filter(
        VendaPeriodo.unidade_id == dados.unidade_id,
        VendaPeriodo.data_inicio <= dados.data_fim,
        VendaPeriodo.data_fim >= dados.data_inicio,
    ).first()
    if conflito:
        raise HTTPException(
            status_code=409,
            detail=f"Já existe faturamento lançado de "
                   f"{conflito.data_inicio.strftime('%d/%m/%Y')} a "
                   f"{conflito.data_fim.strftime('%d/%m/%Y')}, que se sobrepõe a este período. "
                   f"Exclua o anterior ou ajuste as datas — dias contados duas vezes distorcem o CMV %.",
        )

    venda = VendaPeriodo(**dados.model_dump(), usuario_id=usuario.id)
    db.add(venda)
    db.commit()
    db.refresh(venda)
    return venda


@router.delete("/{venda_id}", status_code=204)
def excluir(venda_id: int, db: Session = Depends(get_db),
            usuario=Depends(requer(Capacidade.LANCAR_FATURAMENTO))):
    """Remove um faturamento lançado por engano."""
    venda = db.query(VendaPeriodo).filter(VendaPeriodo.id == venda_id).first()
    if not venda:
        raise HTTPException(status_code=404, detail="Faturamento não encontrado.")
    db.delete(venda)
    db.commit()
