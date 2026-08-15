"""
Serviço de metas — resolve *qual* meta valia *quando*.

DUAS REGRAS, E SÓ DUAS
----------------------
1. VIGÊNCIA. Uma meta vale a partir de uma data. Apurar março tem que usar a
   meta de março, não a que a diretoria definiu ontem. Sem isso, cada ajuste
   de meta falsifica retroativamente todo o histórico de acompanhamento.

2. HERANÇA. A meta de uma família cai para a do bloco (comida/bebida), que
   cai para a geral:

       CMV_FAMILIA (Hortifruti) -> CMV_COMIDA -> CMV_GERAL

   Assim a diretoria começa com um número só e refina quando quiser, em vez
   de ter que preencher doze famílias antes do sistema servir para algo.

A regra vive aqui, e não no router, para que o motor de CMV, o painel e um
futuro bot do Telegram leiam a mesma meta pelo mesmo caminho.
"""
from dataclasses import dataclass
from datetime import date as date_type
from typing import Dict, List, Optional

from sqlalchemy import or_
from sqlalchemy.orm import Session

from models import (
    Meta, TipoMeta, FormatoMeta, PeriodicidadeMeta, OrigemMeta, Categoria,
)

# Fallback de último recurso: sem nenhuma meta cadastrada, o sistema usa o
# mesmo 29% que a planilha usava. Melhor um padrão explícito e documentado
# do que um None se espalhando pelas telas.
META_CMV_PADRAO = 0.29

ROTULOS_TIPO = {
    TipoMeta.CMV_GERAL: "CMV geral",
    TipoMeta.CMV_COMIDA: "CMV comida",
    TipoMeta.CMV_BEBIDA: "CMV bebida",
    TipoMeta.CMV_FAMILIA: "CMV por família",
    TipoMeta.PERDAS: "Perdas",
    TipoMeta.FATURAMENTO: "Faturamento",
}

# Para onde cada tipo cai quando não tem valor próprio
HERANCA = {
    TipoMeta.CMV_COMIDA: TipoMeta.CMV_GERAL,
    TipoMeta.CMV_BEBIDA: TipoMeta.CMV_GERAL,
}


class ErroMeta(Exception):
    def __init__(self, mensagem: str, http: int = 400):
        super().__init__(mensagem)
        self.mensagem = mensagem
        self.http = http


@dataclass
class MetaResolvida:
    """O valor da meta mais a memória de como se chegou nele."""
    tipo: TipoMeta
    valor: Optional[float]
    formato: FormatoMeta = FormatoMeta.PERCENTUAL
    periodicidade: Optional[PeriodicidadeMeta] = None
    categoria_id: Optional[int] = None
    vigencia_inicio: Optional[date_type] = None
    meta_id: Optional[int] = None
    origem: OrigemMeta = OrigemMeta.MANUAL

    # De onde veio: None = definida diretamente; caso contrário, o tipo
    # (e a categoria) de quem emprestou o valor.
    herdada_de: Optional[TipoMeta] = None
    herdada_rotulo: Optional[str] = None
    padrao_do_sistema: bool = False

    @property
    def definida(self) -> bool:
        return self.valor is not None and self.herdada_de is None and not self.padrao_do_sistema

    @property
    def manual(self) -> bool:
        """Definida por decisão humana, não pela repartição da meta geral."""
        return self.definida and self.origem == OrigemMeta.MANUAL


# ---------------------------------------------------------------- consultas


def _consulta_base(db: Session, unidade_id: Optional[int]):
    """Metas da unidade mais as que valem para a empresa inteira.

    Uma meta com unidade_id nulo é o padrão da rede; a da unidade tem
    precedência sobre ela.
    """
    query = db.query(Meta)
    if unidade_id:
        query = query.filter(or_(Meta.unidade_id == unidade_id, Meta.unidade_id.is_(None)))
    return query


