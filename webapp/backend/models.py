"""
Modelo de dados do Solo CMV.

UMA INSTALAÇÃO, UMA REDE
------------------------
Esta instalação é a Rede Josefina. Outra rede será outra instalação — outro
banco, outro deploy — e não um segundo inquilino aqui dentro. A tabela
`empresas` existe e tem uma linha só; ela dá um dono às unidades, produtos e
metas, e é isso.

Por que isso está escrito aqui: o modelo *parece* multiempresa, e essa
aparência já custou caro uma vez — a tela de convite pedia "id da empresa"
ao Arquiteto porque o código decidia pelo papel, e não pelo que sabia. Se
você está lendo isto pensando em acrescentar uma segunda empresa, o caminho
é uma instalação nova, não uma linha nova.

Replica as regras de controle de estoque e CMV hoje operadas nas planilhas
"INVENTÁRIO E CMV" (Josefina / Casa Josefina).

Seções já modeladas mas com regra de negócio ainda não implementada (fases
futuras do plano de migração) ficam claramente sinalizadas nos comentários.
"""
import enum
from datetime import datetime, date

from sqlalchemy import (
    Column, Integer, String, Float, Boolean, Date, DateTime, ForeignKey,
    Enum, Text, Table, UniqueConstraint,
)
from sqlalchemy.orm import relationship

from database import Base


def Enumerado(enum_classe, **kwargs):
    """Coluna de enum guardada como TEXTO, não como tipo nativo do banco.

    POR QUE NÃO O ENUM NATIVO DO POSTGRESQL
    ---------------------------------------
    Com `Enum(...)` puro, o SQLAlchemy cria um TYPE de verdade no PostgreSQL.
    Acrescentar um valor passa a exigir `ALTER TYPE ... ADD VALUE` — uma
    migração por valor novo, que não roda dentro de transação em versões
    antigas e é um estorvo real.

    Só neste projeto já acrescentamos DIRETOR, PERDA, DISTRIBUICAO e seis
    tipos de meta. Guardar como VARCHAR sem CHECK deixa o custo em zero: o
    SQLAlchemy continua validando na entrada e na saída (valor fora do enum
    levanta erro em Python), e o banco fica agnóstico.

    O mesmo mapeamento vale para SQLite e PostgreSQL — o que também mantém
    a migração de dados trivial: texto para texto.
    """
    return Enum(enum_classe, native_enum=False, create_constraint=False,
                length=40, validate_strings=True, **kwargs)


# ==============================================================================
# ENUMS
# ==============================================================================
class PapelUsuario(str, enum.Enum):
    """Hierarquia de acesso, do mais amplo ao mais restrito.

    ARQUITETO e DIRETOR são ambos irrestritos; a diferença é a fronteira.
    O Arquiteto atravessa empresas (é quem opera o produto); o Diretor é o
    topo *de uma empresa* — vê e faz tudo dentro dela, e nada fora.
    """
    ARQUITETO = "ARQUITETO"   # dono do sistema — acesso irrestrito a todas as empresas
    DIRETOR = "DIRETOR"       # topo da empresa — acesso total dentro dela, define metas
    ADMIN = "ADMIN"           # administra a empresa/unidades
    GERENTE = "GERENTE"       # lança, aprova e vê relatórios da(s) unidade(s)
    OPERADOR = "OPERADOR"     # lança compras/contagens no dia a dia


# Quem passa por qualquer verificação de papel, sem precisar ser listado
# endpoint a endpoint. Manter aqui evita esquecer um dos dois num lugar só.
PAPEIS_IRRESTRITOS = (PapelUsuario.ARQUITETO, PapelUsuario.DIRETOR)


class EscopoUnidades(str, enum.Enum):
    """Como as unidades de um usuário são decididas: por lista ou por regra.

    LISTA é uma fotografia — "estas duas lojas". Abrir a Josefina Asa Sul
    amanhã não muda nada para quem tem LISTA, e é isso que se quer: o gerente
    da Casa Josefina não passa a enxergar a loja nova sem alguém decidir.

    TODAS é uma regra — "todas as lojas da empresa". Acompanha as que ainda
    não existem. É o que o convite chama de acesso Regional.

    Antes disso, "todas as unidades" só existia colado ao papel: ARQUITETO e
    DIRETOR enxergam tudo porque são irrestritos. Quem precisasse ver a rede
    inteira sem ser da diretoria não tinha como — ou virava Diretor, o que dá
    muito mais poder do que se queria dar, ou recebia uma lista que envelhecia
    a cada loja nova.
    """
    LISTA = "LISTA"
    TODAS = "TODAS"


