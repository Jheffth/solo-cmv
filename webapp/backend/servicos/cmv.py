"""
Motor de CMV — a conta que a planilha fazia, agora sobre inventários.

A REGRA, EM UMA LINHA
---------------------
    CMV = Estoque Inicial + Compras − Estoque Final

Isso responde "quanto de mercadoria saiu do estoque no período". Não importa
se saiu para o prato, para a lixeira ou pela porta dos fundos: o que entrou e
não está mais lá foi consumido.

DE ONDE VÊM OS ESTOQUES
-----------------------
Do **inventário**, e só dele. Na planilha, "contagem inicial" e "contagem
final" eram duas colunas digitadas na aba da semana. Aqui elas são dois
inventários de verdade:

    estoque inicial  = inventário finalizado até a data de início
    estoque final    = inventário finalizado até a data de fim
    compras          = notas lançadas entre os dois inventários

Quantidade **e custo** vêm da linha do inventário — o custo é o que estava
congelado quando aquele inventário foi fechado. Assim o relatório do
inventário e o CMV falam do mesmo número por construção; não há como um
divergir do outro.

A busca é **por produto**, não pelo inventário inteiro. Isso faz o inventário
rotativo funcionar naturalmente: se o Hortifruti foi contado dia 10 e as
Carnes dia 12, cada item usa o seu próprio par de contagens.

MÉTODO DE CUSTO
---------------
As compras sempre entram pelo custo real de cada nota. O que muda é como o
estoque é valorizado:

  CUSTO_MEDIO (padrão) — custo médio ponderado do período:
        (valor inicial + valor das compras) ÷ (qtd inicial + qtd comprada)
  ULTIMO_CUSTO — o custo congelado em cada inventário, como a planilha fazia.

MODO DE APURAÇÃO
----------------
  PERIODO   — entre os dois inventários que cercam o intervalo pedido.
  ACUMULADO — do primeiro inventário registrado até o último do intervalo.
"""
from dataclasses import dataclass, field
from datetime import date
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from models import (
    Movimento, TipoMovimento, Produto, Categoria, VendaPeriodo,
    ConfiguracaoCMV, MetodoCusto, ModoApuracao,
    SessaoInventario, InventarioItem, StatusSessaoInventario,
)

# Famílias tratadas como bebida quando a unidade ainda não tem configuração.
# Definido com o Arquiteto: Bar + Cervejas formam "Bebidas".
FAMILIAS_BEBIDA_PADRAO = ("bar", "cerveja")


@dataclass
class ContagemDeInventario:
    """A contagem de um produto num inventário específico."""
    inventario_id: int
    numero: str
    data: date
    quantidade: float
    custo: float


@dataclass
class LinhaCMV:
    produto_id: int
    codigo: Optional[str]
    nome: str
    categoria_id: Optional[int]
    categoria: Optional[str]
    unidade_medida: Optional[str]
    eh_bebida: bool

    inicial: Optional[ContagemDeInventario] = None
    final: Optional[ContagemDeInventario] = None
    qtd_comprada: float = 0.0
    valor_comprado: float = 0.0
    qtd_requisitada: float = 0.0
    valor_requisitado: float = 0.0
    qtd_perdida: float = 0.0
    valor_perdido: float = 0.0

    # Preenchidos pelo método de custo escolhido
    custo_inicial: float = 0.0
    custo_final: float = 0.0

    @property
    def qtd_inicial(self) -> float:
        return self.inicial.quantidade if self.inicial else 0.0

    @property
    def qtd_saida(self) -> float:
        """Tudo que saiu do estoque de forma registrada: produção + perda."""
        return round(self.qtd_requisitada + self.qtd_perdida, 3)

    @property
    def valor_saida(self) -> float:
        return round(self.valor_requisitado + self.valor_perdido, 4)

    @property
    def qtd_final(self) -> float:
        if self.final:
            return self.final.quantidade
        # Sem inventário de fechamento, o melhor palpite é o saldo teórico
        return round(self.qtd_inicial + self.qtd_comprada - self.qtd_saida, 3)

    @property
    def final_estimado(self) -> bool:
        return self.final is None

    @property
    def valor_inicial(self) -> float:
        return round(self.qtd_inicial * self.custo_inicial, 4)

    @property
    def valor_final(self) -> float:
        """Sem inventário de fechamento, o estoque final é valorizado na mesma
        base das entradas — senão a diferença de custo unitário viraria um
        CMV que não existiu."""
        if self.final_estimado:
            return round(self.valor_inicial + self.valor_comprado - self.valor_saida, 4)
        return round(self.qtd_final * self.custo_final, 4)

    @property
    def qtd_consumida(self) -> float:
        return round((self.qtd_inicial + self.qtd_comprada) - self.qtd_final, 3)

    @property
    def cmv(self) -> float:
        return round(self.valor_inicial + self.valor_comprado - self.valor_final, 2)

    @property
    def custo_medio(self) -> float:
        base = self.qtd_inicial + self.qtd_comprada
        if base <= 0:
            return 0.0
        return round((self.valor_inicial + self.valor_comprado) / base, 6)

    def tem_movimento(self) -> bool:
        return bool(self.inicial or self.final or self.qtd_comprada or self.qtd_saida)


