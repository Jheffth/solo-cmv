"""
Da nota lida ao movimento de compra — com a conferência no meio.

O PASSO QUE NÃO PODE SER PULADO
-------------------------------
Entre ler a nota e mexer no estoque existe uma pessoa. Não é burocracia:
"PANCETA FOOD - 3VL" não é o nome de nenhum produto nosso, e a máquina que
adivinha errado cria compra do item errado — que ninguém percebe, porque o
número total fecha.

Então a importação tem duas etapas separadas de propósito:
  1. `registrar` guarda a nota e os itens, com o palpite de de-para
  2. `aprovar` transforma em movimento, depois de alguém confirmar

E o palpite de de-para APRENDE. A primeira nota da Suinoaves é mapeada à
mão; da segunda em diante a mesma descrição já vem casada, porque a escolha
virou apelido (servicos/busca.py::aprender).
"""
import logging
from datetime import datetime
from typing import Optional

from sqlalchemy.orm import Session

from models import (Fornecedor, ItemNotaImportada, Movimento,
                    NotaFiscalImportada, Produto, SinonimoProduto,
                    StatusNotaFiscal, TipoMovimento, Usuario)
from servicos import busca as servico_busca
from servicos import nfe_xml

log = logging.getLogger("servicos.nfe_importacao")


class ErroImportacao(Exception):
    """Mensagem pronta para a tela."""


# ==============================================================================
# FORNECEDOR
# ==============================================================================
def _achar_ou_criar_fornecedor(db: Session, cnpj: str, nome: str,
                               empresa_id: Optional[int]) -> Optional[Fornecedor]:
    """Pelo CNPJ primeiro; pelo nome só como último recurso.

    CNPJ é identidade; nome é como alguém digitou. "SUINOAVES ALIMENTOS LTDA"
    e "Suinoaves" são o mesmo fornecedor e dois cadastros diferentes — e dois
    cadastros quebram todo relatório por fornecedor sem dar erro nenhum.
    """
    if not cnpj and not nome:
        return None

    if cnpj:
        achado = db.query(Fornecedor).filter(
            Fornecedor.cnpj == cnpj).first()
        if achado:
            return achado

    if nome:
        achado = db.query(Fornecedor).filter(
            Fornecedor.nome.ilike(nome.strip())).first()
        if achado:
            # Aproveita para gravar o CNPJ que faltava: da próxima vez o
            # encontro é pelo caminho bom.
            if cnpj and not achado.cnpj:
                achado.cnpj = cnpj
            return achado

    novo = Fornecedor(nome=(nome or cnpj)[:180], cnpj=cnpj or None,
                      empresa_id=empresa_id)
    db.add(novo)
    db.flush()
    return novo


# ==============================================================================
# DE-PARA
# ==============================================================================
def _sugerir_produto(db: Session, descricao: str, codigo_fornecedor: str,
                     fornecedor_id: Optional[int],
                     empresa_id: Optional[int]) -> Optional[int]:
    """Qual produto nosso esta linha provavelmente é.

    Ordem que importa:
      1. apelido JÁ CONFIRMADO para este fornecedor — é conhecimento, não
         palpite, e por isso vem antes de tudo
      2. apelido geral (o que o bot aprendeu no chat)
      3. busca por nome, e só se ela tiver certeza (nome idêntico)

    O terceiro caso é deliberadamente tímido. Um palpite razoável aceito sem
    conferência vira compra errada; um campo vazio vira uma pergunta na
    tela. A segunda custa cinco segundos, a primeira custa um inventário.
    """
    termo = servico_busca.normalizar(descricao)

    if fornecedor_id and codigo_fornecedor:
        # O código do fornecedor é o casamento mais forte que existe: ele não
        # muda quando o emitente reescreve a descrição do produto.
        por_codigo = db.query(SinonimoProduto).filter(
            SinonimoProduto.fornecedor_id == fornecedor_id,
            SinonimoProduto.termo == servico_busca.normalizar(
                f"cod:{codigo_fornecedor}")).first()
        if por_codigo:
            return por_codigo.produto_id

    if fornecedor_id:
        do_fornecedor = db.query(SinonimoProduto).filter(
            SinonimoProduto.fornecedor_id == fornecedor_id,
            SinonimoProduto.termo == termo).first()
        if do_fornecedor:
            return do_fornecedor.produto_id

    geral = db.query(SinonimoProduto).filter(
        SinonimoProduto.fornecedor_id.is_(None),
        SinonimoProduto.termo == termo).first()
    if geral:
        return geral.produto_id

    candidatos = servico_busca.buscar(db, descricao, empresa_id=empresa_id,
                                      limite=3)
    exatos = [c for c in candidatos if c.pontos >= servico_busca.PONTOS_EXATO]
    return exatos[0].produto_id if len(exatos) == 1 else None