class TipoMovimento(str, enum.Enum):
    COMPRA = "COMPRA"
    CONTAGEM_INICIAL = "CONTAGEM_INICIAL"
    CONTAGEM_FINAL = "CONTAGEM_FINAL"
    REQUISICAO = "REQUISICAO"   # saída de estoque (hoje, sempre para a produção)
    PERDA = "PERDA"             # saída sem produção: quebra, vencimento, furto…


class MotivoPerda(str, enum.Enum):
    """Por que o item saiu do estoque sem virar venda.

    Separar o motivo é o que transforma a perda em informação útil: perda por
    validade acusa compra em excesso, por quebra acusa manuseio, por furto
    acusa controle. Somadas num número só, todas viram 'CMV alto' e ninguém
    sabe onde agir.
    """
    QUEBRA = "QUEBRA"                 # quebrou, caiu, estragou no manuseio
    VALIDADE = "VALIDADE"             # venceu antes de ser usado
    DETERIORACAO = "DETERIORACAO"     # estragou (hortifruti, refrigeração)
    ERRO_PRODUCAO = "ERRO_PRODUCAO"   # preparo errado, prato descartado
    FURTO = "FURTO"                   # desvio
    CONSUMO_INTERNO = "CONSUMO_INTERNO"  # refeição de funcionário, degustação, cortesia
    OUTRO = "OUTRO"


class StatusRequisicao(str, enum.Enum):
    """Ciclo de vida da requisição.

    ABERTA   -> criada, ainda NÃO recebe itens (precisa ser iniciada)
    INICIADA -> em preenchimento; aceita o lançamento dos itens pedidos
    ATENDIDA -> itens baixados do estoque e enviados para a produção
    CANCELADA-> descartada, mas segue consultável
    """
    ABERTA = "ABERTA"
    INICIADA = "INICIADA"
    ATENDIDA = "ATENDIDA"
    CANCELADA = "CANCELADA"


class MetodoCusto(str, enum.Enum):
    """Como o estoque final é valorizado no cálculo do CMV.

    CUSTO_MEDIO   -> custo médio ponderado do período:
                     (valor inicial + valor das compras) ÷ (qtd inicial + qtd comprada).
                     É o padrão: suaviza oscilações de preço entre compras.
    ULTIMO_CUSTO  -> último custo conhecido do produto, que é o que a
                     planilha faz (cada contagem usa o custo vigente na data).
    """
    CUSTO_MEDIO = "CUSTO_MEDIO"
    ULTIMO_CUSTO = "ULTIMO_CUSTO"


class ModoApuracao(str, enum.Enum):
    """Recorte do cálculo.

    PERIODO   -> só o intervalo pedido. O estoque inicial é a contagem
                 imediatamente anterior ao início; as compras são as do
                 intervalo. É o equivalente a uma aba SEM__ da planilha.
    ACUMULADO -> desde o começo do controle até a data final. O estoque
                 inicial é a primeira contagem já registrada.
    """
    PERIODO = "PERIODO"
    ACUMULADO = "ACUMULADO"


class DestinoRequisicao(str, enum.Enum):
    """Para onde vai o que sai do estoque.

    Hoje só existe PRODUCAO. O enum já existe para que outros destinos
    (perda, transferência entre unidades, consumo interno) entrem depois sem
    quebrar o que estiver gravado.
    """
    PRODUCAO = "PRODUCAO"


class StatusSessaoInventario(str, enum.Enum):
    """Ciclo de vida do inventário.

    ABERTO      -> criado e com escopo definido, mas NÃO aceita contagem ainda.
    CONGELADO   -> estoque fotografado (snapshot); a partir daqui aceita contagem.
    EM_CONTAGEM -> já tem pelo menos uma contagem lançada.
    FINALIZADO  -> contagens aplicadas ao estoque; encerrado.
    CANCELADO   -> descartado, mas permanece consultável para análise.
    """
    ABERTO = "ABERTO"
    CONGELADO = "CONGELADO"
    EM_CONTAGEM = "EM_CONTAGEM"
    FINALIZADO = "FINALIZADO"
    CANCELADO = "CANCELADO"


