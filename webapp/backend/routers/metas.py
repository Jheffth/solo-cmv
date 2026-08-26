"""
Metas — os números que a diretoria define e a operação persegue.

A regra vive em servicos/metas.py; aqui só entra a tradução HTTP e o
cruzamento com o realizado do período, que é o que transforma a definição
de meta num ato informado em vez de um chute.

PERMISSÃO
---------
Ver: qualquer usuário autenticado. Meta escondida não cobra ninguém — o
gerente precisa saber contra o que está sendo medido.
Definir: apenas ARQUITETO e DIRETOR.
"""
from datetime import date as date_type
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Meta, TipoMeta, FormatoMeta, PapelUsuario, PAPEIS_IRRESTRITOS, Categoria,
    ConfiguracaoCMV,
)
from schemas import (
    MetaPainel, MetaLinha, MetaDefinicao, MetaHistoricoItem, MetaDistribuicao,
)
from auth.deps import get_current_user, exigir_papeis, exigir_canal_web
from servicos.permissoes import Capacidade, requer
from servicos import metas as servico
from servicos import cmv as motor_cmv
from servicos.metas import ErroMeta, ROTULOS_TIPO

router = APIRouter(prefix="/metas", tags=["metas"])

PODE_DEFINIR = (PapelUsuario.ARQUITETO, PapelUsuario.DIRETOR)


def _limpar_familia(nome: Optional[str]) -> Optional[str]:
    return nome.replace("Família - ", "") if nome else None


def _mes_corrente() -> tuple:
    hoje = date_type.today()
    inicio = hoje.replace(day=1)
    if hoje.month == 12:
        fim = hoje.replace(year=hoje.year + 1, month=1, day=1)
    else:
        fim = hoje.replace(month=hoje.month + 1, day=1)
    from datetime import timedelta
    return inicio, fim - timedelta(days=1)


def _linha(resolvida, rotulo: str, realizado: Optional[float] = None,
           categoria_id: Optional[int] = None, categoria: Optional[str] = None,
           menor_e_melhor: bool = True) -> MetaLinha:
    atingida = None
    if realizado is not None and resolvida.valor:
        atingida = realizado <= resolvida.valor if menor_e_melhor else realizado >= resolvida.valor
    return MetaLinha(
        tipo=resolvida.tipo, rotulo=rotulo,
        categoria_id=categoria_id, categoria=categoria,
        valor=resolvida.valor, formato=resolvida.formato,
        periodicidade=resolvida.periodicidade,
        vigencia_inicio=resolvida.vigencia_inicio,
        definida=resolvida.definida,
        origem=resolvida.origem, manual=resolvida.manual,
        herdada_de=resolvida.herdada_de, herdada_rotulo=resolvida.herdada_rotulo,
        padrao_do_sistema=resolvida.padrao_do_sistema,
        realizado=realizado, atingida=atingida,
    )


@router.get("/painel", response_model=MetaPainel)
def painel(unidade_id: Optional[int] = None,
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           db: Session = Depends(get_db),
           usuario=Depends(requer(Capacidade.VER_CMV))):
    """Todas as metas vigentes ao lado do que a operação realizou no período."""
    if not data_inicio or not data_fim:
        data_inicio, data_fim = _mes_corrente()

    # Realizado do período, pelo mesmo motor que alimenta o Motor de CMV.
    # Se não houver base para apurar, as metas aparecem sem comparação —
    # melhor sem realizado do que com um realizado inventado.
    apuracao = None
    if unidade_id:
        try:
            apuracao = motor_cmv.apurar(db, unidade_id=unidade_id,
                                        data_inicio=data_inicio, data_fim=data_fim)
        except Exception:
            apuracao = None

    ref = data_fim
    cmv_linhas = [
        _linha(servico.meta_vigente(db, unidade_id, TipoMeta.CMV_GERAL, ref),
               "Geral", apuracao.geral.cmv_percentual if apuracao else None),
        _linha(servico.meta_vigente(db, unidade_id, TipoMeta.CMV_COMIDA, ref),
               "Comida", apuracao.comida.cmv_percentual if apuracao else None),
        _linha(servico.meta_vigente(db, unidade_id, TipoMeta.CMV_BEBIDA, ref),
               "Bebida", apuracao.bebida.cmv_percentual if apuracao else None),
    ]

    # Realizado por família = CMV da família ÷ faturamento TOTAL. É a régua
    # em que as famílias somam exatamente o CMV geral — e por isso a única
    # em que faz sentido repartir a meta geral entre elas (ver servicos/metas).
    realizado_familia = {}
    if apuracao:
        realizado_familia = servico.realizado_por_familia(apuracao)

    ids_bebida = set()
    config = db.query(ConfiguracaoCMV).filter(
        ConfiguracaoCMV.unidade_id == unidade_id).first() if unidade_id else None
    if config:
        ids_bebida = {c.id for c in config.familias_bebida}

    linhas_familia = []
    for cat in servico.familias(db, usuario.empresa_id):
        resolvida = servico.meta_vigente(
            db, unidade_id, TipoMeta.CMV_FAMILIA, ref,
            categoria_id=cat.id, categoria_eh_bebida=cat.id in ids_bebida)
        linhas_familia.append(_linha(
            resolvida, _limpar_familia(cat.nome) or "—",
            realizado_familia.get(cat.id),
            categoria_id=cat.id, categoria=_limpar_familia(cat.nome)))

    # Perdas: percentual do CMV do período
    perdas_realizado = apuracao.geral.perdas_sobre_cmv if apuracao else None
    linha_perdas = _linha(
        servico.meta_vigente(db, unidade_id, TipoMeta.PERDAS, ref),
        "Perdas", perdas_realizado)

    # Faturamento: aqui, mais é melhor
    linha_faturamento = _linha(
        servico.meta_vigente(db, unidade_id, TipoMeta.FATURAMENTO, ref),
        "Faturamento",
        apuracao.geral.faturamento if apuracao else None,
        menor_e_melhor=False)

    aviso = servico.checar_coerencia(
        cmv_linhas[0].valor, cmv_linhas[1].valor, cmv_linhas[2].valor,
        apuracao.comida.faturamento if apuracao else 0,
        apuracao.bebida.faturamento if apuracao else 0,
    )

    return MetaPainel(
        unidade_id=unidade_id,
        periodo_rotulo=f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}",
        data_inicio=data_inicio, data_fim=data_fim,
        cmv=cmv_linhas, familias=linhas_familia,
        perdas=linha_perdas, faturamento=linha_faturamento,
        aviso_coerencia=aviso,
        pode_editar=usuario.papel in PODE_DEFINIR,
    )


