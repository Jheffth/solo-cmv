"""Schemas Pydantic (entrada/saída da API)."""
from datetime import datetime, date
from typing import Optional, List
from pydantic import BaseModel, ConfigDict

from models import (
    PapelUsuario, TipoMovimento, StatusSessaoInventario, TipoDespesaExtra,
    StatusRequisicao, DestinoRequisicao, MotivoPerda,
    TipoMeta, FormatoMeta, PeriodicidadeMeta, OrigemMeta, EscopoUnidades,
)


# ---------- Auth ----------
class LoginRequest(BaseModel):
    login: str
    senha: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UsuarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    login: str
    papel: PapelUsuario
    ativo: bool
    empresa_id: Optional[int] = None

    # Perfil: o que a própria pessoa mantém. Vem junto porque a barra lateral
    # mostra foto e nome desde a abertura — pedir num segundo pedido custaria
    # mais uma ida e volta de ~250 ms só para trocar as iniciais por uma foto.
    apelido: Optional[str] = None
    telefone: Optional[str] = None
    avatar_url: Optional[str] = None

    # Escopo: quais unidades e se enxerga o consolidado da rede.
    # São duas perguntas separadas — ver o comentário em models.Usuario.
    escopo_unidades: EscopoUnidades = EscopoUnidades.LISTA
    acesso_regional: bool = False
    unidades: List["UnidadeResumo"] = []


