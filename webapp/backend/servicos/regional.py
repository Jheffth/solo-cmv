"""
Regional — a rede inteira num número só.

TRÊS ARMADILHAS, E COMO CADA UMA É EVITADA
------------------------------------------

1. PERCENTUAL NÃO SE SOMA NEM SE TIRA MÉDIA.
   Uma loja com CMV 28% faturando R$ 500 mil e outra com 40% faturando
   R$ 50 mil não dão 34%. Dão:

       (0,28 × 500.000 + 0,40 × 50.000) ÷ 550.000 = 29,1%

   A média simples inflaria o número da rede em 5 pontos — e num painel de
   diretoria isso é a diferença entre "está tudo bem" e uma reunião de
   emergência. Aqui só se somam GRANDEZAS ABSOLUTAS (CMV em reais,
   faturamento em reais); o percentual é sempre recalculado no fim.

2. CADA UNIDADE TEM SEU PRÓPRIO CICLO DE INVENTÁRIO.
   Josefina fecha inventário dia 3 e dia 10; Casa Josefina pode fechar dia
   5 e dia 12. Não existe "o inventário da rede". Então cada unidade é
   apurada no ciclo DELA, e a Regional soma os resultados. O cabeçalho diz
   isso explicitamente, com o par de inventários usado em cada loja.

3. UNIDADE SEM CICLO FECHADO SUMIRIA EM SILÊNCIO.
   Se Casa Josefina não fechou inventário em agosto, ela contribuiria com
   zero e a Regional apareceria menor do que é — sem ninguém perceber. Por
   isso toda resposta traz `cobertura`: quantas unidades entraram, quais
   ficaram de fora e por quê. Número incompleto é aceitável; número
   incompleto disfarçado, não.
"""
from dataclasses import dataclass, field
from datetime import date as date_type
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models import Movimento, TipoMovimento, Produto, Unidade, TipoMeta, MotivoPerda
from calculo_estoque import saldos_por_produto, ultimos_custos
from servicos import cmv as motor
from servicos import metas as servico_metas
from servicos import painel as servico_painel
from servicos.perda import ROTULOS_MOTIVO


@dataclass
class ApuracaoDaUnidade:
    """O resultado de uma loja, com a memória do ciclo que a delimitou."""
    unidade_id: int
    unidade: str
    periodo: object                      # servico_painel.Periodo
    resultado: object = None             # motor.ResultadoCMV, ou None
    erro: Optional[str] = None

    @property
    def entrou(self) -> bool:
        return self.resultado is not None


@dataclass
class Consolidado:
    estoque_inicial: float = 0.0
    compras: float = 0.0
    estoque_final: float = 0.0
    faturamento: float = 0.0
    perdas: float = 0.0

    @property
    def cmv(self) -> float:
        return round(self.estoque_inicial + self.compras - self.estoque_final, 2)

    @property
    def cmv_percentual(self) -> Optional[float]:
        """Recalculado sobre os totais — nunca a média dos percentuais."""
        if not self.faturamento:
            return None
        return round(self.cmv / self.faturamento, 6)

    @property
    def perdas_sobre_cmv(self) -> Optional[float]:
        return round(self.perdas / self.cmv, 6) if self.cmv else None

    def somar(self, bloco) -> None:
        self.estoque_inicial += bloco.estoque_inicial
        self.compras += bloco.compras
        self.estoque_final += bloco.estoque_final
        self.faturamento += bloco.faturamento
        self.perdas += bloco.perdas

    def dict(self) -> dict:
        return {
            "estoque_inicial": round(self.estoque_inicial, 2),
            "compras": round(self.compras, 2),
            "estoque_final": round(self.estoque_final, 2),
            "cmv": self.cmv,
            "faturamento": round(self.faturamento, 2),
            "perdas": round(self.perdas, 2),
            "cmv_percentual": self.cmv_percentual,
        }


