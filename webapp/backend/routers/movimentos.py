"""
Lançamento de compras e contagens — equivalente à macro FiltrarEAtualizarTabela
e ao livro-razão da aba "Registros" nas planilhas de origem.

Cada lançamento também atualiza o Histórico de Custo do produto (equivalente
à aba "UCustoInfo"), quando um custo unitário é informado.
"""
from datetime import date as date_type
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Movimento, MovimentoExcluido, HistoricoCusto, TipoMovimento, PapelUsuario,
    SessaoInventario, Requisicao,
)
from schemas import (
    MovimentoOut, MovimentoCreate, NotaFiscalLancamento, NotaFiscalResultado,
)
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer
from servicos import escopo as servico_escopo
from servicos import exclusao as servico_exclusao

router = APIRouter(prefix="/movimentos", tags=["movimentos"])


# Todo movimento nasce de um documento. Qual documento depende do tipo:
#   compra     → nota fiscal        (numero_documento, digitado no Lançador)
#   contagem   → inventário         (numero_documento da sessão)
#   requisição → requisição         (numero da requisição)
#   perda      → registro de perda  (numero_documento, quando houver)
TIPO_DOCUMENTO = {
    TipoMovimento.COMPRA: "NOTA",
    TipoMovimento.CONTAGEM_INICIAL: "INVENTARIO",
    TipoMovimento.CONTAGEM_FINAL: "INVENTARIO",
    TipoMovimento.REQUISICAO: "REQUISICAO",
    TipoMovimento.PERDA: "PERDA",
}

# Inventário nº 01 e requisição nº 01 existem ao mesmo tempo e são coisas
# diferentes. Numa coluna só, o número puro seria ambíguo — daí o prefixo.
PREFIXO_DOCUMENTO = {
    "NOTA": "NF ",
    "INVENTARIO": "INV-",
    "REQUISICAO": "REQ-",
    "PERDA": "",       # a perda já nasce numerada como PER-xxxx
}


def _rotular(tipo_doc: Optional[str], numero: Optional[str]) -> Optional[str]:
    if not numero:
        return None
    prefixo = PREFIXO_DOCUMENTO.get(tipo_doc or "", "")
    # Não duplica prefixo em número que já veio rotulado (REQ-01, PER-0007…)
    if prefixo and numero.upper().startswith(prefixo.strip().upper()):
        return numero
    return f"{prefixo}{numero}"


def _anexar_documentos(db: Session, movimentos: List[Movimento]) -> List[Movimento]:
    """Preenche `documento`/`documento_tipo` de cada movimento.

    Busca inventários e requisições em duas consultas, não uma por linha.
    """
    ids_inv = {m.sessao_inventario_id for m in movimentos if m.sessao_inventario_id}
    ids_req = {m.requisicao_id for m in movimentos if m.requisicao_id}

    numeros_inv = dict(
        db.query(SessaoInventario.id, SessaoInventario.numero_documento)
        .filter(SessaoInventario.id.in_(ids_inv)).all()
    ) if ids_inv else {}
    numeros_req = dict(
        db.query(Requisicao.id, Requisicao.numero)
        .filter(Requisicao.id.in_(ids_req)).all()
    ) if ids_req else {}

    for m in movimentos:
        tipo_doc = TIPO_DOCUMENTO.get(m.tipo)
        if tipo_doc == "INVENTARIO":
            numero = numeros_inv.get(m.sessao_inventario_id)
        elif tipo_doc == "REQUISICAO":
            numero = numeros_req.get(m.requisicao_id)
        else:
            numero = m.numero_documento
        # Sem vínculo (dado antigo ou lançamento solto), cai no que houver
        m.documento = _rotular(tipo_doc, numero or m.numero_documento)
        m.documento_tipo = tipo_doc
    return movimentos


