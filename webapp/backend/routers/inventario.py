"""
Inventários — abertura, congelamento, contagem, finalização e relatório.

CICLO DE VIDA
-------------
    ABERTO ──congelar──> CONGELADO ──1ª contagem──> EM_CONTAGEM ──finalizar──> FINALIZADO
       └──────────────── CANCELADO <────────────────────┘

Regras implementadas:
  * Numeração sequencial por unidade (01, 02, 03…), nunca reaproveitada —
    inventários cancelados consomem número, pois seguem consultáveis.
  * Escopo por família (uma, várias) ou geral (todas).
  * Não pode haver dois inventários ativos cobrindo a mesma família.
  * ABERTO não aceita contagem. Só depois de CONGELADO, quando o estoque
    é fotografado (é essa foto que permite medir a divergência depois).
  * Ao FINALIZAR, as quantidades contadas viram o estoque real dos itens.
"""
from datetime import datetime, date, time
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from models import (
    SessaoInventario, InventarioItem, StatusSessaoInventario, PapelUsuario,
    Categoria, Produto, Movimento, TipoMovimento,
)
from schemas import (
    SessaoInventarioOut, SessaoInventarioAbrir, InventarioDetalheOut,
    InventarioItemOut, ContagemItem, ContagemLancamento, ContagemResultado,
)
from auth.deps import get_current_user, exigir_papeis
from calculo_estoque import saldos_por_produto, ultimos_custos
from servicos.contagem import registrar_contagem, ErroContagem, ORIGEM_WEB
from servicos import escopo as _escopo

router = APIRouter(prefix="/inventario", tags=["inventário"])

# Status em que o inventário ainda "ocupa" o setor
STATUS_ATIVOS = (
    StatusSessaoInventario.ABERTO,
    StatusSessaoInventario.CONGELADO,
    StatusSessaoInventario.EM_CONTAGEM,
)
# Status em que o inventário aceita contagem
STATUS_ACEITA_CONTAGEM = (
    StatusSessaoInventario.CONGELADO,
    StatusSessaoInventario.EM_CONTAGEM,
)

TRANSICOES = {
    StatusSessaoInventario.ABERTO: {StatusSessaoInventario.CONGELADO, StatusSessaoInventario.CANCELADO},
    StatusSessaoInventario.CONGELADO: {StatusSessaoInventario.EM_CONTAGEM, StatusSessaoInventario.FINALIZADO,
                                       StatusSessaoInventario.CANCELADO},
    StatusSessaoInventario.EM_CONTAGEM: {StatusSessaoInventario.FINALIZADO, StatusSessaoInventario.CANCELADO},
    StatusSessaoInventario.FINALIZADO: set(),
    StatusSessaoInventario.CANCELADO: set(),
}


# ==============================================================================
# HELPERS
# ==============================================================================
def _proximo_numero(db: Session, unidade_id: int) -> str:
    """Próximo número da sequência da unidade, com 2 dígitos no mínimo.

    Considera TODOS os inventários já abertos (inclusive cancelados e
    finalizados) — número consumido nunca é reaproveitado.
    """
    numeros = [
        int(s.numero_documento)
        for s in db.query(SessaoInventario).filter(SessaoInventario.unidade_id == unidade_id).all()
        if str(s.numero_documento).strip().isdigit()
    ]
    proximo = (max(numeros) + 1) if numeros else 1
    return f"{proximo:02d}"


def _produtos_do_escopo(db: Session, sessao: SessaoInventario, empresa_id: Optional[int]) -> List[Produto]:
    query = db.query(Produto).filter(Produto.ativo == True)  # noqa: E712
    if empresa_id:
        query = query.filter(Produto.empresa_id == empresa_id)
    if not sessao.geral:
        ids = [c.id for c in sessao.categorias]
        if not ids:
            return []
        query = query.filter(Produto.categoria_id.in_(ids))
    return query.order_by(Produto.nome).all()


def _conflito_de_setor(db: Session, unidade_id: int, geral: bool, categoria_ids: List[int]):
    """Devolve o inventário ativo que colide com o escopo pedido, ou None."""
    ativos = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == unidade_id,
        SessaoInventario.status.in_(STATUS_ATIVOS),
    ).all()

    for ativo in ativos:
        if geral or ativo.geral:
            return ativo   # geral cobre tudo: colide com qualquer inventário ativo
        if set(c.id for c in ativo.categorias) & set(categoria_ids):
            return ativo
    return None


