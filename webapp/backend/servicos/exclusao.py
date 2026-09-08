"""
Tirar um lançamento do estoque sem apagar que ele existiu.

O ESTOQUE É O LIVRO-RAZÃO
-------------------------
Saldo, CMV, painel e relatório são todos a soma dos movimentos. Isso tem uma
consequência que organiza este arquivo inteiro: para desfazer um lançamento
basta RETIRAR o movimento. Não existe contra-lançamento aqui, e não deveria
existir — duas linhas onde houve um fato só transformam o livro-razão numa
sequência de arrependimentos.

POR QUE A LINHA SAI DA TABELA, E NÃO GANHA UMA MARCA
-----------------------------------------------------
A marca `excluido_em` na própria linha é o desenho óbvio. É também o que
mais provavelmente daria errado neste código: vinte e quatro consultas leem
`movimentos` para apurar coisas diferentes, e cada uma teria que lembrar de
filtrar. A que esquecesse não daria erro nenhum — continuaria somando no CMV
um movimento que a tela mostra como excluído, e o número sairia *plausível*.

Retirando a linha, não há o que esquecer. O rastro fica em
`movimentos_excluidos`, completo o bastante para responder o que havia ali,
quem tirou, quando e por quê — e para devolver, se tiver sido engano.

O QUE NÃO SE EXCLUI POR AQUI
----------------------------
Ajuste de inventário e saída de requisição não nascem soltos: nascem de uma
contagem fechada e de um pedido atendido. Apagar o movimento deixaria o
documento de pé, dizendo que aconteceu uma coisa que o estoque não conhece —
e é o documento que alguém vai consultar daqui a seis meses. Esses se
desfazem pelo inventário e pela requisição, que sabem cuidar dos dois lados.
"""
import logging
from datetime import datetime
from typing import List, Optional, Tuple

from sqlalchemy.orm import Session

from models import (Movimento, MovimentoExcluido, NotaFiscalImportada,
                    StatusNotaFiscal, TipoMovimento, Usuario)

log = logging.getLogger("servicos.exclusao")


class ErroExclusao(Exception):
    """Mensagem pronta para a tela."""


# Por que cada um está travado, na voz de quem lê a recusa. O texto vive aqui
# e não na tela para que a API e a interface digam a MESMA coisa — recusa que
# muda de motivo conforme onde se lê é recusa em que ninguém acredita.
TRAVADOS = {
    TipoMovimento.CONTAGEM_INICIAL:
        "Este é o ajuste de um inventário. Apagar a linha deixaria o "
        "inventário fechado apontando um número que o estoque não tem — "
        "desfaça pelo inventário.",
    TipoMovimento.CONTAGEM_FINAL:
        "Este é o ajuste de um inventário. Apagar a linha deixaria o "
        "inventário fechado apontando um número que o estoque não tem — "
        "desfaça pelo inventário.",
    TipoMovimento.REQUISICAO:
        "Esta saída pertence a uma requisição atendida. Apagar só a baixa "
        "deixaria a requisição dizendo que entregou o que o estoque não "
        "entregou — desfaça pela requisição.",
}


def por_que_nao(movimento: Movimento) -> Optional[str]:
    """O motivo de este movimento não poder ser excluído — ou None."""
    if movimento.sessao_inventario_id:
        return TRAVADOS[TipoMovimento.CONTAGEM_FINAL]
    if movimento.requisicao_id:
        return TRAVADOS[TipoMovimento.REQUISICAO]
    return TRAVADOS.get(movimento.tipo)


def _nota_do_movimento(db: Session, movimento: Movimento) -> Optional[NotaFiscalImportada]:
    """A nota que gerou esta compra, quando existe.

    O vínculo é pelo número do documento ("NF 427795") e pela unidade, que é
    como `aprovar` grava. Não é chave estrangeira — e não vale inventar uma
    agora, porque compra também entra digitada à mão, sem nota nenhuma.
    """
    if movimento.tipo != TipoMovimento.COMPRA or not movimento.numero_documento:
        return None
    numero = movimento.numero_documento.replace("NF", "").strip()
    if not numero:
        return None
    return db.query(NotaFiscalImportada).filter(
        NotaFiscalImportada.unidade_id == movimento.unidade_id,
        NotaFiscalImportada.numero == numero,
        NotaFiscalImportada.status == StatusNotaFiscal.PROCESSADA,
    ).first()


def _fotografar(db: Session, movimento: Movimento, usuario: Usuario,
                motivo: str, nota_id: Optional[int]) -> MovimentoExcluido:
    registro = MovimentoExcluido(
        movimento_id=movimento.id,
        unidade_id=movimento.unidade_id,
        produto_id=movimento.produto_id,
        tipo=movimento.tipo.value if movimento.tipo else "",
        quantidade=movimento.quantidade,
        custo_unitario=movimento.custo_unitario,
        custo_total=movimento.custo_total,
        fornecedor_id=movimento.fornecedor_id,
        numero_documento=movimento.numero_documento,
        data=movimento.data,
        motivo_perda=movimento.motivo.value if movimento.motivo else None,
        observacao=movimento.observacao,
        lancado_por_id=movimento.usuario_id,
        lancado_em=movimento.criado_em,
        nota_id=nota_id,
        excluido_por_id=usuario.id if usuario else None,
        excluido_em=datetime.utcnow(),
        excluido_motivo=(motivo or "")[:255] or None,
    )
    db.add(registro)
    return registro


