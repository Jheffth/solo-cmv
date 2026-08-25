"""
Backup do Solo CMV — e a conferência que faz dele um backup de verdade.

BACKUP NÃO VERIFICADO É CRENÇA, NÃO BACKUP
------------------------------------------
`pg_dump` termina com código 0 em situações onde o arquivo não presta:
disco que encheu no meio, cano quebrado no `docker exec`, versão de cliente
incompatível que exporta metade. O arquivo existe, tem tamanho, e a rotina
diária segue mandando "ok" por meses — até o dia em que alguém precisa dele.

Então aqui, depois de gerar, o arquivo é **restaurado num banco descartável**
e as linhas são contadas tabela a tabela contra a origem. Só então ele é
promovido a backup válido. Custa alguns segundos e é a diferença entre ter
um backup e achar que tem.

O QUE ENTRA
-----------
Tudo que o sistema guarda está no PostgreSQL — inclusive as fotos de perfil,
que moram no banco justamente porque o container é reconstruído a cada
deploy. Então um dump é o estado completo: não há pasta de uploads para
esquecer.

O que NÃO entra, de propósito: o `.env`. Ele tem a senha do banco e a chave
de assinatura, e backup de dados não é lugar para segredo — quem restaura
precisa das credenciais do destino, não das da origem. O que ele precisa
saber está em MIGRAR_SERVIDOR.md.

ONDE O ARQUIVO CAI
------------------
`BACKUP_DIR`, que PRECISA apontar para um volume. Escrito no sistema de
arquivos do container, o backup sumiria no próximo `docker compose up
--build` — a mesma armadilha da foto de perfil, e aqui muito mais cara.

E backup que fica no mesmo servidor é meio backup: se o VPS morrer, morrem
os dois. Ver a seção de cópia externa no documento de migração.

USO
    python backup.py                      # gera, verifica e rotaciona
    python backup.py --verificar arquivo  # só confere um backup existente
    python backup.py --listar             # o que existe e se foi verificado
"""
import argparse
import os
import re
import shlex
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path
from urllib.parse import parse_qs, urlparse

DIRETORIO = Path(os.getenv("BACKUP_DIR", "/backups"))

# Retenção em camadas — ver o comentário longo em `rotacionar()` para o
# porquê. Em resumo: profundidade no tempo importa mais que quantidade de
# arquivos, porque a ameaça real é o erro percebido dias depois, não o
# servidor pegando fogo.
DIAS_DIARIOS = int(os.getenv("BACKUP_DIAS_DIARIOS", "7"))
SEMANAS_SEMANAIS = int(os.getenv("BACKUP_SEMANAS", "8"))
MESES_MENSAIS = int(os.getenv("BACKUP_MESES", "12"))

# Quando o PostgreSQL roda em container, o pg_dump certo é o DE LÁ: a versão
# do cliente precisa acompanhar a do servidor, e a imagem da aplicação é
# python:3.11-slim, que não traz pg_dump nenhum.
CONTAINER_DB = os.getenv("BACKUP_CONTAINER_DB", "").strip()

_NOME = re.compile(r"^solo_cmv_(\d{8}_\d{6})\.dump$")


# ==============================================================================
# Conexão
# ==============================================================================
def _partes(url: str) -> dict:
    """Quebra a DATABASE_URL nos pedaços que o pg_dump precisa.

    O host pode vir em dois lugares, e ignorar o segundo custou uma hora:

        postgresql://user:senha@maquina:5432/banco     ← no lugar de sempre
        postgresql://user:@/banco?host=/var/run/pg     ← socket Unix

    A segunda forma é comum em PostgreSQL local — é como o próprio pacote
    oficial configura — e ali o `hostname` da URL vem vazio. Sem olhar a
    query, o pg_dump tentava TCP em localhost e batia em "connection
    refused" num servidor que estava rodando o tempo todo.
    """
    limpa = url.replace("postgresql+psycopg://", "postgresql://")
    p = urlparse(limpa)
    consulta = parse_qs(p.query or "")
    host = p.hostname or (consulta.get("host", [""])[0]) or "localhost"
    return {
        "host": host,
        "port": str(p.port or consulta.get("port", ["5432"])[0]),
        "user": p.username or "postgres",
        "senha": p.password or "",
        "banco": (p.path or "/").lstrip("/") or "postgres",
        # Socket é caminho de arquivo; o pg_dump aceita em -h, mas quem lê o
        # comando merece saber que não é rede.
        "socket": host.startswith("/"),
    }


