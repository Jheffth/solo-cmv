"""
Deixar o banco pronto: criar tabelas, aplicar migrações e popular o catálogo.

POR QUE ISTO SAIU DO `startup` DA APLICAÇÃO
-------------------------------------------
O `@app.on_event("startup")` roda **uma vez por processo**. Com um worker
isso é o mesmo que "uma vez". Com `--workers 4`, que é como o servidor sobe
hoje, são quatro processos executando migração e seed ao mesmo tempo, no
mesmo banco.

O seed é feito de "existe? não? então cria":

    usuario = db.query(Usuario).filter(...).first()
    if usuario is None:
        db.add(Usuario(...))

Entre o `query` e o `add` há uma janela. Quatro processos podem responder
"não existe" juntos e inserir os quatro. O resultado é empresa duplicada,
unidade duplicada, ou erro de chave estrangeira em cima disso.

Hoje não estoura porque o banco de produção já está populado e as migrações
são idempotentes. Estoura no dia em que um banco zerado subir — que é
exatamente o cenário de instalar o sistema num cliente novo. É o pior tipo
de defeito: dorme durante todo o desenvolvimento e acorda na estreia.

COMO FICOU
----------
Duas defesas, porque uma só depende de alguém lembrar:

1. **Chamada explícita antes dos workers.** O `docker-compose.yml` roda
   `python preparar_banco.py` e só então sobe o uvicorn. Quando os workers
   nascem, não há o que fazer.

2. **Trava no banco, para o caso de esquecerem a primeira.** No PostgreSQL,
   `pg_advisory_lock` — uma trava que o próprio banco arbitra, então vale
   entre processos e entre containers. Quem chega primeiro trabalha; os
   outros esperam e encontram tudo pronto.

A segunda defesa é o que permite continuar chamando isto do `startup` sem
risco: rodar quatro vezes em série é inofensivo, porque cada etapa é
idempotente. O que não podia era rodar quatro vezes **ao mesmo tempo**.

No SQLite não há trava a pedir: é um arquivo, e o desenvolvimento roda um
processo só. O `busy_timeout` de 15 s configurado em `database.py` cobre o
resto.
"""
import logging

from sqlalchemy import text

from database import engine, criar_tabelas
from migracoes import aplicar_migracoes
from seed import popular_banco

log = logging.getLogger(__name__)

# Número arbitrário, mas fixo: é o identificador da trava. Só precisa ser o
# mesmo em todos os processos e não colidir com outra trava do sistema.
# Nenhuma outra parte do Solo CMV usa advisory lock, então não há colisão.
TRAVA_PREPARACAO = 8095_2026


def _eh_postgres() -> bool:
    return engine.dialect.name == "postgresql"


def preparar(verboso: bool = True) -> None:
    """Deixa o banco pronto para receber pedidos. Seguro chamar em paralelo."""
    if not _eh_postgres():
        # SQLite: um arquivo, um processo. Nada a arbitrar.
        _executar(verboso)
        return

    conexao = engine.connect()
    try:
        # Bloqueia até conseguir. Quem estiver preparando termina primeiro;
        # quando este processo entrar, as etapas já não terão o que fazer.
        conexao.execute(text("SELECT pg_advisory_lock(:chave)"),
                        {"chave": TRAVA_PREPARACAO})
        conexao.commit()
        _executar(verboso)
    finally:
        try:
            conexao.execute(text("SELECT pg_advisory_unlock(:chave)"),
                            {"chave": TRAVA_PREPARACAO})
            conexao.commit()
        except Exception:            # conexão já caiu: o banco solta sozinho
            log.debug("Trava liberada pelo fim da conexão.")
        conexao.close()


def _executar(verboso: bool) -> None:
    if verboso:
        print(f"[PREPARAR] Banco: {engine.dialect.name}")
    criar_tabelas()
    aplicar_migracoes()      # ajusta bancos criados antes de mudanças de schema
    popular_banco()          # empresa, unidades, Arquiteto e catálogo inicial
    if verboso:
        print("[PREPARAR] Banco pronto.")


if __name__ == "__main__":
    preparar()
