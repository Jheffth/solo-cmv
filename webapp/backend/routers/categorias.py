from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Categoria, PapelUsuario
from schemas import CategoriaOut, CategoriaCreate
from auth.deps import get_current_user, exigir_papeis

router = APIRouter(prefix="/categorias", tags=["categorias"])


@router.get("", response_model=List[CategoriaOut])
def listar(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    empresa_id = usuario.empresa_id
    query = db.query(Categoria)
    if empresa_id:
        query = query.filter(Categoria.empresa_id == empresa_id)
    return query.order_by(Categoria.nome).all()


@router.post("", response_model=CategoriaOut, status_code=201)
def criar(dados: CategoriaCreate, db: Session = Depends(get_db),
          usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    categoria = Categoria(empresa_id=usuario.empresa_id, nome=dados.nome)
    db.add(categoria)
    db.commit()
    db.refresh(categoria)
    return categoria