def excluir(db: Session, movimentos: List[Movimento], usuario: Usuario,
            motivo: str = "") -> Tuple[int, List[str]]:
    """Retira os movimentos do estoque, guardando a fotografia de cada um.

    Devolve quantos saíram e os avisos do que a exclusão implicou — que
    notas voltaram a poder ser lançadas, principalmente. Recusa TUDO se
    algum da lista for travado: excluir sete de oito e avisar depois é a
    forma mais rápida de alguém achar que excluiu os oito.
    """
    if not movimentos:
        raise ErroExclusao("Nenhum lançamento selecionado.")

    recusas = [(m, por_que_nao(m)) for m in movimentos]
    travados = [(m, r) for m, r in recusas if r]
    if travados:
        _mov, razao = travados[0]
        quantos = (f" ({len(travados)} dos {len(movimentos)} selecionados)"
                   if len(movimentos) > 1 else "")
        raise ErroExclusao(f"{razao}{quantos} Nada foi excluído.")

    # Os ids ANTES do delete: depois do flush os objetos perdem a identidade
    # e a consulta do que sobrou passaria a comparar com None.
    ids_saindo = [m.id for m in movimentos]

    notas_afetadas = {}
    for movimento in movimentos:
        nota = _nota_do_movimento(db, movimento)
        _fotografar(db, movimento, usuario, motivo,
                    nota.id if nota else None)
        if nota:
            notas_afetadas[nota.id] = nota
        db.delete(movimento)

    avisos = []
    for nota in notas_afetadas.values():
        sobrou = db.query(Movimento).filter(
            Movimento.unidade_id == nota.unidade_id,
            Movimento.numero_documento == f"NF {nota.numero}",
            Movimento.tipo == TipoMovimento.COMPRA,
            Movimento.id.notin_(ids_saindo),
        ).count()
        if sobrou:
            avisos.append(
                f"A nota {nota.numero} ainda tem {sobrou} item(ns) no "
                f"estoque. Ela continua lançada, com menos itens do que a "
                f"nota de papel.")
            continue
        _anular(nota, usuario, motivo)
        avisos.append(
            f"A nota {nota.numero} saiu inteira do estoque e voltou a poder "
            f"ser lançada com a mesma chave.")

    db.commit()
    return len(movimentos), avisos


def _anular(nota: NotaFiscalImportada, usuario: Usuario, motivo: str) -> None:
    nota.status = StatusNotaFiscal.ANULADA
    nota.processado_em = None
    nota.processado_por_id = None
    carimbo = f"Anulada por {usuario.nome} em {datetime.utcnow():%d/%m/%Y}"
    nota.mensagem = f"{carimbo}. {motivo}".strip() if motivo else carimbo + "."


def anular_nota(db: Session, nota: NotaFiscalImportada, usuario: Usuario,
                motivo: str = "") -> Tuple[int, List[str]]:
    """Tira a nota INTEIRA do estoque e do CMV, e a deixa relançável.

    É a operação de negócio, e a diferença para a exclusão avulsa não é de
    tamanho: aqui o documento e o estoque saem JUNTOS, então nada fica
    mentindo. Uma nota anulada continua contando a sua história — quem
    lançou, quem anulou, quando — e pode ser lançada de novo pela mesma
    chave, que é o caso de uso inteiro.
    """
    if nota.status != StatusNotaFiscal.PROCESSADA:
        raise ErroExclusao(
            f"Esta nota não está lançada no estoque (está como "
            f"{nota.status.value.lower()}), então não há o que anular.")

    documento = f"NF {nota.numero}" if nota.numero else "NF-e"
    movimentos = db.query(Movimento).filter(
        Movimento.unidade_id == nota.unidade_id,
        Movimento.numero_documento == documento,
        Movimento.tipo == TipoMovimento.COMPRA,
    ).all()

    for movimento in movimentos:
        _fotografar(db, movimento, usuario, motivo, nota.id)
        db.delete(movimento)

    _anular(nota, usuario, motivo)
    db.commit()

    if not movimentos:
        # Acontece quando alguém já apagou os movimentos por outro caminho.
        # Anular assim mesmo é o certo: o estado da nota passa a descrever o
        # estoque, que é o que ela deveria fazer desde o começo.
        return 0, ["Esta nota já não tinha movimentos no estoque. "
                   "Marquei como anulada para o estado bater com o saldo."]

    total = sum(m.custo_total or 0 for m in movimentos)
    return len(movimentos), [
        f"{len(movimentos)} item(ns), R$ {total:.2f}, saíram do estoque e do "
        f"CMV. A nota {nota.numero or ''} pode ser lançada de novo.".replace(
            "  ", " ")]
