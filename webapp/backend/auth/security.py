from datetime import datetime, timedelta
from typing import Optional

import bcrypt
from jose import jwt

from config import SECRET_KEY, ALGORITHM, ACCESS_TOKEN_EXPIRE_MINUTES

# Usamos o pacote bcrypt diretamente (sem passlib): passlib está sem
# manutenção desde 2020 e quebra com versões recentes do bcrypt (erro
# "password cannot be longer than 72 bytes" no autoteste interno dele,
# mesmo com senhas curtas). bcrypt puro evita esse problema.
_BCRYPT_MAX_BYTES = 72  # limite físico do algoritmo bcrypt


def hash_senha(senha: str) -> str:
    senha_bytes = senha.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    return bcrypt.hashpw(senha_bytes, bcrypt.gensalt()).decode("utf-8")


def verificar_senha(senha_texto: str, senha_hash: str) -> bool:
    senha_bytes = senha_texto.encode("utf-8")[:_BCRYPT_MAX_BYTES]
    try:
        return bcrypt.checkpw(senha_bytes, senha_hash.encode("utf-8"))
    except ValueError:
        return False


def criar_access_token(dados: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = dados.copy()
    expira = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload.update({"exp": expira})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def decodificar_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
