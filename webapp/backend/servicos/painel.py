"""
Serviço do Painel — monta, numa passada só, tudo que a tela inicial mostra.

POR QUE UM SERVIÇO E NÃO CÁLCULO NA TELA
----------------------------------------
O painel cruza CMV, estoque, perdas, inventários, requisições e faturamento.
Feito no navegador seriam oito chamadas e regra de negócio espalhada em
JavaScript. Aqui é uma chamada só, e — mais importante — **nenhuma fórmula
nova**: este módulo apenas compõe o que os serviços já sabem calcular. Se o
CMV mudar, muda em servicos/cmv.py e o painel acompanha sozinho.

Como é serviço e não router, o futuro bot do Telegram manda o mesmo resumo
por mensagem sem reimplementar nada.

A REGRA DO ENCAIXE NO CICLO
---------------------------
O período padrão é mensal, mas CMV nasce de inventário, não de calendário.
Apurar 01/08 a 31/08 quando o inventário mais próximo é de 03/08 faz 65
itens entrarem com estoque inicial zero — e o CMV do mês despenca de 28,4%
para 10,6%. O número não está errado, é o que os dados permitem; exibido
como manchete, seria desastroso.

Por isso o painel encaixa o mês nos inventários que efetivamente o
delimitam, e escreve no cabeçalho quais foram. Se não houver par válido,
declara a ausência em vez de mostrar zero.
"""
from dataclasses import dataclass, field
from datetime import date as date_type, timedelta
from typing import Dict, List, Optional

from sqlalchemy.orm import Session

from models import (
    Movimento, TipoMovimento, MotivoPerda, Produto, Fornecedor,
    SessaoInventario, StatusSessaoInventario, Requisicao, StatusRequisicao,
    VendaPeriodo, Categoria, TipoMeta,
)
from calculo_estoque import saldos_por_produto, ultimos_custos, data_ultima_contagem
from servicos import cmv as motor
from servicos import metas as servico_metas
from servicos.memoria import lembrar
from servicos.perda import ROTULOS_MOTIVO

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]

DIAS_INVENTARIO_PARADO = 3     # inventário aberto além disso vira pendência
DIAS_SEM_GIRO = 30             # item com saldo e sem movimento vira dinheiro parado


# ==============================================================================
# PERÍODO
# ==============================================================================
@dataclass
class Periodo:
    inicio: date_type
    fim: date_type
    rotulo: str
    inventario_abertura: Optional[str] = None
    inventario_fechamento: Optional[str] = None
    encaixado: bool = False        # True = as datas foram ajustadas ao ciclo
    sem_ciclo: bool = False        # True = não há par de inventários no período


def _fim_do_mes(d: date_type) -> date_type:
    proximo = d.replace(day=28) + timedelta(days=4)
    return proximo - timedelta(days=proximo.day)


def mes_de(referencia: Optional[str] = None) -> tuple:
    """'2026-08' -> (01/08/2026, 31/08/2026). Sem referência, o mês corrente."""
    hoje = date_type.today()
    if referencia:
        ano, mes = (int(x) for x in referencia.split("-")[:2])
    else:
        ano, mes = hoje.year, hoje.month
    inicio = date_type(ano, mes, 1)
    return inicio, _fim_do_mes(inicio)


def _inventarios_finalizados(db: Session, unidade_id: Optional[int]) -> List[tuple]:
    """(data, número) de cada inventário finalizado, do mais antigo ao mais novo.

    Lido uma vez por pedido: o painel pergunta isto a cada faixa da tela —
    o encaixe no ciclo, o histórico, a cobertura — e a resposta é sempre a
    mesma. Eram nove consultas idênticas por página.

    Buscamos só as três colunas usadas, em vez dos objetos inteiros: o ORM
    montaria uma SessaoInventario completa e a registraria na sessão para
    nada.
    """
    def carregar():
        query = db.query(
            SessaoInventario.data_fechamento,
            SessaoInventario.data_abertura,
            SessaoInventario.numero_documento,
        ).filter(SessaoInventario.status == StatusSessaoInventario.FINALIZADO)
        if unidade_id:
            query = query.filter(SessaoInventario.unidade_id == unidade_id)

        saida = []
        for fechamento, abertura, numero in query.all():
            marco = fechamento or abertura
            if marco:
                saida.append((marco.date() if hasattr(marco, "date") else marco,
                              numero))
        return sorted(saida, key=lambda x: x[0])

    return lembrar(db, ("inventarios_finalizados", unidade_id), carregar)