# ==============================================================================
# APURAÇÃO
# ==============================================================================
def apurar_unidades(db: Session, unidades: List[Unidade],
                    referencia: Optional[str] = None,
                    data_inicio: Optional[date_type] = None,
                    data_fim: Optional[date_type] = None,
                    empresa_id: Optional[int] = None,
                    incluir_linhas: bool = True) -> List[ApuracaoDaUnidade]:
    """Apura cada unidade no ciclo de inventário dela."""
    saida = []
    for unidade in unidades:
        if data_inicio and data_fim:
            periodo = servico_painel.encaixar_no_ciclo(
                db, unidade.id, data_inicio, data_fim,
                f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
        else:
            periodo = servico_painel.periodo_mensal(db, unidade.id, referencia)

        item = ApuracaoDaUnidade(unidade_id=unidade.id, unidade=unidade.nome,
                                 periodo=periodo)
        if periodo.sem_ciclo:
            item.erro = "sem ciclo de inventário fechado no período"
        else:
            try:
                item.resultado = motor.apurar(
                    db, unidade_id=unidade.id, data_inicio=periodo.inicio,
                    data_fim=periodo.fim, empresa_id=empresa_id,
                    incluir_linhas=incluir_linhas)
            except Exception as erro:                     # pragma: no cover
                item.erro = str(erro)
        saida.append(item)
    return saida


def _cobertura(apuracoes: List[ApuracaoDaUnidade]) -> dict:
    """Quem entrou na soma e quem ficou de fora — sempre explícito."""
    dentro = [a for a in apuracoes if a.entrou]
    fora = [a for a in apuracoes if not a.entrou]
    return {
        "unidades_totais": len(apuracoes),
        "unidades_apuradas": len(dentro),
        "completa": not fora,
        "dentro": [{
            "unidade_id": a.unidade_id, "unidade": a.unidade,
            "data_inicio": a.periodo.inicio.isoformat(),
            "data_fim": a.periodo.fim.isoformat(),
            "inventario_abertura": a.periodo.inventario_abertura,
            "inventario_fechamento": a.periodo.inventario_fechamento,
        } for a in dentro],
        "fora": [{"unidade_id": a.unidade_id, "unidade": a.unidade,
                  "motivo": a.erro} for a in fora],
    }


def _meta_regional(db: Session, apuracoes: List[ApuracaoDaUnidade],
                   em: date_type) -> dict:
    """A meta da rede.

    Se a diretoria definiu uma meta sem unidade (`unidade_id` nulo), ela
    vale para a rede inteira. Senão, a meta regional é a média das metas
    das lojas PONDERADA PELO FATURAMENTO — pelo mesmo motivo do CMV: uma
    loja pequena não pode puxar o alvo da rede tanto quanto uma grande.
    """
    da_rede = servico_metas.meta_vigente(db, None, TipoMeta.CMV_GERAL, em)
    if da_rede.definida:
        return {"valor": da_rede.valor, "origem": "REDE",
                "explicacao": "Meta definida para a rede inteira."}

    peso_total = 0.0
    acumulado = 0.0
    for a in apuracoes:
        if not a.entrou:
            continue
        faturamento = a.resultado.geral.faturamento or 0
        if faturamento <= 0:
            continue
        acumulado += a.resultado.meta * faturamento
        peso_total += faturamento

    if not peso_total:
        return {"valor": servico_metas.META_CMV_PADRAO, "origem": "PADRAO",
                "explicacao": "Sem faturamento no período; usando o padrão do sistema."}

    return {
        "valor": round(acumulado / peso_total, 6),
        "origem": "PONDERADA",
        "explicacao": "Média das metas das unidades, ponderada pelo faturamento "
                      "de cada uma — uma loja pequena não puxa o alvo da rede "
                      "tanto quanto uma grande.",
    }


# ==============================================================================
# PAINEL REGIONAL
# ==============================================================================
def painel(db: Session, unidades: List[Unidade], referencia: Optional[str] = None,
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           historico: int = 5, empresa_id: Optional[int] = None) -> dict:
    apuracoes = apurar_unidades(db, unidades, referencia, data_inicio, data_fim,
                                empresa_id)
    rotulo = next((a.periodo.rotulo for a in apuracoes), "—")
    referencia_data = next((a.periodo.fim for a in apuracoes), date_type.today())

    geral, comida, bebida = Consolidado(), Consolidado(), Consolidado()
    for a in apuracoes:
        if not a.entrou:
            continue
        geral.somar(a.resultado.geral)
        comida.somar(a.resultado.comida)
        bebida.somar(a.resultado.bebida)

    meta = _meta_regional(db, apuracoes, referencia_data)

    # Quadro por unidade — a Regional precisa mostrar quem puxa para cima
    por_unidade = []
    for a in apuracoes:
        linha = {
            "unidade_id": a.unidade_id, "unidade": a.unidade,
            "entrou": a.entrou, "motivo": a.erro,
            "periodo": a.periodo.rotulo,
            "inventarios": (f"INV-{a.periodo.inventario_abertura or '—'} → "
                            f"INV-{a.periodo.inventario_fechamento or '—'}")
            if a.entrou else None,
        }
        if a.entrou:
            r = a.resultado
            linha.update({
                "cmv": round(r.geral.cmv, 2),
                "cmv_percentual": r.geral.cmv_percentual,
                "faturamento": round(r.geral.faturamento, 2),
                "perdas": round(r.geral.perdas, 2),
                "meta": r.meta,
                "dentro_da_meta": (None if r.geral.cmv_percentual is None
                                   else r.geral.cmv_percentual <= r.meta),
                "participacao_faturamento": (round(r.geral.faturamento / geral.faturamento, 6)
                                             if geral.faturamento else None),
                "participacao_cmv": (round(r.geral.cmv / geral.cmv, 6)
                                     if geral.cmv else None),
            })
        por_unidade.append(linha)
    por_unidade.sort(key=lambda x: (not x["entrou"], -(x.get("faturamento") or 0)))

    # Série histórica: mesma consolidação, meses anteriores
    serie = []
    from datetime import timedelta
    cursor = (next((a.periodo.inicio for a in apuracoes), date_type.today())
              .replace(day=1))
    for _ in range(historico):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        anteriores = apurar_unidades(db, unidades, cursor.strftime("%Y-%m"),
                                     empresa_id=empresa_id, incluir_linhas=False)
        bloco = Consolidado()
        entraram = 0
        for a in anteriores:
            if a.entrou:
                bloco.somar(a.resultado.geral)
                entraram += 1
        if not entraram:
            continue
        serie.append({
            "rotulo": (anteriores[0].periodo.rotulo.split("/")[0][:3]
                       if anteriores else "—"),
            "cmv_percentual": bloco.cmv_percentual,
            "cmv": bloco.cmv,
            "faturamento": round(bloco.faturamento, 2),
            "perdas": round(bloco.perdas, 2),
            "meta": _meta_regional(db, anteriores, cursor)["valor"],
            "unidades_apuradas": entraram,
        })
    serie.reverse()

    estoque = estoque_consolidado(db, [u.id for u in unidades])
    perdas = perdas_consolidadas(db, [u.id for u in unidades],
                                 next((a.periodo.inicio for a in apuracoes), None),
                                 next((a.periodo.fim for a in apuracoes), None))
    top = top_itens(apuracoes, geral.cmv)

    avisos = []
    cobertura = _cobertura(apuracoes)
    if not cobertura["completa"]:
        nomes = ", ".join(f["unidade"] for f in cobertura["fora"])
        avisos.append(
            f"{len(cobertura['fora'])} de {cobertura['unidades_totais']} unidades ficaram "
            f"fora da consolidação ({nomes}) — os totais da rede estão incompletos.")
    for a in apuracoes:
        if a.entrou:
            for aviso in a.resultado.avisos:
                avisos.append(f"{a.unidade}: {aviso}")

    return {
        "regional": True,
        "periodo": {
            "rotulo": rotulo,
            "data_inicio": min((a.periodo.inicio for a in apuracoes),
                               default=date_type.today()).isoformat(),
            "data_fim": max((a.periodo.fim for a in apuracoes),
                            default=date_type.today()).isoformat(),
            "por_unidade": True,
            "explicacao": "Cada unidade foi apurada no próprio ciclo de inventário; "
                          "a Regional soma os resultados.",
        },
        "cobertura": cobertura,
        "meta": meta,
        "geral": geral.dict(),
        "comida": comida.dict(),
        "bebida": bebida.dict(),
        "por_unidade": por_unidade,
        "historico": serie,
        "estoque": estoque,
        "perdas": perdas,
        "top_itens": top,
        "avisos": avisos,
    }


# ==============================================================================
# ESTOQUE E PERDAS CONSOLIDADOS
# ==============================================================================
def estoque_consolidado(db: Session, unidade_ids: List[int]) -> dict:
    """Estoque da rede: quantidade soma, valor soma, e o detalhe por loja.

    Diferente do CMV, aqui não há ciclo envolvido — o saldo é uma posição
    de agora, e posição de agora se soma sem ressalva.
    """
    produtos = {p.id: p for p in db.query(Produto).all()}
    total_valor = 0.0
    com_saldo = set()
    sem_custo = set()
    por_unidade = []
    por_produto: Dict[int, dict] = {}

    for unidade_id in unidade_ids:
        saldos = saldos_por_produto(db, unidade_id)
        custos = ultimos_custos(db, unidade_id)
        valor_unidade = 0.0
        itens_unidade = 0
        for produto_id, saldo in saldos.items():
            custo = custos.get(produto_id)
            if custo is None:
                sem_custo.add((unidade_id, produto_id))
            if not saldo or saldo <= 0:
                continue
            valor = saldo * (custo or 0)
            valor_unidade += valor
            itens_unidade += 1
            com_saldo.add(produto_id)

            produto = produtos.get(produto_id)
            alvo = por_produto.setdefault(produto_id, {
                "produto_id": produto_id,
                "codigo": produto.codigo if produto else None,
                "produto": produto.nome if produto else f"#{produto_id}",
                "unidade_medida": produto.unidade_medida if produto else None,
                "quantidade": 0.0, "valor": 0.0, "unidades": 0,
            })
            alvo["quantidade"] += saldo
            alvo["valor"] += valor
            alvo["unidades"] += 1

        unidade = db.query(Unidade).filter(Unidade.id == unidade_id).first()
        por_unidade.append({
            "unidade_id": unidade_id,
            "unidade": unidade.nome if unidade else f"#{unidade_id}",
            "valor": round(valor_unidade, 2),
            "itens_com_saldo": itens_unidade,
        })
        total_valor += valor_unidade

    itens = sorted(por_produto.values(), key=lambda x: x["valor"], reverse=True)
    for i in itens:
        i["quantidade"] = round(i["quantidade"], 3)
        i["valor"] = round(i["valor"], 2)

    return {
        "valor_total": round(total_valor, 2),
        "total_itens": len(produtos),
        "itens_com_saldo": len(com_saldo),
        "itens_sem_custo": len(sem_custo),
        "por_unidade": sorted(por_unidade, key=lambda x: -x["valor"]),
        "itens": itens[:50],
    }


def perdas_consolidadas(db: Session, unidade_ids: List[int],
                        inicio: Optional[date_type],
                        fim: Optional[date_type]) -> dict:
    if not inicio or not fim:
        return {"valor_total": 0.0, "por_motivo": [], "por_unidade": []}

    query = db.query(Movimento).filter(
        Movimento.tipo == TipoMovimento.PERDA,
        Movimento.unidade_id.in_(unidade_ids),
        Movimento.data >= inicio, Movimento.data <= fim)

    nomes = {u.id: u.nome for u in db.query(Unidade).all()}
    por_motivo: Dict[str, dict] = {}
    por_unidade: Dict[int, dict] = {}
    for m in query.all():
        motivo = m.motivo or MotivoPerda.OUTRO
        alvo = por_motivo.setdefault(motivo.value, {
            "motivo": motivo.value, "rotulo": ROTULOS_MOTIVO.get(motivo, "Outro"),
            "ocorrencias": 0, "valor": 0.0})
        alvo["ocorrencias"] += 1
        alvo["valor"] += m.custo_total or 0

        loja = por_unidade.setdefault(m.unidade_id, {
            "unidade_id": m.unidade_id,
            "unidade": nomes.get(m.unidade_id, f"#{m.unidade_id}"),
            "ocorrencias": 0, "valor": 0.0})
        loja["ocorrencias"] += 1
        loja["valor"] += m.custo_total or 0

    for grupo in (por_motivo, por_unidade):
        for item in grupo.values():
            item["valor"] = round(item["valor"], 2)

    return {
        "valor_total": round(sum(i["valor"] for i in por_motivo.values()), 2),
        "por_motivo": sorted(por_motivo.values(), key=lambda x: -x["valor"]),
        "por_unidade": sorted(por_unidade.values(), key=lambda x: -x["valor"]),
    }


def top_itens(apuracoes: List[ApuracaoDaUnidade], cmv_total: float,
              limite: int = 10) -> List[dict]:
    """Itens que mais custam na rede — o mesmo produto somado entre lojas.

    O catálogo é da empresa, então o produto tem o mesmo id nas duas
    unidades e a soma por produto é direta.
    """
    acumulado: Dict[int, dict] = {}
    for a in apuracoes:
        if not a.entrou:
            continue
        for linha in a.resultado.linhas:
            if linha.cmv <= 0:
                continue
            alvo = acumulado.setdefault(linha.produto_id, {
                "codigo": linha.codigo, "produto": linha.nome,
                "unidade_medida": linha.unidade_medida,
                "categoria": (linha.categoria or "").replace("Família - ", ""),
                "eh_bebida": linha.eh_bebida,
                "cmv": 0.0, "unidades": 0,
            })
            alvo["cmv"] += linha.cmv
            alvo["unidades"] += 1

    itens = sorted(acumulado.values(), key=lambda x: x["cmv"], reverse=True)[:limite]
    for i in itens:
        i["cmv"] = round(i["cmv"], 2)
        i["participacao"] = round(i["cmv"] / cmv_total, 6) if cmv_total else None
    return itens


# ==============================================================================
# RELATÓRIOS REGIONAIS
# ==============================================================================
def fechamento(db: Session, unidades: List[Unidade], referencia: Optional[str] = None,
               data_inicio: Optional[date_type] = None,
               data_fim: Optional[date_type] = None,
               empresa_id: Optional[int] = None) -> dict:
    apuracoes = apurar_unidades(db, unidades, referencia, data_inicio, data_fim,
                                empresa_id)
    dentro = [a for a in apuracoes if a.entrou]
    cobertura = _cobertura(apuracoes)
    rotulo = next((a.periodo.rotulo for a in apuracoes), "—")
    cabecalho = {
        "rotulo": rotulo, "unidade": "Regional",
        "regional": True,
        "data_inicio": min((a.periodo.inicio for a in apuracoes),
                           default=date_type.today()).isoformat(),
        "data_fim": max((a.periodo.fim for a in apuracoes),
                        default=date_type.today()).isoformat(),
        "inventario_abertura": None, "inventario_fechamento": None,
        "encaixado_no_ciclo": True, "sem_ciclo": not dentro,
        "gerado_em": date_type.today().isoformat(),
        "cobertura": cobertura,
    }

    if not dentro:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhuma unidade tem ciclo de inventário fechado no período.",
                "avisos": []}

    geral, comida, bebida = Consolidado(), Consolidado(), Consolidado()
    estimados = 0
    valor_estimado = 0.0
    itens = 0
    for a in dentro:
        geral.somar(a.resultado.geral)
        comida.somar(a.resultado.comida)
        bebida.somar(a.resultado.bebida)
        itens += len(a.resultado.linhas)
        for linha in a.resultado.linhas:
            if linha.final_estimado:
                estimados += 1
                valor_estimado += linha.valor_final

    referencia_data = max(a.periodo.fim for a in dentro)
    meta = _meta_regional(db, apuracoes, referencia_data)
    percentual = geral.cmv_percentual

    avisos = list(_avisos_cobertura(cobertura))
    for a in dentro:
        for aviso in a.resultado.avisos:
            avisos.append(f"{a.unidade}: {aviso}")

    return {
        "cabecalho": cabecalho,
        "disponivel": True,
        "regional": True,
        "formula": "CMV = Estoque Inicial + Compras − Estoque Final "
                   "· percentual recalculado sobre os totais da rede",
        "geral": geral.dict(), "comida": comida.dict(), "bebida": bebida.dict(),
        "meta": meta["valor"], "meta_origem": meta["origem"],
        "meta_explicacao": meta["explicacao"],
        "desvio": None if percentual is None else round(percentual - meta["valor"], 6),
        "dentro_da_meta": None if percentual is None else percentual <= meta["valor"],
        "confiabilidade": {"itens_apurados": itens, "itens_estimados": estimados,
                           "valor_estimado": round(valor_estimado, 2)},
        "por_unidade": [{
            "unidade": a.unidade,
            "inventarios": (f"INV-{a.periodo.inventario_abertura or '—'} → "
                            f"INV-{a.periodo.inventario_fechamento or '—'}"),
            "estoque_inicial": round(a.resultado.geral.estoque_inicial, 2),
            "compras": round(a.resultado.geral.compras, 2),
            "estoque_final": round(a.resultado.geral.estoque_final, 2),
            "cmv": round(a.resultado.geral.cmv, 2),
            "faturamento": round(a.resultado.geral.faturamento, 2),
            "cmv_percentual": a.resultado.geral.cmv_percentual,
            "meta": a.resultado.meta,
        } for a in dentro],
        "cobertura": cobertura,
        "avisos": avisos,
    }


