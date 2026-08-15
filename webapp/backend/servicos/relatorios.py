"""
Relatórios — os documentos que fecham o período e explicam o número.

QUATRO PERGUNTAS, QUATRO RELATÓRIOS
-----------------------------------
  fechamento  · "como fechou o mês?"        — sucessor da aba RESUMO
  comparativo · "melhorou ou piorou?"       — sucessor da aba Relatório
  curva_abc   · "onde negociar primeiro?"   — os poucos itens que explicam tudo
  familias    · "qual setor está fora?"     — consumo por família contra a meta

Nenhuma fórmula nova mora aqui. Este módulo compõe o que servicos/cmv.py já
calcula e o que servicos/metas.py já resolve. Se o CMV mudar, os quatro
relatórios acompanham sozinhos — que é exatamente o que a planilha não
conseguia fazer, porque cada aba tinha sua própria cópia da conta.

A procedência anda junto do número: todo relatório diz de quais inventários
o estoque saiu. Um CMV sem essa informação é indefensável numa reunião.
"""
from datetime import date as date_type, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models import TipoMeta
from servicos import cmv as motor
from servicos import metas as servico_metas
from servicos import painel as servico_painel

# Faixas da curva ABC, no corte clássico de Pareto
FAIXA_A = 0.80
FAIXA_B = 0.95


def _bloco(bloco) -> dict:
    return {
        "estoque_inicial": round(bloco.estoque_inicial, 2),
        "compras": round(bloco.compras, 2),
        "estoque_final": round(bloco.estoque_final, 2),
        "cmv": round(bloco.cmv, 2),
        "faturamento": round(bloco.faturamento, 2),
        "cmv_percentual": bloco.cmv_percentual,
        "perdas": round(bloco.perdas, 2),
    }


def _cabecalho(periodo: servico_painel.Periodo, unidade_nome: Optional[str]) -> dict:
    return {
        "rotulo": periodo.rotulo,
        "data_inicio": periodo.inicio.isoformat(),
        "data_fim": periodo.fim.isoformat(),
        "inventario_abertura": periodo.inventario_abertura,
        "inventario_fechamento": periodo.inventario_fechamento,
        "encaixado_no_ciclo": periodo.encaixado,
        "sem_ciclo": periodo.sem_ciclo,
        "unidade": unidade_nome,
        "gerado_em": date_type.today().isoformat(),
    }


def _resolver_periodo(db: Session, unidade_id: int, referencia: Optional[str],
                      data_inicio: Optional[date_type], data_fim: Optional[date_type]):
    if data_inicio and data_fim:
        return servico_painel.encaixar_no_ciclo(
            db, unidade_id, data_inicio, data_fim,
            f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    return servico_painel.periodo_mensal(db, unidade_id, referencia)


def _apurar(db: Session, unidade_id: int, periodo, empresa_id: Optional[int]):
    if periodo.sem_ciclo:
        return None
    return motor.apurar(db, unidade_id=unidade_id, data_inicio=periodo.inicio,
                        data_fim=periodo.fim, empresa_id=empresa_id)


def _nome_unidade(db: Session, unidade_id: int) -> Optional[str]:
    from models import Unidade
    unidade = db.query(Unidade).filter(Unidade.id == unidade_id).first()
    return unidade.nome if unidade else None


# ==============================================================================
# 1 · FECHAMENTO DO PERÍODO
# ==============================================================================
def fechamento(db: Session, unidade_id: int, referencia: Optional[str] = None,
               data_inicio: Optional[date_type] = None,
               data_fim: Optional[date_type] = None,
               empresa_id: Optional[int] = None) -> dict:
    """A conta fechada do período, com a memória de cálculo aberta."""
    periodo = _resolver_periodo(db, unidade_id, referencia, data_inicio, data_fim)
    apuracao = _apurar(db, unidade_id, periodo, empresa_id)
    cabecalho = _cabecalho(periodo, _nome_unidade(db, unidade_id))

    if not apuracao:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhum ciclo de inventário fechado delimita o período.",
                "avisos": []}

    meta = apuracao.meta
    percentual = apuracao.geral.cmv_percentual
    desvio = None if percentual is None else round(percentual - meta, 6)

    # Itens sem contagem de fechamento entram com estoque final estimado.
    # Quem lê o relatório precisa saber quanto do número é estimativa.
    estimados = [l for l in apuracao.linhas if l.final_estimado]
    valor_estimado = round(sum(l.valor_final for l in estimados), 2)

    return {
        "cabecalho": cabecalho,
        "disponivel": True,
        "formula": "CMV = Estoque Inicial + Compras − Estoque Final",
        "geral": _bloco(apuracao.geral),
        "comida": _bloco(apuracao.comida),
        "bebida": _bloco(apuracao.bebida),
        "meta": meta,
        "desvio": desvio,
        "dentro_da_meta": None if percentual is None else percentual <= meta,
        "confiabilidade": {
            "itens_apurados": len(apuracao.linhas),
            "itens_estimados": len(estimados),
            "valor_estimado": valor_estimado,
        },
        "avisos": list(apuracao.avisos),
    }


