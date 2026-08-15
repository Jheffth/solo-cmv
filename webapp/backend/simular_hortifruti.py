"""
Simulação de uma semana de Hortifruti — dados reais no sistema.

Não cria "movimentos soltos": passa pelo fluxo de verdade, do jeito que a
operação faz. No fim, tudo aparece nas telas — Inventários, Estoque,
Compras e Contagens, e Motor de CMV.

O QUE ELE CRIA
--------------
    03/08  Inventário de abertura — aberto, congelado, contado e finalizado.
           É o estoque inicial da semana.
    04/08 a 09/08  Compras de Hortifruti, com custo por nota (o preço oscila
           entre as compras, como acontece de verdade).
    10/08  Inventário de fechamento — mesmo fluxo. Ele fecha a semana de
           03 a 10/08 e, ao mesmo tempo, abre a semana seguinte.
    Faturamento da semana, para o CMV % ter denominador.

O inventário de fechamento congela o saldo teórico e depois recebe a
contagem física. A diferença entre os dois é a divergência — é isso que
alimenta o relatório de perdas do inventário.

Os números são aleatórios com semente fixa (`SEMENTE`): rodar de novo produz
exatamente os mesmos valores.

COMO USAR
---------
    python simular_hortifruti.py            cria a simulação
    python simular_hortifruti.py --limpar   apaga tudo o que ela criou
    python simular_hortifruti.py --resumo   mostra o que existe hoje

Tudo o que é criado leva o prefixo `SIM-` no documento ou na descrição, então
a limpeza remove só a simulação, sem tocar em lançamento real.
"""
import argparse
import random
import sys
from datetime import date, datetime

from sqlalchemy.orm import Session

from database import SessionLocal, criar_tabelas
from migracoes import aplicar_migracoes
from models import (
    Unidade, Categoria, Produto, Movimento, TipoMovimento, HistoricoCusto,
    Fornecedor, VendaPeriodo, SessaoInventario, InventarioItem,
    StatusSessaoInventario,
)

SEMENTE = 20260803
PREFIXO = "SIM-"

DATA_ABERTURA = date(2026, 8, 3)
DATA_FECHAMENTO = date(2026, 8, 10)
DIAS_DE_COMPRA = [date(2026, 8, d) for d in (4, 5, 6, 7, 8, 9)]

FATURAMENTO_SEMANA = 96_500.00
FATURAMENTO_BEBIDA = 28_900.00


def faixa_do_produto(nome: str, unidade: str):
    """Hortifruti tem itens muito diferentes entre si — folha em maço não se
    parece com batata em saco. Estas faixas deixam a simulação plausível."""
    n = (nome or "").lower()
    u = (unidade or "").lower()
    if u.startswith("m") or any(x in n for x in ("alface", "rucula", "agriao", "cheiro", "salsa",
                                                 "cebolinha", "hortela", "manjericao", "alecrim", "coentro")):
        return (5, 40, 2.50, 9.00)
    if any(x in n for x in ("tomate", "cebola", "batata", "cenoura", "abobora",
                            "banana", "laranja", "limao", "melancia")):
        return (10, 120, 3.00, 12.00)
    if any(x in n for x in ("cogumelo", "shitake", "shimeji", "aspargo", "alcachofra")):
        return (1, 12, 25.00, 70.00)
    return (3, 60, 4.00, 20.00)


def oscilar(v):
    return round(v * random.uniform(0.985, 1.015), 2)


# ==============================================================================
# LIMPEZA
# ==============================================================================
def limpar(db: Session, unidade: Unidade) -> None:
    sessoes = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == unidade.id,
        SessaoInventario.descricao.like(f"{PREFIXO}%"),
    ).all()
    ids = [s.id for s in sessoes]

    movs = db.query(Movimento).filter(Movimento.unidade_id == unidade.id)
    movs = movs.filter(
        Movimento.numero_documento.like(f"{PREFIXO}%")
        | (Movimento.sessao_inventario_id.in_(ids) if ids else False)
    ).all()
    hist = db.query(HistoricoCusto).filter(
        HistoricoCusto.unidade_id == unidade.id,
        HistoricoCusto.numero_documento.like(f"{PREFIXO}%"),
    ).all()
    vendas = db.query(VendaPeriodo).filter(
        VendaPeriodo.unidade_id == unidade.id,
        VendaPeriodo.observacao.like(f"{PREFIXO}%"),
    ).all()

    for lista in (movs, hist, vendas, sessoes):
        for item in lista:
            db.delete(item)
    db.commit()
    print(f"[SIM] Removidos: {len(sessoes)} inventário(s), {len(movs)} movimento(s), "
          f"{len(hist)} custo(s), {len(vendas)} faturamento(s).")