@dataclass
class BlocoCMV:
    estoque_inicial: float = 0.0
    compras: float = 0.0
    estoque_final: float = 0.0
    faturamento: float = 0.0
    # Perda já está dentro do CMV (consumiu estoque sem virar venda). Fica
    # destacada para responder "quanto do meu CMV é desperdício?".
    perdas: float = 0.0

    @property
    def cmv(self) -> float:
        return round(self.estoque_inicial + self.compras - self.estoque_final, 2)

    @property
    def cmv_percentual(self) -> Optional[float]:
        if not self.faturamento:
            return None
        return round(self.cmv / self.faturamento, 6)

    @property
    def perdas_percentual(self) -> Optional[float]:
        """Perda sobre faturamento — o indicador que a operação persegue."""
        if not self.faturamento:
            return None
        return round(self.perdas / self.faturamento, 6)

    @property
    def perdas_sobre_cmv(self) -> Optional[float]:
        if not self.cmv:
            return None
        return round(self.perdas / self.cmv, 6)

    def como_dict(self) -> dict:
        return {
            "estoque_inicial": round(self.estoque_inicial, 2),
            "compras": round(self.compras, 2),
            "estoque_final": round(self.estoque_final, 2),
            "cmv": self.cmv,
            "faturamento": round(self.faturamento, 2),
            "cmv_percentual": self.cmv_percentual,
            "perdas": round(self.perdas, 2),
            "perdas_percentual": self.perdas_percentual,
            "perdas_sobre_cmv": self.perdas_sobre_cmv,
        }


@dataclass
class ResultadoCMV:
    geral: BlocoCMV = field(default_factory=BlocoCMV)
    comida: BlocoCMV = field(default_factory=BlocoCMV)
    bebida: BlocoCMV = field(default_factory=BlocoCMV)
    linhas: List[LinhaCMV] = field(default_factory=list)
    meta: float = 0.29
    avisos: List[str] = field(default_factory=list)
    # Quais inventários foram cruzados — o usuário precisa saber
    inventarios_iniciais: List[dict] = field(default_factory=list)
    inventarios_finais: List[dict] = field(default_factory=list)

    @property
    def lacuna(self) -> Optional[float]:
        p = self.geral.cmv_percentual
        return None if p is None else round(self.meta - p, 6)


# ==============================================================================
# CONFIGURAÇÃO
# ==============================================================================
def obter_configuracao(db: Session, unidade_id: int, empresa_id: Optional[int] = None) -> ConfiguracaoCMV:
    cfg = db.query(ConfiguracaoCMV).filter(ConfiguracaoCMV.unidade_id == unidade_id).first()
    if cfg:
        return cfg

    cfg = ConfiguracaoCMV(unidade_id=unidade_id)
    query = db.query(Categoria)
    if empresa_id:
        query = query.filter(Categoria.empresa_id == empresa_id)
    cfg.familias_bebida = [
        c for c in query.all()
        if any(p in c.nome.lower() for p in FAMILIAS_BEBIDA_PADRAO)
    ]
    db.add(cfg)
    db.commit()
    db.refresh(cfg)
    return cfg


# ==============================================================================
# CONTAGENS VINDAS DOS INVENTÁRIOS
# ==============================================================================
def _data_do_inventario(s: SessaoInventario) -> date:
    momento = s.data_fechamento or s.data_congelamento or s.data_abertura
    return momento.date() if hasattr(momento, "date") else momento


def contagens_por_produto(db: Session, unidade_id: int, ate: date) -> Dict[int, List[ContagemDeInventario]]:
    """Todas as contagens de inventários finalizados até a data, por produto.

    A lista de cada produto vem em ordem cronológica, o que permite escolher
    a contagem que abre e a que fecha o período item a item.
    """
    sessoes = db.query(SessaoInventario).filter(
        SessaoInventario.unidade_id == unidade_id,
        SessaoInventario.status == StatusSessaoInventario.FINALIZADO,
    ).all()
    sessoes = [s for s in sessoes if _data_do_inventario(s) <= ate]
    sessoes.sort(key=lambda s: (_data_do_inventario(s), s.id))

    por_produto: Dict[int, List[ContagemDeInventario]] = {}
    for s in sessoes:
        dia = _data_do_inventario(s)
        for item in s.itens:
            if item.quantidade_contada is None:
                continue          # item não contado não vale como contagem
            por_produto.setdefault(item.produto_id, []).append(
                ContagemDeInventario(
                    inventario_id=s.id, numero=s.numero_documento, data=dia,
                    quantidade=item.quantidade_contada,
                    custo=item.custo_unitario or 0.0,
                )
            )
    return por_produto


