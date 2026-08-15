"""
Unidade de medida do produto — normalização e vocabulário.

POR QUE ISSO EXISTE
-------------------
O motor de CMV é aritmética pura: quantidade x custo unitário. Ele não sabe
o que é "Kg" e não precisa saber — desde que *toda* a vida do produto use a
mesma unidade, a conta fecha sozinha. Batata doce comprada em quilo, contada
em quilo e requisitada em quilo dá custo por quilo, sem conversão nenhuma.

O que quebra a conta não é o motor, é o cadastro: se o mesmo produto aparece
como "Kg", "kg" e "KG", o olho humano lê tudo igual mas relatório, filtro e
agrupamento tratam como três coisas. Pior: se alguém compra 1 caixa de 20kg
lançando quantidade 1, e o contador conta 20 (quilos), o estoque vira ficção.

Este módulo resolve a primeira metade — grafia única. A segunda metade
(comprar em caixa e contar em quilo) é decisão de cadastro: o produto deve
existir na unidade em que é CONTADO, e a nota deve ser lançada convertida.
"""
from typing import Optional

# Grafia canônica de cada unidade. A chave é a forma minúscula sem espaços.
CANONICAS = {
    "kg": "Kg",
    "quilo": "Kg",
    "quilos": "Kg",
    "k": "Kg",
    "g": "g",
    "grama": "g",
    "gramas": "g",
    "l": "L",
    "litro": "L",
    "litros": "L",
    "lt": "L",
    "ml": "ml",
    "und": "Und",
    "un": "Und",
    "unid": "Und",
    "unidade": "Und",
    "ubd": "Und",       # erro de digitação recorrente no cadastro herdado
    "pc": "Und",
    "bdj": "Bdj",       # bandeja
    "bandeja": "Bdj",
    "cx": "Cx",         # caixa
    "caixa": "Cx",
    "pct": "Pct",       # pacote
    "pacote": "Pct",
    "fd": "Fd",         # fardo
    "fardo": "Fd",
    "mc": "Mç",         # maço
    "maco": "Mç",
    "mç": "Mç",
    "dz": "Dz",
    "duzia": "Dz",
}

# O que oferecer na tela de cadastro, na ordem de uso real da operação
SUGERIDAS = ["Kg", "Und", "L", "Bdj", "Cx", "Pct", "Fd", "Mç", "Dz", "g", "ml"]


def normalizar(valor: Optional[str]) -> Optional[str]:
    """Devolve a grafia canônica. Desconhecida passa limpa, sem inventar."""
    if valor is None:
        return None
    limpo = valor.strip()
    if not limpo:
        return None
    return CANONICAS.get(limpo.lower().replace(".", ""), limpo)
