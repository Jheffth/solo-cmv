"""
Gestão de acesso — promover, rebaixar, suspender e excluir.

ESTA ROTA NÃO CRIA CONTA. Conta nasce de um convite (routers/convites.py).
Ela criava, com a senha digitada por outra pessoa; quem entrava não tinha
senha, tinha um segredo compartilhado. Ver o 410 mais abaixo.

QUEM PODE O QUÊ vive em `servicos/hierarquia.py`, e só lá. Em resumo:
concede-se até o próprio nível, mexe-se só em quem está estritamente abaixo,
nunca em si mesmo, nunca fora da própria empresa.

SUSPENDER E EXCLUIR SÃO COISAS DIFERENTES
  · suspender (`ativo=false`) — afastamento reversível
  · excluir (`excluido_em`)   — definitivo, mas a linha permanece para os
                                lançamentos antigos continuarem com autor
"""
from typing import List, Optional

from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario, Unidade, PapelUsuario, EscopoUnidades
from schemas import UsuarioOut, UsuarioEscopo, UsuarioAtivo, UsuarioPapel
from auth.deps import get_current_user
from servicos import escopo as servico_escopo
from servicos import hierarquia

router = APIRouter(prefix="/usuarios", tags=["usuários"])


def _buscar(db: Session, usuario_id: int) -> Usuario:
    alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    return alvo


# ==============================================================================
# LEITURA
# ==============================================================================
@router.get("/poderes")
def poderes(usuario: Usuario = Depends(get_current_user)):
    """O que ESTE usuário pode fazer. A tela se monta a partir daqui."""
    return hierarquia.descrever_poderes(usuario)