def _escolher_par(contagens: List[ContagemDeInventario], data_inicio: date,
                  data_fim: date, acumulado: bool) -> Tuple[Optional[ContagemDeInventario],
                                                            Optional[ContagemDeInventario]]:
    """Escolhe qual contagem abre e qual fecha o período, para um produto."""
    if not contagens:
        return None, None

    if acumulado:
        inicial = contagens[0]                                   # a primeira de todas
    else:
        anteriores = [c for c in contagens if c.data <= data_inicio]
        inicial = anteriores[-1] if anteriores else None

    candidatas = [c for c in contagens if c.data <= data_fim]
    if inicial is not None:
        candidatas = [c for c in candidatas if (c.data, c.inventario_id) > (inicial.data, inicial.inventario_id)]
    final = candidatas[-1] if candidatas else None

    return inicial, final


# ==============================================================================
# APURAÇÃO
# ==============================================================================
def apurar(
    db: Session,
    unidade_id: int,
    data_inicio: date,
    data_fim: date,
    *,
    modo: ModoApuracao = ModoApuracao.PERIODO,
    metodo_custo: MetodoCusto = MetodoCusto.CUSTO_MEDIO,
    empresa_id: Optional[int] = None,
    incluir_linhas: bool = True,
) -> ResultadoCMV:
    cfg = obter_configuracao(db, unidade_id, empresa_id)

    # A meta vem da vigência que valia no fim do período apurado, não do
    # valor de hoje. Sem isso, mudar a meta em setembro passaria a julgar
    # março contra um alvo que não existia em março.
    from servicos.metas import meta_cmv
    resultado = ResultadoCMV(meta=meta_cmv(db, unidade_id, data_fim))
    acumulado = modo == ModoApuracao.ACUMULADO

    ids_bebida = {c.id for c in cfg.familias_bebida}
    if not ids_bebida:
        resultado.avisos.append(
            "Nenhuma família marcada como bebida — todo o CMV está sendo tratado como comida."
        )

    contagens = contagens_por_produto(db, unidade_id, data_fim)
    if not contagens:
        resultado.avisos.append(
            "Nenhum inventário finalizado até esta data. O CMV precisa de um inventário "
            "para abrir e outro para fechar o período."
        )

    produtos = db.query(Produto)
    if empresa_id:
        produtos = produtos.filter(Produto.empresa_id == empresa_id)
    produtos = produtos.all()
    categorias = {c.id: c.nome for c in db.query(Categoria).all()}

    movs = db.query(Movimento).filter(
        Movimento.unidade_id == unidade_id,
        Movimento.data <= data_fim,
    ).all()
    por_produto: Dict[int, List[Movimento]] = {}
    for m in movs:
        por_produto.setdefault(m.produto_id, []).append(m)

    usados_ini: Dict[int, ContagemDeInventario] = {}
    usados_fim: Dict[int, ContagemDeInventario] = {}
    sem_abertura = 0

    for p in produtos:
        inicial, final = _escolher_par(contagens.get(p.id, []), data_inicio, data_fim, acumulado)
        lista = por_produto.get(p.id, [])

        # Compras e requisições entre as duas contagens. Sem contagem de
        # abertura, vale o início do intervalo pedido.
        piso = inicial.data if inicial else (None if acumulado else data_inicio)
        teto = final.data if final else data_fim

        def no_intervalo(m):
            if piso is not None and m.data < piso:
                return False
            # o que entrou no mesmo dia da contagem de abertura já está nela
            if inicial is not None and m.data <= inicial.data:
                return False
            return m.data <= teto

        compras = [m for m in lista if m.tipo == TipoMovimento.COMPRA and no_intervalo(m)]
        requisicoes = [m for m in lista if m.tipo == TipoMovimento.REQUISICAO and no_intervalo(m)]
        perdas = [m for m in lista if m.tipo == TipoMovimento.PERDA and no_intervalo(m)]

        def valor(movs):
            return round(sum((m.custo_total if m.custo_total is not None
                              else (m.custo_unitario or 0) * m.quantidade) for m in movs), 4)

        linha = LinhaCMV(
            produto_id=p.id, codigo=p.codigo, nome=p.nome,
            categoria_id=p.categoria_id, categoria=categorias.get(p.categoria_id),
            unidade_medida=p.unidade_medida,
            eh_bebida=p.categoria_id in ids_bebida,
            inicial=inicial, final=final,
            qtd_comprada=sum(m.quantidade for m in compras),
            valor_comprado=valor(compras),
            qtd_requisitada=sum(m.quantidade for m in requisicoes),
            valor_requisitado=valor(requisicoes),
            qtd_perdida=sum(m.quantidade for m in perdas),
            valor_perdido=valor(perdas),
        )

        # Custo vindo do inventário — é o que estava congelado quando ele fechou
        linha.custo_inicial = inicial.custo if inicial else 0.0
        linha.custo_final = final.custo if final else 0.0

        if metodo_custo == MetodoCusto.CUSTO_MEDIO:
            medio = linha.custo_medio
            if medio:
                linha.custo_final = medio
                if not inicial:
                    linha.custo_inicial = medio

        if not linha.tem_movimento():
            continue
        if inicial is None and final is not None:
            sem_abertura += 1

        if inicial:
            usados_ini[inicial.inventario_id] = inicial
        if final:
            usados_fim[final.inventario_id] = final

        bloco = resultado.bebida if linha.eh_bebida else resultado.comida
        for alvo in (resultado.geral, bloco):
            alvo.estoque_inicial += linha.valor_inicial
            alvo.compras += linha.valor_comprado
            alvo.estoque_final += linha.valor_final
            alvo.perdas += linha.valor_perdido

        if incluir_linhas:
            resultado.linhas.append(linha)

    resultado.inventarios_iniciais = [
        {"numero": c.numero, "data": c.data.isoformat()}
        for c in sorted(usados_ini.values(), key=lambda c: c.data)
    ]
    resultado.inventarios_finais = [
        {"numero": c.numero, "data": c.data.isoformat()}
        for c in sorted(usados_fim.values(), key=lambda c: c.data)
    ]

    estimados = sum(1 for l in resultado.linhas if l.final_estimado)
    if estimados:
        resultado.avisos.append(
            f"{estimados} item(ns) sem inventário de fechamento no período — o estoque final "
            f"deles foi estimado pelo saldo teórico, então o CMV considera apenas as saídas "
            f"já registradas."
        )
    if sem_abertura:
        resultado.avisos.append(
            f"{sem_abertura} item(ns) sem inventário de abertura — entraram com estoque "
            f"inicial zero, o que reduz o CMV apurado deles."
        )

    # ----- Faturamento -----
    limite_inicio = date.min if acumulado else data_inicio
    candidatos = db.query(VendaPeriodo).filter(
        VendaPeriodo.unidade_id == unidade_id,
        VendaPeriodo.data_fim >= limite_inicio,
        VendaPeriodo.data_inicio <= data_fim,
    ).all()
    vendas = [v for v in candidatos if v.data_inicio >= limite_inicio and v.data_fim <= data_fim]

    parciais = [v for v in candidatos if v not in vendas]
    if parciais:
        resultado.avisos.append(
            f"{len(parciais)} lançamento(s) de faturamento cruzam a borda do período e "
            f"ficaram de fora — só entram os que cabem inteiros no intervalo."
        )

    ordenados = sorted(vendas, key=lambda v: (v.data_inicio, v.data_fim))
    sobrepostos = [(a, b) for a, b in zip(ordenados, ordenados[1:]) if b.data_inicio <= a.data_fim]
    if sobrepostos:
        exemplos = "; ".join(
            f"{a.data_inicio:%d/%m}–{a.data_fim:%d/%m} e {b.data_inicio:%d/%m}–{b.data_fim:%d/%m}"
            for a, b in sobrepostos[:3]
        )
        resultado.avisos.append(
            f"Atenção: há faturamentos com períodos sobrepostos ({exemplos}). "
            f"Os dias em comum estão sendo contados mais de uma vez, o que reduz "
            f"artificialmente o CMV %. Revise em 'Faturamento por Período'."
        )

    resultado.geral.faturamento = sum(v.faturamento_total or 0 for v in vendas)
    resultado.bebida.faturamento = sum(v.faturamento_bebida or 0 for v in vendas)
    if any(v.faturamento_comida is not None for v in vendas):
        resultado.comida.faturamento = sum(v.faturamento_comida or 0 for v in vendas)
    else:
        resultado.comida.faturamento = resultado.geral.faturamento - resultado.bebida.faturamento

    if not vendas:
        resultado.avisos.append(
            "Nenhum faturamento informado no período — o CMV % não pode ser calculado."
        )
    elif not resultado.bebida.faturamento and resultado.bebida.cmv:
        resultado.avisos.append(
            "Há CMV de bebida, mas o faturamento de bebida não foi informado — "
            "o CMV % de bebida fica indisponível."
        )

    resultado.linhas.sort(key=lambda l: -abs(l.cmv))
    return resultado