# ==============================================================================
# RESUMO
# ==============================================================================
def resumo(db: Session, unidade: Unidade) -> None:
    sessoes = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == unidade.id,
        SessaoInventario.descricao.like(f"{PREFIXO}%"),
    ).order_by(SessaoInventario.numero_documento).all()
    movs = db.query(Movimento).filter(
        Movimento.unidade_id == unidade.id,
        Movimento.numero_documento.like(f"{PREFIXO}%"),
    ).all()

    if not sessoes and not movs:
        print("[SIM] Nenhum dado de simulação nesta unidade.")
        return

    print(f"[SIM] Simulação em {unidade.nome}:")
    for s in sessoes:
        contados = sum(1 for i in s.itens if i.quantidade_contada is not None)
        print(f"       Inventário nº {s.numero_documento}  {s.descricao}")
        print(f"          {s.status.value} · {len(s.itens)} item(ns), {contados} contado(s)")
    compras = [m for m in movs if m.tipo == TipoMovimento.COMPRA]
    if compras:
        total = sum(m.custo_total or 0 for m in compras)
        print(f"       Compras: {len(compras)} nota(s) · R$ {total:,.2f}")


# ==============================================================================
# UM INVENTÁRIO COMPLETO
# ==============================================================================
def executar_inventario(db, unidade, familia, produtos, numero, descricao, dia,
                        quantidades, custos):
    """Abre, congela, conta e finaliza um inventário — o fluxo real.

    `quantidades` é o que foi encontrado fisicamente por produto.
    O congelamento fotografa o que o sistema achava que tinha; a diferença
    para a contagem é a divergência que aparece no relatório.
    """
    from calculo_estoque import saldos_por_produto

    momento = datetime.combine(dia, datetime.min.time()).replace(hour=8)

    sessao = SessaoInventario(
        unidade_id=unidade.id,
        numero_documento=numero,
        descricao=descricao,
        geral=False,
        data_abertura=momento,
        status=StatusSessaoInventario.ABERTO,
    )
    sessao.categorias = [familia]
    db.add(sessao)
    db.flush()

    # ---------- Congelar: fotografia do estoque ----------
    ids = [p.id for p in produtos]
    saldos = saldos_por_produto(db, unidade.id, ids)
    for p in produtos:
        db.add(InventarioItem(
            sessao_inventario_id=sessao.id,
            produto_id=p.id,
            quantidade_sistema=saldos.get(p.id, 0.0),
            custo_unitario=custos.get(p.id),
        ))
    sessao.data_congelamento = momento.replace(hour=9)
    sessao.status = StatusSessaoInventario.CONGELADO
    db.flush()

    # ---------- Contagem ----------
    contados = 0
    for item in sessao.itens:
        qtd = quantidades.get(item.produto_id)
        if qtd is None:
            continue          # item não contado — acontece na vida real
        item.quantidade_contada = qtd
        item.contado_em = momento.replace(hour=10)
        item.origem = "SIMULACAO"
        contados += 1
    sessao.status = StatusSessaoInventario.EM_CONTAGEM
    db.flush()

    # ---------- Finalizar: as contagens viram estoque ----------
    valor = 0.0
    for item in sessao.itens:
        if item.quantidade_contada is None:
            continue
        custo = custos.get(item.produto_id) or 0.0
        db.add(Movimento(
            unidade_id=unidade.id,
            produto_id=item.produto_id,
            tipo=TipoMovimento.CONTAGEM_FINAL,
            quantidade=item.quantidade_contada,
            custo_unitario=custo,
            custo_total=round(item.quantidade_contada * custo, 2),
            data=dia,
            sessao_inventario_id=sessao.id,
            numero_documento=f"{PREFIXO}INV-{numero}",
        ))
        valor += item.quantidade_contada * custo

    sessao.status = StatusSessaoInventario.FINALIZADO
    sessao.data_fechamento = momento.replace(hour=11)
    db.commit()

    return sessao, contados, round(valor, 2)


