"""
Serviço de contagem de inventário — regra de negócio em um lugar só.

POR QUE ESTE MÓDULO EXISTE
--------------------------
A contagem pode chegar por vários caminhos: a tela web (Lançador), e no
futuro um bot do Telegram, um coletor de código de barras ou uma integração
externa. Se cada caminho tivesse a sua própria lógica, as regras iriam
divergir — foi exatamente o que aconteceu antes: o Lançador gravava um
movimento solto enquanto o relatório lia da tabela do inventário, e a
contagem simplesmente não aparecia no PDF.

Aqui fica a regra única. Cada canal só precisa traduzir a entrada do usuário
e chamar `registrar_contagem`, tratando `ErroContagem` do jeito que fizer
sentido (HTTP 409 na API, mensagem de texto no bot).

IDENTIFICAÇÃO FLEXÍVEL
----------------------
Tanto o inventário quanto o produto podem ser informados de duas formas,
porque cada canal tem o que está à mão:
  * inventário: pelo id interno (web) ou pelo número + unidade (bot: "INV 01")
  * produto:    pelo id interno (web) ou pelo código de 6 dígitos (bot)

O QUE A CONTAGEM FAZ (E NÃO FAZ)
--------------------------------
Ela grava a quantidade contada na linha do inventário. Ela NÃO mexe no
estoque: isso só acontece na finalização, quando as contagens são aplicadas
de uma vez. É o que permite conferir divergências antes de valer.
"""
from dataclasses import dataclass
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import (
    SessaoInventario, InventarioItem, StatusSessaoInventario, Produto,
)

# Canais de origem — registrado na linha para auditoria
ORIGEM_WEB = "WEB"
ORIGEM_TELEGRAM = "TELEGRAM"
ORIGEM_API = "API"

STATUS_ACEITA_CONTAGEM = (
    StatusSessaoInventario.CONGELADO,
    StatusSessaoInventario.EM_CONTAGEM,
)

ROTULOS_STATUS = {
    StatusSessaoInventario.ABERTO: "apenas aberto",
    StatusSessaoInventario.CONGELADO: "congelado",
    StatusSessaoInventario.EM_CONTAGEM: "em contagem",
    StatusSessaoInventario.FINALIZADO: "finalizado",
    StatusSessaoInventario.CANCELADO: "cancelado",
}


class ErroContagem(Exception):
    """Falha de regra de negócio, com mensagem pronta para o usuário final.

    `codigo` permite que cada canal reaja de forma diferente sem depender do
    texto da mensagem (a API mapeia para status HTTP; o bot pode sugerir uma
    ação).
    """

    def __init__(self, mensagem: str, codigo: str = "INVALIDO", http: int = 409):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.codigo = codigo
        self.http = http


@dataclass
class ResultadoContagem:
    item: InventarioItem
    sessao: SessaoInventario
    produto: Produto
    primeira_contagem: bool     # True se este item ainda não tinha contagem
    valor_anterior: Optional[float]
    valor_adicionado: float
    valor_final: float
    foi_acumulado: bool = False


# ==============================================================================
# LOCALIZAÇÃO
# ==============================================================================
def localizar_sessao(db: Session, *, sessao_id: Optional[int] = None,
                     numero: Optional[str] = None,
                     unidade_id: Optional[int] = None) -> SessaoInventario:
    """Encontra o inventário pelo id interno OU pelo número + unidade."""
    if sessao_id:
        sessao = db.query(SessaoInventario).filter(SessaoInventario.id == sessao_id).first()
        if not sessao:
            raise ErroContagem("Inventário não encontrado.", "SESSAO_NAO_ENCONTRADA", 404)
        return sessao

    if numero and unidade_id:
        sessao = db.query(SessaoInventario).filter(
            SessaoInventario.unidade_id == unidade_id,
            SessaoInventario.numero_documento == str(numero).strip(),
        ).first()
        if not sessao:
            raise ErroContagem(
                f"Inventário nº {numero} não encontrado nesta unidade.",
                "SESSAO_NAO_ENCONTRADA", 404,
            )
        return sessao

    raise ErroContagem(
        "Informe o inventário (id, ou número junto da unidade).",
        "SESSAO_NAO_INFORMADA", 400,
    )


def localizar_produto(db: Session, *, produto_id: Optional[int] = None,
                      codigo: Optional[str] = None,
                      empresa_id: Optional[int] = None) -> Produto:
    """Encontra o produto pelo id interno OU pelo código de 6 dígitos."""
    query = db.query(Produto)
    if empresa_id:
        query = query.filter(Produto.empresa_id == empresa_id)

    if produto_id:
        produto = query.filter(Produto.id == produto_id).first()
        if not produto:
            raise ErroContagem("Produto não encontrado.", "PRODUTO_NAO_ENCONTRADO", 404)
        return produto

    if codigo:
        produto = query.filter(Produto.codigo == str(codigo).strip()).first()
        if not produto:
            raise ErroContagem(
                f"Produto {codigo} não encontrado.",
                "PRODUTO_NAO_ENCONTRADO", 404,
            )
        return produto

    raise ErroContagem("Informe o produto (id ou código).", "PRODUTO_NAO_INFORMADO", 400)