class UnidadeResumo(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str


class UsuarioAtivo(BaseModel):
    """Suspensão reversível — afastamento temporário, não exclusão."""
    ativo: bool


class UsuarioPapel(BaseModel):
    """Promoção ou rebaixamento. Quem pode dar o quê está em
    servicos/hierarquia.py — cada um concede até o próprio nível."""
    papel: PapelUsuario


class UsuarioEscopo(BaseModel):
    """Altera só o escopo de acesso, sem mexer em senha ou papel."""
    # LISTA usa `unidade_ids`; TODAS ignora a lista e acompanha as lojas
    # futuras. Guardar a lista junto com TODAS criaria uma segunda verdade,
    # desatualizada na primeira loja nova.
    escopo_unidades: EscopoUnidades = EscopoUnidades.LISTA
    unidade_ids: List[int] = []
    acesso_regional: bool = False


# ---------- Empresa / Unidade ----------
class EmpresaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    cnpj: Optional[str] = None
    ativo: bool


class UnidadeOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    empresa_id: int
    nome: str
    apelido: Optional[str] = None
    ativo: bool


class UnidadeCreate(BaseModel):
    empresa_id: int
    nome: str
    apelido: Optional[str] = None


# ---------- Categoria / Fornecedor / Produto ----------
class CategoriaOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str


class CategoriaCreate(BaseModel):
    nome: str


class FornecedorOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    cnpj: Optional[str] = None


class FornecedorCreate(BaseModel):
    nome: str
    cnpj: Optional[str] = None


class ProdutoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    nome: str
    unidade_medida: Optional[str] = None
    codigo: Optional[str] = None
    categoria_id: Optional[int] = None
    ativo: bool


class ProdutoCreate(BaseModel):
    nome: str
    unidade_medida: Optional[str] = None
    codigo: Optional[str] = None
    categoria_id: Optional[int] = None


# ---------- Movimento ----------
class MovimentoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unidade_id: int
    produto_id: int
    tipo: TipoMovimento
    quantidade: float
    custo_unitario: Optional[float] = None
    custo_total: Optional[float] = None
    fornecedor_id: Optional[int] = None
    numero_documento: Optional[str] = None
    data: date
    motivo: Optional[MotivoPerda] = None      # só em movimentos de PERDA
    observacao: Optional[str] = None

    # De onde o movimento veio. A tela mostra uma coluna só, "Nº documento":
    # nota fiscal na compra, número do inventário na contagem, número da
    # requisição na saída. Resolver aqui evita a tela ter que cruzar tabelas.
    sessao_inventario_id: Optional[int] = None
    requisicao_id: Optional[int] = None
    documento: Optional[str] = None           # o número já pronto para exibir
    documento_tipo: Optional[str] = None       # NOTA | INVENTARIO | REQUISICAO | PERDA
    unidade_nome: Optional[str] = None         # de qual loja é o lançamento


class MovimentoCreate(BaseModel):
    unidade_id: int
    produto_id: int
    tipo: TipoMovimento
    quantidade: float
    custo_unitario: Optional[float] = None
    fornecedor_id: Optional[int] = None
    numero_documento: Optional[str] = None
    data: Optional[date] = None
    sessao_inventario_id: Optional[int] = None


# ---------- Nota fiscal (lançamento em lote pelo Lançador) ----------
class NotaFiscalItem(BaseModel):
    produto_id: int
    quantidade: float
    custo_unitario: Optional[float] = None


class NotaFiscalLancamento(BaseModel):
    """Uma nota fiscal de compra com vários itens — gera um Movimento de
    COMPRA por item, todos compartilhando nº do documento, fornecedor e data."""
    unidade_id: int
    numero_documento: Optional[str] = None
    fornecedor_id: Optional[int] = None
    data: Optional[date] = None
    sessao_inventario_id: Optional[int] = None
    itens: List[NotaFiscalItem]


class NotaFiscalResultado(BaseModel):
    movimentos_criados: int
    valor_total: float
    numero_documento: Optional[str] = None


# ---------- Sessão de Inventário ----------
class SessaoInventarioOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unidade_id: int
    unidade_nome: Optional[str] = None         # preenchido na visão Regional
    numero_documento: str          # "Número Inventário"
    descricao: Optional[str] = None
    geral: bool = False
    data_abertura: datetime
    data_congelamento: Optional[datetime] = None
    data_fechamento: Optional[datetime] = None
    status: StatusSessaoInventario
    observacao: Optional[str] = None
    categorias: List[CategoriaOut] = []


class SessaoInventarioAbrir(BaseModel):
    unidade_id: int
    descricao: Optional[str] = None
    geral: bool = False                      # True = todas as famílias
    categoria_ids: List[int] = []            # usado quando geral = False
    observacao: Optional[str] = None


class InventarioItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    produto_id: int
    codigo: Optional[str] = None
    produto: Optional[str] = None
    categoria: Optional[str] = None
    unidade_medida: Optional[str] = None
    quantidade_sistema: float
    quantidade_contada: Optional[float] = None
    custo_unitario: Optional[float] = None
    divergencia: float = 0
    valor_divergencia: float = 0


class InventarioDetalheOut(BaseModel):
    sessao: SessaoInventarioOut
    itens: List[InventarioItemOut]
    resumo: dict


class ContagemItem(BaseModel):
    produto_id: int
    quantidade: float
    acumular: bool = False


class ContagemLancamento(BaseModel):
    """Contagem vinda de qualquer canal (tela web hoje, bot do Telegram amanhã).

    O inventário pode ser identificado pelo id interno ou pelo número junto
    da unidade; o produto, pelo id ou pelo código de 6 dígitos.
    """
    quantidade: float
    sessao_id: Optional[int] = None
    numero_inventario: Optional[str] = None
    unidade_id: Optional[int] = None
    produto_id: Optional[int] = None
    codigo_produto: Optional[str] = None
    origem: Optional[str] = None
    acumular: bool = False


# ---------- Requisições ----------
class RequisicaoAbrir(BaseModel):
    unidade_id: int
    descricao: Optional[str] = None
    solicitante: Optional[str] = None
    data_producao: Optional[date] = None
    observacao: Optional[str] = None


class RequisicaoItemOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    produto_id: int
    codigo: Optional[str] = None
    produto: Optional[str] = None
    categoria: Optional[str] = None
    unidade_medida: Optional[str] = None
    quantidade: float
    custo_unitario: Optional[float] = None
    saldo_no_pedido: Optional[float] = None
    saldo_atual: Optional[float] = None
    valor_total: float = 0
    observacao: Optional[str] = None


class RequisicaoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unidade_id: int
    unidade_nome: Optional[str] = None         # preenchido na visão Regional
    numero: str
    descricao: Optional[str] = None
    destino: DestinoRequisicao
    solicitante: Optional[str] = None
    data_producao: Optional[date] = None
    observacao: Optional[str] = None
    status: StatusRequisicao
    data_abertura: datetime
    data_inicio: Optional[datetime] = None
    data_atendimento: Optional[datetime] = None


class RequisicaoDetalheOut(BaseModel):
    requisicao: RequisicaoOut
    itens: List[RequisicaoItemOut]
    resumo: dict


class RequisicaoItemLancamento(BaseModel):
    """Item de requisição vindo de qualquer canal (web hoje, bot amanhã)."""
    quantidade: float
    requisicao_id: Optional[int] = None
    numero_requisicao: Optional[str] = None
    unidade_id: Optional[int] = None
    produto_id: Optional[int] = None
    codigo_produto: Optional[str] = None
    observacao: Optional[str] = None
    origem: Optional[str] = None


class RequisicaoItemResultado(BaseModel):
    item: RequisicaoItemOut
    numero_requisicao: str
    status_requisicao: StatusRequisicao
    substituiu: bool
    quantidade_anterior: Optional[float] = None
    saldo_disponivel: float
    mensagem: str


class ContagemResultado(BaseModel):
    item: InventarioItemOut
    numero_inventario: str
    status_inventario: StatusSessaoInventario
    primeira_contagem: bool
    valor_anterior: Optional[float] = None
    mensagem: str


# ---------- Venda por período ----------
class VendaPeriodoOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unidade_id: int
    data_inicio: date
    data_fim: date
    faturamento_total: float
    faturamento_comida: Optional[float] = None
    faturamento_bebida: Optional[float] = None
    observacao: Optional[str] = None


class VendaPeriodoCreate(BaseModel):
    unidade_id: int
    data_inicio: date
    data_fim: date
    faturamento_total: float
    faturamento_comida: Optional[float] = None
    faturamento_bebida: Optional[float] = None
    observacao: Optional[str] = None


# ---------- Despesa extra ----------
class DespesaExtraOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    unidade_id: int
    tipo: TipoDespesaExtra
    valor: float
    data_inicio: date
    data_fim: date
    descricao: Optional[str] = None


class DespesaExtraCreate(BaseModel):
    unidade_id: int
    tipo: TipoDespesaExtra
    valor: float
    data_inicio: date
    data_fim: date
    descricao: Optional[str] = None


# ---------- Perda ----------
class PerdaLancamento(BaseModel):
    unidade_id: int
    quantidade: float
    motivo: MotivoPerda
    produto_id: Optional[int] = None
    codigo_produto: Optional[str] = None   # aceita código no lugar do id (bot, coletor)
    data: Optional[date] = None
    observacao: Optional[str] = None
    custo_unitario: Optional[float] = None  # se ausente, usa o último custo conhecido


class PerdaOut(BaseModel):
    id: int
    unidade_id: int
    produto_id: int
    produto: str
    codigo: Optional[str] = None
    categoria: Optional[str] = None
    quantidade: float
    unidade_medida: Optional[str] = None
    custo_unitario: Optional[float] = None
    custo_total: Optional[float] = None
    motivo: MotivoPerda
    motivo_rotulo: str
    observacao: Optional[str] = None
    numero_documento: Optional[str] = None
    data: date


class PerdaResultado(BaseModel):
    perda: PerdaOut
    saldo_anterior: float
    saldo_atual: float


class PerdaResumoMotivo(BaseModel):
    motivo: MotivoPerda
    rotulo: str
    ocorrencias: int
    quantidade: float
    valor: float


class PerdaResumo(BaseModel):
    total_ocorrencias: int
    valor_total: float
    por_motivo: List[PerdaResumoMotivo]


# ---------- Metas ----------
class MetaLinha(BaseModel):
    """Uma meta pronta para a tela: o alvo, de onde ele veio e o realizado."""
    tipo: TipoMeta
    rotulo: str
    categoria_id: Optional[int] = None
    categoria: Optional[str] = None

    valor: Optional[float] = None
    formato: FormatoMeta = FormatoMeta.PERCENTUAL
    periodicidade: Optional[PeriodicidadeMeta] = None
    vigencia_inicio: Optional[date] = None

    definida: bool = False           # False = herdada ou padrão do sistema
    origem: OrigemMeta = OrigemMeta.MANUAL
    manual: bool = False             # digitada à mão, não vinda da distribuição
    herdada_de: Optional[TipoMeta] = None
    herdada_rotulo: Optional[str] = None
    padrao_do_sistema: bool = False

    # O que a operação entregou no período de referência — é o que torna a
    # definição de meta um ato informado, e não um chute.
    realizado: Optional[float] = None
    atingida: Optional[bool] = None


class MetaPainel(BaseModel):
    unidade_id: Optional[int] = None
    periodo_rotulo: str
    data_inicio: date
    data_fim: date
    cmv: List[MetaLinha]
    familias: List[MetaLinha]
    perdas: MetaLinha
    faturamento: MetaLinha
    aviso_coerencia: Optional[str] = None
    pode_editar: bool = False


class MetaDefinicao(BaseModel):
    unidade_id: Optional[int] = None
    tipo: TipoMeta
    categoria_id: Optional[int] = None
    valor: float
    formato: FormatoMeta = FormatoMeta.PERCENTUAL
    periodicidade: Optional[PeriodicidadeMeta] = None
    vigencia_inicio: Optional[date] = None
    observacao: Optional[str] = None


class MetaHistoricoItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    tipo: TipoMeta
    rotulo: str
    categoria: Optional[str] = None
    valor: float
    formato: FormatoMeta
    vigencia_inicio: date
    vigencia_fim: Optional[date] = None
    observacao: Optional[str] = None
    usuario: Optional[str] = None
    criado_em: datetime


class MetaDistribuicao(BaseModel):
    """Define a meta geral e reparte entre as famílias, proporcional ao custo.

    O período de referência serve só para descobrir o peso de cada família
    no CMV — não é o período de vigência da meta.
    """
    unidade_id: Optional[int] = None
    meta_geral: float
    data_inicio: Optional[date] = None
    data_fim: Optional[date] = None
    vigencia_inicio: Optional[date] = None
    preservar_definidas: bool = True     # não mexe nas famílias já negociadas
    incluir_blocos: bool = True          # recalcula também comida e bebida
    observacao: Optional[str] = None