class TipoDespesaExtra(str, enum.Enum):
    CONSUMO_INTERNO = "CONSUMO_INTERNO"
    MATERIAL_LIMPEZA = "MATERIAL_LIMPEZA"
    EMBALAGENS = "EMBALAGENS"
    TESTES_MKT = "TESTES_MKT"
    OUTRAS = "OUTRAS"


class StatusNotaFiscal(str, enum.Enum):
    PENDENTE = "PENDENTE"
    PROCESSADA = "PROCESSADA"
    ERRO = "ERRO"


# ==============================================================================
# ASSOCIAÇÃO usuário <-> unidade (escopo de acesso)
# ==============================================================================
usuario_unidade = Table(
    "usuario_unidade",
    Base.metadata,
    Column("usuario_id", Integer, ForeignKey("usuarios.id"), primary_key=True),
    Column("unidade_id", Integer, ForeignKey("unidades.id"), primary_key=True),
)

# Quais famílias contam como BEBIDA no desdobramento do CMV.
# Na planilha isso era um texto fixo dentro da fórmula ("*Bebidas bar*"), que
# parou de funcionar quando as famílias foram renomeadas. Aqui o vínculo é
# por id — renomear a família não quebra nada.
cmv_familia_bebida = Table(
    "cmv_familia_bebida",
    Base.metadata,
    Column("configuracao_id", Integer, ForeignKey("configuracoes_cmv.id"), primary_key=True),
    Column("categoria_id", Integer, ForeignKey("categorias.id"), primary_key=True),
)

# Escopo do inventário: quais famílias/setores ele cobre.
# Inventário "geral" (flag na sessão) cobre todas e não usa esta tabela.
inventario_categoria = Table(
    "inventario_categoria",
    Base.metadata,
    Column("sessao_inventario_id", Integer, ForeignKey("sessoes_inventario.id"), primary_key=True),
    Column("categoria_id", Integer, ForeignKey("categorias.id"), primary_key=True),
)


