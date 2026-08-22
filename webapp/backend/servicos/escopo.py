"""
Escopo de acesso — quais unidades cada usuário pode enxergar.

O PROBLEMA QUE ISSO RESOLVE
--------------------------
Até aqui, `unidade_id` era um parâmetro qualquer: bastava trocar o número na
URL para ver os dados de outra loja. A tela escondia a opção, mas a API
entregava — e esconder na tela não é controle de acesso, é decoração.

Agora existe uma fronteira única, aplicada no backend:

    ARQUITETO  → todas as unidades de todas as empresas, e a Regional
    DIRETOR    → todas as unidades da empresa dele, e a Regional
    demais     → só as unidades vinculadas, e a Regional só se marcada

REGIONAL É PERMISSÃO À PARTE
----------------------------
Ter acesso a A e a B não dá acesso à Regional. São coisas diferentes: ver
duas lojas é operação; ver o consolidado da rede é decisão de diretoria.
Por isso `acesso_regional` é uma marca própria, e não uma dedução de
"tem mais de uma unidade".

MIGRAÇÃO SEM QUEBRA
-------------------
Quem já usava o sistema não tem vínculo nenhum registrado. Zerar o acesso
desses usuários seria trocar um furo de segurança por uma parada de
operação. A migração vincula todos às unidades da empresa; a partir daí, o
cadastro passa a exigir a escolha explícita.
"""
from typing import List, Optional

from fastapi import Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from database import get_db
from models import (Unidade, Usuario, PapelUsuario, PAPEIS_IRRESTRITOS,
                    EscopoUnidades)
from auth.deps import get_current_user
from servicos.memoria import lembrar

# Valor que a tela manda quando o usuário escolhe "Regional" no seletor.
# É um sentinela explícito: `unidade_id` ausente já significa outra coisa
# em algumas rotas (todas as unidades, sem filtro), e confundir os dois
# seria abrir a Regional para quem não pode.
ESCOPO_REGIONAL = "REGIONAL"


class SemAcesso(HTTPException):
    def __init__(self, detalhe: str):
        super().__init__(status_code=status.HTTP_403_FORBIDDEN, detail=detalhe)


def irrestrito(usuario: Usuario) -> bool:
    return usuario.papel in PAPEIS_IRRESTRITOS


def unidades_permitidas(db: Session, usuario: Usuario) -> List[Unidade]:
    """As unidades que este usuário pode ver, em ordem alfabética.

    Lida uma vez por pedido: o guarda de unidade pergunta isto antes da rota,
    a rota pergunta de novo, e serviços chamados por ela perguntam mais uma
    vez. A resposta não muda no meio de um pedido — e como isto roda em
    *toda* rota, a consulta economizada aparece no sistema inteiro.
    """
    def carregar():
        # Duas portas levam a "todas as unidades", e são diferentes:
        #   · o PAPEL — ARQUITETO e DIRETOR enxergam tudo por definição;
        #   · o ESCOPO — TODAS, concedido a quem precisa acompanhar a rede
        #     inteira sem receber os poderes da diretoria.
        #
        # As duas são REGRA, não lista: uma loja aberta amanhã entra sozinha.
        # É essa a diferença para LISTA, que é fotografia e não se atualiza.
        ve_tudo = irrestrito(usuario) or usuario.escopo_unidades == EscopoUnidades.TODAS

        if ve_tudo:
            query = db.query(Unidade)
            # ARQUITETO atravessa empresas (é quem opera o produto). Todo o
            # resto — DIRETOR inclusive — para na fronteira da própria empresa,
            # que é o que separa um cliente do outro.
            if usuario.papel != PapelUsuario.ARQUITETO and usuario.empresa_id:
                query = query.filter(Unidade.empresa_id == usuario.empresa_id)
            return query.order_by(Unidade.nome).all()

        return sorted(usuario.unidades or [], key=lambda u: u.nome)

    return lembrar(db, ("unidades_permitidas", usuario.id), carregar)


def ids_permitidos(db: Session, usuario: Usuario) -> List[int]:
    return [u.id for u in unidades_permitidas(db, usuario)]