def _avisos_cobertura(cobertura: dict) -> List[str]:
    if cobertura["completa"]:
        return []
    nomes = ", ".join(f["unidade"] for f in cobertura["fora"])
    return [f"{len(cobertura['fora'])} de {cobertura['unidades_totais']} unidades "
            f"ficaram fora da consolidação ({nomes}) — os totais estão incompletos."]


def curva_abc(db: Session, unidades: List[Unidade], referencia: Optional[str] = None,
              data_inicio: Optional[date_type] = None,
              data_fim: Optional[date_type] = None,
              empresa_id: Optional[int] = None) -> dict:
    """Curva ABC da rede: o mesmo produto somado entre as lojas."""
    apuracoes = apurar_unidades(db, unidades, referencia, data_inicio, data_fim,
                                empresa_id)
    dentro = [a for a in apuracoes if a.entrou]
    cobertura = _cobertura(apuracoes)
    rotulo = next((a.periodo.rotulo for a in apuracoes), "—")
    cabecalho = {
        "rotulo": rotulo, "unidade": "Regional", "regional": True,
        "data_inicio": min((a.periodo.inicio for a in apuracoes),
                           default=date_type.today()).isoformat(),
        "data_fim": max((a.periodo.fim for a in apuracoes),
                        default=date_type.today()).isoformat(),
        "inventario_abertura": None, "inventario_fechamento": None,
        "encaixado_no_ciclo": True, "sem_ciclo": not dentro,
        "gerado_em": date_type.today().isoformat(), "cobertura": cobertura,
    }
    if not dentro:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhuma unidade tem ciclo de inventário fechado no período."}

    acumulado: Dict[int, dict] = {}
    total = 0.0
    for a in dentro:
        for linha in a.resultado.linhas:
            if linha.cmv <= 0:
                continue
            alvo = acumulado.setdefault(linha.produto_id, {
                "codigo": linha.codigo, "produto": linha.nome,
                "unidade_medida": linha.unidade_medida,
                "categoria": (linha.categoria or "").replace("Família - ", ""),
                "eh_bebida": linha.eh_bebida,
                "quantidade": 0.0, "cmv": 0.0, "unidades": 0,
            })
            alvo["quantidade"] += linha.qtd_consumida
            alvo["cmv"] += linha.cmv
            alvo["unidades"] += 1
            total += linha.cmv

    ordenadas = sorted(acumulado.values(), key=lambda x: x["cmv"], reverse=True)
    linhas = []
    corrente = 0.0
    for posicao, item in enumerate(ordenadas, start=1):
        corrente += item["cmv"]
        fracao = corrente / total if total else 0
        faixa = "A" if fracao <= 0.80 else ("B" if fracao <= 0.95 else "C")
        linhas.append({
            "posicao": posicao, **item,
            "quantidade": round(item["quantidade"], 3),
            "cmv": round(item["cmv"], 2),
            "custo_unitario": (round(item["cmv"] / item["quantidade"], 4)
                               if item["quantidade"] else None),
            "participacao": round(item["cmv"] / total, 6) if total else 0,
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
        "cabecalho": cabecalho, "disponivel": True, "regional": True,
        "total_cmv": round(total, 2), "total_itens": len(linhas),
        "resumo": resumo, "linhas": linhas,
        "cobertura": cobertura,
        "avisos": _avisos_cobertura(cobertura),
    }


def comparativo(db: Session, unidades: List[Unidade], referencia: Optional[str] = None,
                data_inicio: Optional[date_type] = None,
                data_fim: Optional[date_type] = None,
                empresa_id: Optional[int] = None) -> dict:
    """Rede no período atual contra o anterior, e cada loja lado a lado."""
    from datetime import timedelta

    atual = fechamento(db, unidades, referencia, data_inicio, data_fim, empresa_id)
    cabecalho = dict(atual["cabecalho"])

    base = date_type.fromisoformat(cabecalho["data_inicio"]).replace(day=1)
    anterior_ref = (base - timedelta(days=1)).strftime("%Y-%m")
    anterior = fechamento(db, unidades, anterior_ref, None, None, empresa_id)
    cabecalho["comparado_com"] = anterior["cabecalho"]["rotulo"]

    if not atual.get("disponivel"):
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": atual.get("motivo")}
    if not anterior.get("disponivel"):
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": f"Não há período apurado antes de {cabecalho['rotulo']} "
                          f"para servir de comparação."}

    def indicador(rotulo, a, b, formato, menor_e_melhor=True):
        if a is None or b in (None, 0):
            variacao = None
        elif formato == "PERCENTUAL":
            variacao = round(a - b, 6)
        else:
            variacao = round((a - b) / abs(b), 6)
        direcao = None
        if variacao is not None and abs(variacao) > 1e-9:
            direcao = "boa" if ((variacao > 0) != menor_e_melhor) else "ruim"
        return {"rotulo": rotulo, "atual": a, "anterior": b, "formato": formato,
                "variacao": variacao, "direcao": direcao}

    ga, gb = atual["geral"], anterior["geral"]
    indicadores = [
        indicador("CMV %", ga["cmv_percentual"], gb["cmv_percentual"], "PERCENTUAL"),
        indicador("CMV em reais", ga["cmv"], gb["cmv"], "MOEDA"),
        indicador("Faturamento", ga["faturamento"], gb["faturamento"], "MOEDA", False),
        indicador("CMV comida %", atual["comida"]["cmv_percentual"],
                  anterior["comida"]["cmv_percentual"], "PERCENTUAL"),
        indicador("CMV bebida %", atual["bebida"]["cmv_percentual"],
                  anterior["bebida"]["cmv_percentual"], "PERCENTUAL"),
        indicador("Perdas", ga["perdas"], gb["perdas"], "MOEDA"),
    ]

    antes = {u["unidade"]: u for u in anterior["por_unidade"]}
    por_unidade = []
    for u in atual["por_unidade"]:
        b = antes.get(u["unidade"])
        por_unidade.append({
            "unidade": u["unidade"],
            "atual": u["cmv_percentual"], "anterior": b["cmv_percentual"] if b else None,
            "variacao": (round(u["cmv_percentual"] - b["cmv_percentual"], 6)
                         if b and u["cmv_percentual"] is not None
                         and b["cmv_percentual"] is not None else None),
            "cmv": u["cmv"], "faturamento": u["faturamento"], "meta": u["meta"],
        })

    return {
        "cabecalho": cabecalho, "disponivel": True, "regional": True,
        "periodo_anterior": {"rotulo": anterior["cabecalho"]["rotulo"],
                             "data_inicio": anterior["cabecalho"]["data_inicio"],
                             "data_fim": anterior["cabecalho"]["data_fim"]},
        "meta": atual["meta"], "meta_anterior": anterior["meta"],
        "indicadores": indicadores,
        "por_unidade": por_unidade,
        "pioraram": [], "melhoraram": [],
        "cobertura": atual["cobertura"],
        "avisos": atual["avisos"],
    }