# ==============================================================================
# VALIDAÇÕES
# ==============================================================================
def validar_sessao_aceita_contagem(sessao: SessaoInventario) -> None:
    """Garante que o inventário está em estado que aceita contagem."""
    if sessao.status not in STATUS_ACEITA_CONTAGEM:
        rotulo = ROTULOS_STATUS.get(sessao.status, sessao.status.value)
        raise ErroContagem(
            f"O inventário nº {sessao.numero_documento} está {rotulo} e não aceita contagens.",
            "STATUS_INVALIDO",
            409,
        )


def descrever_escopo(sessao: SessaoInventario) -> str:
    if sessao.geral:
        return "todas as famílias"
    nomes = [c.nome.replace("Família - ", "") for c in sessao.categorias]
    return ", ".join(nomes) if nomes else "(sem famílias definidas)"


def validar_produto_no_escopo(sessao: SessaoInventario, produto: Produto) -> InventarioItem:
    """Garante que o produto pertence a este inventário e retorna a linha correspondente."""
    item = next((i for i in sessao.itens if i.produto_id == produto.id), None)
    if not item:
        raise ErroContagem(
            f"O produto {produto.nome} não pertence ao escopo do inventário nº {sessao.numero_documento}.",
            "PRODUTO_FORA_DO_ESCOPO",
            409,
        )
    return item


def validar_quantidade(quantidade) -> float:
    """Converte e valida a quantidade contada."""
    try:
        if isinstance(quantidade, str):
            quantidade = quantidade.replace(",", ".").strip()
        valor = float(quantidade)
    except (TypeError, ValueError):
        raise ErroContagem("Quantidade inválida.", "QUANTIDADE_INVALIDA", 400)
    if valor < 0:
        raise ErroContagem("A quantidade contada não pode ser negativa.", "QUANTIDADE_INVALIDA", 400)
    return valor


# ==============================================================================
# OPERAÇÃO PRINCIPAL
# ==============================================================================
def registrar_contagem(
    db: Session,
    *,
    quantidade,
    sessao_id: Optional[int] = None,
    numero_inventario: Optional[str] = None,
    unidade_id: Optional[int] = None,
    produto_id: Optional[int] = None,
    codigo_produto: Optional[str] = None,
    usuario_id: Optional[int] = None,
    empresa_id: Optional[int] = None,
    origem: str = ORIGEM_WEB,
    acumular: bool = False,
) -> ResultadoContagem:
    """Registra (ou corrige/acumula) a quantidade contada de um produto no inventário.

    - Se acumular=True e já havia contagem anterior: soma o valor novo à anterior.
    - Se acumular=False: define o valor exato (sobrescreve).
    """
    sessao = localizar_sessao(db, sessao_id=sessao_id, numero=numero_inventario, unidade_id=unidade_id)
    validar_sessao_aceita_contagem(sessao)

    produto = localizar_produto(db, produto_id=produto_id, codigo=codigo_produto, empresa_id=empresa_id)
    item = validar_produto_no_escopo(sessao, produto)
    valor = validar_quantidade(quantidade)

    anterior = item.quantidade_contada
    foi_acumulado = False
    if acumular and anterior is not None:
        novo_valor = round(anterior + valor, 4)
        foi_acumulado = True
    else:
        novo_valor = valor

    item.quantidade_contada = novo_valor
    item.contado_em = datetime.utcnow()
    item.usuario_contagem_id = usuario_id
    item.origem = origem

    # Primeira contagem tira o inventário de "congelado" para "em contagem"
    if sessao.status == StatusSessaoInventario.CONGELADO:
        sessao.status = StatusSessaoInventario.EM_CONTAGEM

    db.commit()
    db.refresh(item)

    return ResultadoContagem(
        item=item,
        sessao=sessao,
        produto=produto,
        primeira_contagem=anterior is None,
        valor_anterior=anterior,
        valor_adicionado=valor,
        valor_final=novo_valor,
        foi_acumulado=foi_acumulado,
    )


def desfazer_contagem(
    db: Session,
    *,
    sessao_id: int,
    produto_id: int,
    valor_anterior: Optional[float],
    usuario_id: Optional[int] = None,
    origem: str = ORIGEM_WEB,
) -> InventarioItem:
    """Restaura a quantidade contada anterior de um produto no inventário."""
    sessao = localizar_sessao(db, sessao_id=sessao_id)
    validar_sessao_aceita_contagem(sessao)
    produto = localizar_produto(db, produto_id=produto_id)
    item = validar_produto_no_escopo(sessao, produto)

    item.quantidade_contada = valor_anterior
    item.contado_em = datetime.utcnow()
    item.usuario_contagem_id = usuario_id
    item.origem = origem
    db.commit()
    db.refresh(item)
    return item