def candidatos_para_texto(db: Session, texto: str, empresa_id: Optional[int],
                          limite: int = 5) -> dict:
    """Os produtos do catálogo que combinam com um texto sujo de OCR.

    POR QUE ISTO EXISTE
    A tela mostrava a descrição crua da leitura — "eee) COSTELA SALGADA -
    2VL", "ere PE SALGADO « BVL 0" <5 EPSON". Aquilo não é nome de nada: é
    lixo de borda de tabela misturado com o produto. Pedir que alguém leia
    isso e digite o nome certo joga fora justamente o trabalho que a
    máquina deveria ter feito.

    A busca tolerante já sabia resolver isto — é a mesma que o bot usa para
    achar produto por nome no chat. Medido nas quatro linhas da foto de
    referência, com todo o lixo junto:

        "PANCETA FOOD -3¥L"        -> Panceta kg          (único)
        "ere PE SALGADO « BVL 0"   -> Pe Salgado kg       (destacado)
        "eee) COSTELA SALGADA"     -> Costela bovina  E  Costelinha salgada
                                      empatados — e aí a escolha é da pessoa

    QUANDO PRÉ-SELECIONAR
    Só quando o primeiro colocado se destaca do segundo. Empate é dúvida
    real, e resolver dúvida por sorteio é como se cria compra lançada no
    produto errado — que ninguém percebe, porque o valor total fecha.
    """
    achados = servico_busca.buscar(db, texto, empresa_id=empresa_id,
                                   limite=max(limite, 5))
    candidatos = [{
        "produto_id": c.produto_id,
        "nome": c.nome,
        "unidade_medida": c.unidade_medida,
        "pontos": round(c.pontos, 1),
    } for c in achados[:limite]]

    sugerido = None
    if candidatos:
        primeiro = candidatos[0]["pontos"]
        segundo = candidatos[1]["pontos"] if len(candidatos) > 1 else 0.0
        # 1,5x de folga sobre o segundo: abaixo disso os dois são igualmente
        # plausíveis para quem está olhando a nota, e a máquina não sabe mais
        # que a pessoa.
        if primeiro >= 2.0 and (segundo == 0 or primeiro >= segundo * 1.5):
            sugerido = candidatos[0]["produto_id"]

    return {"candidatos": candidatos, "sugerido": sugerido}


def _fator_sugerido(item: nfe_xml.ItemNota, produto: Optional[Produto]) -> float:
    """Quantas unidades NOSSAS cabem numa unidade da nota.

    O XML costuma responder isso sozinho: `qTrib / qCom` quando as unidades
    diferem. Dez bandejas de 500 g viram 5 kg, e o próprio emitente informou.

    Só aceitamos o fator do XML quando a unidade tributável bate com a NOSSA
    unidade de estoque. Sem essa checagem, um item vendido em caixa e
    tributado em quilo entraria convertido para quilo mesmo num produto que
    contamos em caixa — invertendo o erro em vez de corrigi-lo.
    """
    fator = item.fator_para_tributavel
    if not fator or not produto or not produto.unidade_medida:
        return 1.0
    nossa = produto.unidade_medida.strip().upper()
    if item.unidade_tributavel and item.unidade_tributavel.upper() == nossa:
        return fator
    return 1.0


# ==============================================================================
# REGISTRO
# ==============================================================================
def registrar(db: Session, nota: nfe_xml.NotaLida, unidade_id: int,
              usuario: Usuario, origem: str = "XML") -> NotaFiscalImportada:
    """Guarda a nota para conferência. NÃO mexe no estoque."""
    ja = db.query(NotaFiscalImportada).filter(
        NotaFiscalImportada.chave_acesso == nota.chave).first()
    if ja and ja.status == StatusNotaFiscal.PROCESSADA:
        raise ErroImportacao(
            f"A nota {nota.numero} já foi importada e lançada em "
            f"{ja.processado_em:%d/%m/%Y}. Importar de novo duplicaria as "
            f"compras no estoque.")
    if ja:
        # Reimportar uma nota que ainda está em conferência é normal — a
        # pessoa mandou o XML de novo. Substituir é melhor que empilhar.
        db.delete(ja)
        db.flush()

    fornecedor = _achar_ou_criar_fornecedor(
        db, nota.emitente_cnpj, nota.emitente_nome, usuario.empresa_id)

    registro = NotaFiscalImportada(
        unidade_id=unidade_id,
        chave_acesso=nota.chave,
        numero=nota.numero, serie=nota.serie,
        fornecedor_id=fornecedor.id if fornecedor else None,
        emitente_cnpj=nota.emitente_cnpj, emitente_nome=nota.emitente_nome,
        data_emissao=nota.emissao,
        valor_total=nota.valor_nota, valor_produtos=nota.valor_produtos,
        status=StatusNotaFiscal.CONFERINDO,
        origem=origem, xml_bruto=None,
        criado_por_id=usuario.id,
    )
    db.add(registro)
    db.flush()

    for item in nota.itens:
        produto_id = _sugerir_produto(
            db, item.descricao, item.codigo_fornecedor,
            registro.fornecedor_id, usuario.empresa_id)
        produto = db.query(Produto).filter(
            Produto.id == produto_id).first() if produto_id else None

        db.add(ItemNotaImportada(
            nota_id=registro.id,
            numero_item=item.numero,
            codigo_fornecedor=item.codigo_fornecedor,
            descricao=item.descricao,
            unidade_nota=item.unidade_comercial,
            quantidade_nota=item.quantidade_comercial,
            valor_unitario_nota=item.valor_unitario_comercial,
            acrescimos=item.acrescimos,
            custo_total=item.custo_total,
            custo_unitario=item.custo_unitario,
            produto_id=produto_id,
            fator_conversao=_fator_sugerido(item, produto),
        ))

    db.commit()
    db.refresh(registro)
    return registro