@router.get("")
def listar(incluir_excluidos: bool = Query(False),
           db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    """A equipe, com as ações liberadas linha a linha.

    Devolver as ações por usuário evita que a tela recalcule a hierarquia —
    e faz o motivo do bloqueio aparecer como texto ("mesmo nível que o seu")
    em vez de botão morto, que não explica nada.
    """
    # Quem não tem ninguém abaixo não precisa da lista de gente. Não é
    # segredo de estado, mas "quem trabalha aqui e com que poder" é
    # informação de quem administra — e a tela nem aparece para os demais.
    if not hierarquia.pode_convidar(usuario):
        raise HTTPException(
            403, "Você não administra acessos. Fale com quem está acima de você.")

    query = db.query(Usuario)
    if usuario.papel != PapelUsuario.ARQUITETO and usuario.empresa_id:
        query = query.filter(Usuario.empresa_id == usuario.empresa_id)
    if not incluir_excluidos:
        query = query.filter(Usuario.excluido_em.is_(None))

    pessoas = query.order_by(Usuario.nome).all()
    saida = []
    for p in pessoas:
        item = UsuarioOut.model_validate(p).model_dump()
        item["excluido"] = p.excluido_em is not None
        item["excluido_em"] = p.excluido_em.isoformat() if p.excluido_em else None
        item["acoes"] = hierarquia.acoes_possiveis(usuario, p)
        saida.append(item)
    return saida


# ==============================================================================
# PAPEL — promover e rebaixar
# ==============================================================================
@router.put("/{usuario_id}/papel", response_model=UsuarioOut)
def alterar_papel(usuario_id: int, dados: UsuarioPapel,
                  db: Session = Depends(get_db),
                  usuario: Usuario = Depends(get_current_user)):
    """Promove ou rebaixa. Duas checagens, e as duas importam."""
    alvo = _buscar(db, usuario_id)
    if alvo.excluido_em:
        raise HTTPException(400, "Este acesso foi excluído.")

    # 1) posso mexer NESTA pessoa? (estritamente abaixo, mesma empresa, não eu)
    hierarquia.exigir_gerenciar(usuario, alvo)
    # 2) posso dar ESTE papel? (até o meu nível)
    #
    # As duas são necessárias e nenhuma implica a outra: um Gerente pode
    # mexer num Operador (1) mas não pode torná-lo Diretor (2).
    hierarquia.exigir_conceder(usuario, dados.papel)

    alvo.papel = dados.papel
    db.commit()
    db.refresh(alvo)
    return alvo


# ==============================================================================
# ESCOPO — quais lojas e a Regional
# ==============================================================================
def _aplicar_escopo(db: Session, alvo: Usuario, autor: Usuario,
                    escopo_unidades: EscopoUnidades,
                    unidade_ids: List[int], acesso_regional: bool) -> None:
    """Ninguém dá o que não tem.

    Conceder TODAS exige enxergar todas — senão o gerente de uma loja
    ampliaria o próprio alcance criando um usuário e entrando com ele.
    """
    if acesso_regional and not servico_escopo.pode_ver_regional(autor):
        raise HTTPException(
            403, "Você não tem acesso Regional, então não pode concedê-lo.")

    if escopo_unidades == EscopoUnidades.TODAS:
        if not (servico_escopo.irrestrito(autor)
                or autor.escopo_unidades == EscopoUnidades.TODAS):
            raise HTTPException(
                403, "Você não enxerga todas as lojas, então não pode conceder "
                     "esse alcance.")
        alvo.escopo_unidades = EscopoUnidades.TODAS
        # Lista vazia de propósito: com TODAS quem manda é a regra, e uma
        # lista gravada aqui viraria uma segunda verdade, desatualizada na
        # primeira loja nova.
        alvo.unidades = []
        alvo.acesso_regional = bool(acesso_regional)
        return

    permitidas = {u.id for u in servico_escopo.unidades_permitidas(db, autor)}
    pedidas = set(unidade_ids or [])
    if pedidas - permitidas:
        raise HTTPException(
            403, "Você não pode conceder acesso a unidades que não enxerga.")

    alvo.escopo_unidades = EscopoUnidades.LISTA
    alvo.unidades = db.query(Unidade).filter(Unidade.id.in_(pedidas)).all() if pedidas else []
    alvo.acesso_regional = bool(acesso_regional)


@router.put("/{usuario_id}/escopo", response_model=UsuarioOut)
def alterar_escopo(usuario_id: int, dados: UsuarioEscopo,
                   db: Session = Depends(get_db),
                   usuario: Usuario = Depends(get_current_user)):
    alvo = _buscar(db, usuario_id)
    if alvo.excluido_em:
        raise HTTPException(400, "Este acesso foi excluído.")
    hierarquia.exigir_gerenciar(usuario, alvo)

    _aplicar_escopo(db, alvo, usuario, dados.escopo_unidades,
                    dados.unidade_ids, dados.acesso_regional)
    db.commit()
    db.refresh(alvo)
    return alvo


# ==============================================================================
# SUSPENDER — reversível
# ==============================================================================
@router.put("/{usuario_id}/ativo", response_model=UsuarioOut)
def alterar_ativo(usuario_id: int, dados: UsuarioAtivo,
                  db: Session = Depends(get_db),
                  usuario: Usuario = Depends(get_current_user)):
    """Afastamento temporário: tira o acesso hoje, devolve amanhã."""
    alvo = _buscar(db, usuario_id)
    if alvo.excluido_em:
        raise HTTPException(
            400, "Este acesso foi excluído — suspender não se aplica.")
    hierarquia.exigir_gerenciar(usuario, alvo)

    alvo.ativo = bool(dados.ativo)
    db.commit()
    db.refresh(alvo)
    return alvo


# ==============================================================================
# EXCLUIR — definitivo, mas a história fica
# ==============================================================================
@router.delete("/{usuario_id}", response_model=UsuarioOut)
def excluir(usuario_id: int, db: Session = Depends(get_db),
            usuario: Usuario = Depends(get_current_user)):
    """Tira o acesso de vez e some da lista — sem apagar a linha.

    Apagar de verdade deixaria órfão cada compra e cada contagem que a
    pessoa lançou: o movimento continuaria valendo no estoque, e ninguém
    saberia mais quem o fez. Relatório antigo perderia o autor
    retroativamente, e o passado mudaria.

    Então a linha permanece, o acesso morre, e fica registrado quem excluiu.
    """
    alvo = _buscar(db, usuario_id)
    hierarquia.exigir_gerenciar(usuario, alvo)
    if alvo.excluido_em:
        raise HTTPException(400, "Este acesso já foi excluído.")

    alvo.excluido_em = datetime.utcnow()
    alvo.excluido_por_id = usuario.id
    alvo.ativo = False          # cinto e suspensório: o login checa os dois
    db.commit()
    db.refresh(alvo)
    return alvo


@router.post("/{usuario_id}/restaurar", response_model=UsuarioOut)
def restaurar(usuario_id: int, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    """Desfaz uma exclusão feita por engano.

    A conta volta suspensa, não ativa: quem restaura decide depois se o
    acesso é devolvido. Voltar direto ao ar seria surpresa para quem não
    acompanhou.
    """
    alvo = _buscar(db, usuario_id)
    hierarquia.exigir_gerenciar(usuario, alvo)
    if not alvo.excluido_em:
        raise HTTPException(400, "Este acesso não está excluído.")

    alvo.excluido_em = None
    alvo.excluido_por_id = None
    alvo.ativo = False
    db.commit()
    db.refresh(alvo)
    return alvo


# ==============================================================================
# A porta que foi fechada
# ==============================================================================
@router.post("", status_code=410)
def criar_desativado():
    """Conta não nasce mais aqui. Nasce de um convite.

    Devolve 410 (Gone), não 404: a rota existiu, foi retirada de propósito,
    e quem chamar merece saber para onde ir.
    """
    raise HTTPException(
        410,
        "O cadastro é fechado: conta nova entra por convite. "
        "Vá em Equipe, gere um link e envie para a pessoa — ela escolhe a "
        "própria senha. Aqui você administra quem já entrou.")
