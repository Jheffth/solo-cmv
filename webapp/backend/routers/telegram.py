"""
As rotas que o bot e a tela usam para se falar.

DUAS PORTAS DIFERENTES, DE PROPÓSITO
------------------------------------
`/telegram/codigo` e `/telegram/desvincular` são chamadas pela TELA, com o
token normal de quem está logado — é a pessoa pedindo o próprio código.

`/telegram/vincular` é chamada pelo BOT, sem token de PESSOA — nesse momento
ele ainda não existe, é justamente o que ela emite. Mas exige o segredo do
processo, que o bot já carrega para as outras rotas. E o código de 6 dígitos
continua valendo 10 minutos e servindo uma vez só.
"""
import secrets
from typing import Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from config import BOT_SEGREDO
from database import get_db
from models import Usuario
from auth.deps import get_current_user, exigir_canal_web
from auth.security import criar_token_telegram
from servicos import telegram as servico
from servicos import comandos as servico_comandos
from servicos import hierarquia
from servicos import permissoes

router = APIRouter(prefix="/telegram", tags=["telegram"])


def _exigir_segredo(x_bot_segredo: Optional[str] = Header(None)) -> None:
    """Só o processo do bot passa por aqui.

    `compare_digest` e não `==`: comparação comum de string sai no primeiro
    byte diferente, e o tempo dessa saída vaza o prefixo correto. É uma
    precaução barata contra um ataque que exigiria muitas tentativas — e
    muitas tentativas é justamente o que um script faz.
    """
    if not BOT_SEGREDO:
        raise HTTPException(
            503, "O canal do Telegram não está configurado neste servidor "
                 "(BOT_SEGREDO ausente no .env).")
    if not x_bot_segredo or not secrets.compare_digest(x_bot_segredo, BOT_SEGREDO):
        raise HTTPException(401, "Segredo do bot inválido.")


class PedidoVinculo(BaseModel):
    codigo: str
    chat_id: int
    username: Optional[str] = None


@router.post("/codigo")
def gerar_codigo(db: Session = Depends(get_db),
                 usuario: Usuario = Depends(exigir_canal_web)):
    """Um código para ESTA pessoa vincular o próprio Telegram.

    Pelo canal web e só por ele: gerar o próprio código de dentro do bot
    seria um laço — quem já está no bot não precisa, e quem não está não
    consegue pedir.
    """
    return servico.gerar(db, usuario)


@router.post("/vincular", dependencies=[Depends(_exigir_segredo)])
def vincular(dados: PedidoVinculo, db: Session = Depends(get_db)):
    """Consome o código e devolve o token do canal. Chamada pelo bot.

    EXIGE O SEGREDO DO BOT, e a razão é que ela não exigia.

    O desenho original a deixou aberta com um argumento correto: o token
    ainda não existe, é ela quem o emite, e a proteção seria o código de seis
    dígitos. O que faltava é que o bot JÁ CARREGA o segredo para as rotas de
    sessão — então deixá-la aberta não comprava nada e publicava na internet
    um endpoint que aceita palpites.

    Isso sozinho não resolve, e vale dizer por quê: qualquer pessoa pode
    escrever para o bot no Telegram, e é o bot — com segredo válido — que
    repassa o palpite. O segredo fecha a porta direta; quem contém a
    adivinhação é o limite de tentativas por chat, em servicos/telegram.py.

    Duas camadas para o mesmo ataque, porque cada uma sozinha deixa passar um
    caminho diferente.
    """
    try:
        return servico.vincular(db, dados.codigo, dados.chat_id, dados.username)
    except servico.ErroVinculo as erro:
        # 400, não 401: não é credencial inválida, é um código que não serve.
        # E a mensagem vai direto para o chat, então precisa dizer o que fazer.
        raise HTTPException(400, erro.mensagem)


