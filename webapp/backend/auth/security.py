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


# ==============================================================================
# CANAIS
# ==============================================================================
# De onde o pedido veio. Vai dentro do token, assinado, e por isso não pode
# ser forjado pelo cliente.
#
# POR QUE ISSO EXISTE
# O bot do Telegram não deve finalizar inventário, cancelar nem definir meta.
# Escrito só no código do bot, isso seria disciplina: bastaria um segundo bot,
# um script de alguém, ou um descuido numa refatoração para a regra sumir.
#
# Com o canal no token, a recusa mora no BACKEND. Um celular perdido e
# destravado não derruba um inventário nem que quem o pegou saiba exatamente
# qual rota chamar.
#
# Regra que este projeto já aprendeu: controle que depende de o cliente se
# comportar bem não é controle.
CANAL_WEB = "WEB"
CANAL_TELEGRAM = "TELEGRAM"

# Quanto dura o token do bot. Longo de propósito: quem está contando na
# câmara fria não vai parar para fazer login de novo. O que limita o estrago
# não é o prazo, é o que o canal NÃO pode fazer — mais o desvínculo, que
# invalida na hora, sem esperar o token vencer.
DIAS_TOKEN_TELEGRAM = 180


def criar_access_token(dados: dict, expires_delta: Optional[timedelta] = None) -> str:
    payload = dados.copy()
    payload.setdefault("canal", CANAL_WEB)
    expira = datetime.utcnow() + (expires_delta or timedelta(minutes=ACCESS_TOKEN_EXPIRE_MINUTES))
    payload.update({"exp": expira})
    return jwt.encode(payload, SECRET_KEY, algorithm=ALGORITHM)


def criar_token_telegram(usuario_id: int) -> str:
    """O token que o processo do bot guarda para atuar como esta pessoa."""
    return criar_access_token(
        {"sub": str(usuario_id), "canal": CANAL_TELEGRAM},
        expires_delta=timedelta(days=DIAS_TOKEN_TELEGRAM),
    )


def decodificar_access_token(token: str) -> dict:
    return jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