@router.post("", response_model=MetaHistoricoItem, status_code=201,
             dependencies=[Depends(exigir_canal_web)])
def definir(dados: MetaDefinicao, db: Session = Depends(get_db),
            usuario=Depends(requer(Capacidade.DEFINIR_META))):
    """Abre uma vigência nova. A anterior é fechada, nunca apagada."""
    if usuario.papel not in PODE_DEFINIR:
        raise HTTPException(403, "Apenas Diretor e Arquiteto definem metas.")
    try:
        meta = servico.definir(
            db, unidade_id=dados.unidade_id, tipo=dados.tipo, valor=dados.valor,
            vigencia_inicio=dados.vigencia_inicio, categoria_id=dados.categoria_id,
            formato=dados.formato, periodicidade=dados.periodicidade,
            observacao=dados.observacao, usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
        )
    except ErroMeta as erro:
        raise HTTPException(erro.http, erro.mensagem)
    return _historico_item(meta)


def _apuracao_de_referencia(db, unidade_id, data_inicio, data_fim, empresa_id):
    if not unidade_id:
        raise HTTPException(400, "A distribuição precisa de uma unidade.")
    if not data_inicio or not data_fim:
        data_inicio, data_fim = _mes_corrente()
    try:
        return motor_cmv.apurar(db, unidade_id=unidade_id, data_inicio=data_inicio,
                                data_fim=data_fim, empresa_id=empresa_id)
    except Exception as erro:
        raise HTTPException(409, f"Não foi possível apurar o período de referência: {erro}")


@router.get("/previa-distribuicao")
def previa_distribuicao(meta_geral: float,
                        unidade_id: Optional[int] = None,
                        data_inicio: Optional[date_type] = None,
                        data_fim: Optional[date_type] = None,
                        preservar_definidas: bool = True,
                        db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    """Mostra como a meta geral se repartiria, sem gravar nada."""
    if meta_geral <= 0 or meta_geral >= 1:
        raise HTTPException(400, "Meta geral deve ficar entre 0 e 1 (ex.: 0.29).")
    apuracao = _apuracao_de_referencia(db, unidade_id, data_inicio, data_fim,
                                       usuario.empresa_id)
    previa = servico.previa_distribuicao(db, apuracao, meta_geral, unidade_id,
                                         preservar_definidas)
    previa["periodo"] = {
        "data_inicio": (data_inicio or _mes_corrente()[0]).isoformat(),
        "data_fim": (data_fim or _mes_corrente()[1]).isoformat(),
        "cmv_apurado": round(apuracao.geral.cmv, 2),
        "faturamento": round(apuracao.geral.faturamento, 2),
    }
    return previa


@router.post("/distribuir", dependencies=[Depends(exigir_canal_web)])
def distribuir(dados: MetaDistribuicao, db: Session = Depends(get_db),
               usuario=Depends(requer(Capacidade.DEFINIR_META))):
    """Define a meta geral e reparte entre as famílias, proporcional ao custo."""
    if dados.meta_geral <= 0 or dados.meta_geral >= 1:
        raise HTTPException(400, "Meta geral deve ficar entre 0 e 1 (ex.: 0.29).")
    apuracao = _apuracao_de_referencia(db, dados.unidade_id, dados.data_inicio,
                                       dados.data_fim, usuario.empresa_id)
    try:
        return servico.distribuir(
            db, unidade_id=dados.unidade_id, apuracao=apuracao,
            meta_geral=dados.meta_geral, vigencia_inicio=dados.vigencia_inicio,
            preservar_definidas=dados.preservar_definidas,
            incluir_blocos=dados.incluir_blocos,
            observacao=dados.observacao, usuario_id=usuario.id,
            empresa_id=usuario.empresa_id,
        )
    except ErroMeta as erro:
        raise HTTPException(erro.http, erro.mensagem)


@router.get("/historico", response_model=List[MetaHistoricoItem])
def historico(unidade_id: Optional[int] = None, limite: int = Query(100, le=500),
              db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    return [_historico_item(m) for m in servico.historico(db, unidade_id, limite)]


def _historico_item(meta: Meta) -> MetaHistoricoItem:
    return MetaHistoricoItem(
        id=meta.id, tipo=meta.tipo, rotulo=ROTULOS_TIPO.get(meta.tipo, meta.tipo.value),
        categoria=_limpar_familia(meta.categoria.nome) if meta.categoria else None,
        valor=meta.valor, formato=meta.formato,
        vigencia_inicio=meta.vigencia_inicio, vigencia_fim=meta.vigencia_fim,
        observacao=meta.observacao,
        usuario=meta.usuario.nome if meta.usuario else None,
        criado_em=meta.criado_em,
    )
