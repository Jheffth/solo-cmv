"""
Serviço de perda — o que saiu do estoque e não virou venda.

POR QUE ISSO EXISTE
-------------------
Nas planilhas de origem a perda era invisível. O consumo era calculado por
diferença (Estoque Inicial + Compras − Estoque Final), então tudo que sumia —
o que virou prato e o que apodreceu na geladeira — caía no mesmo balde
chamado CMV. O gestor via o CMV subir e não tinha como saber onde agir.

Registrar a perda separadamente não muda o CMV total (o item saiu do estoque
de qualquer jeito), mas responde a pergunta que importa: *quanto* do CMV é
desperdício e *por quê*.

COMO FUNCIONA
-------------
Diferente da requisição, a perda não tem ciclo de vida — ela já aconteceu.
Um único lançamento baixa o estoque na hora, com o custo congelado no momento
do registro (o último custo conhecido do item).

A regra vive aqui, e não no router, para que um bot do Telegram ou um coletor
possam lançar perda pelo mesmo caminho — mesma validação, mesma numeração.
"""
from dataclasses import dataclass
from datetime import date as date_type, datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import Movimento, Produto, TipoMovimento, MotivoPerda
from calculo_estoque import saldos_por_produto, ultimos_custos

ORIGEM_WEB = "WEB"
ORIGEM_TELEGRAM = "TELEGRAM"
ORIGEM_API = "API"

PREFIXO = "PER-"

ROTULOS_MOTIVO = {
    MotivoPerda.QUEBRA: "Quebra / manuseio",
    MotivoPerda.VALIDADE: "Vencimento",
    MotivoPerda.DETERIORACAO: "Deterioração",
    MotivoPerda.ERRO_PRODUCAO: "Erro de produção",
    MotivoPerda.FURTO: "Furto / desvio",
    MotivoPerda.CONSUMO_INTERNO: "Consumo interno",
    MotivoPerda.OUTRO: "Outro",
}


class ErroPerda(Exception):
    def __init__(self, mensagem: str, codigo: str = "INVALIDO", http: int = 409):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.http = http


@dataclass
class ResultadoPerda:
    movimento: Movimento
    produto: Produto
    saldo_anterior: float
    saldo_atual: float


# ==============================================================================
# NUMERAÇÃO
# ==============================================================================
def proximo_numero(db: Session, unidade_id: int) -> str:
    """Sequência própria da perda, por unidade: PER-01, PER-02…

    Lê os documentos já gravados em vez de manter um contador, pelo mesmo
    motivo do inventário e da requisição: o número tem que sobreviver a
    restauração de backup sem depender de tabela auxiliar.
    """
    numeros = []
    for m in (db.query(Movimento)
              .filter(Movimento.unidade_id == unidade_id,
                      Movimento.tipo == TipoMovimento.PERDA).all()):
        doc = (m.numero_documento or "").strip()
        if doc.upper().startswith(PREFIXO) and doc[len(PREFIXO):].isdigit():
            numeros.append(int(doc[len(PREFIXO):]))
    return f"{PREFIXO}{(max(numeros) + 1) if numeros else 1:02d}"


# ==============================================================================
# VALIDAÇÕES
# ==============================================================================
def localizar_produto(db: Session, *, produto_id: Optional[int] = None,
                      codigo: Optional[str] = None,
                      empresa_id: Optional[int] = None) -> Produto:
    query = db.query(Produto)
    if empresa_id:
        query = query.filter(Produto.empresa_id == empresa_id)

    if produto_id:
        produto = query.filter(Produto.id == produto_id).first()
        if not produto:
            raise ErroPerda("Produto não encontrado.", "PRODUTO_NAO_ENCONTRADO", 404)
        return produto
    if codigo:
        produto = query.filter(Produto.codigo == str(codigo).strip()).first()
        if not produto:
            raise ErroPerda(f"Nenhum produto com o código {codigo}.",
                            "PRODUTO_NAO_ENCONTRADO", 404)
        return produto
    raise ErroPerda("Informe o produto (id ou código).", "PRODUTO_NAO_INFORMADO", 400)