# ==============================================================================
# 2 · COMPARATIVO ENTRE PERÍODOS
# ==============================================================================
def _periodo_anterior(db: Session, unidade_id: int, periodo):
    """O mês imediatamente anterior ao do período exibido, já encaixado."""
    anterior = (periodo.inicio.replace(day=1) - timedelta(days=1)).replace(day=1)
    return servico_painel.periodo_mensal(db, unidade_id, anterior.strftime("%Y-%m"))


def _variacao(atual: Optional[float], anterior: Optional[float],
              percentual: bool = False) -> Optional[float]:
    if atual is None or anterior in (None, 0):
        return None
    if percentual:
        return round(atual - anterior, 6)      # diferença em pontos percentuais
    return round((atual - anterior) / abs(anterior), 6)


def comparativo(db: Session, unidade_id: int, referencia: Optional[str] = None,
                data_inicio: Optional[date_type] = None,
                data_fim: Optional[date_type] = None,
                empresa_id: Optional[int] = None) -> dict:
    """Período atual × anterior × meta, e os itens que mais mudaram."""
    periodo = _resolver_periodo(db, unidade_id, referencia, data_inicio, data_fim)
    anterior = _periodo_anterior(db, unidade_id, periodo)

    atual_ap = _apurar(db, unidade_id, periodo, empresa_id)
    anterior_ap = _apurar(db, unidade_id, anterior, empresa_id)
    cabecalho = _cabecalho(periodo, _nome_unidade(db, unidade_id))
    cabecalho["comparado_com"] = anterior.rotulo

    if not atual_ap:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhum ciclo de inventário fechado delimita o período."}
    if not anterior_ap:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": f"Não há período apurado antes de {periodo.rotulo} "
                          f"para servir de comparação."}

    def linha(rotulo, valor_atual, valor_anterior, formato, menor_e_melhor=True):
        variacao = _variacao(valor_atual, valor_anterior, formato == "PERCENTUAL")
        direcao = None
        if variacao is not None and abs(variacao) > 1e-9:
            direcao = "boa" if ((variacao > 0) != menor_e_melhor) else "ruim"
        return {"rotulo": rotulo, "atual": valor_atual, "anterior": valor_anterior,
                "formato": formato, "variacao": variacao, "direcao": direcao}

    indicadores = [
        linha("CMV %", atual_ap.geral.cmv_percentual,
              anterior_ap.geral.cmv_percentual, "PERCENTUAL"),
        linha("CMV em reais", round(atual_ap.geral.cmv, 2),
              round(anterior_ap.geral.cmv, 2), "MOEDA"),
        linha("Faturamento", round(atual_ap.geral.faturamento, 2),
              round(anterior_ap.geral.faturamento, 2), "MOEDA", menor_e_melhor=False),
        linha("CMV comida %", atual_ap.comida.cmv_percentual,
              anterior_ap.comida.cmv_percentual, "PERCENTUAL"),
        linha("CMV bebida %", atual_ap.bebida.cmv_percentual,
              anterior_ap.bebida.cmv_percentual, "PERCENTUAL"),
        linha("Perdas", round(atual_ap.geral.perdas, 2),
              round(anterior_ap.geral.perdas, 2), "MOEDA"),
    ]

    # Item a item: quem subiu e quem caiu mais em reais
    cmv_atual = {l.produto_id: l for l in atual_ap.linhas}
    cmv_anterior = {l.produto_id: l.cmv for l in anterior_ap.linhas}
    movimentos = []
    for produto_id, linha_atual in cmv_atual.items():
        antes = cmv_anterior.get(produto_id, 0.0)
        delta = linha_atual.cmv - antes
        if abs(delta) < 0.01:
            continue
        movimentos.append({
            "codigo": linha_atual.codigo, "produto": linha_atual.nome,
            "unidade_medida": linha_atual.unidade_medida,
            "atual": round(linha_atual.cmv, 2), "anterior": round(antes, 2),
            "delta": round(delta, 2),
            "delta_percentual": (round(delta / antes, 6) if antes else None),
        })
    movimentos.sort(key=lambda m: m["delta"], reverse=True)

    return {
        "cabecalho": cabecalho,
        "disponivel": True,
        "periodo_anterior": {
            "rotulo": anterior.rotulo,
            "data_inicio": anterior.inicio.isoformat(),
            "data_fim": anterior.fim.isoformat(),
        },
        "meta": atual_ap.meta,
        "meta_anterior": anterior_ap.meta,
        "indicadores": indicadores,
        "pioraram": movimentos[:10],
        "melhoraram": [m for m in reversed(movimentos) if m["delta"] < 0][:10],
        "avisos": list(atual_ap.avisos),
    }