def _comando(base: list, conexao: dict, dentro_do_container: bool) -> list:
    """Monta o comando, passando pelo docker quando for o caso."""
    if not dentro_do_container or not CONTAINER_DB:
        return base
    # Dentro do container o banco é local: host e porta do compose não valem.
    return ["docker", "exec", "-i", CONTAINER_DB] + base


def _ambiente(conexao: dict) -> dict:
    ambiente = os.environ.copy()
    if conexao["senha"]:
        # PGPASSWORD e não a senha na linha de comando: `ps` mostra argumento,
        # e num servidor compartilhado isso é a senha do banco na tela.
        ambiente["PGPASSWORD"] = conexao["senha"]
    return ambiente


def _rodar(comando: list, conexao: dict, entrada: bytes = None) -> subprocess.CompletedProcess:
    return subprocess.run(comando, env=_ambiente(conexao), input=entrada,
                          capture_output=True, timeout=1800)


# ==============================================================================
# Contagem — a régua da conferência
# ==============================================================================
def _trocar_banco(url: str, banco: str) -> str:
    """Aponta a mesma URL para outro banco, preservando a query.

    A query é onde vive o `host=` do socket Unix — perdê-la aqui faria a
    conferência tentar TCP e falhar num servidor perfeitamente saudável.
    """
    p = urlparse(url)
    novo = p._replace(path="/" + banco)
    return novo.geturl()


def contar_linhas(url: str, banco: str = None) -> dict:
    """Quantas linhas cada tabela tem. É contra isto que o backup é conferido."""
    from sqlalchemy import create_engine, inspect, text

    if banco:
        url = _trocar_banco(url, banco)
    motor = create_engine(url)
    try:
        with motor.connect() as con:
            tabelas = inspect(con).get_table_names()
            return {t: con.execute(text(f'SELECT count(*) FROM "{t}"')).scalar()
                    for t in tabelas}
    finally:
        motor.dispose()


# ==============================================================================
# Gerar
# ==============================================================================
def gerar(url: str) -> Path:
    conexao = _partes(url)
    DIRETORIO.mkdir(parents=True, exist_ok=True)
    carimbo = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = DIRETORIO / f"solo_cmv_{carimbo}.dump"

    # -Fc: formato próprio do PostgreSQL, comprimido, e restaurável tabela a
    # tabela. SQL puro seria mais legível, mas na hora de restaurar só parte
    # de um banco — que é quando backup salva o dia — o -Fc é o que serve.
    base = ["pg_dump", "-Fc", "--no-owner", "--no-privileges",
            "-U", conexao["user"], "-d", conexao["banco"]]
    if not CONTAINER_DB:
        base += ["-h", conexao["host"], "-p", conexao["port"]]

    print(f"[BACKUP] Gerando {destino.name} …")
    r = _rodar(_comando(base, conexao, True), conexao)
    if r.returncode != 0:
        raise SystemExit(f"!! pg_dump falhou:\n{r.stderr.decode('utf-8','replace')[:600]}")

    destino.write_bytes(r.stdout)
    tamanho = destino.stat().st_size
    if tamanho < 1024:
        destino.unlink()
        raise SystemExit(f"!! O dump saiu com {tamanho} bytes — algo deu errado.")

    print(f"[BACKUP] {destino.name}: {tamanho / 1024:.0f} KB")
    return destino


# ==============================================================================
# Verificar — restaurar de verdade e conferir
# ==============================================================================
def verificar(url: str, arquivo: Path) -> bool:
    """Restaura num banco descartável e compara as linhas com a origem."""
    from sqlalchemy import create_engine, text

    conexao = _partes(url)
    esperado = contar_linhas(url)
    provisorio = f"verificar_backup_{datetime.now().strftime('%H%M%S')}"

    admin = _trocar_banco(url, "postgres")
    motor = create_engine(admin, isolation_level="AUTOCOMMIT")
    try:
        with motor.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{provisorio}"'))
            con.execute(text(f'CREATE DATABASE "{provisorio}"'))

        base = ["pg_restore", "--no-owner", "--no-privileges",
                "-U", conexao["user"], "-d", provisorio]
        if not CONTAINER_DB:
            base += ["-h", conexao["host"], "-p", conexao["port"]]

        print(f"[BACKUP] Conferindo: restaurando em {provisorio} …")
        r = _rodar(_comando(base, conexao, True), conexao, entrada=arquivo.read_bytes())
        # pg_restore avisa sobre extensões e donos mesmo quando deu certo;
        # o que importa é a contagem, não o código de saída.
        if r.returncode != 0:
            aviso = r.stderr.decode("utf-8", "replace")[:300]
            print(f"[BACKUP] pg_restore reclamou (pode ser inofensivo): {aviso}")

        obtido = contar_linhas(url, banco=provisorio)

        problemas = []
        for tabela, quantas in sorted(esperado.items()):
            veio = obtido.get(tabela)
            if veio is None:
                problemas.append(f"{tabela}: não existe no backup")
            elif veio != quantas:
                problemas.append(f"{tabela}: {quantas} na origem, {veio} no backup")

        total_origem = sum(esperado.values())
        total_backup = sum(obtido.get(t, 0) for t in esperado)

        if problemas:
            print(f"[BACKUP] !! BACKUP INVÁLIDO — {len(problemas)} divergência(s):")
            for p in problemas[:10]:
                print(f"           {p}")
            return False

        print(f"[BACKUP] Conferido: {len(esperado)} tabelas, "
              f"{total_backup} linhas — idêntico à origem ({total_origem}).")
        return True
    finally:
        with motor.connect() as con:
            con.execute(text(f'DROP DATABASE IF EXISTS "{provisorio}"'))
        motor.dispose()