def validar_quantidade(quantidade) -> float:
    try:
        valor = float(quantidade)
    except (TypeError, ValueError):
        raise ErroPerda("Quantidade inválida.", "QUANTIDADE_INVALIDA", 400)
    if valor <= 0:
        raise ErroPerda("A quantidade perdida deve ser maior que zero.",
                        "QUANTIDADE_INVALIDA", 400)
    return valor


def validar_motivo(motivo) -> MotivoPerda:
    if motivo is None:
        raise ErroPerda("Informe o motivo da perda.", "MOTIVO_NAO_INFORMADO", 400)
    if isinstance(motivo, MotivoPerda):
        return motivo
    try:
        return MotivoPerda(str(motivo).strip().upper())
    except ValueError:
        validos = ", ".join(m.value for m in MotivoPerda)
        raise ErroPerda(f"Motivo inválido. Use um destes: {validos}.",
                        "MOTIVO_INVALIDO", 400)


# ==============================================================================
# REGISTRO
# ==============================================================================
def registrar(
    db: Session,
    *,
    unidade_id: int,
    quantidade,
    motivo,
    produto_id: Optional[int] = None,
    codigo_produto: Optional[str] = None,
    data: Optional[date_type] = None,
    observacao: Optional[str] = None,
    custo_unitario: Optional[float] = None,
    usuario_id: Optional[int] = None,
    empresa_id: Optional[int] = None,
    origem: str = ORIGEM_WEB,
) -> ResultadoPerda:
    """Baixa a quantidade perdida do estoque, na hora.

    O saldo pode ficar negativo — igual à requisição. Estoque teórico negativo
    não é erro de digitação a ser bloqueado, é sintoma de que falta inventário,
    e travar o registro só faria a perda deixar de ser anotada.
    """
    produto = localizar_produto(db, produto_id=produto_id, codigo=codigo_produto,
                                empresa_id=empresa_id)
    valor = validar_quantidade(quantidade)
    motivo_val = validar_motivo(motivo)

    if motivo_val == MotivoPerda.OUTRO and not (observacao or "").strip():
        raise ErroPerda("Perda com motivo 'Outro' exige uma observação explicando.",
                        "OBSERVACAO_OBRIGATORIA", 400)

    saldo_antes = saldos_por_produto(db, unidade_id, [produto.id]).get(produto.id, 0.0)

    custo = custo_unitario
    if custo is None:
        custo = ultimos_custos(db, unidade_id).get(produto.id)

    movimento = Movimento(
        unidade_id=unidade_id,
        produto_id=produto.id,
        tipo=TipoMovimento.PERDA,
        quantidade=valor,
        custo_unitario=custo,
        custo_total=round((custo or 0) * valor, 4),
        data=data or date_type.today(),
        numero_documento=proximo_numero(db, unidade_id),
        motivo=motivo_val,
        observacao=(observacao or "").strip() or None,
        usuario_id=usuario_id,
    )
    db.add(movimento)
    db.commit()
    db.refresh(movimento)

    return ResultadoPerda(
        movimento=movimento,
        produto=produto,
        saldo_anterior=saldo_antes,
        saldo_atual=round(saldo_antes - valor, 3),
    )


def estornar(db: Session, movimento_id: int) -> None:
    """Apaga uma perda lançada por engano, devolvendo a quantidade ao estoque.

    Não guarda estorno como contra-lançamento porque perda registrada errado
    é ruído puro: manter os dois lados só polui o livro-razão.
    """
    mov = db.query(Movimento).filter(
        Movimento.id == movimento_id,
        Movimento.tipo == TipoMovimento.PERDA,
    ).first()
    if not mov:
        raise ErroPerda("Perda não encontrada.", "NAO_ENCONTRADA", 404)
    db.delete(mov)
    db.commit()
