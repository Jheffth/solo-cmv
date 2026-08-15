from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import DespesaExtra, PapelUsuario
from schemas import DespesaExtraOut, DespesaExtraCreate
from auth.deps import get_current_user, exigir_papeis

router = APIRouter(prefix="/despesas", tags=["despesas extras"])


@router.get("", response_model=List[DespesaExtraOut])
def listar(unidade_id: Optional[int] = None,
           db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    query = db.query(DespesaExtra)
    if unidade_id:
        query = query.filter(DespesaExtra.unidade_id == unidade_id)
    return query.order_by(DespesaExtra.data_inicio.desc()).limit(200).all()


@router.post("", response_model=DespesaExtraOut, status_code=201)
def registrar(dados: DespesaExtraCreate, db: Session = Depends(get_db),
              usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    despesa = DespesaExtra(**dados.model_dump())
    db.add(despesa)
    db.commit()
    db.refresh(despesa)
    return despesa