# ==============================================================================
# GERAÇÃO
# ==============================================================================
def simular(db: Session, unidade: Unidade, empresa_id: int) -> None:
    random.seed(SEMENTE)

    familia = db.query(Categoria).filter(
        Categoria.empresa_id == empresa_id,
        Categoria.nome.ilike("%hortifruti%"),
    ).first()
    if not familia:
        print("[SIM] Família Hortifruti não encontrada.")
        sys.exit(1)

    produtos = db.query(Produto).filter(
        Produto.empresa_id == empresa_id,
        Produto.categoria_id == familia.id,
        Produto.ativo == True,  # noqa: E712
    ).order_by(Produto.nome).all()
    if not produtos:
        print("[SIM] Nenhum produto ativo em Hortifruti.")
        sys.exit(1)

    fornecedores = db.query(Fornecedor).filter(Fornecedor.empresa_id == empresa_id).all()

    print(f"[SIM] Unidade: {unidade.nome}")
    print(f"[SIM] Família: {familia.nome} — {len(produtos)} produto(s)")

    # Números sorteados de uma vez, para as duas contagens serem coerentes
    faixas = {p.id: faixa_do_produto(p.nome, p.unidade_medida) for p in produtos}
    custo_base = {p.id: round(random.uniform(faixas[p.id][2], faixas[p.id][3]), 2) for p in produtos}

    # ---------- 1) Inventário de abertura (03/08) ----------
    from routers.inventario import _proximo_numero

    qtd_abertura = {p.id: round(random.uniform(faixas[p.id][0], faixas[p.id][1]), 1) for p in produtos}
    inv1, n1, valor1 = executar_inventario(
        db, unidade, familia, produtos,
        numero=_proximo_numero(db, unidade.id),
        descricao=f"{PREFIXO}INV HORTIFRUTI — abertura 03/08",
        dia=DATA_ABERTURA, quantidades=qtd_abertura, custos=custo_base,
    )
    print(f"[SIM] Inventário nº {inv1.numero_documento} (abertura) — {n1} itens · R$ {valor1:,.2f}")

    # ---------- 2) Compras (04 a 09/08) ----------
    qtd_comprada = {p.id: 0.0 for p in produtos}
    custo_atual = dict(custo_base)
    total_compras = 0.0
    n_notas = 0
    for p in produtos:
        qmin, qmax, _, _ = faixas[p.id]
        for _ in range(random.choices([0, 1, 2, 3], weights=[15, 40, 30, 15])[0]):
            dia = random.choice(DIAS_DE_COMPRA)
            qtd = round(random.uniform(qmin * 0.4, qmax * 0.6), 1)
            # o preço do hortifruti oscila bastante de uma compra para outra
            custo = oscilar(custo_base[p.id] * random.uniform(0.82, 1.22))
            fornecedor = random.choice(fornecedores) if fornecedores else None
            doc = f"{PREFIXO}NF-{random.randint(10000, 99999)}"

            db.add(Movimento(
                unidade_id=unidade.id, produto_id=p.id,
                tipo=TipoMovimento.COMPRA,
                quantidade=qtd, custo_unitario=custo,
                custo_total=round(qtd * custo, 2),
                data=dia, numero_documento=doc,
                fornecedor_id=fornecedor.id if fornecedor else None,
            ))
            db.add(HistoricoCusto(
                produto_id=p.id, unidade_id=unidade.id,
                custo=custo, data=dia, numero_documento=doc,
                fornecedor_id=fornecedor.id if fornecedor else None,
            ))
            qtd_comprada[p.id] += qtd
            custo_atual[p.id] = custo
            total_compras += qtd * custo
            n_notas += 1
    db.commit()
    print(f"[SIM] Compras 04 a 09/08 — {n_notas} nota(s) · R$ {total_compras:,.2f}")

    # ---------- 3) Inventário de fechamento (10/08) ----------
    qtd_fechamento = {}
    zerados = nao_contados = 0
    for p in produtos:
        disponivel = qtd_abertura[p.id] + qtd_comprada[p.id]
        sorteio = random.random()
        if sorteio < 0.08:
            nao_contados += 1
            continue                        # não contado — vira "estimado"
        if sorteio < 0.18:
            qtd_fechamento[p.id] = 0.0      # zerou o estoque
            zerados += 1
        else:
            qtd_fechamento[p.id] = round(disponivel * random.uniform(0.05, 0.45), 1)

    inv2, n2, valor2 = executar_inventario(
        db, unidade, familia, produtos,
        numero=_proximo_numero(db, unidade.id),
        descricao=f"{PREFIXO}INV HORTIFRUTI — fechamento 10/08",
        dia=DATA_FECHAMENTO, quantidades=qtd_fechamento, custos=custo_atual,
    )
    print(f"[SIM] Inventário nº {inv2.numero_documento} (fechamento) — {n2} itens · R$ {valor2:,.2f}")
    print(f"       ({zerados} item(ns) zeraram o estoque; {nao_contados} ficaram sem contagem)")

    # ---------- 4) Faturamento ----------
    db.add(VendaPeriodo(
        unidade_id=unidade.id,
        data_inicio=DATA_ABERTURA, data_fim=DATA_FECHAMENTO,
        faturamento_total=FATURAMENTO_SEMANA,
        faturamento_bebida=FATURAMENTO_BEBIDA,
        observacao=f"{PREFIXO}faturamento da semana simulada",
    ))
    db.commit()

    # O resumo abaixo vem do PRÓPRIO motor de CMV, não de uma conta paralela.
    # Repetir a fórmula aqui só criaria uma segunda versão da verdade — foi
    # assim que a planilha original acumulou divergências.
    from servicos.cmv import apurar
    from models import MetodoCusto, ModoApuracao

    r = apurar(db, unidade.id, DATA_ABERTURA, DATA_FECHAMENTO,
               modo=ModoApuracao.PERIODO, metodo_custo=MetodoCusto.ULTIMO_CUSTO,
               empresa_id=empresa_id)
    g = r.geral

    print()
    print("[SIM] Semana de 03 a 10/08 — apurado pelo motor (Último custo):")
    print(f"       Estoque inicial ..... R$ {g.estoque_inicial:12,.2f}   (inventário nº {inv1.numero_documento})")
    print(f"       Compras ............. R$ {g.compras:12,.2f}")
    print(f"       Estoque final ....... R$ {g.estoque_final:12,.2f}   (inventário nº {inv2.numero_documento})")
    print(f"       CMV ................. R$ {g.cmv:12,.2f}")
    print(f"       Faturamento ......... R$ {g.faturamento:12,.2f}")
    print(f"       CMV % ...............    {(g.cmv_percentual or 0) * 100:9.2f}%   (meta {r.meta*100:.0f}%)")
    for aviso in r.avisos:
        print(f"       · {aviso}")
    print()
    print("       Onde acompanhar na plataforma:")
    print("         Inventários ....... dois inventários finalizados, com relatório PDF")
    print("         Estoque ........... saldo por item após o fechamento")
    print("         Compras e Contagens  todas as notas e contagens")
    print("         Motor de CMV ...... período 03/08 a 10/08")


def main():
    p = argparse.ArgumentParser(description="Simulação de uma semana de Hortifruti no fluxo real do sistema.")
    p.add_argument("--limpar", action="store_true", help="remove os dados da simulação")
    p.add_argument("--resumo", action="store_true", help="mostra o que a simulação criou")
    p.add_argument("--unidade", type=str, default=None, help="nome da unidade (padrão: a primeira)")
    args = p.parse_args()

    criar_tabelas()
    aplicar_migracoes()

    db = SessionLocal()
    try:
        q = db.query(Unidade)
        if args.unidade:
            q = q.filter(Unidade.nome.ilike(f"%{args.unidade}%"))
        unidade = q.order_by(Unidade.id).first()
        if not unidade:
            print("[SIM] Nenhuma unidade encontrada.")
            sys.exit(1)

        if args.resumo:
            resumo(db, unidade)
            return
        if args.limpar:
            limpar(db, unidade)
            return

        limpar(db, unidade)      # recria do zero
        simular(db, unidade, unidade.empresa_id)
    finally:
        db.close()


if __name__ == "__main__":
    main()