def guardar_xml(db: Session, registro: NotaFiscalImportada, xml: str) -> None:
    """O documento fiscal fica inteiro, e por isso não vai no `registrar`.

    Separado porque o XML pesa e nem toda origem tem um — a nota que entra só
    pela chave ainda não tem arquivo nenhum.
    """
    registro.xml_bruto = xml
    db.commit()


# ==============================================================================
# APROVAÇÃO
# ==============================================================================
def aprovar(db: Session, registro: NotaFiscalImportada,
            usuario: Usuario) -> dict:
    """Transforma os itens conferidos em movimentos de COMPRA.

    Aprender vem DEPOIS de gravar o movimento, e de propósito: se a gravação
    falhar, o sistema não pode ter aprendido um de-para de uma compra que
    não aconteceu.
    """
    if registro.status == StatusNotaFiscal.PROCESSADA:
        raise ErroImportacao("Esta nota já foi lançada no estoque.")

    considerados = [i for i in registro.itens if not i.ignorar]
    if not considerados:
        raise ErroImportacao("Todos os itens estão marcados para ignorar — "
                             "não há o que lançar.")

    sem_produto = [i for i in considerados if not i.produto_id]
    if sem_produto:
        # Nomear os itens em vez de dizer "há itens sem produto": a pessoa
        # precisa saber QUAIS para resolver, e a lista já está na tela dela.
        nomes = ", ".join(i.descricao[:32] for i in sem_produto[:4])
        resto = f" e mais {len(sem_produto) - 4}" if len(sem_produto) > 4 else ""
        raise ErroImportacao(
            f"{len(sem_produto)} item(ns) ainda sem produto escolhido: "
            f"{nomes}{resto}. Escolha o produto ou marque para ignorar.")

    data = registro.data_emissao or datetime.utcnow().date()
    documento = f"NF {registro.numero}" if registro.numero else "NF-e"
    criados = 0

    for item in considerados:
        quantidade = item.quantidade_final
        if quantidade <= 0:
            continue
        db.add(Movimento(
            unidade_id=registro.unidade_id,
            produto_id=item.produto_id,
            tipo=TipoMovimento.COMPRA,
            quantidade=quantidade,
            custo_unitario=item.custo_final,
            custo_total=round(item.custo_total, 4),
            fornecedor_id=registro.fornecedor_id,
            numero_documento=documento,
            data=data,
            usuario_id=usuario.id,
        ))
        criados += 1

    registro.status = StatusNotaFiscal.PROCESSADA
    registro.processado_por_id = usuario.id
    registro.processado_em = datetime.utcnow()
    db.commit()

    # O aprendizado só acontece agora, com a compra já gravada. E só do que
    # a PESSOA confirmou — nunca do palpite que o sistema deu sozinho, senão
    # um acerto duvidoso de hoje vira regra amanhã.
    for item in considerados:
        if not item.produto_id:
            continue
        try:
            servico_busca.aprender(db, item.produto_id, item.descricao,
                                   fornecedor_id=registro.fornecedor_id,
                                   fator=item.fator_conversao or 1.0)
            if item.codigo_fornecedor:
                servico_busca.aprender(
                    db, item.produto_id, f"cod:{item.codigo_fornecedor}",
                    fornecedor_id=registro.fornecedor_id,
                    fator=item.fator_conversao or 1.0)
        except Exception:
            log.exception("apelido não aprendido para o item %s", item.id)

    return {
        "movimentos_criados": criados,
        "valor_total": round(sum(i.custo_total for i in considerados), 2),
        "numero_documento": documento,
        "mensagem": f"{criados} item(ns) lançados como compra no estoque.",
    }
