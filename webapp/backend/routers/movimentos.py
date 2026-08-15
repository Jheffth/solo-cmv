"""
Lançamento de compras e contagens — equivalente à macro FiltrarEAtualizarTabela
e ao livro-razão da aba "Registros" nas planilhas de origem.

Cada lançamento também atualiza o Histórico de Custo do produto (equivalente
à aba "UCustoInfo"), quando um custo unitário é informado.
"""
from datetime import date as date_type
from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Movimento, HistoricoCusto, TipoMovimento, PapelUsuario,
    SessaoInventario, Requisicao,
)
from schemas import (
    MovimentoOut, MovimentoCreate, NotaFiscalLancamento, NotaFiscalResultado,
)
from auth.deps import get_current_user, exigir_papeis
from servicos import escopo as servico_escopo

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
    return movimentos


@router.post("", response_model=MovimentoOut, status_code=201)
def registrar(dados: MovimentoCreate, db: Session = Depends(get_db),
              usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
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
                          usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
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