def pode_ver_unidade(db: Session, usuario: Usuario, unidade_id: int) -> bool:
    """Uma pergunta, uma fonte: `unidades_permitidas`.

    Este ramo já teve caminho próprio — lia `usuario.unidades` direto para
    quem não é irrestrito. Funcionou enquanto "todas as unidades" era só
    consequência do papel. Quando surgiu o escopo TODAS, a lista crua deixou
    de contar a história inteira: o sistema dizia que a pessoa via a loja nova
    e depois devolvia 403 nela.

    A lição vale além deste caso: sempre que a mesma pergunta tem duas
    respostas no código, uma delas envelhece sem ninguém perceber.
    """
    return unidade_id in ids_permitidos(db, usuario)


def pode_ver_regional(usuario: Usuario) -> bool:
    """Regional exige marca própria — ou ser um dos papéis irrestritos."""
    return irrestrito(usuario) or bool(usuario.acesso_regional)


def exigir_unidade(db: Session, usuario: Usuario, unidade_id: int) -> int:
    """Valida o acesso e devolve o id. Levanta 403 quando não pode."""
    if not pode_ver_unidade(db, usuario, unidade_id):
        raise SemAcesso("Você não tem acesso a esta unidade.")
    return unidade_id


def exigir_regional(usuario: Usuario) -> None:
    if not pode_ver_regional(usuario):
        raise SemAcesso("Você não tem acesso à visão Regional.")


# ------------------------------------------------------------------ resolução


class Escopo:
    """O recorte pedido, já validado.

    `regional=True` significa consolidar; caso contrário, `unidade_id` é
    uma unidade que o usuário comprovadamente pode ver.
    """

    def __init__(self, regional: bool, unidade_id: Optional[int],
                 unidades: List[Unidade]):
        self.regional = regional
        self.unidade_id = unidade_id
        self.unidades = unidades          # as unidades cobertas pelo recorte

    @property
    def ids(self) -> List[int]:
        return [u.id for u in self.unidades]

    @property
    def rotulo(self) -> str:
        if self.regional:
            return "Regional"
        return self.unidades[0].nome if self.unidades else "—"

    def __repr__(self):
        return f"<Escopo {'REGIONAL' if self.regional else self.unidade_id}>"


def resolver(db: Session, usuario: Usuario, unidade: Optional[str]) -> Escopo:
    """Traduz o parâmetro da URL em um escopo validado.

    Aceita o id da unidade ("2") ou o sentinela "REGIONAL". Sem valor,
    assume a primeira unidade permitida — nunca a Regional, que precisa
    ser pedida de propósito.
    """
    permitidas = unidades_permitidas(db, usuario)

    if unidade is not None and str(unidade).upper() == ESCOPO_REGIONAL:
        exigir_regional(usuario)
        if not permitidas:
            raise SemAcesso("Você não tem unidades vinculadas.")
        return Escopo(regional=True, unidade_id=None, unidades=permitidas)

    if unidade in (None, ""):
        if not permitidas:
            raise SemAcesso("Você não tem unidades vinculadas.")
        primeira = permitidas[0]
        return Escopo(regional=False, unidade_id=primeira.id, unidades=[primeira])

    try:
        unidade_id = int(unidade)
    except (TypeError, ValueError):
        raise HTTPException(400, f"Unidade inválida: {unidade!r}")

    exigir_unidade(db, usuario, unidade_id)
    alvo = next((u for u in permitidas if u.id == unidade_id), None)
    return Escopo(regional=False, unidade_id=unidade_id,
                  unidades=[alvo] if alvo else [])


# ------------------------------------------------------------------ dependency


def escopo_da_requisicao(
    unidade_id: Optional[str] = Query(
        None, description='Id da unidade ou "REGIONAL" para o consolidado'),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Escopo:
    """Dependency para as rotas que aceitam unidade ou Regional."""
    return resolver(db, usuario, unidade_id)


def validar_unidade(
    unidade_id: Optional[int] = None,
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
) -> Optional[int]:
    """Dependency para as rotas que só operam numa unidade concreta.

    Lançamento, inventário e requisição entram aqui: não existe "lançar na
    Regional", porque a Regional é uma soma, não um lugar.
    """
    if unidade_id is None:
        return None
    return exigir_unidade(db, usuario, unidade_id)
