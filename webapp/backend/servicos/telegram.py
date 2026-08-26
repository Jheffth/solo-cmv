"""
Pareamento entre uma pessoa e uma conta de Telegram.

O QUE ESTE ARQUIVO EVITA
------------------------
Pedir login e senha dentro do chat. Seria o caminho óbvio e é o errado: a
mensagem fica no histórico do aparelho, no aparelho de quem receber um
encaminhamento, e nos servidores do Telegram. Três lugares que não
controlamos guardando uma credencial nossa, para sempre.

O código de 6 dígitos troca isso por um segredo que vale 10 minutos, serve
uma vez só e não abre nada sozinho — quem o digita precisa estar com o
celular na mão no momento em que alguém de dentro do sistema o gerou.

A REVOGAÇÃO É O QUE TORNA O TOKEN LONGO ACEITÁVEL
--------------------------------------------------
O token do bot dura meses, porque ninguém vai parar de contar na câmara fria
para fazer login de novo. O que compensa isso não é encurtar o prazo — é o
desvínculo valer na hora: `auth/deps.py` recusa qualquer token de canal
TELEGRAM cujo usuário não tenha mais `telegram_chat_id`, antes de olhar
qualquer regra de negócio.

Celular perdido: alguém desvincula na tela de Equipe e o acesso morre no
pedido seguinte.
"""
import json
import secrets
from datetime import datetime, timedelta
from typing import Optional

from fastapi import HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from models import (CodigoPareamento, ModoTelegram, SessaoTelegram,
                    TentativaVinculo, UpdateProcessado, Usuario)
from auth.security import criar_token_telegram

MINUTOS_VALIDADE = 10

# Cinco palpites errados e o chat espera quinze minutos.
#
# Cinco é generoso para quem digita: o código tem seis dígitos, vem de outra
# tela, e trocar 5 por S ou 0 por O é o erro normal — daí a fonte
# monoespaçada no campo. Quem erra de verdade acerta na segunda ou terceira.
#
# E é apertado para quem varre: com quinze minutos de castigo, um milhão de
# combinações levaria séculos por chat. O atacante teria que criar uma conta
# de Telegram nova a cada cinco tentativas, e é aí que o ataque deixa de
# valer a pena — que é tudo o que se pede de um limite.
TENTATIVAS_ATE_BLOQUEAR = 5
MINUTOS_BLOQUEIO = 15

# Seis dígitos dão um milhão de combinações e o código morre em 10 minutos.
# Adivinhar por tentativa exigiria milhares de mensagens ao bot nesse
# intervalo — e o `_limpar_expirados` some com os candidatos antigos, então
# a janela nunca acumula.
DIGITOS = 6


def _gerar_codigo() -> str:
    # secrets, não random: random é previsível a partir de saídas anteriores,
    # e aqui a saída anterior é entregue a alguém de propósito.
    return "".join(str(secrets.randbelow(10)) for _ in range(DIGITOS))


def _limpar_expirados(db: Session) -> None:
    db.query(CodigoPareamento).filter(
        CodigoPareamento.expira_em < datetime.utcnow(),
        CodigoPareamento.usado_em.is_(None),
    ).delete(synchronize_session=False)


def gerar(db: Session, usuario: Usuario) -> dict:
    """Um código novo para esta pessoa vincular o próprio Telegram.

    Códigos anteriores dela são descartados: dois códigos válidos ao mesmo
    tempo criam a dúvida de qual é o certo, e quem gerou de novo foi porque
    o primeiro não serviu.
    """
    _limpar_expirados(db)
    db.query(CodigoPareamento).filter(
        CodigoPareamento.usuario_id == usuario.id,
        CodigoPareamento.usado_em.is_(None),
    ).delete(synchronize_session=False)

    # Colisão com um código vivo de OUTRA pessoa mandaria o vínculo para a
    # conta errada. É improvável e é catastrófico — a combinação que merece
    # um laço em vez de um comentário dizendo "não vai acontecer".
    for _ in range(20):
        codigo = _gerar_codigo()
        existe = db.query(CodigoPareamento).filter(
            CodigoPareamento.codigo == codigo,
            CodigoPareamento.usado_em.is_(None),
            CodigoPareamento.expira_em >= datetime.utcnow(),
        ).first()
        if not existe:
            break
    else:
        raise HTTPException(500, "Não foi possível gerar um código agora. Tente de novo.")

    registro = CodigoPareamento(
        usuario_id=usuario.id,
        codigo=codigo,
        expira_em=datetime.utcnow() + timedelta(minutes=MINUTOS_VALIDADE),
    )
    db.add(registro)
    db.commit()

    return {
        "codigo": codigo,
        "expira_em": registro.expira_em.isoformat(),
        "minutos": MINUTOS_VALIDADE,
        "instrucao": f"No Telegram, mande para o bot:  /vincular {codigo}",
    }