# ==============================================================================
# 3 · CURVA ABC
# ==============================================================================
def curva_abc(db: Session, unidade_id: int, referencia: Optional[str] = None,
              data_inicio: Optional[date_type] = None,
              data_fim: Optional[date_type] = None,
              empresa_id: Optional[int] = None) -> dict:
    """Ordena os itens por custo e marca onde está a maior parte do dinheiro.

    A faixa A concentra 80% do custo. Em restaurante ela costuma caber em
    quinze ou vinte itens — é a lista com que se negocia com fornecedor, e a
    única em que 1% de desconto vira dinheiro perceptível.
    """
    periodo = _resolver_periodo(db, unidade_id, referencia, data_inicio, data_fim)
    apuracao = _apurar(db, unidade_id, periodo, empresa_id)
    cabecalho = _cabecalho(periodo, _nome_unidade(db, unidade_id))

    if not apuracao or not apuracao.geral.cmv:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Sem CMV apurado no período — não há o que ordenar."}

    total = apuracao.geral.cmv
    ordenadas = sorted([l for l in apuracao.linhas if l.cmv > 0],
                       key=lambda l: l.cmv, reverse=True)

    linhas = []
    acumulado = 0.0
    for posicao, l in enumerate(ordenadas, start=1):
        acumulado += l.cmv
        fracao = acumulado / total
        faixa = "A" if fracao <= FAIXA_A else ("B" if fracao <= FAIXA_B else "C")
        linhas.append({
            "posicao": posicao,
            "codigo": l.codigo, "produto": l.nome,
            "unidade_medida": l.unidade_medida,
            "categoria": (l.categoria or "").replace("Família - ", ""),
            "eh_bebida": l.eh_bebida,
            "quantidade": round(l.qtd_consumida, 3),
            "custo_unitario": round(l.custo_final, 4),
            "cmv": round(l.cmv, 2),
            "participacao": round(l.cmv / total, 6),
            "acumulado": round(fracao, 6),
            "faixa": faixa,
        })

    resumo = {}
    for faixa in ("A", "B", "C"):
        da_faixa = [l for l in linhas if l["faixa"] == faixa]
        resumo[faixa] = {
            "itens": len(da_faixa),
            "valor": round(sum(l["cmv"] for l in da_faixa), 2),
            "participacao": round(sum(l["participacao"] for l in da_faixa), 6),
        }

    return {
        "cabecalho": cabecalho,
        "disponivel": True,
        "total_cmv": round(total, 2),
        "total_itens": len(linhas),
        "resumo": resumo,
        "linhas": linhas,
        "avisos": list(apuracao.avisos),
    }