def encaixar_no_ciclo(db: Session, unidade_id: Optional[int],
                      inicio: date_type, fim: date_type, rotulo: str) -> Periodo:
    """Ajusta as datas para os inventários que delimitam o período."""
    inventarios = _inventarios_finalizados(db, unidade_id)
    if not inventarios:
        return Periodo(inicio, fim, rotulo, sem_ciclo=True)

    abertura = None
    for data, numero in inventarios:
        if data <= inicio:
            abertura = (data, numero)
    fechamento = None
    for data, numero in inventarios:
        if data <= fim and (abertura is None or data > abertura[0]):
            fechamento = (data, numero)

    if fechamento is None:
        return Periodo(inicio, fim, rotulo, sem_ciclo=True)

    # Sem inventário anterior ao início, usa o primeiro que existir dentro
    # do período — é o que evita o estoque inicial zerado.
    if abertura is None:
        dentro = [x for x in inventarios if inicio <= x[0] < fechamento[0]]
        if dentro:
            abertura = dentro[0]

    novo_inicio = abertura[0] if abertura else inicio
    novo_fim = fechamento[0]
    return Periodo(
        inicio=novo_inicio, fim=novo_fim, rotulo=rotulo,
        inventario_abertura=abertura[1] if abertura else None,
        inventario_fechamento=fechamento[1],
        encaixado=(novo_inicio != inicio or novo_fim != fim),
    )


def periodo_mensal(db: Session, unidade_id: Optional[int],
                   referencia: Optional[str] = None) -> Periodo:
    inicio, fim = mes_de(referencia)
    rotulo = f"{MESES[inicio.month - 1].capitalize()}/{inicio.year}"
    return encaixar_no_ciclo(db, unidade_id, inicio, fim, rotulo)


# ==============================================================================
# INDICADORES
# ==============================================================================
@dataclass
class Kpi:
    valor: Optional[float] = None
    valor_anterior: Optional[float] = None
    formato: str = "MOEDA"          # MOEDA | PERCENTUAL | NUMERO
    meta: Optional[float] = None
    dentro_da_meta: Optional[bool] = None
    serie: List[float] = field(default_factory=list)
    detalhe: Optional[str] = None
    menor_e_melhor: bool = True

    @property
    def variacao(self) -> Optional[float]:
        """Diferença relativa; em percentual, diferença absoluta em pontos."""
        if self.valor is None or self.valor_anterior in (None, 0):
            return None
        if self.formato == "PERCENTUAL":
            return round(self.valor - self.valor_anterior, 6)
        return round((self.valor - self.valor_anterior) / abs(self.valor_anterior), 6)

    def dict(self) -> dict:
        variacao = self.variacao
        direcao = None
        if variacao is not None and abs(variacao) > 1e-9:
            subiu = variacao > 0
            direcao = "boa" if (subiu != self.menor_e_melhor) else "ruim"
        return {
            "valor": self.valor,
            "valor_anterior": self.valor_anterior,
            "formato": self.formato,
            "meta": self.meta,
            "dentro_da_meta": self.dentro_da_meta,
            "variacao": variacao,
            "direcao": direcao,
            "serie": self.serie,
            "detalhe": self.detalhe,
        }


def _periodos_anteriores(db: Session, unidade_id: Optional[int],
                         referencia: date_type, quantos: int) -> List[Periodo]:
    """Os N meses que antecedem o período exibido, já encaixados no ciclo."""
    saida = []
    cursor = referencia.replace(day=1)
    for _ in range(quantos):
        cursor = (cursor - timedelta(days=1)).replace(day=1)
        saida.append(periodo_mensal(db, unidade_id, cursor.strftime("%Y-%m")))
    return list(reversed(saida))