class ErroVinculo(Exception):
    """Falha de pareamento com mensagem pronta para o chat."""

    def __init__(self, mensagem: str):
        self.mensagem = mensagem
        super().__init__(mensagem)


def _erros_recentes(db: Session, chat_id: int) -> int:
    desde = datetime.utcnow() - timedelta(minutes=MINUTOS_BLOQUEIO)
    return db.query(TentativaVinculo).filter(
        TentativaVinculo.chat_id == chat_id,
        TentativaVinculo.quando >= desde).count()


def _anotar_erro(db: Session, chat_id: int) -> None:
    """Grava o palpite errado — e só ele.

    Acerto não deixa rastro aqui: o registro existe para conter quem tenta,
    não para virar histórico de quem entrou. Isso também é o que faz o
    contador zerar sozinho para quem errou e depois acertou.
    """
    db.add(TentativaVinculo(chat_id=chat_id))
    # Poda oportunista: a tabela é de curto prazo, e um serviço à parte só
    # para varrê-la seria mais peça para manter do que o problema merece.
    db.query(TentativaVinculo).filter(
        TentativaVinculo.quando < datetime.utcnow() - timedelta(hours=24)
    ).delete(synchronize_session=False)
    db.commit()


def vincular(db: Session, codigo: str, chat_id: int,
             username: Optional[str] = None) -> dict:
    """Consome o código e liga o chat ao usuário. Devolve o token do canal."""
    if _erros_recentes(db, chat_id) >= TENTATIVAS_ATE_BLOQUEAR:
        raise ErroVinculo(
            f"Muitas tentativas erradas. Espere {MINUTOS_BLOQUEIO} minutos e "
            f"gere um código novo no seu Perfil, em “Vincular Telegram”.")

    codigo = (codigo or "").strip()
    if not codigo.isdigit() or len(codigo) != DIGITOS:
        # Formato errado não conta como palpite: quem manda "/vincular" sem
        # nada, ou cola um texto junto, não está adivinhando — está errando o
        # comando. Gastar uma das cinco chances aí puniria a pessoa certa.
        raise ErroVinculo(
            f"O código tem {DIGITOS} dígitos. No sistema, abra seu Perfil e "
            f"toque em “Vincular Telegram”.")

    registro = db.query(CodigoPareamento).filter(
        CodigoPareamento.codigo == codigo).order_by(
            CodigoPareamento.id.desc()).first()

    # Três respostas diferentes para três situações diferentes. "Código
    # inválido" para tudo faria a pessoa tentar de novo o mesmo código
    # vencido, indefinidamente.
    #
    # As três anotam o erro. A tentação é poupar o caso "já usado" e o
    # "expirou", que parecem engano honesto — mas quem varre um milhão de
    # números também cai neles, e um contador com exceções é um contador que
    # se contorna.
    if not registro:
        _anotar_erro(db, chat_id)
        raise ErroVinculo("Não encontrei esse código. Confira os dígitos e "
                          "tente de novo.")
    if registro.usado_em is not None:
        _anotar_erro(db, chat_id)
        raise ErroVinculo("Esse código já foi usado. Gere um novo no seu "
                          "Perfil, em “Vincular Telegram”.")
    if registro.expira_em < datetime.utcnow():
        _anotar_erro(db, chat_id)
        raise ErroVinculo(f"Esse código expirou (vale {MINUTOS_VALIDADE} "
                          f"minutos). Gere um novo no seu Perfil.")

    usuario = registro.usuario
    if usuario is None or not usuario.ativo or usuario.excluido_em is not None:
        raise ErroVinculo("Essa conta não está ativa. Fale com quem "
                          "administra os acessos.")

    # Este chat já pertence a outra pessoa? Trocar em silêncio faria os
    # lançamentos passarem a ter o autor errado — e ninguém repararia até
    # alguém perguntar quem lançou aquilo.
    outro = db.query(Usuario).filter(
        Usuario.telegram_chat_id == chat_id,
        Usuario.id != usuario.id).first()
    if outro is not None:
        raise ErroVinculo(
            f"Este Telegram já está vinculado a outra conta ({outro.nome}). "
            f"Peça para desvincular antes, na tela de Equipe.")

    usuario.telegram_chat_id = chat_id
    usuario.telegram_username = username
    usuario.telegram_vinculado_em = datetime.utcnow()

    registro.usado_em = datetime.utcnow()
    registro.chat_id = chat_id

    # Acertou: o histórico de erros deste chat some. Quem digitou errado duas
    # vezes e acertou na terceira não pode carregar essas duas para a próxima
    # vez que trocar de aparelho, semanas depois.
    db.query(TentativaVinculo).filter(
        TentativaVinculo.chat_id == chat_id).delete(synchronize_session=False)
    db.commit()

    return {
        "usuario_id": usuario.id,
        "nome": usuario.apelido or usuario.nome,
        "papel": usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel,
        "token": criar_token_telegram(usuario.id),
    }


