from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError
from sqlalchemy.orm import Session

from database import get_db
from auth.security import decodificar_access_token, CANAL_WEB, CANAL_TELEGRAM
from models import Usuario, PapelUsuario, PAPEIS_IRRESTRITOS

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="/api/auth/login")

CREDENCIAIS_INVALIDAS = HTTPException(
    status_code=status.HTTP_401_UNAUTHORIZED,
    detail="Credenciais inválidas ou sessão expirada.",
    headers={"WWW-Authenticate": "Bearer"},
)


def get_current_user(token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)) -> Usuario:
    try:
        payload = decodificar_access_token(token)
        usuario_id = payload.get("sub")
        if usuario_id is None:
            raise CREDENCIAIS_INVALIDAS
    except JWTError:
        raise CREDENCIAIS_INVALIDAS

    usuario = db.query(Usuario).filter(Usuario.id == int(usuario_id)).first()
    # Suspender ou excluir precisa valer AGORA, não quando o token vencer.
    # O token dura 8 horas; sem esta checagem, quem fosse desligado às 9h
    # continuaria lançando compras até as 17h.
    if usuario is None or not usuario.ativo or usuario.excluido_em is not None:
        raise CREDENCIAIS_INVALIDAS

    canal = payload.get("canal") or CANAL_WEB

    # O token do bot dura meses, e é isso que torna o desvínculo importante:
    # ele precisa valer na hora, sem esperar o token vencer. Perdeu o
    # celular, alguém desvincula na tela e o token morre aqui — antes de
    # qualquer regra de negócio ser consultada.
    if canal == CANAL_TELEGRAM and not usuario.telegram_chat_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Este Telegram não está mais vinculado. Peça um novo código.",
        )

    # Viaja no objeto para as rotas poderem perguntar sem reabrir o token.
    usuario.canal = canal
    return usuario


def exigir_canal_web(usuario: Usuario = Depends(get_current_user)) -> Usuario:
    """Recusa o que não deve existir fora da tela.

    Finalizar inventário aplica as contagens ao estoque real; cancelar
    descarta trabalho; definir meta muda o alvo de todo mundo. Os três são
    irreversíveis ou quase, e os três merecem a tela — com o relatório de
    divergências à vista, não um botão num chat.

    A recusa é aqui, no servidor, e não no código do bot. Ver o comentário
    sobre CANAL_* em auth/security.py: se amanhã existir um segundo bot, ou
    um script, a fronteira continua de pé.
    """
    if getattr(usuario, "canal", CANAL_WEB) != CANAL_WEB:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Esta ação não existe pelo Telegram — ela precisa da tela, "
                   "onde dá para conferir antes de confirmar. Abra o sistema "
                   "no navegador.",
        )
    return usuario


def exigir_papeis(*papeis: PapelUsuario):
    """Dependency factory: restringe o endpoint aos papéis informados.

    ARQUITETO e DIRETOR passam sempre — são os níveis irrestritos. Listá-los
    em cada endpoint seria ruído e, mais cedo ou mais tarde, esquecimento."""

    def checador(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        if usuario.papel in PAPEIS_IRRESTRITOS:
            return usuario
        if usuario.papel not in papeis:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Você não tem permissão para executar esta ação.",
            )
        return usuario

    return checador