def _vigente_em(db: Session, unidade_id: Optional[int], tipo: TipoMeta,
                em: date_type, categoria_id: Optional[int] = None) -> Optional[Meta]:
    """A meta daquele tipo que estava valendo na data — sem herança."""
    query = _consulta_base(db, unidade_id).filter(
        Meta.tipo == tipo,
        Meta.vigencia_inicio <= em,
        or_(Meta.vigencia_fim.is_(None), Meta.vigencia_fim >= em),
    )
    if tipo == TipoMeta.CMV_FAMILIA:
        query = query.filter(Meta.categoria_id == categoria_id)

    # Unidade específica ganha da meta geral da rede; entre duas, a mais
    # recente. `nullslast` não existe em todo dialeto, então ordena em Python.
    candidatas = query.all()
    if not candidatas:
        return None
    candidatas.sort(
        key=lambda m: (1 if m.unidade_id else 0, m.vigencia_inicio, m.id),
        reverse=True,
    )
    return candidatas[0]


def meta_vigente(db: Session, unidade_id: Optional[int], tipo: TipoMeta,
                 em: Optional[date_type] = None,
                 categoria_id: Optional[int] = None,
                 categoria_eh_bebida: bool = False) -> MetaResolvida:
    """A meta que vale para (unidade, tipo, data), já com herança aplicada."""
    em = em or date_type.today()

    direta = _vigente_em(db, unidade_id, tipo, em, categoria_id)
    if direta:
        return MetaResolvida(
            tipo=tipo, valor=direta.valor, formato=direta.formato,
            periodicidade=direta.periodicidade, categoria_id=direta.categoria_id,
            vigencia_inicio=direta.vigencia_inicio, meta_id=direta.id,
            origem=direta.origem or OrigemMeta.MANUAL,
        )

    # Família herda do bloco a que pertence; o bloco herda do geral
    if tipo == TipoMeta.CMV_FAMILIA:
        cadeia = [TipoMeta.CMV_BEBIDA if categoria_eh_bebida else TipoMeta.CMV_COMIDA,
                  TipoMeta.CMV_GERAL]
    elif tipo in HERANCA:
        cadeia = [HERANCA[tipo]]
    else:
        cadeia = []

    for tipo_pai in cadeia:
        pai = _vigente_em(db, unidade_id, tipo_pai, em)
        if pai:
            return MetaResolvida(
                tipo=tipo, valor=pai.valor, formato=pai.formato,
                categoria_id=categoria_id, vigencia_inicio=pai.vigencia_inicio,
                meta_id=pai.id, herdada_de=tipo_pai,
                herdada_rotulo=ROTULOS_TIPO[tipo_pai],
            )

    # Nada cadastrado: só o CMV tem padrão de sistema; perdas e faturamento
    # sem meta simplesmente não têm meta — inventar um número seria pior.
    if tipo in (TipoMeta.CMV_GERAL, TipoMeta.CMV_COMIDA,
                TipoMeta.CMV_BEBIDA, TipoMeta.CMV_FAMILIA):
        return MetaResolvida(tipo=tipo, valor=META_CMV_PADRAO, categoria_id=categoria_id,
                             padrao_do_sistema=True)
    return MetaResolvida(tipo=tipo, valor=None, categoria_id=categoria_id)


def meta_cmv(db: Session, unidade_id: Optional[int], em: Optional[date_type] = None) -> float:
    """Atalho para quem só quer o número do CMV geral (motor de CMV, painel)."""
    return meta_vigente(db, unidade_id, TipoMeta.CMV_GERAL, em).valor or META_CMV_PADRAO


def historico(db: Session, unidade_id: Optional[int], limite: int = 100) -> List[Meta]:
    """Todas as vigências, da mais recente para a mais antiga."""
    return (_consulta_base(db, unidade_id)
            .order_by(Meta.vigencia_inicio.desc(), Meta.id.desc())
            .limit(limite).all())


# ---------------------------------------------------------------- escrita