@router.get("/status")
def status(db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    """Se este usuário tem Telegram vinculado, para a tela de Perfil."""
    return {
        "vinculado": usuario.telegram_chat_id is not None,
        "username": usuario.telegram_username,
        "desde": usuario.telegram_vinculado_em.isoformat()
                 if usuario.telegram_vinculado_em else None,
    }


@router.delete("/vinculo")
def desvincular(db: Session = Depends(get_db),
                usuario: Usuario = Depends(exigir_canal_web)):
    """Corta o próprio vínculo. Vale no pedido seguinte, não no vencimento."""
    servico.desvincular(db, usuario)
    return {"vinculado": False,
            "mensagem": "Telegram desvinculado. O bot para de responder agora."}


@router.delete("/vinculo/{usuario_id}")
def desvincular_de(usuario_id: int, db: Session = Depends(get_db),
                   autor: Usuario = Depends(exigir_canal_web)):
    """Cortar o vínculo de OUTRA pessoa — o caso do celular perdido.

    Passa pela mesma régua de quem pode mexer em quem (`hierarquia`), porque
    é exatamente isso que está acontecendo: alguém alterando o acesso de
    outra pessoa.
    """
    alvo = db.query(Usuario).filter(Usuario.id == usuario_id).first()
    if not alvo:
        raise HTTPException(404, "Usuário não encontrado.")
    hierarquia.exigir_gerenciar(autor, alvo)
    servico.desvincular(db, alvo)
    return {"vinculado": False, "usuario": alvo.nome}


# ==============================================================================
# A PORTA DO PROCESSO DO BOT
# ==============================================================================
class PedidoSessao(BaseModel):
    chat_id: int


@router.post("/sessao", dependencies=[Depends(_exigir_segredo)])
def abrir_sessao_do_chat(dados: PedidoSessao, db: Session = Depends(get_db)):
    """Tudo que o bot precisa para atender uma mensagem, numa viagem só.

    Quem é a pessoa, o que ela pode, onde a conversa parou, e um token curto
    para as chamadas seguintes. O token não é guardado em lugar nenhum — nem
    aqui, nem no bot: nasce a cada pedido e morre com ele.
    """
    usuario = servico.por_chat(db, dados.chat_id)
    if usuario is None:
        # Não é erro: é o estado normal de quem ainda não vinculou. Tratar
        # como 401 faria o bot logar exceção a cada mensagem de desconhecido.
        return {"vinculado": False}

    sessao = servico.estado_da_sessao(db, dados.chat_id, usuario)
    return {
        "vinculado": True,
        "token": criar_token_telegram(usuario.id),
        "usuario": {
            "id": usuario.id,
            "nome": usuario.apelido or usuario.nome,
            "papel": usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel,
        },
        "capacidades": permissoes.concedidas(usuario),
        "ve_dinheiro": permissoes.ve_dinheiro(usuario),
        "sessao": sessao,
        "ajuda": servico_comandos.ajuda_para(usuario, sessao.get("modo")),
        # O que ela NÃO pode, com o nome do comando: é o que permite o bot
        # responder "/cmv não está no seu acesso" em vez de "não conheço".
        "comandos_fora": [
            {"nome": c.nome, "descricao": c.descricao}
            for c in servico_comandos.COMANDOS
            if not servico_comandos.permitido(usuario, c.nome)
        ],
    }


class GravarSessao(BaseModel):
    chat_id: int
    modo: Optional[str] = None
    unidade_id: Optional[int] = None
    contexto: Optional[dict] = None
    ultimo_lancamento: Optional[dict] = None


@router.put("/sessao", dependencies=[Depends(_exigir_segredo)])
def gravar_sessao(dados: GravarSessao, db: Session = Depends(get_db)):
    """Onde a conversa parou.

    No banco, e não na memória do bot, porque o bot reinicia a cada deploy —
    e quem estivesse no item 30 de 42 voltaria ao começo sem entender por
    quê, recontando o que já contou.
    """
    usuario = servico.por_chat(db, dados.chat_id)
    if usuario is None:
        raise HTTPException(404, "Chat não vinculado.")
    return servico.gravar_sessao(
        db, dados.chat_id, usuario,
        modo=dados.modo, unidade_id=dados.unidade_id,
        contexto=dados.contexto, ultimo_lancamento=dados.ultimo_lancamento)


class MarcarUpdate(BaseModel):
    update_id: int


@router.post("/update", dependencies=[Depends(_exigir_segredo)])
def marcar_update(dados: MarcarUpdate, db: Session = Depends(get_db)):
    """Registra o update e diz se ele JÁ tinha sido processado.

    O Telegram reentrega tudo que o servidor não confirmou. Sem isto, uma
    queda de rede no momento errado vira contagem duplicada — que não dá
    erro, não avisa ninguém, e estraga o inventário em silêncio.

    A decisão vem do banco, e não de um conjunto na memória do bot, porque o
    caso perigoso é justamente o bot ter caído entre receber e confirmar.
    """
    return {"novo": servico.registrar_update(db, dados.update_id)}


@router.get("/comandos")
def comandos(db: Session = Depends(get_db),
             usuario: Usuario = Depends(get_current_user)):
    """O que ESTE usuário pode mandar para o bot.

    Mesma lista que o despachante usa para recusar. A ajuda não descreve a
    regra — ela é a regra, exibida. Ver servicos/comandos.py.
    """
    return servico_comandos.descrever(usuario)