def por_familia(db: Session, unidades: List[Unidade], referencia: Optional[str] = None,
                data_inicio: Optional[date_type] = None,
                data_fim: Optional[date_type] = None,
                empresa_id: Optional[int] = None) -> dict:
    """Consumo por família na rede — CMV somado, percentual recalculado."""
    apuracoes = apurar_unidades(db, unidades, referencia, data_inicio, data_fim,
                                empresa_id)
    dentro = [a for a in apuracoes if a.entrou]
    cobertura = _cobertura(apuracoes)
    rotulo = next((a.periodo.rotulo for a in apuracoes), "—")
    cabecalho = {
        "rotulo": rotulo, "unidade": "Regional", "regional": True,
        "data_inicio": min((a.periodo.inicio for a in apuracoes),
                           default=date_type.today()).isoformat(),
        "data_fim": max((a.periodo.fim for a in apuracoes),
                        default=date_type.today()).isoformat(),
        "inventario_abertura": None, "inventario_fechamento": None,
        "encaixado_no_ciclo": True, "sem_ciclo": not dentro,
        "gerado_em": date_type.today().isoformat(), "cobertura": cobertura,
    }
    if not dentro:
        return {"cabecalho": cabecalho, "disponivel": False,
                "motivo": "Nenhuma unidade tem ciclo de inventário fechado no período."}

    geral = Consolidado()
    for a in dentro:
        geral.somar(a.resultado.geral)

    acumulado: Dict[int, dict] = {}
    for a in dentro:
        for linha in a.resultado.linhas:
            if linha.categoria_id is None:
                continue
            alvo = acumulado.setdefault(linha.categoria_id, {
                "categoria_id": linha.categoria_id,
                "familia": (linha.categoria or "").replace("Família - ", ""),
                "eh_bebida": linha.eh_bebida, "cmv": 0.0, "itens": 0,
            })
            alvo["cmv"] += linha.cmv
            alvo["itens"] += 1

    referencia_data = max(a.periodo.fim for a in dentro)
    meta_rede = _meta_regional(db, apuracoes, referencia_data)

    linhas = []
    for item in sorted(acumulado.values(), key=lambda x: -x["cmv"]):
        percentual = (round(item["cmv"] / geral.faturamento, 6)
                      if geral.faturamento else None)
        meta = servico_metas.meta_vigente(
            db, None, TipoMeta.CMV_FAMILIA, referencia_data,
            categoria_id=item["categoria_id"], categoria_eh_bebida=item["eh_bebida"])
        linhas.append({
            **item,
            "cmv": round(item["cmv"], 2),
            "percentual": percentual,
            "participacao": round(item["cmv"] / geral.cmv, 6) if geral.cmv else None,
            "meta": meta.valor, "meta_definida": meta.definida,
            "meta_herdada_de": meta.herdada_rotulo,
            "dentro_da_meta": (None if percentual is None or meta.valor is None
                               else percentual <= meta.valor),
        })

    return {
        "cabecalho": cabecalho, "disponivel": True, "regional": True,
        "total_cmv": geral.cmv, "faturamento": round(geral.faturamento, 2),
        "meta_geral": meta_rede["valor"],
        "linhas": linhas, "evolucao": [],
        "cobertura": cobertura,
        "avisos": _avisos_cobertura(cobertura),
    }


RELATORIOS = {
    "fechamento": fechamento,
    "comparativo": comparativo,
    "curva-abc": curva_abc,
    "familias": por_familia,
}
