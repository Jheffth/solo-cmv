from typing import List
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Unidade, PapelUsuario
from schemas import UnidadeOut, UnidadeCreate
from auth.deps import get_current_user, exigir_papeis
from servicos import escopo as servico_escopo

router = APIRouter(prefix="/unidades", tags=["unidades"])


@router.get("", response_model=List[UnidadeOut])
def listar(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Só as unidades que este usuário pode ver.

    A lista alimenta o seletor da barra de topo; devolver tudo aqui e
    esconder na tela não seria controle de acesso, seria decoração.
    """
    return servico_escopo.unidades_permitidas(db, usuario)


@router.get("/escopo")
def escopo(db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """O que este usuário enxerga — usado pela tela para montar o seletor."""
    unidades = servico_escopo.unidades_permitidas(db, usuario)
    return {
        "unidades": [{"id": u.id, "nome": u.nome, "apelido": u.apelido}
                     for u in unidades],
        "regional": servico_escopo.pode_ver_regional(usuario),
        "papel": usuario.papel.value,
        "irrestrito": servico_escopo.irrestrito(usuario),
    }


@router.post("", response_model=UnidadeOut, status_code=201)
def criar(dados: UnidadeCreate, db: Session = Depends(get_db),
          usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    unidade = Unidade(**dados.model_dump())
    db.add(unidade)
    db.commit()
    db.refresh(unidade)
    return unidade
