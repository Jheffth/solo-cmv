"""
Correção pontual de unidade de medida — decidida pelo Arquiteto em 13/08/2026.

Os 18 produtos abaixo tinham conflito entre o nome e o campo de unidade
(ver normalizar_unidades.py, bloco [2]). A unidade correta veio de quem
conhece a operação, não de heurística — por isso a lista é explícita.

    python corrigir_unidades_2026_08.py            # simula
    python corrigir_unidades_2026_08.py --aplicar  # grava

ATENÇÃO: trocar a unidade NÃO converte quantidade nem custo dos movimentos
já lançados. Se um produto era comprado em bandeja e passa a ser Kg, os
lançamentos antigos continuam em bandeja. O script avisa quando isso pode
ter acontecido; a decisão de recontar ou estornar é humana.
"""
import sys

from database import SessionLocal
from models import Produto, Movimento

DECISOES = {
    "112013": ("Presunto kg", "Kg"),
    "112018": ("Queijo de cabra kg", "Und"),
    "112000": ("Acem moido kg", "Kg"),
    "130009": ("File de Peito de Frango kg", "Kg"),
    "130012": ("Frango a passarinho Kg", "Kg"),
    "130016": ("Panceta kg", "Kg"),
    "112020": ("Rabo Bovino Kg", "Kg"),
    "111039": ("Massa de Pastel Especial kg (500G)", "Und"),
    "112005": ("Espeto Alcatra und", "Und"),
    "112008": ("Espeto frango und", "Und"),
    "130007": ("Espeto Frango und", "Und"),
    "130013": ("Linguiça de Frango Fina und", "Und"),
    "111021": ("Cogumelo Paris kg", "Kg"),
    "111022": ("Cogumelo Shitake kg", "Kg"),
    "111014": ("Caju bdj", "Und"),
    "111040": ("Milho Verde Bdj (Espiga)", "Und"),
    "111060": ("Tomate Cereja bdj", "Und"),
    "111048": ("Ovos Grandes (Bdj 30 und)", "Bdj"),
}


def main(aplicar: bool) -> int:
    db = SessionLocal()
    try:
        mudar, confirmados, ausentes, com_historico = [], [], [], []

        for codigo, (nome_ref, correta) in DECISOES.items():
            p = db.query(Produto).filter(Produto.codigo == codigo).first()
            if not p:
                ausentes.append((codigo, nome_ref))
                continue
            if p.unidade_medida == correta:
                confirmados.append((codigo, p.nome, correta))
                continue
            movimentos = db.query(Movimento).filter(Movimento.produto_id == p.id).count()
            mudar.append((p, p.unidade_medida, correta, movimentos))
            if movimentos:
                com_historico.append((codigo, p.nome, p.unidade_medida, correta, movimentos))

        print(f"[=] JÁ CORRETOS — {len(confirmados)}")
        for c, n, u in confirmados:
            print(f"    {c}  {n[:44]:44} {u}")

        print(f"\n[>] A CORRIGIR — {len(mudar)}")
        for p, de, para, movs in mudar:
            marca = f"  ({movs} movimento(s) já lançado(s))" if movs else ""
            print(f"    {p.codigo}  {p.nome[:44]:44} {de!r} -> {para!r}{marca}")

        if ausentes:
            print(f"\n[!] NÃO ENCONTRADOS — {len(ausentes)}")
            for c, n in ausentes:
                print(f"    {c}  {n}")

        if com_historico:
            print(f"\n[!] REVISAR — {len(com_historico)} produto(s) mudam de unidade e já têm "
                  f"movimento lançado.\n    Quantidade e custo antigos ficam na unidade "
                  f"antiga; confira na próxima contagem.")

        if not aplicar:
            print("\n(simulação — rode com --aplicar para gravar)")
            return 0

        for p, _de, para, _m in mudar:
            p.unidade_medida = para
        db.commit()
        print(f"\n{len(mudar)} produto(s) atualizado(s).")
        return 0
    finally:
        db.close()


if __name__ == "__main__":
    sys.exit(main("--aplicar" in sys.argv))
