"""
Usuários e o escopo de acesso de cada um.

ESCOPO É PARTE DO CADASTRO, NÃO UM DETALHE
------------------------------------------
Criar usuário sem dizer quais unidades ele enxerga deixaria a pessoa sem
acesso a nada — ou, pior, com acesso a tudo por omissão. Por isso o
formulário pede a escolha, e quem cria não pode conceder mais do que ele
mesmo tem: o middleware de unidade barra o pedido antes de chegar aqui.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario, Unidade, PapelUsuario, PAPEIS_IRRESTRITOS
from schemas import UsuarioOut, UsuarioCreate, UsuarioEscopo
from auth.deps import get_current_user, exigir_papeis
from auth.security import hash_senha
from servicos import escopo as servico_escopo

router = APIRouter(prefix="/usuarios", tags=["usuários"])


@router.get("", response_model=List[UsuarioOut])
def listar(db: Session = Depends(get_db),
           usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    query = db.query(Usuario)
    if usuario.empresa_id:
        query = query.filter(Usuario.empresa_id == usuario.empresa_id)
    return query.order_by(Usuario.nome).all()


def _aplicar_escopo(db: Session, alvo: Usuario, autor: Usuario,
                    unidade_ids: List[int], acesso_regional: bool) -> None:
    """Vincula unidades e concede (ou não) a Regional.

    Ninguém pode dar o que não tem: um gerente da unidade A não consegue
    criar um usuário com acesso à unidade B nem à Regional.
    """
    permitidas = {u.id for u in servico_escopo.unidades_permitidas(db, autor)}
    pedidas = set(unidade_ids or [])
    invasoras = pedidas - permitidas
    if invasoras:
        raise HTTPException(
            403, "Você não pode conceder acesso a unidades que não enxerga.")

    if acesso_regional and not servico_escopo.pode_ver_regional(autor):
        raise HTTPException(
            403, "Você não pode conceder acesso à Regional sem tê-lo.")

    alvo.unidades = db.query(Unidade).filter(Unidade.id.in_(pedidas)).all() if pedidas else []
    alvo.acesso_regional = bool(acesso_regional)


@router.post("", response_model=UsuarioOut, status_code=201)
def criar(dados: UsuarioCreate, db: Session = Depends(get_db),
          usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    if db.query(Usuario).filter(Usuario.login == dados.login).first():
        raise HTTPException(409, "Já existe um usuário com este login.")

    novo = Usuario(
        empresa_id=dados.empresa_id or usuario.empresa_id,
        nome=dados.nome,
        login=dados.login,
        senha_hash=hash_senha(dados.senha),
        papel=dados.papel,
    )
    # Papéis irrestritos enxergam tudo por definição; o vínculo é registrado
    # mesmo assim, para o cadastro ficar legível.
    unidades = dados.unidade_ids
    if dados.papel in PAPEIS_IRRESTRITOS and not unidades:
        unidades = [u.id for u in servico_escopo.unidades_permitidas(db, usuario)]

    _aplicar_escopo(db, novo, usuario, unidades,
                    dados.acesso_regional or dados.papel in PAPEIS_IRRESTRITOS)
    db.add(novo)
    db.commit()
    db.refresh(novo)
    return novo


@router.put("/{usuario_id}/escopo", response_model=UsuarioOut)
def alterar_escopo(usuario_id: int, dados: UsuarioEscopo,
                   db: Session = Depends(get_db),
                   usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if usuario.empresa_id and alvo.empresa_id != usuario.empresa_id:
        raise HTTPException(403, "Este usuário é de outra empresa.")

    _aplicar_escopo(db, alvo, usuario, dados.unidade_ids, dados.acesso_regional)
    db.commit()
    db.refresh(alvo)
    return alvo
