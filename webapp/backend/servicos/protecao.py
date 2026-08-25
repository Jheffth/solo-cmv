"""
O sistema sabendo se está protegido.

A PERGUNTA CERTA É "HOUVE SUCESSO RECENTE?", NÃO "HOUVE FALHA?"
---------------------------------------------------------------
Parece a mesma coisa e não é. Se o alerta dependesse de alguém registrar um
erro, o pior caso não acenderia luz nenhuma: serviço de backup que morreu,
container que nunca subiu, banco fora do ar na hora da rotina. Nenhum desses
grava uma falha — eles simplesmente não gravam nada, e o silêncio pareceria
calmaria.

Perguntando pela ausência de sucesso, todos caem na mesma rede. Inclusive o
caso em que este código nunca viu backup nenhum.

E O CUSTO?
----------
Uma linha. `ORDER BY id DESC LIMIT 1` num índice, sobre uma tabela que a
rotação mantém em noventa registros. Some no ruído de um painel que já faz
trinta consultas, e roda uma vez por pedido porque passa pela memória de
`servicos/memoria.py`.

A verificação de verdade — restaurar o dump e conferir linha a linha —
acontece no serviço de backup, uma vez por dia, longe de qualquer usuário.
Aqui só se lê o veredito.
"""
from datetime import datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

from models import ExecucaoBackup
from servicos.memoria import lembrar

# Um dia e meio, não um dia. O serviço roda a cada 24 h contadas da subida do
# container, então o horário escorrega a cada deploy. Com o limite exato em
# 24 h, um deploy às 15h05 faria o painel acusar atraso às 15h01 do dia
# seguinte — alarme falso, e alarme falso ensina a ignorar alarme.
HORAS_ATE_ALERTAR = 36


# Quantas execuções recentes trazer. Uma só não bastaria: é preciso saber a
# última tentativa E o último sucesso, e eles podem ser linhas diferentes.
#
# Cinco resolve os dois numa consulta. E se nenhuma das cinco últimas deu
# certo, a rotina está quebrada há dias — o painel já vai gritar, e a data
# exata do último sucesso deixou de ser a informação útil.
ULTIMAS = 5


def _recentes(db: Session):
    """As últimas execuções — UMA consulta, reaproveitada no pedido inteiro.

    Duas perguntas (última tentativa, último sucesso) eram duas consultas.
    Trazendo cinco linhas de uma tabela que a rotação mantém em noventa
    registros, as duas se respondem em Python e o painel volta ao custo de
    antes.
    """
    return lembrar(db, ("backups_recentes",), lambda: (
        db.query(ExecucaoBackup)
          .order_by(ExecucaoBackup.id.desc())
          .limit(ULTIMAS).all()))


def ultimo_backup(db: Session) -> Optional[ExecucaoBackup]:
    """A execução mais recente, com ou sem sucesso."""
    recentes = _recentes(db)
    return recentes[0] if recentes else None


def ultimo_sucesso(db: Session) -> Optional[ExecucaoBackup]:
    return next((e for e in _recentes(db) if e.sucesso), None)


def _humanizar(quando: datetime) -> str:
    horas = (datetime.utcnow() - quando).total_seconds() / 3600
    if horas < 1:
        return "há menos de uma hora"
    if horas < 24:
        return f"há {int(horas)} hora{'s' if int(horas) != 1 else ''}"
    dias = int(horas / 24)
    return f"há {dias} dia{'s' if dias != 1 else ''}"


def situacao(db: Session) -> dict:
    """Como está a proteção dos dados. Só a diretoria vê isto."""
    ok = ultimo_sucesso(db)
    ultima = ultimo_backup(db)
    agora = datetime.utcnow()

    if ok is None:
        return {
            "estado": "nunca",
            "titulo": "Nenhum backup registrado",
            "detalhe": ("O sistema ainda não guardou nenhuma cópia dos dados. "
                        "Se isto persistir, um problema no servidor levaria "
                        "junto o estoque e o histórico das lojas."),
            "quando": None,
            "ultima_falhou": bool(ultima and not ultima.sucesso),
            "mensagem_da_falha": ultima.mensagem if ultima and not ultima.sucesso else None,
        }

    atraso = agora - ok.quando
    atrasado = atraso > timedelta(hours=HORAS_ATE_ALERTAR)
    falhou_depois = bool(ultima and not ultima.sucesso and ultima.quando > ok.quando)

    if atrasado or falhou_depois:
        return {
            "estado": "atrasado" if atrasado else "falhou",
            "titulo": ("Backup atrasado" if atrasado
                       else "A última tentativa de backup falhou"),
            "detalhe": (f"A última cópia conferida é de {_humanizar(ok.quando)}"
                        f" ({ok.quando.strftime('%d/%m às %H:%M')})."
                        + (f" Depois disso houve uma tentativa que não deu certo."
                           if falhou_depois else "")),
            "quando": ok.quando.isoformat(),
            "linhas": ok.linhas,
            "ultima_falhou": falhou_depois,
            "mensagem_da_falha": ultima.mensagem if falhou_depois else None,
        }

    return {
        "estado": "ok",
        "titulo": "Dados protegidos",
        "detalhe": (f"Última cópia conferida {_humanizar(ok.quando)} "
                    f"({ok.quando.strftime('%d/%m às %H:%M')}), "
                    f"com {ok.linhas or 0} registros restaurados e conferidos."),
        "quando": ok.quando.isoformat(),
        "linhas": ok.linhas,
        "ultima_falhou": False,
        "mensagem_da_falha": None,
    }


def pendencia(db: Session) -> Optional[dict]:
    """A pendência para a fila do Painel — ou nada, quando está tudo certo.

    Painel que sempre mostra alerta ensina a ignorar alerta. Com o backup em
    dia, esta função devolve None e nada aparece.
    """
    s = situacao(db)
    if s["estado"] == "ok":
        return None
    return {
        "chave": "backup",
        "gravidade": "urgente" if s["estado"] in ("nunca", "falhou") else "atencao",
        "texto": s["titulo"] + " — " + s["detalhe"],
        "rota": None,          # não há tela para resolver: é assunto do servidor
        "quantidade": None,
    }
