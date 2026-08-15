"""
Normaliza a unidade de medida dos produtos já cadastrados e aponta os
conflitos que só uma pessoa pode resolver.

    python normalizar_unidades.py            # só mostra o que faria
    python normalizar_unidades.py --aplicar  # grava

DUAS COISAS DIFERENTES
----------------------
1. Grafia  — "kg", "Kg", "KG" são a mesma unidade escrita de três jeitos.
   Mecânico e seguro: o script arruma sozinho.

2. Conflito — o nome do produto diz uma unidade e o campo diz outra
   ("Espeto Alcatra und" cadastrado como Kg). Aqui o script não adivinha:
   ele lista, e alguém que conhece a operação decide. Chutar errado aqui
   estraga custo unitário, estoque e CMV de uma vez só.
"""
import re
import sys

from database import SessionLocal
from models import Produto
from unidades_medida import normalizar

# Pistas de unidade escritas no próprio nome do produto ("Banana Terra kg")
PISTAS = [
    (re.compile(r"\bkgs?\b|\bquilos?\b", re.I), "Kg"),
    (re.compile(r"\bunds?\b|\bunids?\b|\bunidades?\b", re.I), "Und"),
    (re.compile(r"\bbdj\b|\bbandejas?\b", re.I), "Bdj"),
    (re.compile(r"\bcx\b|\bcaixas?\b", re.I), "Cx"),
    (re.compile(r"\bl\b|\blitros?\b", re.I), "L"),
]


def pista_do_nome(nome: str):
    for regex, unidade in PISTAS:
        if regex.search(nome or ""):
            return unidade
    return None


def main(aplicar: bool) -> int:
    db = SessionLocal()
    try:
        produtos = db.query(Produto).order_by(Produto.codigo).all()

        grafia, conflitos, sem_unidade = [], [], []
        for p in produtos:
            atual = p.unidade_medida
            canonica = normalizar(atual)

            if not canonica:
                sem_unidade.append(p)
                continue
            if canonica != atual:
                grafia.append((p, atual, canonica))

            pista = pista_do_nome(p.nome)
            if pista and pista != canonica:
                conflitos.append((p, canonica, pista))

        print(f"{len(produtos)} produtos analisados\n")

        print(f"[1] GRAFIA A CORRIGIR — {len(grafia)}")
        for p, de, para in grafia:
            print(f"    {p.codigo}  {p.nome[:42]:42} {de!r} -> {para!r}")

        print(f"\n[2] CONFLITO NOME x UNIDADE — {len(conflitos)}  (decisão humana)")
        for p, unidade, pista in conflitos:
            print(f"    {p.codigo}  {p.nome[:42]:42} cadastro={unidade!r}  nome sugere={pista!r}")

        print(f"\n[3] SEM UNIDADE — {len(sem_unidade)}")
        for p in sem_unidade[:20]:
            print(f"    {p.codigo}  {p.nome}")
        if len(sem_unidade) > 20:
            print(f"    … e mais {len(sem_unidade) - 20}")

        if not aplicar:
            print("\n(simulação — rode com --aplicar para gravar o bloco [1])")
            return 0

        for p, _de, para in grafia:
            p.unidade_medida = para
        db.commit()
        print(f"\n{len(grafia)} produto(s) atualizado(s). "
              f"Blocos [2] e [3] não foram tocados de propósito.")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main("--aplicar" in sys.argv))