# ==============================================================================
# EMPRESA / UNIDADE — base multicliente e multiunidade
# ==============================================================================
class Empresa(Base):
    __tablename__ = "empresas"

    id = Column(Integer, primary_key=True)
    nome = Column(String(150), nullable=False)
    cnpj = Column(String(20), nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidades = relationship("Unidade", back_populates="empresa", cascade="all, delete-orphan")
    usuarios = relationship("Usuario", back_populates="empresa")
    categorias = relationship("Categoria", back_populates="empresa", cascade="all, delete-orphan")
    fornecedores = relationship("Fornecedor", back_populates="empresa", cascade="all, delete-orphan")
    produtos = relationship("Produto", back_populates="empresa", cascade="all, delete-orphan")
    certificados = relationship("CertificadoDigital", back_populates="empresa", cascade="all, delete-orphan")


class Unidade(Base):
    __tablename__ = "unidades"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    nome = Column(String(120), nullable=False)
    apelido = Column(String(60), nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa", back_populates="unidades")
    usuarios = relationship("Usuario", secondary=usuario_unidade, back_populates="unidades")
    movimentos = relationship("Movimento", back_populates="unidade", cascade="all, delete-orphan")
    sessoes_inventario = relationship("SessaoInventario", back_populates="unidade", cascade="all, delete-orphan")
    requisicoes = relationship("Requisicao", back_populates="unidade", cascade="all, delete-orphan")
    vendas_periodo = relationship("VendaPeriodo", back_populates="unidade", cascade="all, delete-orphan")
    despesas_extra = relationship("DespesaExtra", back_populates="unidade", cascade="all, delete-orphan")
    metas_cmv = relationship("MetaCMV", back_populates="unidade", cascade="all, delete-orphan")


# ==============================================================================
# USUÁRIO / AUTENTICAÇÃO
# ==============================================================================
class Usuario(Base):
    __tablename__ = "usuarios"

    id = Column(Integer, primary_key=True)
    # Todo mundo pertence à empresa da instalação, o Arquiteto inclusive.
    # Nulo é tolerado por herança do modelo antigo, mas não é o caminho:
    # usuário sem empresa não tem unidade possível nem convite que herde.
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=True)
    nome = Column(String(120), nullable=False)
    login = Column(String(60), unique=True, nullable=False, index=True)
    senha_hash = Column(String(255), nullable=False)
    papel = Column(Enumerado(PapelUsuario), nullable=False, default=PapelUsuario.OPERADOR)
    ativo = Column(Boolean, default=True, nullable=False)

    # Ver a consolidação de TODAS as unidades é permissão à parte do papel:
    # um gerente pode responder por duas lojas sem que a diretoria queira
    # que ele enxergue o número da rede inteira.
    acesso_regional = Column(Boolean, default=False, nullable=False)

    # LISTA = exatamente as unidades vinculadas abaixo.
    # TODAS = todas as da empresa, inclusive as que ainda não existem.
    #
    # São duas perguntas diferentes, e misturá-las seria erro: `escopo_unidades`
    # responde QUAIS lojas a pessoa enxerga; `acesso_regional` responde se ela
    # pode ver a SOMA delas. Dá para ver as duas lojas sem ver o número da rede,
    # e dá para acompanhar todas as lojas sem que isso implique ver o total.
    escopo_unidades = Column(Enumerado(EscopoUnidades), nullable=False,
                             default=EscopoUnidades.LISTA)

    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    # EXCLUSÃO QUE NÃO APAGA A HISTÓRIA
    #
    # Apagar a linha do usuário deixaria órfão todo movimento que ele lançou:
    # a compra continuaria no estoque, o inventário continuaria valendo, e
    # ninguém saberia mais quem contou o quê. Relatório antigo perderia o
    # autor retroativamente — o passado mudaria.
    #
    # Então "excluir" tira o acesso e some da lista de gente, mas a linha
    # fica. O nome continua resolvendo nos lançamentos de antes.
    #
    # Diferente de `ativo`, que é suspensão: reversível, para afastamento
    # temporário. A exclusão é definitiva e guarda quem a fez.
    excluido_em = Column(DateTime, nullable=True)
    excluido_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    empresa = relationship("Empresa", back_populates="usuarios")
    # Unidades que o usuário pode ver. Lista vazia = nenhuma (para papéis
    # comuns); ARQUITETO e DIRETOR passam por cima disso.
    unidades = relationship("Unidade", secondary=usuario_unidade, back_populates="usuarios")
    # Auto-referência: a chave estrangeira `excluido_por_id` aponta para a
    # mesma tabela, então o SQLAlchemy precisa saber por qual coluna juntar.
    excluido_por = relationship("Usuario", remote_side=[id],
                                foreign_keys=[excluido_por_id])

    @property
    def excluido(self) -> bool:
        return self.excluido_em is not None


# ==============================================================================
# CADASTROS MESTRES — Categoria (Família), Fornecedor, Produto
# ==============================================================================
class Categoria(Base):
    __tablename__ = "categorias"
    __table_args__ = (UniqueConstraint("empresa_id", "nome", name="uq_categoria_empresa_nome"),)

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    nome = Column(String(120), nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa", back_populates="categorias")
    produtos = relationship("Produto", back_populates="categoria")


class Fornecedor(Base):
    __tablename__ = "fornecedores"
    __table_args__ = (UniqueConstraint("empresa_id", "nome", name="uq_fornecedor_empresa_nome"),)

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    nome = Column(String(200), nullable=False)
    cnpj = Column(String(20), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa", back_populates="fornecedores")
    movimentos = relationship("Movimento", back_populates="fornecedor")


class Produto(Base):
    __tablename__ = "produtos"
    __table_args__ = (UniqueConstraint("empresa_id", "nome", name="uq_produto_empresa_nome"),)

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)
    nome = Column(String(200), nullable=False)
    unidade_medida = Column(String(20), nullable=True)  # Kg, L, Und, etc.
    codigo = Column(String(50), nullable=True)
    ativo = Column(Boolean, default=True, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa", back_populates="produtos")
    categoria = relationship("Categoria", back_populates="produtos")
    movimentos = relationship("Movimento", back_populates="produto")
    historico_custos = relationship("HistoricoCusto", back_populates="produto")


# ==============================================================================
# MOVIMENTOS — ledger transacional (equivalente à aba "Registros")
# ==============================================================================
class Movimento(Base):
    __tablename__ = "movimentos"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    tipo = Column(Enumerado(TipoMovimento), nullable=False)
    quantidade = Column(Float, nullable=False, default=0)
    custo_unitario = Column(Float, nullable=True)
    custo_total = Column(Float, nullable=True)
    fornecedor_id = Column(Integer, ForeignKey("fornecedores.id"), nullable=True)
    numero_documento = Column(String(60), nullable=True)
    data = Column(Date, nullable=False, default=date.today)
    sessao_inventario_id = Column(Integer, ForeignKey("sessoes_inventario.id"), nullable=True)
    requisicao_id = Column(Integer, ForeignKey("requisicoes.id"), nullable=True)
    # Só a perda usa: diz por que o item saiu sem virar venda
    motivo = Column(Enumerado(MotivoPerda), nullable=True)
    observacao = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidade = relationship("Unidade", back_populates="movimentos")
    produto = relationship("Produto", back_populates="movimentos")
    fornecedor = relationship("Fornecedor", back_populates="movimentos")
    sessao_inventario = relationship("SessaoInventario", back_populates="movimentos")


# ==============================================================================
# SESSÃO DE INVENTÁRIO — equivalente às macros AbrirInventario / FecharInventario
# ==============================================================================
class SessaoInventario(Base):
    __tablename__ = "sessoes_inventario"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    numero_documento = Column(String(60), nullable=False)   # "Número Inventário" (01, 02, …)
    descricao = Column(String(255), nullable=True)          # nome livre dado pelo usuário
    geral = Column(Boolean, default=False, nullable=False)  # True = cobre todas as famílias
    data_abertura = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_congelamento = Column(DateTime, nullable=True)     # quando o estoque foi fotografado
    data_fechamento = Column(DateTime, nullable=True)
    status = Column(Enumerado(StatusSessaoInventario), nullable=False, default=StatusSessaoInventario.ABERTO)
    observacao = Column(Text, nullable=True)
    usuario_abertura_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario_fechamento_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    unidade = relationship("Unidade", back_populates="sessoes_inventario")
    movimentos = relationship("Movimento", back_populates="sessao_inventario")
    categorias = relationship("Categoria", secondary=inventario_categoria)
    itens = relationship("InventarioItem", back_populates="sessao", cascade="all, delete-orphan")


class ConfiguracaoCMV(Base):
    """Preferências de apuração do CMV por unidade.

    Existe uma linha por unidade, criada sob demanda com os padrões.
    """
    __tablename__ = "configuracoes_cmv"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False, unique=True)

    metodo_custo = Column(Enumerado(MetodoCusto), nullable=False, default=MetodoCusto.CUSTO_MEDIO)
    modo_apuracao = Column(Enumerado(ModoApuracao), nullable=False, default=ModoApuracao.PERIODO)
    meta_percentual = Column(Float, nullable=False, default=0.29)   # 29%, como na planilha

    atualizado_em = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    unidade = relationship("Unidade")
    familias_bebida = relationship("Categoria", secondary=cmv_familia_bebida)


class Requisicao(Base):
    """Pedido de retirada de itens do estoque.

    Diferente do inventário, a requisição não tem escopo por família: quem
    requisita escolhe livremente qualquer item cadastrado. O destino, por
    enquanto, é sempre a produção — a requisição atendida é o que alimenta a
    agenda de produção (campo `data_producao`).
    """
    __tablename__ = "requisicoes"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    numero = Column(String(60), nullable=False)          # sequência própria, por unidade
    descricao = Column(String(255), nullable=True)       # nome livre dado pelo requisitante
    destino = Column(Enumerado(DestinoRequisicao), nullable=False, default=DestinoRequisicao.PRODUCAO)
    data_producao = Column(Date, nullable=True)          # para quando é o pedido (agenda)
    solicitante = Column(String(120), nullable=True)     # quem pediu (texto livre)
    observacao = Column(Text, nullable=True)

    status = Column(Enumerado(StatusRequisicao), nullable=False, default=StatusRequisicao.ABERTA)
    data_abertura = Column(DateTime, default=datetime.utcnow, nullable=False)
    data_inicio = Column(DateTime, nullable=True)        # quando passou a aceitar itens
    data_atendimento = Column(DateTime, nullable=True)   # quando saiu do estoque

    usuario_abertura_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usuario_atendimento_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)

    unidade = relationship("Unidade", back_populates="requisicoes")
    itens = relationship("RequisicaoItem", back_populates="requisicao", cascade="all, delete-orphan")


class RequisicaoItem(Base):
    """Uma linha da requisição: produto e quantidade pedida."""
    __tablename__ = "requisicao_itens"
    __table_args__ = (UniqueConstraint("requisicao_id", "produto_id", name="uq_req_item"),)

    id = Column(Integer, primary_key=True)
    requisicao_id = Column(Integer, ForeignKey("requisicoes.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)

    quantidade = Column(Float, nullable=False, default=0)
    custo_unitario = Column(Float, nullable=True)   # congelado no atendimento
    saldo_no_pedido = Column(Float, nullable=True)  # saldo do estoque quando foi pedido
    observacao = Column(String(255), nullable=True)
    lancado_em = Column(DateTime, default=datetime.utcnow, nullable=False)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    origem = Column(String(20), nullable=True)      # WEB, TELEGRAM, API

    requisicao = relationship("Requisicao", back_populates="itens")
    produto = relationship("Produto")

    @property
    def valor_total(self) -> float:
        return round(self.quantidade * (self.custo_unitario or 0), 2)


class InventarioItem(Base):
    """Uma linha do inventário: o que o sistema dizia e o que foi contado.

    Criada no momento do CONGELAMENTO, com a fotografia do estoque de cada
    produto do escopo. É o que permite comparar depois: quantidade do sistema
    (antes) × quantidade contada (real) = divergência e valor de perda.
    """
    __tablename__ = "inventario_itens"
    __table_args__ = (UniqueConstraint("sessao_inventario_id", "produto_id", name="uq_inv_item"),)

    id = Column(Integer, primary_key=True)
    sessao_inventario_id = Column(Integer, ForeignKey("sessoes_inventario.id"), nullable=False)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)

    quantidade_sistema = Column(Float, nullable=False, default=0)   # snapshot no congelamento
    quantidade_contada = Column(Float, nullable=True)               # nulo = ainda não contado
    custo_unitario = Column(Float, nullable=True)                   # último custo no congelamento
    contado_em = Column(DateTime, nullable=True)
    usuario_contagem_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    # De onde veio a contagem: WEB, TELEGRAM, API… (ver servicos/contagem.py)
    origem = Column(String(20), nullable=True)

    sessao = relationship("SessaoInventario", back_populates="itens")
    produto = relationship("Produto")

    @property
    def divergencia(self) -> float:
        """Contado − sistema. Negativo = faltou (perda); positivo = sobrou."""
        if self.quantidade_contada is None:
            return 0.0
        return round(self.quantidade_contada - self.quantidade_sistema, 3)

    @property
    def valor_divergencia(self) -> float:
        return round(self.divergencia * (self.custo_unitario or 0), 2)


# ==============================================================================
# HISTÓRICO DE CUSTO — equivalente à aba "UCustoInfo"
# ==============================================================================
class HistoricoCusto(Base):
    __tablename__ = "historico_custos"

    id = Column(Integer, primary_key=True)
    produto_id = Column(Integer, ForeignKey("produtos.id"), nullable=False)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    custo = Column(Float, nullable=False)
    data = Column(Date, nullable=False, default=date.today)
    numero_documento = Column(String(60), nullable=True)
    fornecedor_id = Column(Integer, ForeignKey("fornecedores.id"), nullable=True)

    produto = relationship("Produto", back_populates="historico_custos")


# ==============================================================================
# VENDA POR PERÍODO — faturamento informado manualmente pelo usuário
# (fonte do CMV % enquanto não há integração com PDV/certificado digital)
# ==============================================================================
class VendaPeriodo(Base):
    __tablename__ = "vendas_periodo"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=False)
    faturamento_total = Column(Float, nullable=False, default=0)
    faturamento_comida = Column(Float, nullable=True)
    faturamento_bebida = Column(Float, nullable=True)
    observacao = Column(Text, nullable=True)
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidade = relationship("Unidade", back_populates="vendas_periodo")


# ==============================================================================
# DESPESA EXTRA — ajustes do CMV bruto (aba RESUMO)
# ==============================================================================
class DespesaExtra(Base):
    __tablename__ = "despesas_extra"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    tipo = Column(Enumerado(TipoDespesaExtra), nullable=False)
    valor = Column(Float, nullable=False, default=0)
    data_inicio = Column(Date, nullable=False)
    data_fim = Column(Date, nullable=False)
    descricao = Column(String(255), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidade = relationship("Unidade", back_populates="despesas_extra")


# ==============================================================================
# META DE CMV
# ==============================================================================
class MetaCMV(Base):
    __tablename__ = "metas_cmv"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    percentual_meta = Column(Float, nullable=False)
    vigente_desde = Column(Date, nullable=False, default=date.today)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidade = relationship("Unidade", back_populates="metas_cmv")


# ==============================================================================
# INTEGRAÇÃO FUTURA — Certificado Digital / Importação de NF-e
# Estrutura já modelada (Fase 10 do plano de migração); regra de negócio e
# integração com a SEFAZ ainda não implementadas.
# ==============================================================================
class CertificadoDigital(Base):
    __tablename__ = "certificados_digitais"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    nome_arquivo = Column(String(255), nullable=True)
    tipo = Column(String(10), nullable=True)  # "A1" ou "A3"
    validade = Column(Date, nullable=True)
    ativo = Column(Boolean, default=False, nullable=False)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa", back_populates="certificados")


class NotaFiscalImportada(Base):
    __tablename__ = "notas_fiscais_importadas"

    id = Column(Integer, primary_key=True)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=False)
    chave_acesso = Column(String(60), nullable=True)
    numero = Column(String(30), nullable=True)
    fornecedor_id = Column(Integer, ForeignKey("fornecedores.id"), nullable=True)
    data_emissao = Column(Date, nullable=True)
    valor_total = Column(Float, nullable=True)
    status = Column(Enumerado(StatusNotaFiscal), nullable=False, default=StatusNotaFiscal.PENDENTE)
    xml_bruto = Column(Text, nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)


# ==============================================================================
# METAS — os números que a diretoria define para o negócio perseguir
# ==============================================================================
class TipoMeta(str, enum.Enum):
    CMV_GERAL = "CMV_GERAL"
    CMV_COMIDA = "CMV_COMIDA"
    CMV_BEBIDA = "CMV_BEBIDA"
    CMV_FAMILIA = "CMV_FAMILIA"   # usa categoria_id
    PERDAS = "PERDAS"
    FATURAMENTO = "FATURAMENTO"


class FormatoMeta(str, enum.Enum):
    PERCENTUAL = "PERCENTUAL"   # 0.29 = 29%
    REAIS = "REAIS"


class PeriodicidadeMeta(str, enum.Enum):
    MENSAL = "MENSAL"
    SEMANAL = "SEMANAL"


class OrigemMeta(str, enum.Enum):
    """Quem decidiu o número.

    Sem essa distinção, redistribuir a meta geral não mexeria em nada: as
    metas da distribuição anterior seriam confundidas com decisões manuais
    e ficariam todas travadas. "Preservar o que foi negociado" só significa
    alguma coisa se dá para saber o que foi negociado.
    """
    MANUAL = "MANUAL"              # alguém digitou o número
    DISTRIBUICAO = "DISTRIBUICAO"  # caiu da repartição da meta geral


class Meta(Base):
    """Um valor-alvo com data de validade.

    POR QUE NÃO É UM CAMPO SOLTO
    ----------------------------
    A meta muda com o tempo, e o histórico precisa ser julgado pela meta que
    valia na época. Guardando um número só (como era em ConfiguracaoCMV),
    trocar 29% por 27% em setembro faria o gráfico de acompanhamento
    recalcular março, abril e maio contra uma meta que não existia — o
    passado seria reescrito em silêncio.

    Por isso meta não se edita: definir um valor novo fecha a vigência do
    anterior e abre outra. Histórico e auditoria saem de graça.
    """
    __tablename__ = "metas"

    id = Column(Integer, primary_key=True)
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=True)
    # Nulo = vale para todas as unidades da empresa (gancho da visão REGIONAL)
    unidade_id = Column(Integer, ForeignKey("unidades.id"), nullable=True)

    tipo = Column(Enumerado(TipoMeta), nullable=False)
    categoria_id = Column(Integer, ForeignKey("categorias.id"), nullable=True)  # só em CMV_FAMILIA

    valor = Column(Float, nullable=False)
    formato = Column(Enumerado(FormatoMeta), nullable=False, default=FormatoMeta.PERCENTUAL)
    periodicidade = Column(Enumerado(PeriodicidadeMeta), nullable=True)   # só quando o valor é em R$

    vigencia_inicio = Column(Date, nullable=False, default=date.today)
    vigencia_fim = Column(Date, nullable=True)     # nulo = vigente hoje

    origem = Column(Enumerado(OrigemMeta), nullable=False, default=OrigemMeta.MANUAL)

    observacao = Column(Text, nullable=True)       # por que a meta mudou
    usuario_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    unidade = relationship("Unidade")
    categoria = relationship("Categoria")
    usuario = relationship("Usuario")


