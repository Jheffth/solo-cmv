"""
Restauração — levantar o Solo CMV a partir de um backup, em qualquer servidor.

DOIS MOMENTOS MUITO DIFERENTES, E O SCRIPT SABE DISSO
-----------------------------------------------------
**Servidor novo.** O banco está vazio. É a migração: os donos saindo de um
provedor para outro, ou montando o próprio. Nada a perder, tudo a ganhar.

**Servidor em produção.** O banco tem os lançamentos de hoje. Restaurar aqui
apaga o que existe e substitui pelo que estava no backup — é o que se faz
quando algo deu muito errado, e é irreversível.

Os dois usam o mesmo arquivo e o mesmo comando, e confundi-los custaria o
trabalho de um dia inteiro. Por isso: banco com dados exige `--forcar`, e o
script diz em voz alta quantas linhas vai apagar antes de fazer qualquer
coisa.

SIMULA POR PADRÃO
-----------------
Sem `--aplicar`, mostra o que faria e não toca em nada. Restauração não deve
ser um comando que roda por acidente — a mesma decisão do
`migrar_para_postgres.py`, pelo mesmo motivo.

USO
    # ver o que aconteceria
    DATABASE_URL=... python restaurar.py backup.dump

    # servidor novo, banco vazio
    DATABASE_URL=... python restaurar.py backup.dump --aplicar

    # por cima de um banco com dados (destrutivo)
    DATABASE_URL=... python restaurar.py backup.dump --aplicar --forcar
"""
import argparse
import os
import subprocess
import sys
from pathlib import Path

from backup import _ambiente, _comando, _partes, _trocar_banco, contar_linhas


def _existe_e_serve(arquivo: Path) -> None:
    if not arquivo.exists():
        raise SystemExit(f"!! Arquivo não encontrado: {arquivo}")
    if arquivo.stat().st_size < 1024:
        raise SystemExit(f"!! {arquivo.name} tem {arquivo.stat().st_size} bytes — "
                         f"não é um backup.")
    # PGDMP é a assinatura do formato -Fc. Conferir aqui evita a mensagem
    # críptica que o pg_restore daria com um arquivo qualquer.
    if arquivo.read_bytes()[:5] != b"PGDMP":
        raise SystemExit(f"!! {arquivo.name} não parece um dump do PostgreSQL "
                         f"(esperava a assinatura PGDMP no começo).")


def _estado_do_destino(url: str) -> dict:
    try:
        return contar_linhas(url)
    except Exception:
        return {}       # banco ainda não existe: é o caso do servidor novo


def _garantir_banco(url: str, nome: str) -> None:
    from sqlalchemy import create_engine, text
    motor = create_engine(_trocar_banco(url, "postgres"), isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as con:
            existe = con.execute(
                text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": nome}
            ).first()
            if not existe:
                con.execute(text(f'CREATE DATABASE "{nome}"'))
                print(f"[RESTAURAR] Banco '{nome}' criado.")
    finally:
        motor.dispose()


def restaurar(url: str, arquivo: Path, aplicar: bool, forcar: bool) -> None:
    _existe_e_serve(arquivo)
    conexao = _partes(url)
    antes = _estado_do_destino(url)
    linhas = sum(antes.values())

    print(f"arquivo:  {arquivo.name} ({arquivo.stat().st_size / 1024:.0f} KB)")
    print(f"destino:  {conexao['banco']} em {conexao['host']}")
    print(f"estado:   {len(antes)} tabela(s), {linhas} linha(s)\n")

    if linhas and not forcar:
        # A mensagem lista o que se perde, não só avisa que se perde. Ver
        # "231 movimentos" faz pensar de um jeito que "há dados" não faz.
        maiores = sorted(antes.items(), key=lambda x: -x[1])[:5]
        detalhe = ", ".join(f"{t} ({n})" for t, n in maiores if n)
        raise SystemExit(
            f"!! O banco de destino JÁ TEM DADOS: {detalhe}.\n\n"
            f"   Restaurar apagaria tudo isso e poria no lugar o conteúdo do\n"
            f"   backup. Se é mesmo o que você quer, repita com --forcar.\n\n"
            f"   Se a intenção era migrar para um servidor novo, você está\n"
            f"   apontando para o banco errado.")

    if not aplicar:
        print("(simulação — nada foi alterado)")
        print("Rode de novo com --aplicar para restaurar de verdade.")
        return

    _garantir_banco(url, conexao["banco"])

    base = ["pg_restore", "--no-owner", "--no-privileges", "--clean", "--if-exists",
            "-U", conexao["user"], "-d", conexao["banco"]]
    if not os.getenv("BACKUP_CONTAINER_DB", "").strip():
        base += ["-h", conexao["host"], "-p", conexao["port"]]

    print("[RESTAURAR] Restaurando …")
    r = subprocess.run(_comando(base, conexao, True), env=_ambiente(conexao),
                       input=arquivo.read_bytes(), capture_output=True, timeout=3600)
    if r.returncode != 0:
        # O pg_restore reclama de dono e extensão mesmo quando deu certo. Quem
        # decide é a contagem, logo abaixo — não o código de saída.
        print(f"[RESTAURAR] Avisos do pg_restore:\n"
              f"{r.stderr.decode('utf-8', 'replace')[:400]}")

    depois = contar_linhas(url)
    total = sum(depois.values())
    print(f"\n[RESTAURAR] {len(depois)} tabela(s), {total} linha(s) no destino.")

    if not total:
        raise SystemExit("!! O destino ficou vazio — a restauração não funcionou.")

    print("\nPróximos passos:")
    print("  1. Confira o .env do servidor (DATABASE_URL, SECRET_KEY, CORS_ORIGINS)")
    print("  2. Suba a aplicação: docker compose up -d --build")
    print("  3. Entre no sistema e confira o Painel de um mês conhecido")
    print("\n  A SECRET_KEY do servidor novo deve ser NOVA — não a da origem.")
    print("  Trocá-la só derruba as sessões abertas; ninguém perde dado.")


def main():
    ap = argparse.ArgumentParser(description="Restaura o Solo CMV a partir de um backup")
    ap.add_argument("arquivo")
    ap.add_argument("--aplicar", action="store_true",
                    help="grava de verdade (sem isto, só simula)")
    ap.add_argument("--forcar", action="store_true",
                    help="permite restaurar por cima de um banco com dados")
    args = ap.parse_args()

    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("!! DATABASE_URL precisa apontar para um PostgreSQL.")

    restaurar(url, Path(args.arquivo), args.aplicar, args.forcar)


if __name__ == "__main__":
    main()
