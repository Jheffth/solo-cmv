from typing import List, Optional
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Produto, Categoria, PapelUsuario, SessaoInventario
from schemas import ProdutoOut, ProdutoCreate
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer
from servicos import busca as servico_busca
from codigos import gerar_codigo
from unidades_medida import normalizar as normalizar_unidade, SUGERIDAS

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.get("/unidades-medida")
def unidades_medida(usuario=Depends(get_current_user)):
    """Unidades sugeridas na tela de cadastro, para não nascer 'kg', 'Kg' e 'KG'."""
    return SUGERIDAS


@router.get("/buscar")
def buscar_produtos(termo: str,
                    sessao_inventario_id: Optional[int] = None,
                    limite: int = 8,
                    db: Session = Depends(get_db),
                    usuario=Depends(get_current_user)):
    """Busca tolerante — sem acento, sem caixa, por palavra parcial.

    Existe para o bot conversar por nome, mas serve a todos os canais: o
    Lançador da tela usa `<select>` hoje e fica melhor com isto, e um futuro
    coletor vai fazer a mesma pergunta.

    Com `sessao_inventario_id`, filtra e ordena pelo escopo do inventário —
    contando Hortifruti, "cerveja" não deve nem aparecer como opção.
    """
    sessao = None
    if sessao_inventario_id:
        sessao = db.query(SessaoInventario).filter(
            SessaoInventario.id == sessao_inventario_id).first()
        if sessao is None:
            raise HTTPException(404, "Inventário não encontrado.")

    candidatos = servico_busca.buscar(
        db, termo, empresa_id=usuario.empresa_id,
        sessao_inventario=sessao, limite=max(1, min(limite, 25)))
    return {"termo": termo, "itens": servico_busca.como_dicionario(candidatos)}


class ApelidoAprendido(BaseModel):
    produto_id: int
    termo: str
    fornecedor_id: Optional[int] = None
    fator_conversao: float = 1.0


@router.post("/apelido", status_code=204)
def aprender_apelido(dados: ApelidoAprendido, db: Session = Depends(get_db),
                     usuario=Depends(requer(Capacidade.CADASTRAR))):
    """"Quando eu escrevo isto, quero aquele produto."

    A busca já sabia consultar apelidos e nada os criava — a tabela existia
    vazia, e o sistema recomeçava do zero toda vez. O laço só fecha aqui: a
    pessoa digita "bata doce", recebe três opções, escolhe uma, e o canal
    avisa qual foi. Na segunda vez a mesma digitação acerta sozinha.

    Aprender é uma ESCOLHA CONFIRMADA, nunca um palpite do sistema. Guardar
    o que ele achou provável faria o erro se reforçar sozinho, e ninguém
    entenderia por que "batata" passou a significar Batata Baroa.

    Silencioso por desenho (204): quem acabou de escolher um item quer
    lançar a quantidade, não receber um aviso de que o sistema anotou algo.
    """
    produto = db.query(Produto).filter(Produto.id == dados.produto_id).first()
    if not produto:
        raise HTTPException(404, "Produto não encontrado.")
    if usuario.empresa_id and produto.empresa_id != usuario.empresa_id:
        raise HTTPException(403, "Este produto é de outra empresa.")
    servico_busca.aprender(db, dados.produto_id, dados.termo,
                           fornecedor_id=dados.fornecedor_id,
                           fator=dados.fator_conversao or 1.0)


@router.get("", response_model=List[ProdutoOut])
def listar(categoria_id: Optional[int] = None, busca: Optional[str] = None,
           db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    query = db.query(Produto).filter(Produto.ativo == True)  # noqa: E712
    if usuario.empresa_id:
        query = query.filter(Produto.empresa_id == usuario.empresa_id)
    if categoria_id:
        query = query.filter(Produto.categoria_id == categoria_id)
    if busca:
        termo = f"%{busca}%"
        query = query.filter((Produto.nome.ilike(termo)) | (Produto.codigo.ilike(termo)))
    return query.order_by(Produto.nome).limit(500).all()


@router.post("", response_model=ProdutoOut, status_code=201)
def criar(dados: ProdutoCreate, db: Session = Depends(get_db),
          usuario=Depends(requer(Capacidade.CADASTRAR))):
    campos = dados.model_dump()

    # Grafia única da unidade: o cadastro é o único lugar onde "kg" e "Kg"
    # podem virar dois produtos diferentes aos olhos de um relatório.
    campos["unidade_medida"] = normalizar_unidade(campos.get("unidade_medida"))

    # Código único de 6 dígitos, no bloco da família do produto (ver codigos.py).
    # Se o usuário informou um código manualmente, respeita o que ele digitou.
    if not campos.get("codigo"):
        familia = None
        if campos.get("categoria_id"):
            cat = db.query(Categoria).filter(Categoria.id == campos["categoria_id"]).first()
            familia = cat.nome if cat else None
        campos["codigo"] = gerar_codigo(db, usuario.empresa_id, familia)

    produto = Produto(empresa_id=usuario.empresa_id, **campos)
    db.add(produto)
    db.commit()
    db.refresh(produto)
    return produto