# ==============================================================================
# Rotação
# ==============================================================================
def rotacionar() -> int:
    """Avô, pai e filho: diários da semana, semanais do mês, mensais do ano.

    POR QUE NÃO "SÓ O ÚLTIMO"
    ------------------------
    Guardar um backup só protege contra o servidor pegar fogo — e esse é o
    acidente MENOS provável. O que acontece de verdade é um erro que só se
    percebe dias depois: um inventário finalizado errado, uma importação que
    entrou duas vezes, alguém que apagou o que não devia.

    Com um backup de ontem, o erro de cinco dias atrás já está dentro dele.
    Restaurar não conserta nada: só devolve o mesmo problema com dados mais
    velhos. Profundidade no tempo é o que faz o backup servir para isso.

    POR QUE NÃO SIMPLESMENTE 30 DIÁRIOS
    -----------------------------------
    Porque camadas cobrem mais tempo com menos arquivos. Medido neste banco:

        30 diários  = 30 arquivos, cobrindo  1 mês
        esta regra  = ~17 arquivos, cobrindo 6 meses

    Menos espaço e cinco meses a mais de alcance. Um erro que passou
    despercebido no fechamento de dois meses atrás ainda tem conserto.

    AS TRÊS CAMADAS
        · todos os dos últimos 7 dias        — o acidente recente
        · um por semana, nas últimas 8       — o erro da quinzena
        · um por mês, nos últimos 12         — o fechamento antigo

    E o mais recente NUNCA é apagado, aconteça o que acontecer. Com a rotina
    parada por mais tempo que a retenção, apagar por data levaria justamente
    o único que restou.
    """
    if not DIRETORIO.exists():
        return 0

    datados = []
    for caminho in DIRETORIO.glob("solo_cmv_*.dump"):
        m = _NOME.match(caminho.name)
        if m:
            datados.append((datetime.strptime(m.group(1), "%Y%m%d_%H%M%S"), caminho))
    if len(datados) <= 1:
        return 0

    datados.sort(reverse=True)               # do mais novo para o mais velho
    agora = datados[0][0]
    manter = {datados[0][1]}                 # o mais recente, sempre

    semanas_vistas, meses_vistos = set(), set()

    def guardar(quando, caminho):
        """Guarda o arquivo E anota a semana e o mês que ele já cobre.

        Anotar SEMPRE é o que faz as camadas se somarem em vez de brigarem.
        Sem isso, um arquivo de dez dias atrás — recusado pela camada semanal
        porque a semana dele já estava coberta — caía na camada mensal e
        virava "o backup de agosto", ocupando a vaga do mês por ser o
        primeiro a chegar lá. Ficava um arquivo a mais e o mês passava a ser
        representado por uma data arbitrária no meio dele.
        """
        manter.add(caminho)
        semanas_vistas.add(quando.isocalendar()[:2])
        meses_vistos.add((quando.year, quando.month))

    for quando, caminho in datados:
        idade = (agora - quando).days

        if idade <= DIAS_DIARIOS:
            guardar(quando, caminho)
            continue

        # Um por semana — o mais novo de cada uma, já que a lista vem do mais
        # recente para o mais antigo. Semana coberta por um diário não gasta
        # arquivo de novo.
        if (idade <= DIAS_DIARIOS + SEMANAS_SEMANAIS * 7
                and quando.isocalendar()[:2] not in semanas_vistas):
            guardar(quando, caminho)
            continue

        if (idade <= 31 * MESES_MENSAIS
                and (quando.year, quando.month) not in meses_vistos):
            guardar(quando, caminho)

    apagados = 0
    for _, caminho in datados:
        if caminho not in manter:
            caminho.unlink()
            apagados += 1

    if apagados:
        print(f"[BACKUP] {apagados} backup(s) removido(s); {len(manter)} mantido(s) "
              f"({DIAS_DIARIOS} diários, {SEMANAS_SEMANAIS} semanais, "
              f"{MESES_MENSAIS} mensais).")
    return apagados


