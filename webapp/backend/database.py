"""
Conexão com o banco — o mesmo código serve SQLite e PostgreSQL.

QUAL BANCO USAR
---------------
A escolha é do ambiente, via `DATABASE_URL`:

    sqlite:///./solo_cmv.db                              desenvolvimento
    postgresql+psycopg://usuario:senha@host/solo_cmv     produção

Nada no resto do código pergunta qual banco está atrás. Onde a diferença
importa de verdade — sintaxe de migração, tipo de enum — o tratamento fica
isolado em `migracoes.py` e no helper `Enumerado` de `models.py`.
"""
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker, declarative_base

from config import DATABASE_URL

EH_SQLITE = DATABASE_URL.startswith("sqlite")

if EH_SQLITE:
    # check_same_thread: o SQLite recusa uso da conexão em outra thread por
    # padrão, e o uvicorn atende cada requisição numa thread do pool.
    engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
else:
    # pool_pre_ping: conexão que o servidor derrubou (timeout, restart do
    # PostgreSQL) é descartada em vez de estourar na cara do usuário.
    # pool_recycle: recicla antes do limite típico de firewall/pgbouncer.
    engine = create_engine(
        DATABASE_URL,
        pool_pre_ping=True,
        pool_recycle=1800,
        pool_size=5,
        max_overflow=10,
    )


if EH_SQLITE:
    @event.listens_for(engine, "connect")
    def _ajustar_sqlite(conexao, _registro):
        """WAL e espera maior — muda o comportamento sob concorrência.

        Sem WAL (o padrão é `delete`), leitura e escrita se bloqueiam: abrir
        o painel enquanto alguém lança uma contagem trava um dos dois. Com
        WAL, leitores não esperam o escritor.

        `busy_timeout` de 15 s: se ainda assim houver disputa, a conexão
        espera em vez de devolver "database is locked" na hora.

        Nada disso vale para PostgreSQL, que resolve concorrência por MVCC.
        """
        cursor = conexao.cursor()
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.execute("PRAGMA busy_timeout=15000")
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.close()


SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)

Base = declarative_base()


def get_db():
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def criar_tabelas():
    import models  # noqa: F401  (garante que todos os models sejam registrados)
    Base.metadata.create_all(bind=engine)
