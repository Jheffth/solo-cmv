from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario
from schemas import LoginRequest, TokenResponse, UsuarioOut
from auth.security import verificar_senha, criar_access_token
from auth.deps import get_current_user

router = APIRouter(prefix="/auth", tags=["autenticação"])


@router.post("/login", response_model=TokenResponse)
def login(dados: LoginRequest, db: Session = Depends(get_db)):
    usuario = db.query(Usuario).filter(Usuario.login == dados.login).first()
    if not usuario or not verificar_senha(dados.senha, usuario.senha_hash):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Login ou senha inválidos.")
    if not usuario.ativo:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Usuário inativo.")

    token = criar_access_token({"sub": str(usuario.id), "papel": usuario.papel.value})
    return TokenResponse(access_token=token)


@router.get("/me", response_model=UsuarioOut)
def me(usuario: Usuario = Depends(get_current_user)):
    return usuario