def definir(db: Session, unidade_id: Optional[int], tipo: TipoMeta, valor: float,
            vigencia_inicio: Optional[date_type] = None,
            categoria_id: Optional[int] = None,
            formato: FormatoMeta = FormatoMeta.PERCENTUAL,
            periodicidade: Optional[PeriodicidadeMeta] = None,
            observacao: Optional[str] = None,
            usuario_id: Optional[int] = None,
            empresa_id: Optional[int] = None,
            origem: OrigemMeta = OrigemMeta.MANUAL) -> Meta:
    """Abre uma vigência nova e fecha a anterior.

    Nunca altera o registro existente: é isso que preserva o histórico e
    permite julgar cada período pela meta que valia nele.
    """
    inicio = vigencia_inicio or date_type.today()

    if tipo == TipoMeta.CMV_FAMILIA and not categoria_id:
        raise ErroMeta("Meta por família precisa dizer qual família.")
    if categoria_id and tipo != TipoMeta.CMV_FAMILIA:
        categoria_id = None

    if formato == FormatoMeta.PERCENTUAL:
        if valor is None or valor <= 0 or valor >= 1:
            raise ErroMeta("Percentual deve ficar entre 0 e 1 (ex.: 0.29 para 29%).")
    elif valor is None or valor < 0:
        raise ErroMeta("Valor em reais não pode ser negativo.")

    if formato == FormatoMeta.REAIS and periodicidade is None:
        periodicidade = PeriodicidadeMeta.MENSAL

    # Fecha o que estava valendo na véspera da nova vigência
    anterior = _vigente_em(db, unidade_id, tipo, inicio, categoria_id)
    if anterior and anterior.unidade_id == unidade_id:
        if anterior.vigencia_inicio == inicio:
            # Mesma data: é correção do que acabou de ser definido, não
            # uma vigência nova. Substituir evita lixo de dois registros
            # válidos no mesmo dia.
            db.delete(anterior)
        else:
            anterior.vigencia_fim = _dia_anterior(inicio)

    # Vigência retroativa: se já existe uma meta que começa DEPOIS desta, a
    # nova preenche só até a véspera dela. Uma decisão tomada depois foi
    # tomada com mais informação — corrigir o passado não pode apagar o
    # futuro que alguém já definiu.
    proxima = _proxima_apos(db, unidade_id, tipo, inicio, categoria_id)
    fim = _dia_anterior(proxima.vigencia_inicio) if proxima else None

    meta = Meta(
        empresa_id=empresa_id, unidade_id=unidade_id, tipo=tipo,
        categoria_id=categoria_id, valor=valor, formato=formato,
        periodicidade=periodicidade, vigencia_inicio=inicio, vigencia_fim=fim,
        observacao=observacao, usuario_id=usuario_id, origem=origem,
    )
    db.add(meta)
    db.commit()
    db.refresh(meta)
    return meta


def _proxima_apos(db: Session, unidade_id: Optional[int], tipo: TipoMeta,
                  inicio: date_type, categoria_id: Optional[int]) -> Optional[Meta]:
    """A meta de mesmo tipo cuja vigência começa depois da data informada."""
    query = db.query(Meta).filter(
        Meta.tipo == tipo,
        Meta.unidade_id == unidade_id,
        Meta.vigencia_inicio > inicio,
    )
    if tipo == TipoMeta.CMV_FAMILIA:
        query = query.filter(Meta.categoria_id == categoria_id)
    return query.order_by(Meta.vigencia_inicio.asc(), Meta.id.asc()).first()


def _dia_anterior(d: date_type) -> date_type:
    from datetime import timedelta
    return d - timedelta(days=1)


# ---------------------------------------------------------------- coerência


def checar_coerencia(meta_geral: Optional[float], meta_comida: Optional[float],
                     meta_bebida: Optional[float],
                     faturamento_comida: float, faturamento_bebida: float) -> Optional[str]:
    """Comida e bebida, ponderadas pelo mix real, deveriam dar a meta geral.

    Devolve o aviso quando não dão, e None quando dão (ou quando falta dado
    para saber). Não bloqueia: numa transição de cardápio a divergência
    pode ser deliberada.
    """
    if None in (meta_geral, meta_comida, meta_bebida):
        return None
    total = (faturamento_comida or 0) + (faturamento_bebida or 0)
    if total <= 0:
        return None

    peso_comida = faturamento_comida / total
    ponderada = meta_comida * peso_comida + meta_bebida * (1 - peso_comida)
    if abs(ponderada - meta_geral) < 0.005:      # meio ponto percentual de tolerância
        return None

    return (
        f"Comida {meta_comida * 100:.1f}% e bebida {meta_bebida * 100:.1f}%, no mix atual "
        f"de faturamento ({peso_comida * 100:.0f}/{(1 - peso_comida) * 100:.0f}), dão "
        f"{ponderada * 100:.1f}% — {'acima' if ponderada > meta_geral else 'abaixo'} da meta "
        f"geral de {meta_geral * 100:.1f}%."
    )