@router.get("", response_model=List[MovimentoOut])
def listar(unidade_id: Optional[str] = None, produto_id: Optional[int] = None,
           tipo: Optional[TipoMovimento] = None,
           db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Livro-razão de uma unidade, ou de todas quando unidade_id=REGIONAL.

    Movimento não se soma nem se agrupa: cada lançamento é um fato de uma
    loja específica. Na Regional a lista é a união dos livros, com a coluna
    de unidade dizendo de onde cada linha veio.
    """
    recorte = servico_escopo.resolver(db, usuario, unidade_id)
    query = db.query(Movimento).filter(Movimento.unidade_id.in_(recorte.ids))
    if produto_id:
        query = query.filter(Movimento.produto_id == produto_id)
    if tipo:
        query = query.filter(Movimento.tipo == tipo)
    movimentos = query.order_by(Movimento.data.desc(), Movimento.id.desc()).limit(500).all()
    _anexar_documentos(db, movimentos)

    # De qual loja é cada linha — sem isto a Regional viraria uma lista
    # de lançamentos sem dono.
    nomes = {u.id: u.nome for u in recorte.unidades}
    for m in movimentos:
        m.unidade_nome = nomes.get(m.unidade_id)
        m.travado_para_excluir = servico_exclusao.por_que_nao(m)
    return movimentos


class ExclusaoEmLote(BaseModel):
    ids: List[int]
    motivo: Optional[str] = None


@router.post("/excluir")
def excluir_movimentos(
        dados: ExclusaoEmLote, db: Session = Depends(get_db),
        usuario=Depends(requer(Capacidade.EXCLUIR_MOVIMENTO))):
    """Retira lançamentos do livro-razão, guardando a fotografia de cada um.

    POST e não DELETE porque é um lote com motivo: DELETE com corpo é
    aceito por alguns servidores e descartado por outros, e perder o motivo
    no meio do caminho estragaria justamente a parte que serve para
    entender depois.

    Estoque e CMV são a soma dos movimentos, então tirar a linha já desfaz
    o efeito — não há contra-lançamento. O rastro fica em
    `movimentos_excluidos`, com quem tirou, quando e por quê.
    """
    if not dados.ids:
        raise HTTPException(400, "Nenhum lançamento selecionado.")
    if len(dados.ids) > 200:
        raise HTTPException(
            400, "São muitos lançamentos de uma vez. Exclua em partes — "
                 "assim dá para conferir o que saiu a cada passo.")

    recorte = servico_escopo.resolver(db, usuario, None)
    movimentos = db.query(Movimento).filter(
        Movimento.id.in_(dados.ids),
        Movimento.unidade_id.in_(recorte.ids),
    ).all()

    # Sumiram, ou são de uma loja que esta pessoa não alcança. Nos dois casos
    # a resposta é a mesma, e prosseguir com os que sobraram seria excluir
    # menos do que a pessoa mandou sem ela saber.
    if len(movimentos) != len(set(dados.ids)):
        raise HTTPException(
            404, "Algum dos lançamentos selecionados não existe mais ou não "
                 "é de uma loja sua. Atualize a lista e tente de novo.")

    try:
        quantos, avisos = servico_exclusao.excluir(
            db, movimentos, usuario, dados.motivo or "")
    except servico_exclusao.ErroExclusao as erro:
        raise HTTPException(409, str(erro))
    return {"excluidos": quantos, "avisos": avisos}


@router.get("/excluidos")
def listar_excluidos(unidade_id: Optional[str] = None,
                     db: Session = Depends(get_db),
                     usuario=Depends(requer(Capacidade.ANULAR_NOTA))):
    """O que foi tirado do estoque, por quem e quando.

    Fica atrás de ANULAR_NOTA e não de EXCLUIR_MOVIMENTO de propósito: quem
    responde pelo número da empresa precisa poder auditar o que sumiu dele,
    mesmo sem poder excluir linha avulsa.
    """
    recorte = servico_escopo.resolver(db, usuario, unidade_id)
    registros = db.query(MovimentoExcluido).filter(
        MovimentoExcluido.unidade_id.in_(recorte.ids)
    ).order_by(MovimentoExcluido.excluido_em.desc()).limit(200).all()

    nomes = {u.id: u.nome for u in recorte.unidades}
    return [{
        "id": r.id,
        "movimento_id": r.movimento_id,
        "unidade_nome": nomes.get(r.unidade_id),
        "produto": r.produto.nome if r.produto else None,
        "tipo": r.tipo,
        "quantidade": r.quantidade,
        "custo_total": r.custo_total,
        "documento": r.numero_documento,
        "data": r.data.isoformat() if r.data else None,
        "nota_id": r.nota_id,
        "excluido_por": r.excluido_por.nome if r.excluido_por else None,
        "excluido_em": r.excluido_em.isoformat() if r.excluido_em else None,
        "motivo": r.excluido_motivo,
    } for r in registros]


@router.post("", response_model=MovimentoOut, status_code=201)
def registrar(dados: MovimentoCreate, db: Session = Depends(get_db),
              usuario=Depends(requer(Capacidade.LANCAR_COMPRA))):
    # Contagem não é lançamento avulso: ela nasce de um inventário. Permitir
    # os dois caminhos criaria duas fontes de verdade para o mesmo número —
    # exatamente o problema que o inventário veio resolver.
    if dados.tipo in (TipoMovimento.CONTAGEM_INICIAL, TipoMovimento.CONTAGEM_FINAL):
        raise HTTPException(
            status_code=400,
            detail="Contagem de estoque é feita pelo inventário, não por lançamento avulso. "
                   "Abra um inventário, congele-o e lance a contagem pelo Lançador.",
        )

    data_mov = dados.data or date_type.today()
    custo_total = None
    if dados.custo_unitario is not None:
        custo_total = round(dados.custo_unitario * dados.quantidade, 4)

    movimento = Movimento(
        unidade_id=dados.unidade_id,
        produto_id=dados.produto_id,
        tipo=dados.tipo,
        quantidade=dados.quantidade,
        custo_unitario=dados.custo_unitario,
        custo_total=custo_total,
        fornecedor_id=dados.fornecedor_id,
        numero_documento=dados.numero_documento,
        data=data_mov,
        sessao_inventario_id=dados.sessao_inventario_id,
        usuario_id=usuario.id,
    )
    db.add(movimento)

    # Atualiza histórico de último custo (equivalente à aba UCustoInfo)
    if dados.tipo == TipoMovimento.COMPRA and dados.custo_unitario is not None:
        db.add(HistoricoCusto(
            produto_id=dados.produto_id,
            unidade_id=dados.unidade_id,
            custo=dados.custo_unitario,
            data=data_mov,
            numero_documento=dados.numero_documento,
            fornecedor_id=dados.fornecedor_id,
        ))

    db.commit()
    db.refresh(movimento)
    return movimento


@router.post("/nota-fiscal", response_model=NotaFiscalResultado, status_code=201)
def registrar_nota_fiscal(dados: NotaFiscalLancamento, db: Session = Depends(get_db),
                          usuario=Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Lança uma nota fiscal inteira de uma vez: cada item vira um Movimento
    de COMPRA, todos com o mesmo nº de documento, fornecedor e data — do jeito
    que a compra chega na prática (uma nota com vários produtos)."""
    if not dados.itens:
        raise HTTPException(status_code=400, detail="A nota fiscal precisa ter pelo menos um item.")

    data_mov = dados.data or date_type.today()
    valor_total = 0.0

    for item in dados.itens:
        custo_total = None
        if item.custo_unitario is not None:
            custo_total = round(item.custo_unitario * item.quantidade, 4)
            valor_total += custo_total

        db.add(Movimento(
            unidade_id=dados.unidade_id,
            produto_id=item.produto_id,
            tipo=TipoMovimento.COMPRA,
            quantidade=item.quantidade,
            custo_unitario=item.custo_unitario,
            custo_total=custo_total,
            fornecedor_id=dados.fornecedor_id,
            numero_documento=dados.numero_documento,
            data=data_mov,
            sessao_inventario_id=dados.sessao_inventario_id,
            usuario_id=usuario.id,
        ))

        if item.custo_unitario is not None:
            db.add(HistoricoCusto(
                produto_id=item.produto_id,
                unidade_id=dados.unidade_id,
                custo=item.custo_unitario,
                data=data_mov,
                numero_documento=dados.numero_documento,
                fornecedor_id=dados.fornecedor_id,
            ))

    db.commit()
    return NotaFiscalResultado(
        movimentos_criados=len(dados.itens),
        valor_total=round(valor_total, 2),
        numero_documento=dados.numero_documento,
    )