# ==============================================================================
# PENDÊNCIAS
# ==============================================================================
def _pendencias(db: Session, unidade_id: Optional[int], periodo: Periodo,
                resumo_estoque: dict, avisos_cmv: List[str],
                pode_ver_metas: bool) -> List[dict]:
    """A fila de trabalho. Vazia quando não há nada — um painel que sempre
    mostra alerta ensina o usuário a ignorar alerta."""
    itens = []

    def juntar(chave, gravidade, texto, rota, quantidade=None):
        itens.append({"chave": chave, "gravidade": gravidade, "texto": texto,
                      "rota": rota, "quantidade": quantidade})

    # Faturamento sem cobertura no período
    query_vendas = db.query(VendaPeriodo).filter(
        VendaPeriodo.data_inicio <= periodo.fim, VendaPeriodo.data_fim >= periodo.inicio)
    if unidade_id:
        query_vendas = query_vendas.filter(VendaPeriodo.unidade_id == unidade_id)
    if not query_vendas.count():
        juntar("faturamento", "urgente",
               f"Faturamento de {periodo.rotulo.lower()} não lançado",
               "vendas")

    # Inventário parado
    query_inv = db.query(SessaoInventario).filter(SessaoInventario.status.in_((
        StatusSessaoInventario.ABERTO, StatusSessaoInventario.CONGELADO,
        StatusSessaoInventario.EM_CONTAGEM)))
    if unidade_id:
        query_inv = query_inv.filter(SessaoInventario.unidade_id == unidade_id)
    hoje = date_type.today()
    for sessao in query_inv.all():
        dias = (hoje - sessao.data_abertura.date()).days
        if dias >= DIAS_INVENTARIO_PARADO:
            juntar("inventario_parado", "atencao",
                   f"Inventário {sessao.numero_documento} aberto há {dias} dias",
                   "inventario", dias)

    # Requisições aguardando
    query_req = db.query(Requisicao).filter(Requisicao.status.in_((
        StatusRequisicao.ABERTA, StatusRequisicao.INICIADA)))
    if unidade_id:
        query_req = query_req.filter(Requisicao.unidade_id == unidade_id)
    pendentes = query_req.count()
    if pendentes:
        juntar("requisicoes", "atencao",
               f"{pendentes} requisição(ões) aguardando atendimento",
               "requisicoes", pendentes)

    # Itens sem custo: sem custo não há valorização, e sem valorização não há CMV
    sem_custo = resumo_estoque.get("itens_sem_custo") or 0
    if sem_custo:
        juntar("itens_sem_custo", "atencao",
               f"{sem_custo} itens sem custo cadastrado", "estoque", sem_custo)

    # Avisos que o próprio motor de CMV levantou
    for aviso in avisos_cmv:
        if "sem inventário de abertura" in aviso:
            juntar("sem_abertura", "atencao", aviso, "inventario")
        elif "sobrep" in aviso.lower():
            juntar("faturamento_sobreposto", "urgente", aviso, "vendas")

    if periodo.sem_ciclo:
        juntar("sem_ciclo", "urgente",
               f"Nenhum ciclo de inventário fechado em {periodo.rotulo.lower()} — "
               f"o CMV do período não pode ser apurado", "inventario")

    if pode_ver_metas:
        familias = db.query(Categoria).count()
        sem_meta = 0
        for cat in db.query(Categoria).all():
            resolvida = servico_metas.meta_vigente(
                db, unidade_id, TipoMeta.CMV_FAMILIA, periodo.fim, categoria_id=cat.id)
            if not resolvida.definida:
                sem_meta += 1
        if sem_meta and familias:
            juntar("metas_familia", "atencao",
                   f"CMV por família sem meta definida em {sem_meta} de {familias} famílias",
                   "metas", sem_meta)

    ordem = {"urgente": 0, "atencao": 1}
    return sorted(itens, key=lambda i: ordem.get(i["gravidade"], 9))


