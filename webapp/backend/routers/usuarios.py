"""
Usuários e o escopo de acesso de cada um.

ESCOPO É PARTE DO CADASTRO, NÃO UM DETALHE
------------------------------------------
Criar usuário sem dizer quais unidades ele enxerga deixaria a pessoa sem
acesso a nada — ou, pior, com acesso a tudo por omissão. Por isso o
formulário pede a escolha, e quem cria não pode conceder mais do que ele
mesmo tem: o middleware de unidade barra o pedido antes de chegar aqui.
"""
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario, Unidade, PapelUsuario, EscopoUnidades
from schemas import UsuarioOut, UsuarioEscopo, UsuarioAtivo
from auth.deps import exigir_papeis
from servicos import escopo as servico_escopo

router = APIRouter(prefix="/usuarios", tags=["usuários"])


@router.get("", response_model=List[UsuarioOut])
def listar(db: Session = Depends(get_db),
           usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    query = db.query(Usuario)
    if usuario.empresa_id:
        query = query.filter(Usuario.empresa_id == usuario.empresa_id)
    return query.order_by(Usuario.nome).all()


def _aplicar_escopo(db: Session, alvo: Usuario, autor: Usuario,
                    escopo_unidades: EscopoUnidades,
                    unidade_ids: List[int], acesso_regional: bool) -> None:
    """Vincula unidades e concede (ou não) a Regional.

    Ninguém pode dar o que não tem: um gerente da unidade A não consegue
    conceder acesso à unidade B nem à Regional.

    Conceder TODAS exige enxergar todas — senão o gerente de uma loja
    ampliaria o próprio alcance criando um usuário e entrando com ele.
    """
    if acesso_regional and not servico_escopo.pode_ver_regional(autor):
        raise HTTPException(
            403, "Você não pode conceder acesso à Regional sem tê-lo.")

    if escopo_unidades == EscopoUnidades.TODAS:
        if not (servico_escopo.irrestrito(autor)
                or autor.escopo_unidades == EscopoUnidades.TODAS):
            raise HTTPException(
                403, "Você não enxerga todas as lojas, então não pode conceder "
                     "esse alcance.")
        alvo.escopo_unidades = EscopoUnidades.TODAS
        # A lista fica vazia de propósito: com TODAS quem manda é a regra, e
        # uma lista gravada aqui viraria uma segunda verdade, desatualizada na
        # primeira loja nova.
        alvo.unidades = []
        alvo.acesso_regional = bool(acesso_regional)
        return

    permitidas = {u.id for u in servico_escopo.unidades_permitidas(db, autor)}
    pedidas = set(unidade_ids or [])
    invasoras = pedidas - permitidas
    if invasoras:
        raise HTTPException(
            403, "Você não pode conceder acesso a unidades que não enxerga.")

    alvo.escopo_unidades = EscopoUnidades.LISTA
    alvo.unidades = db.query(Unidade).filter(Unidade.id.in_(pedidas)).all() if pedidas else []
    alvo.acesso_regional = bool(acesso_regional)


@router.post("", status_code=410)
def criar_desativado():
    """Conta não nasce mais aqui. Nasce de um convite.

    POR QUE ESTA ROTA FOI FECHADA
    ----------------------------
    Ela criava a conta com a senha digitada por OUTRA pessoa. Quem entrava
    pela primeira vez não tinha senha — tinha um segredo compartilhado com
    quem cadastrou. E ninguém troca senha no primeiro acesso quando o sistema
    não obriga.

    O convite resolve isso pela raiz: quem emite decide papel e unidades,
    quem aceita escolhe a própria senha, e as duas metades nunca se cruzam.
    De quebra, fica o registro de quem autorizou a entrada de quem — coisa
    que a criação direta não deixava.

    Devolve 410 (Gone), não 404: a rota existiu, foi retirada de propósito, e
    quem chamar merece saber para onde ir.
    """
    raise HTTPException(
        410,
        "O cadastro é fechado: conta nova entra por convite. "
        "Vá em Convites, gere um link e envie para a pessoa — ela escolhe a "
        "própria senha. Aqui você administra quem já entrou.")


@router.put("/{usuario_id}/escopo", response_model=UsuarioOut)
def alterar_escopo(usuario_id: int, dados: UsuarioEscopo,
                   db: Session = Depends(get_db),
                   usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if usuario.empresa_id and alvo.empresa_id != usuario.empresa_id:
        raise HTTPException(403, "Este usuário é de outra empresa.")

    _aplicar_escopo(db, alvo, usuario, dados.escopo_unidades,
                    dados.unidade_ids, dados.acesso_regional)
    db.commit()
    db.refresh(alvo)
    return alvo


@router.put("/{usuario_id}/ativo", response_model=UsuarioOut)
def alterar_ativo(usuario_id: int, dados: UsuarioAtivo,
                  db: Session = Depends(get_db),
                  usuario=Depends(exigir_papeis(PapelUsuario.ADMIN))):
    """Liga e desliga o acesso.

    Desativar é o que substitui "apagar o usuário": o histórico de quem
    lançou cada compra e cada contagem precisa continuar apontando para
    alguém. Conta apagada deixaria movimento órfão.
    """
    alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    if usuario.empresa_id and alvo.empresa_id != usuario.empresa_id:
        raise HTTPException(403, "Este usuário é de outra empresa.")
    if alvo.id == usuario.id:
        raise HTTPException(400, "Você não pode desativar a própria conta.")

    alvo.ativo = bool(dados.ativo)
    db.commit()
    db.refresh(alvo)
    return alvo
