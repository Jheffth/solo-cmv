"""
Geração do código único de produto (6 dígitos), por família.

O esquema foi extraído dos códigos que já existiam nas planilhas de origem
(coluna "Cod." das abas semanais), para que os produtos migrados mantenham
a mesma numeração que a operação já conhece:

    Mercearia ................ 100000+
    Hortifruti ............... 111000+
    Resfriados ............... 112000+
    Carnes ................... 130000+
    Peixes e Frutos do Mar ... 140000+

As famílias que ainda não tinham código nas planilhas (Cervejas, Bebidas sem
álcool e Bar) receberam os blocos seguintes, mantendo o mesmo padrão.

Cada família ocupa um bloco de 1000 códigos. O número é sequencial dentro do
bloco: o próximo código livre da família é sempre o menor não utilizado.
"""
from typing import Optional

from sqlalchemy.orm import Session

# Prefixo (início do bloco) de cada família. A comparação é feita por trecho
# do nome, sem acento e em minúsculas, para tolerar variações de cadastro
# ("Família - Mercearia", "Mercearia", "mercearia" …).
BLOCOS_FAMILIA = [
    ("mercearia", 100000),
    ("hortifruti", 111000),
    ("resfriado", 112000),
    ("carne", 130000),
    ("peixe", 140000),
    ("cerveja", 150000),
    ("bebida", 160000),
    ("bar", 170000),
]

BLOCO_GENERICO = 190000   # famílias novas, fora da lista acima
TAMANHO_BLOCO = 1000


def _normalizar(texto: str) -> str:
    import unicodedata
    sem_acento = unicodedata.normalize("NFKD", texto or "")
    sem_acento = "".join(c for c in sem_acento if not unicodedata.combining(c))
    return sem_acento.lower()


def bloco_da_familia(nome_familia: Optional[str]) -> int:
    """Início do bloco de códigos da família informada."""
    if not nome_familia:
        return BLOCO_GENERICO
    nome = _normalizar(nome_familia)
    for chave, inicio in BLOCOS_FAMILIA:
        if chave in nome:
            return inicio
    return BLOCO_GENERICO


def gerar_codigo(db: Session, empresa_id: int, nome_familia: Optional[str]) -> str:
    """Devolve o próximo código livre no bloco da família, com 6 dígitos.

    Se o bloco da família lotar (1000 itens), continua no bloco genérico —
    melhor um código fora da faixa do que impedir o cadastro do produto.
    """
    from models import Produto   # import local evita dependência circular

    inicio = bloco_da_familia(nome_familia)
    fim = inicio + TAMANHO_BLOCO

    usados = {
        int(c[0]) for c in db.query(Produto.codigo)
        .filter(Produto.empresa_id == empresa_id, Produto.codigo.isnot(None))
        .all()
        if c[0] and str(c[0]).strip().isdigit()
    }

    for numero in range(inicio, fim):
        if numero not in usados:
            return f"{numero:06d}"

    # Bloco da família cheio: cai no genérico
    numero = BLOCO_GENERICO
    while numero in usados:
        numero += 1
    return f"{numero:06d}"
