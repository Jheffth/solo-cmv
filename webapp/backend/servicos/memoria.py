"""
Memória de curtíssimo prazo: dentro de um pedido, a mesma pergunta só vai
ao banco uma vez.

POR QUE ISTO EXISTE
-------------------
O painel fazia 60 consultas para montar uma tela. Vinte e cinco delas eram
*idênticas*: a tabela de metas, relida uma vez para cada família e para cada
degrau da herança (família → bloco → geral). Mais nove eram a lista de
inventários finalizados, relida a cada faixa do painel.

Em SQLite isso não aparece: o banco está dentro do processo e cada consulta
custa microssegundos. Em PostgreSQL cada uma é uma conversa por rede. Foi
exatamente o que medimos no servidor: o painel gastava ~620 ms de trabalho
real, com o banco devolvendo pouquíssimos dados.

A tabela de metas tem quatro linhas. O problema nunca foi o tamanho da
resposta — foi a quantidade de idas e voltas.

COMO FUNCIONA
-------------
A sessão do SQLAlchemy vive exatamente um pedido HTTP (o `get_db` abre e
fecha). Então `db.info` é um lugar seguro para guardar resposta: nasce e
morre com o pedido, e nunca vaza de um usuário para outro.

A validade é garantida pelo evento: qualquer `flush`, `commit` ou `rollback`
esvazia a memória. Ou seja, gravou — esquece tudo o que sabia. É conservador
de propósito: prefere consultar de novo a devolver dado velho.

COMO USAR

    from servicos.memoria import lembrar

    def inventarios(db, unidade_id):
        return lembrar(db, ("inventarios", unidade_id),
                       lambda: db.query(...).all())

A chave precisa conter *todo* argumento que muda a resposta. Esquecer um é a
única forma de errar aqui — por isso as chaves abaixo são tuplas explícitas,
nunca strings montadas.
"""
from typing import Any, Callable, Hashable

from sqlalchemy import event
from sqlalchemy.orm import Session

_ESPACO = "_memoria_do_pedido"


def lembrar(db: Session, chave: Hashable, calcular: Callable[[], Any]) -> Any:
    """Devolve `calcular()`, mas só o executa uma vez por pedido e por chave."""
    memoria = db.info.setdefault(_ESPACO, {})
    if chave not in memoria:
        memoria[chave] = calcular()
    return memoria[chave]


def esquecer(db: Session) -> None:
    """Descarta a memória. Chamado sozinho a cada escrita."""
    db.info.pop(_ESPACO, None)


# Qualquer escrita invalida tudo. Registrado na classe Session, então vale
# para toda sessão do sistema — inclusive as dos testes e as do futuro bot.
@event.listens_for(Session, "after_flush")
@event.listens_for(Session, "after_commit")
@event.listens_for(Session, "after_rollback")
def _limpar_apos_escrita(sessao, *_ignorado):
    esquecer(sessao)