def familias(db: Session, empresa_id: Optional[int]) -> List[Categoria]:
    query = db.query(Categoria)
    if empresa_id:
        query = query.filter(Categoria.empresa_id == empresa_id)
    return query.order_by(Categoria.nome).all()


# ---------------------------------------------------------------- distribuição

"""
QUAL É O "CMV %" DE UMA FAMÍLIA
-------------------------------
Existem duas contas possíveis, e a escolha entre elas decide se as metas
somam ou não:

  (a) CMV da família ÷ faturamento TOTAL
  (b) CMV da família ÷ faturamento do bloco (comida ou bebida)

Bloco usa (b), porque é assim que a operação fala: "bebida roda a 22% do
faturamento de bebida". Mas família usa (a), e por um motivo estrutural:
só em (a) a soma das famílias dá exatamente o CMV geral.

    hortifruti 4% + carnes 11% + mercearia 6% + ... = 29%

É isso que torna possível pegar a meta geral e reparti-la. Em (b) as
famílias não somam nada — repartir seria inventar número.
"""


def realizado_por_familia(apuracao) -> Dict[int, float]:
    """CMV de cada família como fração do faturamento total do período."""
    faturamento = apuracao.geral.faturamento
    if not faturamento:
        return {}
    acumulado: Dict[int, float] = {}
    for linha in apuracao.linhas:
        if linha.categoria_id is None:
            continue
        acumulado[linha.categoria_id] = acumulado.get(linha.categoria_id, 0.0) + linha.cmv
    return {chave: round(valor / faturamento, 6) for chave, valor in acumulado.items()}


def participacoes(apuracao) -> Dict[int, float]:
    """Quanto cada família pesa dentro do CMV total (soma 1,0)."""
    total = apuracao.geral.cmv
    if not total:
        return {}
    acumulado: Dict[int, float] = {}
    for linha in apuracao.linhas:
        if linha.categoria_id is None or linha.cmv <= 0:
            continue
        acumulado[linha.categoria_id] = acumulado.get(linha.categoria_id, 0.0) + linha.cmv
    soma = sum(acumulado.values())
    if soma <= 0:
        return {}
    return {chave: valor / soma for chave, valor in acumulado.items()}


def previa_distribuicao(db: Session, apuracao, meta_geral: float,
                        unidade_id: Optional[int],
                        preservar_definidas: bool = True,
                        em: Optional[date_type] = None) -> dict:
    """Calcula, sem gravar, como a meta geral se reparte entre as famílias.

    A repartição é PROPORCIONAL AO CUSTO, não igual entre famílias. Dividir
    29% por oito famílias daria 3,6% para cada — o que condenaria carnes
    (que sozinha responde por 40% do custo) a uma meta impossível e daria à
    mercearia uma meta folgada demais para significar alguma coisa.

    Com `preservar_definidas`, as famílias com meta digitada à mão ficam de
    fora e o restante da meta geral é repartido entre as demais. É o que
    permite à diretoria travar duas ou três famílias negociadas e deixar o
    sistema cuidar do resto.

    Metas vindas de uma distribuição anterior NÃO são preservadas — senão
    redistribuir não mudaria nada, que é justamente o oposto do pedido.
    """
    em = em or date_type.today()
    pesos = participacoes(apuracao)
    if not pesos:
        return {"linhas": [], "sem_base": True, "meta_geral": meta_geral,
                "soma": 0.0, "aviso": "Sem CMV apurado no período de referência — "
                                      "não há como saber o peso de cada família."}

    nomes = {c.id: c.nome for c in db.query(Categoria).all()}

    travadas = {}
    if preservar_definidas:
        for categoria_id in pesos:
            atual = meta_vigente(db, unidade_id, TipoMeta.CMV_FAMILIA, em,
                                 categoria_id=categoria_id)
            if atual.manual:
                travadas[categoria_id] = atual.valor

    reservado = sum(travadas.values())
    peso_livre = sum(p for c, p in pesos.items() if c not in travadas)
    restante = max(meta_geral - reservado, 0.0)

    linhas = []
    for categoria_id, peso in sorted(pesos.items(), key=lambda x: x[1], reverse=True):
        if categoria_id in travadas:
            linhas.append({
                "categoria_id": categoria_id,
                "categoria": (nomes.get(categoria_id) or "").replace("Família - ", ""),
                "participacao": round(peso, 6),
                "meta": round(travadas[categoria_id], 6),
                "travada": True,
            })
            continue
        fatia = (peso / peso_livre) if peso_livre else 0.0
        linhas.append({
            "categoria_id": categoria_id,
            "categoria": (nomes.get(categoria_id) or "").replace("Família - ", ""),
            "participacao": round(peso, 6),
            "meta": round(restante * fatia, 6),
            "travada": False,
        })

    soma = sum(l["meta"] for l in linhas)
    aviso = None
    if reservado > meta_geral:
        aviso = (f"As metas travadas já somam {reservado * 100:.1f}%, acima da meta geral "
                 f"de {meta_geral * 100:.1f}%. As demais famílias ficariam com zero.")
    elif len(linhas) < len(nomes):
        faltando = len(nomes) - len(linhas)
        aviso = (f"{faltando} família(s) sem movimento no período de referência ficam de "
                 f"fora e seguem herdando a meta do bloco.")

    return {
        "linhas": linhas,
        "meta_geral": meta_geral,
        "soma": round(soma, 6),
        "reservado": round(reservado, 6),
        "sem_base": False,
        "aviso": aviso,
    }


