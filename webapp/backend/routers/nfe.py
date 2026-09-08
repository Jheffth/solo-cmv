"""
Importação de nota fiscal — chave, foto, XML e a conferência antes do estoque.

O CAMINHO DA PESSOA
-------------------
    digita a chave  ─┐
    manda a foto   ─┼─> confere emitente e número ─> traz o XML ─┐
    sobe o XML     ─┘                                            │
                                                                 v
                                            confere item a item, aprova,
                                            e só então vira compra

Os três começos existem porque as três situações existem: a nota na mão, a
foto no celular, e o arquivo que o contador mandou. O que muda é só a
origem — da conferência em diante é tudo igual.

POR QUE A CHAVE SOZINHA JÁ VALE UMA ROTA
----------------------------------------
Validar e decodificar não exige SEFAZ nem certificado: os 44 dígitos já
dizem quem emitiu, quando e qual o número da nota. Quem digita vê na hora se
pegou a nota certa, e o dígito verificador pega o erro de digitação antes de
qualquer viagem à rede.
"""
import logging
import re
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import (Fornecedor, ItemNotaImportada, NotaFiscalImportada,
                    Produto, StatusNotaFiscal, Unidade, Usuario)
from auth.deps import get_current_user
from servicos import (chave_nfe, danfe, danfe_cabecalho, danfe_itens,
                      nfe_importacao, nfe_xml, sefaz)
from servicos import busca as servico_busca
from servicos import exclusao as servico_exclusao
from servicos import escopo as servico_escopo
from servicos.permissoes import Capacidade, requer

log = logging.getLogger("routers.nfe")
router = APIRouter(prefix="/nfe", tags=["notas fiscais"])

# 8 MB. Foto de celular moderno passa de 4 MB; acima disso é quase sempre
# alguém mandando um PDF grande ou um vídeo por engano.
TAMANHO_MAXIMO = 8 * 1024 * 1024


@router.get("/status")
def status(usuario: Usuario = Depends(get_current_user)):
    """O que está ligado neste servidor — e o que falta para o resto."""
    cfg = sefaz.configuracao()
    return {
        "implementado": True,
        "consulta_sefaz": cfg.como_dicionario(),
        "caminhos": [
            {"chave": "chave", "nome": "Digitar a chave",
             "disponivel": True,
             "detalhe": "Valida e identifica a nota na hora, sem internet."},
            {"chave": "foto", "nome": "Ler de uma foto",
             "disponivel": danfe_disponivel(),
             "detalhe": "Lê o código de barras da DANFE; se falhar, tenta os "
                        "números impressos."},
            {"chave": "xml", "nome": "Enviar o XML",
             "disponivel": True,
             "detalhe": "O arquivo que o contador manda. Traz os itens."},
            {"chave": "sefaz", "nome": "Buscar na SEFAZ",
             "disponivel": cfg.pronto,
             "detalhe": sefaz.explicacao(cfg)},
        ],
    }


def danfe_disponivel() -> bool:
    try:
        danfe._carregar()
        return True
    except danfe.LeitorIndisponivel:
        return False


# ==============================================================================
# 1. A CHAVE
# ==============================================================================
class PedidoChave(BaseModel):
    chave: str


