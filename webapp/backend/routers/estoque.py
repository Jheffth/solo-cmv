"""
Estoque — posição atual de todos os itens cadastrados.

COMO O SALDO É CALCULADO
------------------------
A conta vive em `calculo_estoque.py` e é a mesma usada pelo congelamento do
inventário e pelas requisições — saldo teórico desde a última contagem:

    saldo = última contagem + compras posteriores − requisições posteriores

Item sem contagem e sem movimento fica zerado, como esperado para um produto
recém-cadastrado.

O custo mostrado é o último custo pago (tabela historico_custos, equivalente
à aba "UCustoInfo" da planilha); se o produto nunca teve compra com custo
informado, vem zerado.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Produto, Categoria
from auth.deps import get_current_user
from calculo_estoque import saldos_por_produto, ultimos_custos, data_ultima_contagem
from servicos import escopo as servico_escopo
from servicos.permissoes import ve_dinheiro

router = APIRouter(prefix="/estoque", tags=["estoque"])


@router.get("")
def posicao_estoque(unidade_id: Optional[str] = None,
                    categoria_id: Optional[int] = None,
                    busca: Optional[str] = None,
                    db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Posição de uma unidade, ou de todas quando unidade_id=REGIONAL.

    Na Regional o mesmo produto aparece uma linha por loja: somar saldo de
    unidades diferentes esconderia o que interessa — dez quilos parados na
    Casa Josefina e zero na Josefina não é "cinco em cada".

    QUEM NÃO VÊ DINHEIRO RECEBE A MESMA TELA SEM O R$
    -------------------------------------------------
    Filtrar, e não recusar. O operador precisa do saldo — pedir 20 kg de um
    item que tem 12 é erro que só aparece na hora de atender, quando já é
    tarde. Um 403 aqui tiraria dele a informação de que ele mais precisa
    para proteger uma que não é dele.
    """
    recorte = servico_escopo.resolver(db, usuario, unidade_id)
    com_valores = ve_dinheiro(usuario)
    q_produtos = db.query(Produto).filter(Produto.ativo == True)  # noqa: E712
    if usuario.empresa_id:
        q_produtos = q_produtos.filter(Produto.empresa_id == usuario.empresa_id)
    if categoria_id:
        q_produtos = q_produtos.filter(Produto.categoria_id == categoria_id)
    if busca:
        termo = f"%{busca}%"
        q_produtos = q_produtos.filter(
            (Produto.nome.ilike(termo)) | (Produto.codigo.ilike(termo))
        )
    produtos = q_produtos.order_by(Produto.nome).all()

    categorias = {c.id: c.nome for c in db.query(Categoria).all()}

    # Saldo e custo vêm do módulo compartilhado (calculo_estoque.py) — a mesma
    # conta usada pelo congelamento do inventário e pelas requisições. Manter
    # uma cópia da fórmula aqui já causou divergência antes.
    ids = [p.id for p in produtos]
    itens = []
    total_valor = 0.0
    por_unidade = []

    for unidade in recorte.unidades:
        saldos = saldos_por_produto(db, unidade.id, ids)
        custos = ultimos_custos(db, unidade.id)
        datas_contagem = data_ultima_contagem(db, unidade.id)
        valor_unidade = 0.0
        com_saldo_unidade = 0

        for p in produtos:
            saldo = saldos.get(p.id, 0.0)
            # Na Regional, item zerado numa loja só polui a lista; na visão
            # de uma unidade ele importa (é o catálogo dela).
            if recorte.regional and saldo <= 0:
                continue

            ultima = datas_contagem.get(p.id)
            custo = custos.get(p.id)
            valor = round(saldo * custo, 2) if custo is not None else 0.0
            total_valor += valor
            valor_unidade += valor
            if saldo > 0:
                com_saldo_unidade += 1

            linha = {
                "produto_id": p.id,
                "codigo": p.codigo,
                "nome": p.nome,
                "unidade_medida": p.unidade_medida,
                "categoria_id": p.categoria_id,
                "categoria": categorias.get(p.categoria_id),
                "quantidade": round(saldo, 3),
                "ultima_contagem": ultima.isoformat() if ultima else None,
                # De qual loja é esta linha — a diferenciação que a Regional exige
                "unidade_id": unidade.id,
                "unidade_nome": unidade.nome,
            }
            if com_valores:
                linha["ultimo_custo"] = custo
                linha["valor_em_estoque"] = valor
            itens.append(linha)

        bloco = {"unidade_id": unidade.id, "unidade": unidade.nome,
                 "itens_com_saldo": com_saldo_unidade}
        if com_valores:
            bloco["valor"] = round(valor_unidade, 2)
        por_unidade.append(bloco)

    # Sem valores, a ordenação por dinheiro não existe — e ordenar por nome é
    # o que serve a quem está procurando um item na lista.
    if recorte.regional:
        if com_valores:
            itens.sort(key=lambda i: (-i["valor_em_estoque"], i["nome"]))
        else:
            itens.sort(key=lambda i: i["nome"])
        por_unidade.sort(key=lambda x: -x["valor"] if com_valores else x["unidade"])

    resumo = {
        "total_itens": len(itens),
        "itens_com_saldo": sum(1 for i in itens if i["quantidade"] > 0),
        "itens_zerados": sum(1 for i in itens if i["quantidade"] <= 0),
        "unidades": len(recorte.unidades),
    }
    if com_valores:
        resumo["itens_sem_custo"] = sum(
            1 for i in itens if i["ultimo_custo"] is None)
        resumo["valor_total"] = round(total_valor, 2)

    return {
        "regional": recorte.regional,
        "escopo": recorte.rotulo,
        # Dito em voz alta para a tela não adivinhar pela ausência da chave.
        # Coluna que some sem explicação parece defeito; declarada, é regra.
        "com_valores": com_valores,
        "itens": itens,
        "por_unidade": por_unidade,
        "resumo": resumo,
    }