def _montar_itens_out(sessao: SessaoInventario) -> List[InventarioItemOut]:
    saida = []
    for item in sessao.itens:
        p = item.produto
        saida.append(InventarioItemOut(
            id=item.id,
            produto_id=item.produto_id,
            codigo=p.codigo if p else None,
            produto=p.nome if p else None,
            categoria=p.categoria.nome if (p and p.categoria) else None,
            unidade_medida=p.unidade_medida if p else None,
            quantidade_sistema=item.quantidade_sistema,
            quantidade_contada=item.quantidade_contada,
            custo_unitario=item.custo_unitario,
            divergencia=item.divergencia,
            valor_divergencia=item.valor_divergencia,
        ))
    saida.sort(key=lambda i: (i.produto or ""))
    return saida


def _resumo(itens: List[InventarioItemOut]) -> dict:
    contados = [i for i in itens if i.quantidade_contada is not None]
    perdas = [i for i in contados if i.valor_divergencia < 0]
    sobras = [i for i in contados if i.valor_divergencia > 0]
    return {
        "total_itens": len(itens),
        "itens_contados": len(contados),
        "itens_nao_contados": len(itens) - len(contados),
        "itens_com_divergencia": sum(1 for i in contados if abs(i.divergencia) > 0.0001),
        "valor_perdas": round(sum(i.valor_divergencia for i in perdas), 2),
        "valor_sobras": round(sum(i.valor_divergencia for i in sobras), 2),
        "valor_liquido": round(sum(i.valor_divergencia for i in contados), 2),
        "valor_contado": round(sum((i.quantidade_contada or 0) * (i.custo_unitario or 0) for i in contados), 2),
    }


def _buscar_sessao(db: Session, sessao_id: int) -> SessaoInventario:
    sessao = db.query(SessaoInventario).filter(SessaoInventario.id == sessao_id).first()
    if not sessao:
        raise HTTPException(status_code=404, detail="Inventário não encontrado.")
    return sessao


# ==============================================================================
# LISTAGEM E CONSULTA
# ==============================================================================
@router.get("/sessoes", response_model=List[SessaoInventarioOut])
def listar_sessoes(
    unidade_id: Optional[str] = None,
    status: Optional[StatusSessaoInventario] = None,
    busca: Optional[str] = None,
    data_inicio: Optional[date] = None,
    data_fim: Optional[date] = None,
    limite: int = 200,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    # Aceita "REGIONAL": o histórico de inventários de todas as lojas, com a
    # coluna de unidade separando quem é quem. Abrir/congelar/finalizar
    # continua sendo ato de uma unidade — só a CONSULTA é consolidada.
    recorte = _escopo.resolver(db, usuario, unidade_id)
    query = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id.in_(recorte.ids))
    if status:
        query = query.filter(SessaoInventario.status == status)
    if busca:
        termo = f"%{busca.strip()}%"
        query = query.filter(
            (SessaoInventario.numero_documento.ilike(termo))
            | (SessaoInventario.descricao.ilike(termo))
        )
    if data_inicio:
        query = query.filter(SessaoInventario.data_abertura >= datetime.combine(data_inicio, time.min))
    if data_fim:
        query = query.filter(SessaoInventario.data_abertura <= datetime.combine(data_fim, time.max))

    sessoes = query.order_by(SessaoInventario.data_abertura.desc()).limit(
        max(1, min(limite, 1000))).all()

    # Na Regional, cada linha precisa dizer de qual loja é: inventário nº 01
    # existe em todas elas, e sem a unidade a lista seria ilegível.
    nomes = {u.id: u.nome for u in recorte.unidades}
    for s in sessoes:
        s.unidade_nome = nomes.get(s.unidade_id)
    return sessoes


