"""
Abertura do sistema em uma única viagem.

O PROBLEMA QUE ISTO RESOLVE
---------------------------
Abrir o Solo CMV disparava três pedidos, um esperando o outro:

    GET /auth/me            → quem é você
    GET /unidades/escopo    → o que você pode ver
    GET /dashboard/painel   → os números da tela

Nenhum deles é pesado. Medindo o servidor, `/api/health` — cinquenta bytes,
sem banco — leva ~250 ms, e o aperto de mão TCP sozinho custa 226 ms. Ou
seja: o servidor responde na hora, e o que se paga é a distância. Três
pedidos em fila são três pedágios: ~750 ms antes de a primeira letra
aparecer.

Juntando os três, sobra um. O trabalho do servidor é o mesmo; o que
desaparece são duas viagens.

O PARÂMETRO CHAMA-SE `preferida`, NÃO `unidade_id`
--------------------------------------------------
De propósito. O guarda de unidade (auth/guarda_unidade.py) intercepta
`unidade_id` em qualquer pedido e devolve 403 quando a unidade não é
permitida — que é exatamente o que queremos em toda rota de dado.

Aqui não. `preferida` é a última unidade que a pessoa usou, lembrada no
navegador. Ela pode ter perdido o acesso desde então, ou a unidade pode ter
sido removida. Se isso virasse 403, a tela de abertura não carregaria e a
pessoa ficaria trancada do lado de fora sem entender por quê.

Com outro nome, o guarda ignora, e a decisão fica aqui: preferência inválida
é ignorada em silêncio e cai na primeira unidade permitida.
"""
import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario
from auth.deps import get_current_user
from servicos import escopo as servico_escopo
from servicos import permissoes
from routers.dashboard import painel as rota_do_painel

router = APIRouter(prefix="/sessao", tags=["sessão"])
log = logging.getLogger(__name__)

REGIONAL = servico_escopo.ESCOPO_REGIONAL

# Mesmo padrão da rota /dashboard/painel — quantos meses de histórico o
# painel traz. Repetido aqui porque a chamada direta não herda defaults.
HISTORICO_PADRAO = 5


def _resolver_unidade(preferida: Optional[str], permitidas, pode_regional: bool):
    """A unidade em que a tela deve abrir.

    Ordem: o que a pessoa usava por último, se ainda puder; senão a primeira
    unidade permitida; senão nada (usuário sem unidade alguma).
    """
    if preferida:
        alvo = str(preferida).strip().upper()
        if alvo == REGIONAL:
            if pode_regional and len(permitidas) > 1:
                return REGIONAL
        else:
            try:
                numero = int(alvo)
            except (TypeError, ValueError):
                numero = None
            if numero is not None and any(u.id == numero for u in permitidas):
                return numero

    return permitidas[0].id if permitidas else None


@router.get("")
def abrir(
    preferida: Optional[str] = Query(
        None, description="Última unidade usada, lembrada pelo navegador. "
                          "Inválida é ignorada, não recusada."),
    com_painel: bool = Query(
        False, description="Traz também os números do Painel. A tela só pede "
                           "quando é o Painel que vai abrir — indo direto para "
                           "outra página, seria trabalho jogado fora."),
    referencia: Optional[str] = Query(None, description="Mês do painel (AAAA-MM)"),
    db: Session = Depends(get_db),
    usuario: Usuario = Depends(get_current_user),
):
    """Tudo que a tela precisa para abrir: quem é, o que vê, e os números."""
    permitidas = servico_escopo.unidades_permitidas(db, usuario)
    pode_regional = servico_escopo.pode_ver_regional(usuario)
    unidade = _resolver_unidade(preferida, permitidas, pode_regional)

    resposta = {
        "usuario": {
            "id": usuario.id,
            "nome": usuario.nome,
            "login": usuario.login,
            "papel": usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel,
            "empresa_id": usuario.empresa_id,
            # A barra lateral desenha a foto na abertura. Vindo aqui, ela
            # aparece na primeira pintura em vez de trocar as iniciais por
            # uma foto meio segundo depois — que é o tipo de tremida que
            # todo mundo nota e ninguém sabe explicar.
            "apelido": usuario.apelido,
            "avatar_url": usuario.avatar_url,
        },
        "escopo": {
            "unidades": [{"id": u.id, "nome": u.nome} for u in permitidas],
            "regional": pode_regional and len(permitidas) > 1,
            "papel": usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel,
            "irrestrito": servico_escopo.irrestrito(usuario),
        },
        # O que esta pessoa pode fazer, para o menu se montar sem repetir a
        # régua em JavaScript. Vem na abertura porque é aqui que a barra
        # lateral é desenhada — pedir depois faria o menu piscar itens que
        # somem, que é como o usuário aprende a não confiar na tela.
        "capacidades": permissoes.concedidas(usuario),
        "ve_dinheiro": permissoes.ve_dinheiro(usuario),
        "unidade": unidade,
        "painel": None,
    }

    if com_painel and unidade is not None:
        # Chamamos a própria rota do painel, como função. Duplicar a regra
        # aqui abriria espaço para os dois caminhos discordarem com o tempo —
        # e "o painel mostra um número na abertura e outro ao atualizar" é o
        # tipo de erro que ninguém acredita até ver.
        #
        # Falha aqui não derruba a abertura: sem o painel a tela ainda abre e
        # busca os números por conta própria, como antes.
        # Todos os argumentos são passados na mão de propósito: chamada
        # direta não passa pelo FastAPI, então os defaults continuam sendo
        # objetos `Query(...)` em vez dos valores. Omitir um não dá erro na
        # hora — vira um `Query` viajando como se fosse número.
        try:
            resposta["painel"] = rota_do_painel(
                unidade_id=str(unidade),
                referencia=referencia,
                data_inicio=None,
                data_fim=None,
                historico=HISTORICO_PADRAO,
                db=db,
                usuario=usuario,
            )
        except Exception:
            log.exception("Painel não pôde ser embutido na abertura; "
                          "a tela vai buscá-lo separadamente.")
            resposta["painel"] = None

    return resposta
