from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Fornecedor, PapelUsuario
from schemas import FornecedorOut, FornecedorCreate
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer

router = APIRouter(prefix="/fornecedores", tags=["fornecedores"])


@router.get("", response_model=List[FornecedorOut])
def listar(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    query = db.query(Fornecedor)
    if usuario.empresa_id:
        query = query.filter(Fornecedor.empresa_id == usuario.empresa_id)
    return query.order_by(Fornecedor.nome).all()


@router.post("", response_model=FornecedorOut, status_code=201)
def criar(dados: FornecedorCreate, db: Session = Depends(get_db),
          usuario=Depends(requer(Capacidade.CADASTRAR))):
    fornecedor = Fornecedor(empresa_id=usuario.empresa_id, **dados.model_dump())
    db.add(fornecedor)
    db.commit()
    db.refresh(fornecedor)
    return fornecedor