@router.get("/sessoes/buscar", response_model=SessaoInventarioOut)
def buscar_por_numero(numero: str, unidade_id: int,
                      db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Valida um número de inventário digitado no Lançador.

    Só libera inventário que aceita contagem (CONGELADO ou EM_CONTAGEM).
    Inventário apenas ABERTO ainda não foi congelado e por isso não recebe
    contagem — a fotografia do estoque precisa existir antes.
    """
    sessao = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == unidade_id,
        SessaoInventario.numero_documento == numero.strip(),
    ).first()

    if not sessao:
        raise HTTPException(status_code=404, detail=f"Inventário nº {numero} não encontrado nesta unidade.")

    if sessao.status == StatusSessaoInventario.ABERTO:
        raise HTTPException(
            status_code=409,
            detail=f"Inventário nº {numero} está apenas aberto. Congele o inventário para poder lançar contagens.",
        )
    if sessao.status not in STATUS_ACEITA_CONTAGEM:
        rotulos = {StatusSessaoInventario.FINALIZADO: "finalizado", StatusSessaoInventario.CANCELADO: "cancelado"}
        raise HTTPException(
            status_code=409,
            detail=f"Inventário nº {numero} está {rotulos.get(sessao.status, sessao.status.value)} "
                   f"e não aceita novos lançamentos.",
        )
    return sessao


@router.get("/sessoes/{sessao_id}", response_model=InventarioDetalheOut)
def detalhe(sessao_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    sessao = _buscar_sessao(db, sessao_id)
    itens = _montar_itens_out(sessao)
    return InventarioDetalheOut(sessao=sessao, itens=itens, resumo=_resumo(itens))


# ==============================================================================
# ABERTURA
# ==============================================================================
@router.post("/sessoes/abrir", response_model=SessaoInventarioOut, status_code=201)
def abrir_sessao(dados: SessaoInventarioAbrir, db: Session = Depends(get_db),
                 usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
    if not dados.geral and not dados.categoria_ids:
        raise HTTPException(
            status_code=400,
            detail="Selecione ao menos uma família, ou marque o inventário como geral.",
        )

    conflito = _conflito_de_setor(db, dados.unidade_id, dados.geral, dados.categoria_ids)
    if conflito:
        escopo = "geral" if conflito.geral else ", ".join(c.nome for c in conflito.categorias)
        raise HTTPException(
            status_code=409,
            detail=f"Já existe um inventário em andamento cobrindo este setor "
                   f"(nº {conflito.numero_documento} — {escopo}). Finalize ou cancele antes de abrir outro.",
        )

    sessao = SessaoInventario(
        unidade_id=dados.unidade_id,
        numero_documento=_proximo_numero(db, dados.unidade_id),
        descricao=(dados.descricao or "").strip() or None,
        geral=dados.geral,
        observacao=(dados.observacao or "").strip() or None,
        usuario_abertura_id=usuario.id,
        status=StatusSessaoInventario.ABERTO,
    )
    if not dados.geral:
        sessao.categorias = db.query(Categoria).filter(Categoria.id.in_(dados.categoria_ids)).all()

    db.add(sessao)
    db.commit()
    db.refresh(sessao)
    return sessao


# ==============================================================================
# CONGELAMENTO — fotografa o estoque e libera a contagem
# ==============================================================================
@router.post("/sessoes/{sessao_id}/congelar", response_model=InventarioDetalheOut)
def congelar(sessao_id: int, db: Session = Depends(get_db),
             usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
    """Tira a fotografia do estoque de todos os itens do escopo.

    É esse retrato que, no fim, permite comparar o que o sistema dizia com o
    que foi realmente contado. Sem congelar, não há contagem.
    """
    sessao = _buscar_sessao(db, sessao_id)
    if sessao.status != StatusSessaoInventario.ABERTO:
        raise HTTPException(
            status_code=409,
            detail=f"Só é possível congelar um inventário Aberto (este está {sessao.status.value}).",
        )

    produtos = _produtos_do_escopo(db, sessao, usuario.empresa_id)
    if not produtos:
        raise HTTPException(status_code=400, detail="Nenhum produto ativo no escopo deste inventário.")

    ids = [p.id for p in produtos]
    saldos = saldos_por_produto(db, sessao.unidade_id, ids)
    custos = ultimos_custos(db, sessao.unidade_id)

    for p in produtos:
        db.add(InventarioItem(
            sessao_inventario_id=sessao.id,
            produto_id=p.id,
            quantidade_sistema=saldos.get(p.id, 0.0),
            custo_unitario=custos.get(p.id),
        ))

    sessao.status = StatusSessaoInventario.CONGELADO
    sessao.data_congelamento = datetime.utcnow()
    db.commit()
    db.refresh(sessao)

    itens = _montar_itens_out(sessao)
    return InventarioDetalheOut(sessao=sessao, itens=itens, resumo=_resumo(itens))


# ==============================================================================
# CONTAGEM
# ==============================================================================
def _item_para_saida(item: InventarioItem) -> InventarioItemOut:
    p = item.produto
    return InventarioItemOut(
        id=item.id, produto_id=item.produto_id,
        codigo=p.codigo if p else None, produto=p.nome if p else None,
        categoria=p.categoria.nome if (p and p.categoria) else None,
        unidade_medida=p.unidade_medida if p else None,
        quantidade_sistema=item.quantidade_sistema,
        quantidade_contada=item.quantidade_contada,
        custo_unitario=item.custo_unitario,
        divergencia=item.divergencia, valor_divergencia=item.valor_divergencia,
    )


@router.post("/contagem", response_model=ContagemResultado)
def lancar_contagem_flexivel(dados: ContagemLancamento, db: Session = Depends(get_db),
                             usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
    """Registra uma contagem no inventário.

    Aceita identificação flexível (id ou número do inventário; id ou código do
    produto) justamente para servir a outros canais além da tela — o bot do
    Telegram, por exemplo, vai receber "INV 01, código 130001, 12" e chamar
    este mesmo endpoint. Toda a regra vive em servicos/contagem.py.
    """
    try:
        resultado = registrar_contagem(
            db,
            quantidade=dados.quantidade,
            sessao_id=dados.sessao_id,
            numero_inventario=dados.numero_inventario,
            unidade_id=dados.unidade_id,
            produto_id=dados.produto_id,
            codigo_produto=dados.codigo_produto,
            usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
            origem=dados.origem or ORIGEM_WEB,
        )
    except ErroContagem as erro:
        raise HTTPException(status_code=erro.http, detail=erro.mensagem)

    item = resultado.item
    if resultado.primeira_contagem:
        msg = f"Contagem registrada: {resultado.produto.nome} = {item.quantidade_contada}."
    else:
        msg = (f"Contagem corrigida: {resultado.produto.nome} = {item.quantidade_contada} "
               f"(antes era {resultado.valor_anterior}).")

    return ContagemResultado(
        item=_item_para_saida(item),
        numero_inventario=resultado.sessao.numero_documento,
        status_inventario=resultado.sessao.status,
        primeira_contagem=resultado.primeira_contagem,
        valor_anterior=resultado.valor_anterior,
        mensagem=msg,
    )


@router.post("/sessoes/{sessao_id}/contagem", response_model=InventarioItemOut)
def lancar_contagem(sessao_id: int, dados: ContagemItem, db: Session = Depends(get_db),
                    usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE, PapelUsuario.OPERADOR))):
    """Atalho por sessão — mesma regra, usando o serviço compartilhado."""
    try:
        resultado = registrar_contagem(
            db,
            quantidade=dados.quantidade,
            sessao_id=sessao_id,
            produto_id=dados.produto_id,
            usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
            origem=ORIGEM_WEB,
        )
    except ErroContagem as erro:
        raise HTTPException(status_code=erro.http, detail=erro.mensagem)
    return _item_para_saida(resultado.item)


# ==============================================================================
# FINALIZAÇÃO — aplica as contagens ao estoque
# ==============================================================================
@router.post("/sessoes/{sessao_id}/finalizar", response_model=InventarioDetalheOut)
def finalizar(sessao_id: int, db: Session = Depends(get_db),
              usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    """Encerra o inventário e passa as quantidades contadas para o estoque.

    Cada item contado gera um movimento de CONTAGEM_FINAL na data de hoje —
    é isso que faz o estoque do produto passar a valer a quantidade contada.
    Itens não contados ficam como estão (não são zerados), e aparecem no
    relatório como "não contado".
    """
    sessao = _buscar_sessao(db, sessao_id)
    if sessao.status not in (StatusSessaoInventario.CONGELADO, StatusSessaoInventario.EM_CONTAGEM):
        raise HTTPException(
            status_code=409,
            detail=f"Só é possível finalizar um inventário congelado ou em contagem "
                   f"(este está {sessao.status.value}).",
        )

    # Inventário sem nenhuma contagem PODE ser finalizado: nesse caso nada é
    # aplicado e o estoque fica como estava. É um encerramento legítimo —
    # a contagem pode simplesmente não ter sido necessária.
    contados = [i for i in sessao.itens if i.quantidade_contada is not None]

    hoje = date.today()
    for item in contados:
        db.add(Movimento(
            unidade_id=sessao.unidade_id,
            produto_id=item.produto_id,
            tipo=TipoMovimento.CONTAGEM_FINAL,
            quantidade=item.quantidade_contada,
            custo_unitario=item.custo_unitario,
            custo_total=round((item.custo_unitario or 0) * item.quantidade_contada, 4),
            data=hoje,
            sessao_inventario_id=sessao.id,
            numero_documento=f"INV-{sessao.numero_documento}",
            usuario_id=usuario.id,
        ))

    sessao.status = StatusSessaoInventario.FINALIZADO
    sessao.data_fechamento = datetime.utcnow()
    sessao.usuario_fechamento_id = usuario.id
    db.commit()
    db.refresh(sessao)

    itens = _montar_itens_out(sessao)
    return InventarioDetalheOut(sessao=sessao, itens=itens, resumo=_resumo(itens))


# ==============================================================================
# CANCELAMENTO
# ==============================================================================
@router.post("/sessoes/{sessao_id}/cancelar", response_model=SessaoInventarioOut)
def cancelar(sessao_id: int, db: Session = Depends(get_db),
             usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    """Cancela o inventário. Ele continua consultável para análise, e o número
    dele segue consumido (a sequência nunca reaproveita)."""
    sessao = _buscar_sessao(db, sessao_id)
    if sessao.status not in STATUS_ATIVOS:
        raise HTTPException(status_code=409, detail=f"Inventário já está {sessao.status.value}.")

    sessao.status = StatusSessaoInventario.CANCELADO
    sessao.data_fechamento = datetime.utcnow()
    sessao.usuario_fechamento_id = usuario.id
    db.commit()
    db.refresh(sessao)
    return sessao


@router.post("/sessoes/{sessao_id}/status", response_model=SessaoInventarioOut)
def mudar_status(sessao_id: int, novo_status: StatusSessaoInventario, db: Session = Depends(get_db),
                 usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    """Transição manual de status, respeitando o ciclo de vida."""
    sessao = _buscar_sessao(db, sessao_id)
    if novo_status not in TRANSICOES.get(sessao.status, set()):
        raise HTTPException(
            status_code=409,
            detail=f"Não é possível mudar de {sessao.status.value} para {novo_status.value}.",
        )
    sessao.status = novo_status
    if novo_status in (StatusSessaoInventario.FINALIZADO, StatusSessaoInventario.CANCELADO):
        sessao.data_fechamento = datetime.utcnow()
        sessao.usuario_fechamento_id = usuario.id
    db.commit()
    db.refresh(sessao)
    return sessao


# ==============================================================================
# RELATÓRIO PDF
# ==============================================================================
@router.get("/sessoes/{sessao_id}/relatorio.pdf")
def relatorio_pdf(sessao_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    from relatorio_inventario import gerar_pdf_inventario

    sessao = _buscar_sessao(db, sessao_id)
    itens = _montar_itens_out(sessao)
    buffer = gerar_pdf_inventario(sessao, itens, _resumo(itens))

    nome = f"inventario_{sessao.numero_documento}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )


@router.get("/sessoes/{sessao_id}/contagem-cega.pdf")
def folha_contagem_cega(sessao_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Folha A4 para imprimir e contar na mão.

    CONTROLE ANTIFRAUDE: só pode ser emitida enquanto o inventário está
    ABERTO, isto é, antes do congelamento. Depois que o estoque é congelado
    a folha deixa de ser emitida — assim ninguém imprime uma segunda via já
    sabendo o que o sistema registrou, nem gera folha de inventário encerrado.

    Como ainda não existem linhas de inventário nesse momento, a folha é
    montada a partir do escopo (as famílias escolhidas na abertura).
    """
    from folha_contagem import gerar_pdf_contagem_cega

    sessao = _buscar_sessao(db, sessao_id)
    if sessao.status != StatusSessaoInventario.ABERTO:
        rotulos = {
            StatusSessaoInventario.CONGELADO: "congelado",
            StatusSessaoInventario.EM_CONTAGEM: "em contagem",
            StatusSessaoInventario.FINALIZADO: "finalizado",
            StatusSessaoInventario.CANCELADO: "cancelado",
        }
        raise HTTPException(
            status_code=409,
            detail=f"A folha de contagem só pode ser emitida com o inventário aberto, "
                   f"antes do congelamento. O inventário nº {sessao.numero_documento} está "
                   f"{rotulos.get(sessao.status, sessao.status.value)}.",
        )

    produtos = _produtos_do_escopo(db, sessao, usuario.empresa_id)
    if not produtos:
        raise HTTPException(status_code=400, detail="Nenhum produto ativo no escopo deste inventário.")

    # A folha não mostra quantidade nenhuma — só identifica o item
    itens = [
        InventarioItemOut(
            id=0,
            produto_id=p.id,
            codigo=p.codigo,
            produto=p.nome,
            categoria=p.categoria.nome if p.categoria else None,
            unidade_medida=p.unidade_medida,
            quantidade_sistema=0,
        )
        for p in produtos
    ]

    buffer = gerar_pdf_contagem_cega(sessao, itens)
    nome = f"contagem_cega_inventario_{sessao.numero_documento}.pdf"
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )
