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
from typing import Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import (ItemNotaImportada, NotaFiscalImportada, Produto,
                    StatusNotaFiscal, Usuario)
from auth.deps import get_current_user
from servicos import chave_nfe, danfe, nfe_importacao, nfe_xml, sefaz
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
        raise HTTPException(409, "Esta nota já virou compra no estoque.")
    nota.status = StatusNotaFiscal.DESCARTADA
    db.commit()
    return {"status": nota.status.value}