def desvincular(db: Session, usuario: Usuario) -> None:
    """Corta o acesso deste Telegram agora — não quando o token vencer."""
    usuario.telegram_chat_id = None
    usuario.telegram_username = None
    usuario.telegram_vinculado_em = None
    db.commit()


def por_chat(db: Session, chat_id: int) -> Optional[Usuario]:
    return db.query(Usuario).filter(
        Usuario.telegram_chat_id == chat_id,
        Usuario.ativo.is_(True),
        Usuario.excluido_em.is_(None),
    ).first()


# ==============================================================================
# ESTADO DA CONVERSA
# ==============================================================================
def _json(valor) -> Optional[str]:
    return json.dumps(valor, ensure_ascii=False) if valor is not None else None


def _do_json(texto) -> Optional[dict]:
    if not texto:
        return None
    try:
        return json.loads(texto)
    except (ValueError, TypeError):
        # Contexto corrompido não pode derrubar a conversa: perder o "onde eu
        # estava" custa um /contar a mais; estourar exceção custa o bot.
        return None


def _sessao_do_chat(db: Session, chat_id: int, usuario: Usuario) -> SessaoTelegram:
    sessao = db.query(SessaoTelegram).filter(
        SessaoTelegram.chat_id == chat_id).first()
    if sessao is None:
        sessao = SessaoTelegram(chat_id=chat_id, usuario_id=usuario.id,
                                modo=ModoTelegram.LIVRE)
        db.add(sessao)
        db.commit()
        db.refresh(sessao)
    elif sessao.usuario_id != usuario.id:
        # O chat trocou de dono (desvinculado e revinculado por outra
        # pessoa). Herdar o contexto faria a nova pessoa continuar a contagem
        # da anterior — com o autor errado gravado em cada item.
        sessao.usuario_id = usuario.id
        sessao.modo = ModoTelegram.LIVRE
        sessao.contexto = None
        sessao.ultimo_lancamento = None
        db.commit()
    return sessao


def estado_da_sessao(db: Session, chat_id: int, usuario: Usuario) -> dict:
    s = _sessao_do_chat(db, chat_id, usuario)
    return {
        "modo": s.modo.value if hasattr(s.modo, "value") else s.modo,
        "unidade_id": s.unidade_id,
        "contexto": _do_json(s.contexto) or {},
        "ultimo_lancamento": _do_json(s.ultimo_lancamento),
    }


def gravar_sessao(db: Session, chat_id: int, usuario: Usuario,
                  modo: Optional[str] = None,
                  unidade_id: Optional[int] = None,
                  contexto: Optional[dict] = None,
                  ultimo_lancamento: Optional[dict] = None) -> dict:
    s = _sessao_do_chat(db, chat_id, usuario)
    if modo is not None:
        s.modo = ModoTelegram(modo)
    if unidade_id is not None:
        s.unidade_id = unidade_id
    if contexto is not None:
        s.contexto = _json(contexto)
    if ultimo_lancamento is not None:
        # {} explícito significa "esqueça o último" — depois de um /desfazer,
        # desfazer de novo não pode reverter o penúltimo sem a pessoa ver.
        s.ultimo_lancamento = _json(ultimo_lancamento) if ultimo_lancamento else None
    db.commit()
    return estado_da_sessao(db, chat_id, usuario)


# ==============================================================================
# IDEMPOTÊNCIA
# ==============================================================================
DIAS_GUARDA_UPDATE = 7


def registrar_update(db: Session, update_id: int) -> bool:
    """True se este update é NOVO. False se já foi processado antes.

    A corrida existe: dois workers podem tentar gravar o mesmo update_id ao
    mesmo tempo. O UNIQUE no banco é quem decide — quem perder leva
    IntegrityError e trata como repetido, que é exatamente o que ele é.
    Verificar antes de inserir, sozinho, deixaria a janela aberta.
    """
    ja = db.query(UpdateProcessado).filter(
        UpdateProcessado.update_id == update_id).first()
    if ja is not None:
        return False
    try:
        db.add(UpdateProcessado(update_id=update_id))
        db.commit()
    except IntegrityError:
        db.rollback()
        return False

    # Poda barata, feita de vez em quando em vez de num serviço à parte: o
    # Telegram não reentrega nada com mais de 24 h, então 7 dias é folga.
    if update_id % 200 == 0:
        limite = datetime.utcnow() - timedelta(days=DIAS_GUARDA_UPDATE)
        db.query(UpdateProcessado).filter(
            UpdateProcessado.processado_em < limite).delete(
                synchronize_session=False)
        db.commit()
    return True
