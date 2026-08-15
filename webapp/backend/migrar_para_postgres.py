"""
Transferência do banco SQLite para o PostgreSQL.

    python migrar_para_postgres.py --destino postgresql+psycopg://user:senha@host/solo_cmv
    python migrar_para_postgres.py --destino ... --aplicar

Sem `--aplicar`, só simula: lê tudo, mostra o que seria transferido e não
grava nada. É o modo padrão de propósito — migração de banco não deve ser um
comando que roda por acidente.

COMO FUNCIONA
-------------
Não usa `pg_dump` nem SQL cru: lê pelo próprio modelo do SQLAlchemy e escreve
pelo mesmo modelo. Isso resolve sozinho as três diferenças que costumam
morder numa migração:

  · booleano       SQLite guarda 0/1; o PostgreSQL quer TRUE/FALSE
  · data e hora    SQLite guarda texto; o PostgreSQL quer date/timestamp
  · enums          já são texto nos dois lados (ver `Enumerado` em models.py)

A ordem das tabelas vem de `metadata.sorted_tables`, que respeita as chaves
estrangeiras — empresa antes de unidade, unidade antes de movimento.

DEPOIS DE INSERIR, AS SEQUÊNCIAS
--------------------------------
No PostgreSQL o `id` vem de uma sequência. Inserindo com id explícito, a
sequência não avança — e o primeiro cadastro novo tentaria usar o id 1,
colidindo com o que acabou de entrar. Por isso o passo final reposiciona
cada sequência no maior id existente. Esquecer isso é o erro clássico deste
tipo de migração, e ele só aparece depois, na cara do usuário.
"""
import argparse
import os
import sys
from datetime import date, datetime

from sqlalchemy import create_engine, func, select, text
from sqlalchemy.orm import sessionmaker


def _conectar(url: str):
    if url.startswith("sqlite"):
        return create_engine(url, connect_args={"check_same_thread": False})
    return create_engine(url, pool_pre_ping=True)


def _converter(valor, coluna):
    """Ajusta o que o SQLite devolve para o que o PostgreSQL espera."""
    if valor is None:
        return None

    tipo = coluna.type.__class__.__name__

    if tipo == "Boolean" and isinstance(valor, int):
        return bool(valor)

    if tipo in ("Date", "DateTime") and isinstance(valor, str):
        texto = valor.strip()
        if tipo == "Date":
            return date.fromisoformat(texto[:10])
        # SQLite grava com ou sem microssegundos, com "T" ou espaço
        texto = texto.replace("T", " ")
        for formato in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d"):
            try:
                return datetime.strptime(texto, formato)
            except ValueError:
                continue
        raise ValueError(f"data/hora não reconhecida: {valor!r}")

    return valor


def migrar(origem_url: str, destino_url: str, aplicar: bool) -> int:
    # Importar models registra tudo em Base.metadata
    os.environ.setdefault("DATABASE_URL", origem_url)
    import models  # noqa: F401
    from database import Base

    origem = _conectar(origem_url)
    destino = _conectar(destino_url)

    tabelas = Base.metadata.sorted_tables
    print(f"origem : {origem_url}")
    print(f"destino: {destino_url.split('@')[-1] if '@' in destino_url else destino_url}")
    print(f"{len(tabelas)} tabelas, na ordem das chaves estrangeiras\n")

    # ---------------------------------------------------------------- leitura
    conteudo = {}
    total_origem = 0
    with origem.connect() as con:
        for tabela in tabelas:
            try:
                linhas = [dict(l._mapping) for l in con.execute(select(tabela))]
            except Exception as erro:
                print(f"  !! {tabela.name}: não foi possível ler ({erro})")
                linhas = []
            conteudo[tabela.name] = linhas
            total_origem += len(linhas)
            print(f"  {tabela.name:26} {len(linhas):>6} linha(s)")

    print(f"\n  TOTAL {total_origem} linha(s)")

    if not aplicar:
        print("\n(simulação — rode com --aplicar para gravar no PostgreSQL)")
        return 0

    # ---------------------------------------------------------------- destino
    print("\nCriando o esquema no destino…")
    Base.metadata.create_all(bind=destino)

    # Recusa sobrescrever base com dado — migração é operação de uma vez só
    with destino.connect() as con:
        ocupadas = []
        for tabela in tabelas:
            quantas = con.execute(select(func.count()).select_from(tabela)).scalar()
            if quantas:
                ocupadas.append(f"{tabela.name} ({quantas})")
        if ocupadas:
            print("\nERRO: o banco de destino já tem dados: " + ", ".join(ocupadas))
            print("Migre para um banco vazio. Sobrescrever aqui misturaria "
                  "registros e quebraria as chaves estrangeiras.")
            return 1

    print("Transferindo…")
    with destino.begin() as con:
        for tabela in tabelas:
            linhas = conteudo[tabela.name]
            if not linhas:
                continue
            convertidas = [
                {chave: _converter(valor, tabela.columns[chave])
                 for chave, valor in linha.items()}
                for linha in linhas
            ]
            con.execute(tabela.insert(), convertidas)
            print(f"  {tabela.name:26} {len(convertidas):>6} gravada(s)")

    # ------------------------------------------------------------- sequências
    if destino.dialect.name == "postgresql":
        print("\nReposicionando as sequências…")
        with destino.begin() as con:
            for tabela in tabelas:
                for coluna in tabela.primary_key.columns:
                    if not coluna.autoincrement or coluna.type.__class__.__name__ != "Integer":
                        continue
                    sequencia = con.execute(text(
                        "SELECT pg_get_serial_sequence(:t, :c)"
                    ), {"t": tabela.name, "c": coluna.name}).scalar()
                    if not sequencia:
                        continue
                    maior = con.execute(text(
                        f"SELECT COALESCE(MAX({coluna.name}), 0) FROM {tabela.name}"
                    )).scalar()
                    con.execute(text("SELECT setval(:s, :v)"),
                                {"s": sequencia, "v": max(maior, 1)})
                    print(f"  {tabela.name:26} próximo id: {max(maior, 1) + 1}")

    # ------------------------------------------------------------- conferência
    print("\nConferindo linha a linha…")
    divergencias = []
    with destino.connect() as con:
        for tabela in tabelas:
            gravadas = con.execute(select(func.count()).select_from(tabela)).scalar()
            esperadas = len(conteudo[tabela.name])
            marca = "ok" if gravadas == esperadas else "XX"
            if gravadas != esperadas:
                divergencias.append(f"{tabela.name}: {esperadas} → {gravadas}")
            print(f"  {marca}  {tabela.name:26} {esperadas:>6} → {gravadas}")

    if divergencias:
        print("\nDIVERGÊNCIAS:\n  " + "\n  ".join(divergencias))
        return 1

    print(f"\n{total_origem} linha(s) transferida(s) e conferida(s).")
    print("Aponte DATABASE_URL para o PostgreSQL e reinicie a aplicação.")
    return 0


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--origem", default="sqlite:///./solo_cmv.db")
    parser.add_argument("--destino", required=True)
    parser.add_argument("--aplicar", action="store_true",
                        help="grava de verdade; sem isto, só simula")
    args = parser.parse_args()
    sys.exit(migrar(args.origem, args.destino, args.aplicar))