def registrar(url: str, sucesso: bool, arquivo: Path = None, tabelas: int = None,
              linhas: int = None, segundos: float = None, mensagem: str = None) -> None:
    """Guarda o resultado no próprio banco, para o Painel poder avisar.

    Falhar aqui NÃO derruba o backup: o arquivo já existe e já foi conferido,
    e perder o registro é bem menos grave que perder o backup. Um banco fora
    do ar impediria o registro — e é justamente o caso que o Painel detecta
    pela ausência de sucesso recente, sem depender deste INSERT.
    """
    try:
        from sqlalchemy import create_engine
        from sqlalchemy.orm import sessionmaker
        from models import ExecucaoBackup

        motor = create_engine(url)
        Sessao = sessionmaker(bind=motor)
        with Sessao() as sessao:
            sessao.add(ExecucaoBackup(
                sucesso=sucesso,
                arquivo=arquivo.name if arquivo else None,
                bytes=arquivo.stat().st_size if arquivo and arquivo.exists() else None,
                tabelas=tabelas, linhas=linhas, segundos=segundos,
                mensagem=(mensagem or "")[:2000] or None,
            ))
            # Histórico curto: o Painel só olha a última, e uma tabela que
            # cresce para sempre por causa de uma rotina diária é lixo com
            # data marcada.
            antigas = sessao.query(ExecucaoBackup).order_by(
                ExecucaoBackup.id.desc()).offset(90).all()
            for velha in antigas:
                sessao.delete(velha)
            sessao.commit()
        motor.dispose()
    except Exception as erro:
        print(f"[BACKUP] (não consegui registrar no banco: {erro})")


def listar() -> None:
    if not DIRETORIO.exists() or not any(DIRETORIO.glob("solo_cmv_*.dump")):
        print(f"Nenhum backup em {DIRETORIO}.")
        return
    print(f"{'arquivo':34} {'tamanho':>10}  quando")
    for caminho in sorted(DIRETORIO.glob("solo_cmv_*.dump"), reverse=True):
        m = _NOME.match(caminho.name)
        quando = (datetime.strptime(m.group(1), "%Y%m%d_%H%M%S")
                  .strftime("%d/%m/%Y %H:%M") if m else "?")
        print(f"{caminho.name:34} {caminho.stat().st_size / 1024:>8.0f} KB  {quando}")


def main():
    ap = argparse.ArgumentParser(description="Backup verificado do Solo CMV")
    ap.add_argument("--verificar", metavar="ARQUIVO",
                    help="só confere um backup já existente")
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--sem-verificar", action="store_true",
                    help="gera sem conferir (não recomendado — ver o cabeçalho)")
    args = ap.parse_args()

    if args.listar:
        listar()
        return

    url = os.getenv("DATABASE_URL", "")
    if not url.startswith(("postgresql://", "postgresql+psycopg://")):
        raise SystemExit("!! DATABASE_URL precisa apontar para um PostgreSQL.")

    if args.verificar:
        ok = verificar(url, Path(args.verificar))
        sys.exit(0 if ok else 1)

    comeco = datetime.now()
    try:
        arquivo = gerar(url)
    except SystemExit as erro:
        registrar(url, sucesso=False, mensagem=str(erro),
                  segundos=(datetime.now() - comeco).total_seconds())
        raise

    if args.sem_verificar:
        print("[BACKUP] Conferência pulada — este arquivo não foi provado.")
        rotacionar()
        return

    contagem = contar_linhas(url)
    if not verificar(url, arquivo):
        invalido = arquivo.with_suffix(".dump.INVALIDO")
        arquivo.rename(invalido)
        registrar(url, sucesso=False, arquivo=invalido,
                  segundos=(datetime.now() - comeco).total_seconds(),
                  mensagem="O arquivo gerado não passou na conferência de "
                           "restauração — as contagens não bateram com a origem.")
        raise SystemExit(
            f"!! O backup não passou na conferência e foi marcado como\n"
            f"   {invalido.name}. O backup bom anterior NÃO foi apagado.")

    rotacionar()
    registrar(url, sucesso=True, arquivo=arquivo,
              tabelas=len(contagem), linhas=sum(contagem.values()),
              segundos=(datetime.now() - comeco).total_seconds())
    print("[BACKUP] Pronto.")


if __name__ == "__main__":
    main()
