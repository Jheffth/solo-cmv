import os
import sys

from dotenv import load_dotenv

load_dotenv()

APP_NAME = "Solo CMV"
APP_VERSION = "0.1.0"

ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = int(os.getenv("ACCESS_TOKEN_EXPIRE_MINUTES", "480"))
DATABASE_URL = os.getenv("DATABASE_URL", "sqlite:///./solo_cmv.db")

AMBIENTE = os.getenv("AMBIENTE", "dev").lower()
EH_PRODUCAO = AMBIENTE in ("prod", "producao", "production")

# ============================================================================
# CHAVE DE ASSINATURA — a fechadura do sistema inteiro
# ============================================================================
# Todo token de sessão é assinado com ela. Quem tem a chave escreve um token
# dizendo "sou o Arquiteto" e entra — sem precisar de senha nenhuma. Por isso
# ela é diferente de uma senha: trocar a senha de todo mundo não adianta se a
# chave vazou. Só trocar a chave adianta.
#
# ANTES ISTO ERA UMA LINHA SÓ:
#
#     SECRET_KEY = os.getenv("SECRET_KEY", "troque-esta-chave-em-producao...")
#
# E o problema não era o valor — era o silêncio. Sem a variável definida, o
# sistema subia normalmente usando um padrão que está escrito neste arquivo,
# num repositório público. Ninguém percebia, porque nada quebrava.
#
# Pior ainda com Docker: `SECRET_KEY: ${SECRET_KEY}` sem `.env` no servidor
# não cai no padrão — define a variável como string VAZIA. E `os.getenv` com
# valor padrão só devolve o padrão quando a variável **não existe**; existindo
# vazia, devolve "". O sistema passaria a assinar tokens com chave vazia, e
# continuaria funcionando como se estivesse tudo bem.
#
# Agora, em produção, chave ausente, vazia, curta ou conhecida derruba a
# subida. Falhar alto no primeiro segundo é melhor que rodar meses com a
# porta destrancada.

_PADRAO_DESENVOLVIMENTO = "chave-de-desenvolvimento-nao-use-em-producao"

# Valores que já circularam em repositório público ou em exemplo. Qualquer um
# deles em produção significa que a rotação não chegou até aqui.
_CHAVES_QUEIMADAS = {
    "troque-esta-chave-em-producao-solo-cmv",
    "chave-secreta-solo-cmv-2026-xyz",
    "chave-secreta-solo-cmv-2026",
    _PADRAO_DESENVOLVIMENTO,
    "", "None", "null", "changeme", "secret",
}

_TAMANHO_MINIMO = 32   # 32 caracteres aleatórios ~ 190 bits; token_hex(32) dá 64


def _resolver_chave() -> str:
    bruta = os.getenv("SECRET_KEY")

    if not EH_PRODUCAO:
        # Desenvolvimento segue sem cerimônia: se não houver chave, usa a de
        # brincadeira. Ninguém precisa configurar nada para rodar local.
        return bruta or _PADRAO_DESENVOLVIMENTO

    chave = (bruta or "").strip()
    motivo = None
    if not chave:
        motivo = ("SECRET_KEY não chegou à aplicação. Com Docker, isso "
                  "costuma ser .env ausente em /var/www/solo-cmv — o compose "
                  "substitui ${SECRET_KEY} por vazio sem reclamar.")
    elif chave in _CHAVES_QUEIMADAS:
        motivo = ("SECRET_KEY é um valor que já esteve em repositório "
                  "público. Quem tem o histórico do Git consegue assinar um "
                  "token de Arquiteto.")
    elif len(chave) < _TAMANHO_MINIMO:
        motivo = (f"SECRET_KEY tem {len(chave)} caracteres; o mínimo é "
                  f"{_TAMANHO_MINIMO}. Chave curta é chave adivinhável.")

    if motivo:
        print("\n" + "=" * 72, file=sys.stderr)
        print("  SOLO CMV NÃO VAI SUBIR — problema na chave de assinatura",
              file=sys.stderr)
        print("=" * 72, file=sys.stderr)
        print(f"  {motivo}\n", file=sys.stderr)
        print("  Para gerar uma chave nova:", file=sys.stderr)
        print('    python -c "import secrets; print(secrets.token_hex(32))"',
              file=sys.stderr)
        print("\n  E colocar em /var/www/solo-cmv/.env:", file=sys.stderr)
        print("    SECRET_KEY=<a chave gerada>", file=sys.stderr)
        print("\n  Trocar a chave invalida as sessões abertas: todo mundo "
              "entra de novo.", file=sys.stderr)
        print("=" * 72 + "\n", file=sys.stderr)
        raise RuntimeError(f"SECRET_KEY inválida em produção: {motivo}")

    return chave


SECRET_KEY = _resolver_chave()