# ==============================================================================
# 4 · CONSUMO POR FAMÍLIA
# ==============================================================================
def por_familia(db: Session, unidade_id: int, referencia: Optional[str] = None,
                data_inicio: Optional[date_type] = None,
                data_fim: Optional[date_type] = None,
                historico: int = 5,
                empresa_id: Optional[int] = None) -> dict:
    """Consumo de cada família contra a meta dela, com evolução no tempo."""
    periodo = _resolver_periodo(db, unidade_id, referencia, data_inicio, data_fim)
    apuracao = _apurar(db, unidade_id, periodo, empresa_id)
    cabecalho = _cabecalho(periodo, _nome_unidade(db, unidade_id))

    if not apuracao:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhum ciclo de inventário fechado delimita o período."}

    from models import ConfiguracaoCMV
    config = db.query(ConfiguracaoCMV).filter(
        ConfiguracaoCMV.unidade_id == unidade_id).first()
    ids_bebida = {c.id for c in config.familias_bebida} if config else set()

    realizado = servico_metas.realizado_por_familia(apuracao)
    custo = {}
    quantidade_itens = {}
    for l in apuracao.linhas:
        if l.categoria_id is None:
            continue
        custo[l.categoria_id] = custo.get(l.categoria_id, 0.0) + l.cmv
        quantidade_itens[l.categoria_id] = quantidade_itens.get(l.categoria_id, 0) + 1

    linhas = []
    for cat in servico_metas.familias(db, empresa_id):
        cmv_familia = custo.get(cat.id)
        if cmv_familia is None:
            continue
        meta = servico_metas.meta_vigente(
            db, unidade_id, TipoMeta.CMV_FAMILIA, periodo.fim,
            categoria_id=cat.id, categoria_eh_bebida=cat.id in ids_bebida)
        percentual = realizado.get(cat.id)
        linhas.append({
            "categoria_id": cat.id,
            "familia": cat.nome.replace("Família - ", ""),
            "eh_bebida": cat.id in ids_bebida,
            "itens": quantidade_itens.get(cat.id, 0),
            "cmv": round(cmv_familia, 2),
            "percentual": percentual,
            "participacao": round(cmv_familia / apuracao.geral.cmv, 6)
            if apuracao.geral.cmv else None,
            "meta": meta.valor,
            "meta_definida": meta.definida,
            "meta_herdada_de": meta.herdada_rotulo,
            "dentro_da_meta": (None if percentual is None or meta.valor is None
                               else percentual <= meta.valor),
        })
    linhas.sort(key=lambda x: x["cmv"], reverse=True)

    # Evolução: mesma família, meses anteriores
    serie = []
    cursor = periodo.inicio.replace(day=1)
    for _ in range(historico):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        anterior = servico_painel.periodo_mensal(db, unidade_id, cursor.strftime("%Y-%m"))
        if anterior.sem_ciclo:
            continue
        ap = motor.apurar(db, unidade_id=unidade_id, data_inicio=anterior.inicio,
                          data_fim=anterior.fim, empresa_id=empresa_id)
        serie.append({
            "rotulo": anterior.rotulo,
            "por_familia": servico_metas.realizado_por_familia(ap),
        })
    serie.reverse()

    return {
        "cabecalho": cabecalho,
        "disponivel": True,
        "total_cmv": round(apuracao.geral.cmv, 2),
        "faturamento": round(apuracao.geral.faturamento, 2),
        "meta_geral": apuracao.meta,
        "linhas": linhas,
        "evolucao": serie,
        "avisos": list(apuracao.avisos),
    }


RELATORIOS = {
    "fechamento": ("Fechamento do período", fechamento),
    "comparativo": ("Comparativo entre períodos", comparativo),
    "curva-abc": ("Curva ABC de itens", curva_abc),
    "familias": ("Consumo por família", por_familia),
}