@router.post("/chave")
def conferir_chave(dados: PedidoChave,
                   usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Valida os 44 dígitos e diz de quem é a nota. Sem rede, sem certificado."""
    try:
        chave = chave_nfe.validar(dados.chave)
    except chave_nfe.ChaveInvalida as erro:
        raise HTTPException(400, str(erro))

    resposta = chave.como_dicionario()
    resposta["proximo_passo"] = (
        "Agora mande o XML desta nota para trazer os itens."
        if not sefaz.configuracao().pronto else
        "Clique em Consultar para buscar os itens na SEFAZ.")
    return resposta


# ==============================================================================
# 2. A FOTO
# ==============================================================================
@router.post("/foto")
async def chave_da_foto(arquivo: UploadFile = File(...),
                        usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Acha a chave de acesso numa foto da DANFE."""
    dados = await arquivo.read()
    if not dados:
        raise HTTPException(400, "O arquivo chegou vazio.")
    if len(dados) > TAMANHO_MAXIMO:
        raise HTTPException(
            400, f"A foto tem {len(dados) / 1024 / 1024:.1f} MB e o limite é "
                 f"8 MB. Tire outra com menos resolução.")
    try:
        return danfe.achar_chave(dados)
    except danfe.LeitorIndisponivel as erro:
        raise HTTPException(503, str(erro))
    except ValueError as erro:
        raise HTTPException(400, str(erro))


def _conferir_a_loja(db: Session, destinatario: str, unidade_id: Optional[int],
                     empresa_id: Optional[int]) -> Optional[str]:
    """Avisa quando o destinatário da nota parece ser OUTRA loja.

    Compra entra em UMA loja, e a loja errada estraga duas apurações de CMV
    de uma vez: sobra onde não entrou e falta onde entrou. A nota sabe para
    quem foi vendida — não usar isso é jogar fora uma conferência de graça.

    O aviso é conservador de propósito. Só sai quando outra loja aparece no
    texto do destinatário e a escolhida NÃO aparece; texto sujo, empate ou
    nenhuma das duas reconhecível ficam em silêncio. Alarme que dispara à toa
    é desligado pela pessoa em uma semana, e aí não avisa mais nem quando
    importa.
    """
    if not destinatario or not unidade_id:
        return None
    alvo = servico_busca.normalizar(destinatario)
    if not alvo:
        return None

    consulta = db.query(Unidade)
    if empresa_id:
        consulta = consulta.filter(Unidade.empresa_id == empresa_id)
    lojas = consulta.all()

    def aparece(loja: Unidade) -> bool:
        nome = servico_busca.normalizar(loja.nome)
        palavras = [p for p in nome.split() if len(p) >= 4]
        return bool(palavras) and all(p in alvo for p in palavras)

    escolhida = next((l for l in lojas if l.id == unidade_id), None)
    if escolhida is None or aparece(escolhida):
        return None
    outras = [l.nome for l in lojas if l.id != unidade_id and aparece(l)]
    if not outras:
        return None
    return (f"A nota foi emitida para {' / '.join(outras)}, e você escolheu "
            f"{escolhida.nome}. Se a compra entrar na loja errada, o CMV das "
            f"duas sai errado — confira antes de aprovar.")


@router.post("/foto/itens")
async def itens_da_foto(arquivo: UploadFile = File(...),
                        chave: Optional[str] = Form(None),
                        unidade_id: Optional[int] = Form(None),
                        db: Session = Depends(get_db),
                        usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Lê a NOTA INTEIRA da foto — o caminho de quem não tem o XML.

    Devolve o que foi lido com cada campo marcado como provado ou não, e o
    total impresso na nota para a tela conferir a soma. Não grava nada: o
    que sai daqui é rascunho, e vira nota só depois que alguém confirma.

    E JÁ VEM COM OS PRODUTOS CANDIDATOS. A descrição crua do OCR ("eee)
    COSTELA SALGADA - 2VL") não serve para ninguém escolher nada; o que
    serve é o produto do catálogo que ela provavelmente é. A busca tolerante
    resolve isso — a mesma que o bot usa no chat.

    O CABEÇALHO VEM JUNTO, e é ele que torna a compra lançável: item sem
    fornecedor, sem número de nota e sem data não é compra, é uma lista de
    coisas. A `chave`, quando a tela já a tem, entra aqui como AUTORIDADE —
    o CNPJ do emitente, o número e a série saem dela, não da leitura.
    """
    dados = await arquivo.read()
    if not dados:
        raise HTTPException(400, "O arquivo chegou vazio.")
    if len(dados) > TAMANHO_MAXIMO:
        raise HTTPException(400, "A foto passa de 8 MB. Tire outra com menos "
                                 "resolução.")
    decodificada = None
    if chave:
        try:
            decodificada = chave_nfe.validar(chave)
        except chave_nfe.ChaveInvalida:
            # Chave ruim não derruba a leitura: ela só deixa de ser
            # autoridade, e o cabeçalho volta a depender da foto.
            log.info("chave inválida junto da foto; seguindo só com o OCR")

    # A TABELA E O CABEÇALHO SÃO LIDOS AO MESMO TEMPO.
    #
    # São faixas diferentes da página e nenhuma precisa da outra para ser
    # LIDA. O cabeçalho só precisa do total dos produtos para INTERPRETAR o
    # valor da nota — e interpretar é instantâneo. Por isso a transcrição
    # dele entra na mesma fila da tabela, e a espera passa a ser a da mais
    # lenta em vez da soma das duas.
    def ler_a_tabela():
        return danfe_itens.ler(dados).como_dicionario()

    def transcrever_o_cabecalho():
        return danfe_cabecalho.transcrever(dados, decodificada)

    try:
        rascunho, texto_do_cabecalho = danfe.em_paralelo(
            [ler_a_tabela, transcrever_o_cabecalho])
    except danfe.LeitorIndisponivel as erro:
        raise HTTPException(503, str(erro))
    except ValueError as erro:
        raise HTTPException(400, str(erro))
    if rascunho is None:
        raise HTTPException(400, "Não consegui ler nada nessa foto. Tente "
                                 "outra, com a nota esticada e sem sombra.")

    for linha in rascunho.get("linhas", []):
        achado = nfe_importacao.candidatos_para_texto(
            db, linha.get("descricao") or "", usuario.empresa_id)
        linha["produtos"] = achado["candidatos"]
        linha["produto_id"] = achado["sugerido"]
    sem_palpite = sum(1 for l in rascunho.get("linhas", [])
                      if not l.get("produtos"))
    if sem_palpite:
        rascunho.setdefault("avisos", []).append(
            f"{sem_palpite} linha(s) não bateram com nenhum produto do "
            f"cadastro. Escolha na lista ou deixe de fora.")

    # ------------------------------------------------------------ cabeçalho
    # Agora sim, com o total dos produtos em mãos: é ele que serve de piso
    # para o valor da nota, e sem ele um número qualquer da página passaria.
    try:
        cabecalho = danfe_cabecalho.interpretar(
            texto_do_cabecalho or "", decodificada,
            valor_produtos=rascunho.get("total_produtos"))
    except Exception:
        log.exception("cabeçalho da foto falhou")
        cabecalho = danfe_cabecalho.Cabecalho(avisos=[
            "Não consegui ler o cabeçalho desta foto. Preencha o fornecedor "
            "e o número da nota à mão."])

    dados_cabecalho = cabecalho.como_dicionario()
    dados_cabecalho["fornecedor"] = nfe_importacao.candidatos_de_fornecedor(
        db, cabecalho.emitente_nome, cabecalho.emitente_cnpj,
        usuario.empresa_id)
    rascunho["cabecalho"] = dados_cabecalho

    rascunho.setdefault("avisos", []).extend(cabecalho.avisos)
    alerta = _conferir_a_loja(db, cabecalho.destinatario_texto, unidade_id,
                              usuario.empresa_id)
    if alerta:
        rascunho["avisos"].append(alerta)
        dados_cabecalho["loja_divergente"] = True
    return rascunho


class ItemDigitado(BaseModel):
    descricao: str
    quantidade: float
    valor_unitario: float
    valor_total: Optional[float] = None
    produto_id: Optional[int] = None


class NotaDigitada(BaseModel):
    unidade_id: int
    chave: Optional[str] = None
    numero: Optional[str] = None
    serie: Optional[str] = None
    data_emissao: Optional[date] = None
    valor_nota: Optional[float] = None
    emitente_nome: Optional[str] = None
    emitente_cnpj: Optional[str] = None
    # O fornecedor do CADASTRO que a pessoa confirmou. É o campo que faz a
    # compra ser lançável: sem ele a nota não tem de quem se comprou.
    fornecedor_id: Optional[int] = None
    # Só `True` quando a pessoa clicou em criar o fornecedor da nota. Nada
    # entra no cadastro por omissão.
    criar_fornecedor: bool = False
    itens: List[ItemDigitado]


@router.post("/manual")
def nota_conferida(dados: NotaDigitada, db: Session = Depends(get_db),
                   usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Cria a nota a partir dos itens que a PESSOA confirmou.

    É onde o caminho da foto encontra o do XML: daqui em diante os dois são
    idênticos — casar produto, converter unidade, aprovar. A diferença é só
    a procedência, e ela fica gravada (`origem`) porque importa saber depois
    se aquele custo veio do documento fiscal ou de uma leitura conferida.

    O ICMS ST NÃO ENTRA por aqui, e é uma limitação honesta desta via: ele
    não é legível numa foto de celular com confiança suficiente. O custo sai
    o da tabela — para a nota da Suinoaves, R$ 12,99 e não R$ 13,97. Quem
    quiser o custo com imposto dentro precisa do XML.
    """
    unidade = _unidade_permitida(db, usuario, dados.unidade_id)
    if not dados.itens:
        raise HTTPException(400, "Nenhum item conferido.")

    chave = ""
    decodificada = None
    if dados.chave:
        try:
            decodificada = chave_nfe.validar(dados.chave)
            chave = decodificada.digitos
        except chave_nfe.ChaveInvalida as erro:
            raise HTTPException(400, str(erro))

    # A chave manda no que ela sabe, aqui também. Sem isso o número e o CNPJ
    # entrariam pelo que a tela mandou — que veio de leitura.
    cnpj = re.sub(r"\D", "", dados.emitente_cnpj or "")
    numero = dados.numero or ""
    serie = dados.serie or ""
    if decodificada is not None:
        cnpj = decodificada.cnpj_emitente
        numero = str(decodificada.numero)
        serie = str(int(decodificada.serie))

    fornecedor, avisos_fornecedor = _resolver_fornecedor(db, dados, cnpj,
                                                         usuario)

    itens = [nfe_xml.ItemNota(
        numero=i + 1, codigo_fornecedor="", descricao=item.descricao[:255],
        ncm="", cfop="", ean=None,
        unidade_comercial="UN",
        quantidade_comercial=item.quantidade,
        valor_unitario_comercial=item.valor_unitario,
        valor_produto=round(item.valor_total
                            if item.valor_total is not None
                            else item.quantidade * item.valor_unitario, 2),
    ) for i, item in enumerate(dados.itens)]

    soma_dos_itens = round(sum(i.custo_total for i in itens), 2)
    avisos = ["Nota montada a partir de leitura por foto, conferida à mão. "
              "Sem o XML, o ICMS ST não entra no custo."]
    avisos.extend(avisos_fornecedor)

    # O total da nota inclui frete e imposto, que não estão nos itens desta
    # via. Guardar o valor lido do rodapé preserva a diferença — é ela que
    # explica, meses depois, por que a soma dos custos não bate com o que foi
    # pago. Zerar isso seria apagar a pergunta junto com a resposta.
    valor_nota = dados.valor_nota
    if valor_nota and valor_nota + 0.02 < soma_dos_itens:
        avisos.append(
            f"O total informado (R$ {valor_nota:.2f}) é menor que a soma dos "
            f"itens (R$ {soma_dos_itens:.2f}). Usei a soma dos itens.")
        valor_nota = None
    elif valor_nota and valor_nota - soma_dos_itens > 0.02:
        avisos.append(
            f"A nota fecha em R$ {valor_nota:.2f} e os itens somam "
            f"R$ {soma_dos_itens:.2f}. A diferença de "
            f"R$ {valor_nota - soma_dos_itens:.2f} é frete e imposto, que "
            f"não entram no custo por esta via.")

    lida = nfe_xml.NotaLida(
        chave=chave,
        numero=numero, serie=serie,
        emissao=dados.data_emissao,
        emitente_cnpj=cnpj,
        emitente_nome=(fornecedor.nome if fornecedor
                       else (dados.emitente_nome or "")),
        destinatario_cnpj="", destinatario_nome="",
        valor_produtos=round(sum(i.valor_produto for i in itens), 2),
        valor_nota=valor_nota or soma_dos_itens,
        itens=itens,
        avisos=avisos,
    )

    try:
        registro = nfe_importacao.registrar(db, lida, unidade, usuario,
                                            origem="FOTO",
                                            fornecedor=fornecedor)
    except nfe_importacao.ErroImportacao as erro:
        raise HTTPException(409, str(erro))

    # O produto que a pessoa escolheu na leitura vale mais que o palpite do
    # de-para: ela estava com a nota na mão. Sobrescreve o que `registrar`
    # tiver adivinhado, na ordem dos itens.
    escolhidos = [i.produto_id for i in dados.itens]
    for item, produto_id in zip(sorted(registro.itens,
                                       key=lambda i: i.numero_item or 0),
                                escolhidos):
        if produto_id:
            item.produto_id = produto_id
    db.commit()
    return _detalhe(db, registro, avisos=lida.avisos)


def _resolver_fornecedor(db: Session, dados: "NotaDigitada", cnpj: str,
                         usuario: Usuario):
    """O fornecedor que a pessoa confirmou — e o CNPJ gravado no cadastro.

    Três caminhos, e nenhum deles cadastra por conta própria:

      · escolheu um da lista  -> é esse, e ele ganha o CNPJ da chave;
      · pediu para criar      -> cria com o nome e o CNPJ lidos da nota;
      · não escolheu nada     -> a nota entra sem fornecedor, e a tela cobra.

    O terceiro caso é de propósito. Recusar a nota inteira por falta de
    fornecedor jogaria fora a conferência de doze números que a pessoa acabou
    de fazer; a compra fica registrada e o fornecedor é preenchido depois,
    antes de aprovar.
    """
    avisos = []
    if dados.fornecedor_id:
        consulta = db.query(Fornecedor).filter(
            Fornecedor.id == dados.fornecedor_id)
        if usuario.empresa_id:
            consulta = consulta.filter(
                Fornecedor.empresa_id == usuario.empresa_id)
        fornecedor = consulta.first()
        if not fornecedor:
            raise HTTPException(404, "Esse fornecedor não está no cadastro.")
        conflito = nfe_importacao.fixar_cnpj(fornecedor, cnpj)
        if conflito:
            avisos.append(conflito)
        return fornecedor, avisos

    if dados.criar_fornecedor:
        nome = (dados.emitente_nome or "").strip()
        if len(nome) < 4:
            raise HTTPException(
                400, "Sem o nome do fornecedor não dá para cadastrar. "
                     "Escolha um da lista ou digite o nome.")
        fornecedor = Fornecedor(nome=nome[:180], cnpj=cnpj or None,
                                empresa_id=usuario.empresa_id)
        db.add(fornecedor)
        db.flush()
        avisos.append(f"Fornecedor {fornecedor.nome} cadastrado a partir "
                      f"desta nota.")
        return fornecedor, avisos

    avisos.append("Esta nota ficou SEM FORNECEDOR. Escolha um antes de "
                  "aprovar — sem ele a compra não aparece em nenhum "
                  "relatório por fornecedor.")
    return None, avisos


# ==============================================================================
# 3. O XML
# ==============================================================================
def _unidade_permitida(db: Session, usuario: Usuario, unidade_id: int) -> int:
    recorte = servico_escopo.resolver(db, usuario, str(unidade_id))
    if recorte.regional or recorte.unidade_id is None:
        raise HTTPException(
            400, "Escolha uma loja específica: compra entra em uma loja, "
                 "não no consolidado da rede.")
    return recorte.unidade_id


@router.post("/xml")
async def importar_xml(unidade_id: int,
                       arquivo: UploadFile = File(...),
                       db: Session = Depends(get_db),
                       usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Lê o XML, guarda a nota e monta a conferência. NÃO mexe no estoque."""
    unidade = _unidade_permitida(db, usuario, unidade_id)
    dados = await arquivo.read()
    if not dados:
        raise HTTPException(400, "O arquivo chegou vazio.")

    try:
        texto = dados.decode("utf-8")
    except UnicodeDecodeError:
        # XML da SEFAZ às vezes vem em latin-1, principalmente o que passou
        # por sistema antigo de contabilidade.
        texto = dados.decode("latin-1", errors="replace")

    try:
        lida = nfe_xml.ler(texto)
    except nfe_xml.XmlInvalido as erro:
        raise HTTPException(400, str(erro))

    try:
        registro = nfe_importacao.registrar(db, lida, unidade, usuario, origem="XML")
    except nfe_importacao.ErroImportacao as erro:
        raise HTTPException(409, str(erro))

    nfe_importacao.guardar_xml(db, registro, texto)
    return _detalhe(db, registro, avisos=lida.avisos)


# ==============================================================================
# 4. A SEFAZ
# ==============================================================================
class PedidoConsulta(BaseModel):
    chave: str
    unidade_id: int


@router.post("/consultar")
def consultar_sefaz(dados: PedidoConsulta, db: Session = Depends(get_db),
                    usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Busca o XML na SEFAZ. Recusa com explicação enquanto não der.

    503 e não 500: não é defeito, é configuração que falta — e a mensagem
    diz qual, para o Diretor saber a quem pedir.
    """
    unidade = _unidade_permitida(db, usuario, dados.unidade_id)
    try:
        chave = chave_nfe.validar(dados.chave)
    except chave_nfe.ChaveInvalida as erro:
        raise HTTPException(400, str(erro))

    try:
        xml = sefaz.consultar_por_chave(chave.digitos)
    except sefaz.SefazIndisponivel as erro:
        raise HTTPException(503, str(erro))

    lida = nfe_xml.ler(xml)
    registro = nfe_importacao.registrar(db, lida, unidade, usuario, origem="SEFAZ")
    nfe_importacao.guardar_xml(db, registro, xml)
    return _detalhe(db, registro, avisos=lida.avisos)


# ==============================================================================
# 5. CONFERÊNCIA E APROVAÇÃO
# ==============================================================================
def _detalhe(db: Session, registro: NotaFiscalImportada,
             avisos: Optional[list] = None) -> dict:
    itens = []
    for item in sorted(registro.itens, key=lambda i: i.numero_item or 0):
        itens.append({
            "id": item.id,
            "numero": item.numero_item,
            "codigo_fornecedor": item.codigo_fornecedor,
            "descricao": item.descricao,
            "unidade_nota": item.unidade_nota,
            "quantidade_nota": item.quantidade_nota,
            "valor_unitario_nota": item.valor_unitario_nota,
            "acrescimos": item.acrescimos,
            "custo_total": item.custo_total,
            "custo_unitario": item.custo_unitario,
            "produto_id": item.produto_id,
            "produto_nome": item.produto.nome if item.produto else None,
            "produto_unidade": item.produto.unidade_medida if item.produto else None,
            "fator_conversao": item.fator_conversao,
            "quantidade_final": item.quantidade_final,
            "custo_final": item.custo_final,
            "ignorar": item.ignorar,
        })

    pendentes = sum(1 for i in registro.itens if not i.produto_id and not i.ignorar)
    return {
        "id": registro.id,
        "chave": registro.chave_acesso,
        "numero": registro.numero, "serie": registro.serie,
        "emitente": registro.emitente_nome,
        "emitente_cnpj": registro.emitente_cnpj,
        "fornecedor_id": registro.fornecedor_id,
        # O NOME do fornecedor, e não só o id: a tela de conferência precisa
        # dizer de quem foi a compra, e quem lê a nota não sabe o que é 48.
        "fornecedor": registro.fornecedor.nome if registro.fornecedor else None,
        "emissao": registro.data_emissao.isoformat() if registro.data_emissao else None,
        "valor_total": registro.valor_total,
        "valor_produtos": registro.valor_produtos,
        "status": registro.status.value,
        "origem": registro.origem,
        "itens": itens,
        "itens_sem_produto": pendentes,
        "pronta_para_aprovar": pendentes == 0,
        "avisos": avisos or [],
    }


@router.get("")
def listar(unidade_id: Optional[str] = None, limite: int = 30,
           db: Session = Depends(get_db),
           usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    recorte = servico_escopo.resolver(db, usuario, unidade_id)
    notas = db.query(NotaFiscalImportada).filter(
        NotaFiscalImportada.unidade_id.in_(recorte.ids)).order_by(
            NotaFiscalImportada.criado_em.desc()).limit(
                max(1, min(limite, 200))).all()
    return [{
        "id": n.id, "chave": n.chave_acesso, "numero": n.numero,
        "emitente": n.emitente_nome,
        "emissao": n.data_emissao.isoformat() if n.data_emissao else None,
        "valor_total": n.valor_total, "status": n.status.value,
        "itens": len(n.itens),
        "itens_sem_produto": sum(1 for i in n.itens
                                 if not i.produto_id and not i.ignorar),
    } for n in notas]


def _buscar(db: Session, nota_id: int) -> NotaFiscalImportada:
    nota = db.query(NotaFiscalImportada).filter(
        NotaFiscalImportada.id == nota_id).first()
    if not nota:
        raise HTTPException(404, "Nota não encontrada.")
    return nota


@router.get("/{nota_id}")
def detalhe(nota_id: int, db: Session = Depends(get_db),
            usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    return _detalhe(db, _buscar(db, nota_id))


class AjusteItem(BaseModel):
    produto_id: Optional[int] = None
    fator_conversao: Optional[float] = None
    ignorar: Optional[bool] = None


@router.put("/{nota_id}/item/{item_id}")
def ajustar_item(nota_id: int, item_id: int, dados: AjusteItem,
                 db: Session = Depends(get_db),
                 usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """A conferência: casar o produto e confirmar a conversão."""
    nota = _buscar(db, nota_id)
    if nota.status == StatusNotaFiscal.PROCESSADA:
        raise HTTPException(409, "Esta nota já foi lançada; não dá para mudar "
                                 "os itens. Lance um ajuste no estoque.")
    item = db.query(ItemNotaImportada).filter(
        ItemNotaImportada.id == item_id,
        ItemNotaImportada.nota_id == nota_id).first()
    if not item:
        raise HTTPException(404, "Item não encontrado nesta nota.")

    if dados.produto_id is not None:
        if dados.produto_id and not db.query(Produto).filter(
                Produto.id == dados.produto_id).first():
            raise HTTPException(404, "Produto não encontrado.")
        item.produto_id = dados.produto_id or None
    if dados.fator_conversao is not None:
        if dados.fator_conversao <= 0:
            raise HTTPException(
                400, "O fator de conversão precisa ser maior que zero — ele "
                     "multiplica a quantidade da nota.")
        item.fator_conversao = dados.fator_conversao
    if dados.ignorar is not None:
        item.ignorar = dados.ignorar

    db.commit()
    return _detalhe(db, nota)


@router.post("/{nota_id}/aprovar")
def aprovar(nota_id: int, db: Session = Depends(get_db),
            usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Vira compra no estoque — e o sistema aprende o de-para confirmado."""
    nota = _buscar(db, nota_id)
    try:
        return nfe_importacao.aprovar(db, nota, usuario)
    except nfe_importacao.ErroImportacao as erro:
        raise HTTPException(409, str(erro))


@router.post("/{nota_id}/descartar")
def descartar(nota_id: int, db: Session = Depends(get_db),
              usuario: Usuario = Depends(requer(Capacidade.LANCAR_COMPRA))):
    """Recusa a nota, sem apagar: fica no histórico como decisão tomada."""
    nota = _buscar(db, nota_id)
    if nota.status == StatusNotaFiscal.PROCESSADA:
        raise HTTPException(
            409, "Esta nota já virou compra no estoque. Para tirá-la, use "
                 "Anular — descartar só serve para nota que nunca entrou.")
    nota.status = StatusNotaFiscal.DESCARTADA
    db.commit()
    return {"status": nota.status.value}


class Anulacao(BaseModel):
    motivo: Optional[str] = None


@router.post("/{nota_id}/anular")
def anular(nota_id: int, dados: Optional[Anulacao] = None,
           db: Session = Depends(get_db),
           usuario: Usuario = Depends(requer(Capacidade.ANULAR_NOTA))):
    """Tira a nota INTEIRA do estoque e do CMV, e a deixa relançável.

    A operação que faltava. Até aqui uma compra lançada errada não tinha
    volta: descartar recusa antes de entrar, e aprovar não tem inverso. Quem
    percebia o erro depois só podia lançar uma perda para compensar — o que
    tira a quantidade do estoque e deixa o custo dentro do CMV, escondendo
    o erro em vez de desfazê-lo.

    Aqui o documento e o estoque saem juntos, com rastro de quem anulou. E
    a mesma chave volta a poder ser importada, que é o ponto: a nota estava
    errada, não inexistente.
    """
    nota = _buscar(db, nota_id)
    try:
        quantos, avisos = servico_exclusao.anular_nota(
            db, nota, usuario, (dados.motivo if dados else "") or "")
    except servico_exclusao.ErroExclusao as erro:
        raise HTTPException(409, str(erro))
    return {"status": nota.status.value, "movimentos_removidos": quantos,
            "avisos": avisos}