# ==============================================================================
# CONVITE — a única porta de entrada para uma conta nova
# ==============================================================================
# O cadastro é fechado: ninguém cria a própria conta. Quem tem autoridade
# emite um convite JÁ COM o que a pessoa vai poder ver, e o convidado só
# escolhe nome, login e senha.
#
# Isso importa porque o convite é uma rota PÚBLICA — quem a chama ainda não
# tem conta, logo não tem token, logo o guarda de unidade não tem usuário para
# conferir. Se o papel e as unidades viessem no corpo do pedido, qualquer um
# se concederia o que quisesse. Vindo do convite, a decisão fica com quem
# tinha autoridade no momento da emissão.
convite_unidade = Table(
    "convite_unidade",
    Base.metadata,
    Column("convite_id", Integer, ForeignKey("convites.id"), primary_key=True),
    Column("unidade_id", Integer, ForeignKey("unidades.id"), primary_key=True),
)


class Convite(Base):
    __tablename__ = "convites"

    id = Column(Integer, primary_key=True)

    # Formato SOLO-XXXX-XXXX, alfabeto sem 0/O e sem 1/I/L: o código é ditado
    # por telefone e colado de WhatsApp, onde essas letras viram suporte.
    codigo = Column(String(20), unique=True, nullable=False, index=True)

    # A empresa do convidado. O Arquiteto tem empresa_id nulo — é assim que ele
    # atravessa empresas —, então quando é ele quem convida, a empresa precisa
    # ser escolhida. Sem isso o convidado nasceria órfão.
    empresa_id = Column(Integer, ForeignKey("empresas.id"), nullable=False)
    criado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=False, index=True)

    # O que o convite concede. Copiado para o usuário no aceite, sem retoque.
    papel = Column(Enumerado(PapelUsuario), nullable=False, default=PapelUsuario.OPERADOR)
    escopo_unidades = Column(Enumerado(EscopoUnidades), nullable=False,
                             default=EscopoUnidades.LISTA)
    acesso_regional = Column(Boolean, default=False, nullable=False)

    nota = Column(String(200), nullable=True)      # "para a Maria, do estoque"

    expira_em = Column(DateTime, nullable=True)    # nulo = não expira
    revogado = Column(Boolean, default=False, nullable=False)

    # Uso único. Guardamos QUEM usou e QUANDO — um convite gasto é registro de
    # quem autorizou a entrada de quem, e isso não se apaga.
    usado_por_id = Column(Integer, ForeignKey("usuarios.id"), nullable=True)
    usado_em = Column(DateTime, nullable=True)

    criado_em = Column(DateTime, default=datetime.utcnow, nullable=False)

    empresa = relationship("Empresa")
    criado_por = relationship("Usuario", foreign_keys=[criado_por_id])
    usado_por = relationship("Usuario", foreign_keys=[usado_por_id])
    # Só faz sentido com escopo LISTA; com TODAS a regra substitui a lista.
    unidades = relationship("Unidade", secondary=convite_unidade)

    @property
    def estado(self) -> str:
        """DISPONIVEL, USADO, EXPIRADO ou REVOGADO — calculado, nunca guardado.

        Estado guardado envelhece sozinho: um convite que expirou às 3 da manhã
        continuaria marcado como disponível até alguém rodar alguma rotina.
        """
        if self.revogado:
            return "REVOGADO"
        if self.usado_por_id:
            return "USADO"
        if self.expira_em and datetime.utcnow() > self.expira_em:
            return "EXPIRADO"
        return "DISPONIVEL"