# ==============================================================================
# MONTAGEM
# ==============================================================================
def montar(db: Session, unidade_id: Optional[int] = None,
           referencia: Optional[str] = None,
           data_inicio: Optional[date_type] = None,
           data_fim: Optional[date_type] = None,
           historico: int = 5,
           empresa_id: Optional[int] = None,
           pode_ver_metas: bool = False) -> dict:
    if data_inicio and data_fim:
        periodo = encaixar_no_ciclo(
            db, unidade_id, data_inicio, data_fim,
            f"{data_inicio.strftime('%d/%m/%Y')} a {data_fim.strftime('%d/%m/%Y')}")
    else:
        periodo = periodo_mensal(db, unidade_id, referencia)

    apuracao = None
    if unidade_id and not periodo.sem_ciclo:
        apuracao = motor.apurar(db, unidade_id=unidade_id, data_inicio=periodo.inicio,
                                data_fim=periodo.fim, empresa_id=empresa_id)

    anteriores = _periodos_anteriores(db, unidade_id, periodo.inicio, historico)
    serie = []
    for p in anteriores:
        if not unidade_id or p.sem_ciclo:
            continue
        r = motor.apurar(db, unidade_id=unidade_id, data_inicio=p.inicio,
                         data_fim=p.fim, empresa_id=empresa_id, incluir_linhas=False)
        serie.append({
            "rotulo": p.rotulo.split("/")[0][:3],
            "cmv_percentual": r.geral.cmv_percentual,
            "cmv": round(r.geral.cmv, 2),
            "faturamento": round(r.geral.faturamento, 2),
            "perdas": round(r.geral.perdas, 2),
            "meta": r.meta,
        })

    anterior = serie[-1] if serie else {}

    # ---- estoque
    saldos = saldos_por_produto(db, unidade_id) if unidade_id else {}
    custos = ultimos_custos(db, unidade_id) if unidade_id else {}
    ultima_contagem = data_ultima_contagem(db, unidade_id) if unidade_id else {}

    valor_estoque = 0.0
    com_saldo = 0
    sem_custo = 0
    produtos = {p.id: p for p in db.query(Produto).all()}
    for produto_id, saldo in saldos.items():
        custo = custos.get(produto_id)
        if custo is None:
            sem_custo += 1
        if saldo and saldo > 0:
            com_saldo += 1
            valor_estoque += saldo * (custo or 0)
    resumo_estoque = {
        "total_itens": len(produtos),
        "itens_com_saldo": com_saldo,
        "itens_sem_custo": sem_custo,
        "valor_total": round(valor_estoque, 2),
    }

    # ---- KPIs
    meta_cmv = apuracao.meta if apuracao else servico_metas.meta_cmv(db, unidade_id, periodo.fim)
    cmv_pct = apuracao.geral.cmv_percentual if apuracao else None
    kpis = {
        "cmv_percentual": Kpi(
            valor=cmv_pct, valor_anterior=anterior.get("cmv_percentual"),
            formato="PERCENTUAL", meta=meta_cmv,
            dentro_da_meta=None if cmv_pct is None else cmv_pct <= meta_cmv,
            serie=[s["cmv_percentual"] for s in serie if s["cmv_percentual"] is not None],
        ),
        "cmv_valor": Kpi(
            valor=round(apuracao.geral.cmv, 2) if apuracao else None,
            valor_anterior=anterior.get("cmv"),
            serie=[s["cmv"] for s in serie],
        ),
        "faturamento": Kpi(
            valor=round(apuracao.geral.faturamento, 2) if apuracao else None,
            valor_anterior=anterior.get("faturamento"),
            menor_e_melhor=False,
            serie=[s["faturamento"] for s in serie],
        ),
        "perdas": Kpi(
            valor=round(apuracao.geral.perdas, 2) if apuracao else None,
            valor_anterior=anterior.get("perdas"),
            serie=[s["perdas"] for s in serie],
            detalhe=(f"{apuracao.geral.perdas_sobre_cmv * 100:.1f}% do CMV"
                     if apuracao and apuracao.geral.perdas_sobre_cmv else None),
        ),
        "estoque": Kpi(
            valor=resumo_estoque["valor_total"], formato="MOEDA",
            detalhe=f"{com_saldo} de {len(produtos)} itens com saldo",
        ),
    }

    # ---- composição comida x bebida
    composicao = {}
    if apuracao:
        for nome, bloco in (("comida", apuracao.comida), ("bebida", apuracao.bebida)):
            composicao[nome] = {
                "cmv": round(bloco.cmv, 2),
                "cmv_percentual": bloco.cmv_percentual,
                "faturamento": round(bloco.faturamento, 2),
            }

    # ---- top itens por CMV
    top_itens = []
    if apuracao and apuracao.geral.cmv:
        ordenadas = sorted(apuracao.linhas, key=lambda l: l.cmv, reverse=True)[:10]
        for linha in ordenadas:
            if linha.cmv <= 0:
                continue
            top_itens.append({
                "codigo": linha.codigo, "produto": linha.nome,
                "unidade_medida": linha.unidade_medida,
                "categoria": (linha.categoria or "").replace("Família - ", ""),
                "eh_bebida": linha.eh_bebida,
                "cmv": round(linha.cmv, 2),
                "participacao": round(linha.cmv / apuracao.geral.cmv, 6),
            })

    # ---- perdas por motivo
    query_perdas = db.query(Movimento).filter(
        Movimento.tipo == TipoMovimento.PERDA,
        Movimento.data >= periodo.inicio, Movimento.data <= periodo.fim)
    if unidade_id:
        query_perdas = query_perdas.filter(Movimento.unidade_id == unidade_id)
    por_motivo: Dict[str, dict] = {}
    for m in query_perdas.all():
        motivo = m.motivo or MotivoPerda.OUTRO
        alvo = por_motivo.setdefault(motivo.value, {
            "motivo": motivo.value, "rotulo": ROTULOS_MOTIVO.get(motivo, "Outro"),
            "ocorrencias": 0, "valor": 0.0})
        alvo["ocorrencias"] += 1
        alvo["valor"] += m.custo_total or 0
    perdas_motivo = sorted(por_motivo.values(), key=lambda x: x["valor"], reverse=True)
    for p in perdas_motivo:
        p["valor"] = round(p["valor"], 2)

    # ---- estoque parado: dinheiro dormindo na câmara
    estoque_parado = []
    if unidade_id:
        limite = date_type.today() - timedelta(days=DIAS_SEM_GIRO)
        ultimo_movimento = {}
        from sqlalchemy import func
        query_max = db.query(
            Movimento.produto_id,
            func.max(Movimento.data)
        ).filter(Movimento.unidade_id == unidade_id).group_by(Movimento.produto_id)
        for produto_id, max_data in query_max.all():
            ultimo_movimento[produto_id] = max_data
        for produto_id, saldo in saldos.items():
            if not saldo or saldo <= 0:
                continue
            visto = ultimo_movimento.get(produto_id)
            if visto and visto > limite:
                continue
            produto = produtos.get(produto_id)
            if not produto:
                continue
            valor = saldo * (custos.get(produto_id) or 0)
            if valor <= 0:
                continue
            estoque_parado.append({
                "codigo": produto.codigo, "produto": produto.nome,
                "unidade_medida": produto.unidade_medida,
                "quantidade": round(saldo, 3), "valor": round(valor, 2),
                "dias": (date_type.today() - visto).days if visto else None,
            })
        estoque_parado.sort(key=lambda x: x["valor"], reverse=True)
        estoque_parado = estoque_parado[:8]

    # ---- atividade recente
    query_atividade = db.query(Movimento)
    if unidade_id:
        query_atividade = query_atividade.filter(Movimento.unidade_id == unidade_id)
    recentes = query_atividade.order_by(
        Movimento.data.desc(), Movimento.id.desc()).limit(10).all()
    fornecedores = {f.id: f.nome for f in db.query(Fornecedor).all()}
    from routers.movimentos import TIPO_DOCUMENTO, _rotular
    numeros_inv = {s.id: s.numero_documento for s in db.query(SessaoInventario).all()}
    numeros_req = {r.id: r.numero for r in db.query(Requisicao).all()}
    atividade = []
    for m in recentes:
        tipo_doc = TIPO_DOCUMENTO.get(m.tipo)
        if tipo_doc == "INVENTARIO":
            numero = numeros_inv.get(m.sessao_inventario_id)
        elif tipo_doc == "REQUISICAO":
            numero = numeros_req.get(m.requisicao_id)
        else:
            numero = m.numero_documento
        produto = produtos.get(m.produto_id)
        atividade.append({
            "data": m.data.isoformat(), "tipo": m.tipo.value,
            "documento": _rotular(tipo_doc, numero or m.numero_documento),
            "produto": produto.nome if produto else f"#{m.produto_id}",
            "codigo": produto.codigo if produto else None,
            "quantidade": m.quantidade,
            "valor": m.custo_total,
            "fornecedor": fornecedores.get(m.fornecedor_id),
        })

    avisos = list(apuracao.avisos) if apuracao else []

    return {
        "periodo": {
            "rotulo": periodo.rotulo,
            "data_inicio": periodo.inicio.isoformat(),
            "data_fim": periodo.fim.isoformat(),
            "inventario_abertura": periodo.inventario_abertura,
            "inventario_fechamento": periodo.inventario_fechamento,
            "encaixado_no_ciclo": periodo.encaixado,
            "sem_ciclo": periodo.sem_ciclo,
        },
        "pendencias": _pendencias(db, unidade_id, periodo, resumo_estoque,
                                  avisos, pode_ver_metas),
        "kpis": {chave: kpi.dict() for chave, kpi in kpis.items()},
        "historico": serie,
        "composicao": composicao,
        "top_itens": top_itens,
        "perdas": {
            "valor_total": round(sum(p["valor"] for p in perdas_motivo), 2),
            "por_motivo": perdas_motivo,
        },
        "estoque": resumo_estoque,
        "estoque_parado": estoque_parado,
        "atividade": atividade,
        "avisos": avisos,
    }
