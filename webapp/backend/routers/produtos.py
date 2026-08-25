from typing import List, Optional
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from database import get_db
from models import Produto, Categoria, PapelUsuario
from schemas import ProdutoOut, ProdutoCreate
from auth.deps import get_current_user, exigir_papeis
from servicos.permissoes import Capacidade, requer
from codigos import gerar_codigo
from unidades_medida import normalizar as normalizar_unidade, SUGERIDAS

router = APIRouter(prefix="/produtos", tags=["produtos"])


@router.get("/unidades-medida")
def unidades_medida(usuario=Depends(get_current_user)):
    """Unidades sugeridas na tela de cadastro, para não nascer 'kg', 'Kg' e 'KG'."""
    return SUGERIDAS


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