def distribuir(db: Session, unidade_id: Optional[int], apuracao, meta_geral: float,
               vigencia_inicio: Optional[date_type] = None,
               preservar_definidas: bool = True,
               incluir_blocos: bool = True,
               observacao: Optional[str] = None,
               usuario_id: Optional[int] = None,
               empresa_id: Optional[int] = None) -> dict:
    """Grava a meta geral e a repartição entre famílias, tudo numa vigência.

    Também recalcula comida e bebida, para que a checagem de coerência não
    acuse divergência logo depois de uma distribuição automática.
    """
    inicio = vigencia_inicio or date_type.today()
    previa = previa_distribuicao(db, apuracao, meta_geral, unidade_id,
                                 preservar_definidas, inicio)
    if previa["sem_base"]:
        raise ErroMeta(previa["aviso"], http=409)

    nota = observacao or f"Distribuição automática a partir da meta geral de {meta_geral:.1%}."

    definir(db, unidade_id, TipoMeta.CMV_GERAL, meta_geral, vigencia_inicio=inicio,
            observacao=nota, usuario_id=usuario_id, empresa_id=empresa_id,
            origem=OrigemMeta.DISTRIBUICAO)

    gravadas = 0
    for linha in previa["linhas"]:
        if linha["travada"] or linha["meta"] <= 0:
            continue
        definir(db, unidade_id, TipoMeta.CMV_FAMILIA, linha["meta"],
                vigencia_inicio=inicio, categoria_id=linha["categoria_id"],
                observacao=nota, usuario_id=usuario_id, empresa_id=empresa_id,
                origem=OrigemMeta.DISTRIBUICAO)
        gravadas += 1

    if incluir_blocos:
        for tipo, bloco in ((TipoMeta.CMV_COMIDA, apuracao.comida),
                            (TipoMeta.CMV_BEBIDA, apuracao.bebida)):
            # Meta do bloco na régua dele (÷ faturamento do próprio bloco),
            # mantendo a proporção de custo observada no período de referência.
            if not bloco.faturamento or not apuracao.geral.cmv:
                continue
            peso = bloco.cmv / apuracao.geral.cmv
            valor = meta_geral * peso * (apuracao.geral.faturamento / bloco.faturamento)
            if valor <= 0 or valor >= 1:
                continue
            definir(db, unidade_id, tipo, round(valor, 6), vigencia_inicio=inicio,
                    observacao=nota, usuario_id=usuario_id, empresa_id=empresa_id,
                    origem=OrigemMeta.DISTRIBUICAO)

    return {"meta_geral": meta_geral, "familias_definidas": gravadas,
            "preservadas": sum(1 for l in previa["linhas"] if l["travada"]),
            "vigencia_inicio": inicio, "linhas": previa["linhas"],
            "aviso": previa["aviso"]}
