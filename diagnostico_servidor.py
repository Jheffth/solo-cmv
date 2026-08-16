"""
Diagnóstico do Solo CMV na Contabo — só lê, não altera nada.

Responde a quatro perguntas, nesta ordem:
  1. A lentidão é da máquina (CPU/RAM/disco) ou da aplicação?
  2. Há mais de uma instância do Solo CMV rodando e brigando pela porta?
  3. Quais rotas estão lentas, e o tempo é de banco ou de Python?
  4. O Caddy está entregando os arquivos estáticos ou repassando ao Python?

Uso:
    pip install paramiko
    set SOLO_SSH_HOST=<ip do servidor>          (Windows: set / Linux: export)
    set SOLO_SSH_SENHA=<senha do root>
    python diagnostico_servidor.py

Nem o endereço nem a senha ficam escritos aqui. Este arquivo é versionado num
repositório público: endereço de servidor mais usuário `root` é meio caminho
andado para quem procura alvo, e o mesmo servidor sustenta outros sistemas.
"""
import os
import sys
import getpass

try:
    import paramiko
except ImportError:
    sys.exit("Falta a biblioteca: pip install paramiko")

HOST = os.environ.get("SOLO_SSH_HOST", "")
USER = os.environ.get("SOLO_SSH_USUARIO", "root")
DOMINIO = os.environ.get("SOLO_DOMINIO", "solocmv.duckdns.org")

# Cada item: (título, comando, o que procurar no resultado)
CHECAGENS = [
    ("CARGA DA MÁQUINA",
     "uptime; echo; echo '--- núcleos ---'; nproc",
     "load acima do nº de núcleos = fila de processos"),

    ("MEMÓRIA",
     "free -h; echo; echo '--- swap em uso ---'; "
     "swapon --show 2>/dev/null || echo 'sem swap'",
     "swap em uso = RAM estourou; é a causa nº 1 de lentidão em VPS"),

    ("OS 10 PROCESSOS QUE MAIS COMEM",
     "ps aux --sort=-%mem | head -11 | awk '{printf \"%-6s %5s %5s %s\\n\", "
     "$1, $3, $4, substr($0, index($0,$11), 90)}'",
     "usuario cpu% mem% comando"),

    ("QUEM ESTÁ ESCUTANDO NAS PORTAS",
     "ss -tlnp 2>/dev/null | grep -E '8000|8080|8095|5432|443|80' "
     "|| netstat -tlnp | grep -E '8000|8080|8095|5432|443|80'",
     "8095 duas vezes = dois deploys brigando (systemd + docker)"),

    ("O SOLO CMV ESTÁ DUPLICADO?",
     "echo '--- systemd ---'; systemctl is-active solo-cmv 2>/dev/null || echo 'sem servico systemd'; "
     "echo '--- docker ---'; docker ps --format '{{.Names}}\\t{{.Status}}\\t{{.Ports}}' 2>/dev/null "
     "|| echo 'sem docker'",
     "se os dois estiverem ativos, um deles esta orfao consumindo recursos"),

    ("REINÍCIOS RECENTES (aplicação caindo e subindo?)",
     "systemctl show solo-cmv -p NRestarts 2>/dev/null; "
     "journalctl -u solo-cmv --since '2 hours ago' --no-pager 2>/dev/null | "
     "grep -icE 'error|traceback|restart' | xargs -I{} echo 'linhas de erro nas ultimas 2h: {}'",
     "NRestarts alto = a aplicacao esta morrendo e o systemd ressuscitando"),

    ("ERROS NA APLICAÇÃO (últimas 2h)",
     "journalctl -u solo-cmv --since '2 hours ago' --no-pager 2>/dev/null | "
     "grep -E 'Traceback|Error|500' | tail -15 "
     "|| docker logs solo_cmv_app --since 2h 2>&1 | grep -E 'Traceback|Error|500' | tail -15",
     "IndexError em calculo_estoque = o bug que encontrei localmente"),

    ("TEMPO DE RESPOSTA — ESTÁTICO vs API",
     "for u in / /css/main.css /js/vendor/chart.umd.js /api/health; do "
     "printf '%-28s ' $u; "
     "curl -s -o /dev/null -w 'total %{time_total}s  conexao %{time_connect}s  "
     "servidor %{time_starttransfer}s  %{size_download} bytes  encoding=%{content_type}\\n' "
     "https://" + DOMINIO + "$u; done",
     "servidor >> conexao = o tempo e da aplicacao, nao da rede"),

    ("O CADDY ESTÁ COMPRIMINDO?",
     "curl -s -H 'Accept-Encoding: gzip,br' -D - -o /dev/null "
     "https://" + DOMINIO + "/js/vendor/chart.umd.js | "
     "grep -iE 'content-encoding|content-length|cache-control|server' "
     "|| echo 'nenhum cabecalho de compressao/cache'",
     "sem content-encoding = 204 KB viajando crus a cada carga"),

    ("POSTGRES — CONEXÕES E CONSULTAS LENTAS",
     "(sudo -u postgres psql -d solo_cmv -c \\\"SELECT count(*) AS conexoes, "
     "max(EXTRACT(epoch FROM now()-query_start))::int AS consulta_mais_antiga_seg "
     "FROM pg_stat_activity WHERE datname='solo_cmv';\\\" 2>/dev/null) "
     "|| (docker exec solo_cmv_db psql -U solo_cmv -d solo_cmv -c "
     "\\\"SELECT count(*) FROM pg_stat_activity WHERE datname='solo_cmv';\\\" 2>/dev/null) "
     "|| echo 'nao consegui consultar o postgres'",
     "conexoes perto de 15 = o pool (5+10) esgotou e ha fila"),

    ("TAMANHO DO BANCO E ÍNDICES FALTANDO",
     "(sudo -u postgres psql -d solo_cmv -c \\\"SELECT relname, n_live_tup AS linhas, "
     "seq_scan AS varreduras_completas, idx_scan AS via_indice FROM pg_stat_user_tables "
     "WHERE n_live_tup > 50 ORDER BY seq_scan DESC LIMIT 10;\\\" 2>/dev/null) "
     "|| echo 'pular'",
     "varreduras_completas alto com muitas linhas = falta indice"),

    ("DISCO",
     "df -h / | tail -1; echo; iostat -x 1 2 2>/dev/null | tail -6 || echo 'iostat nao instalado'",
     "disco cheio ou %util perto de 100 = gargalo de I/O"),
]


def main():
    global HOST
    if not HOST:
        HOST = input("Endereço do servidor (defina SOLO_SSH_HOST para não digitar): ").strip()
    if not HOST:
        sys.exit("Sem endereço não há o que diagnosticar.")

    senha = os.environ.get("SOLO_SSH_SENHA") or getpass.getpass(f"Senha de {USER}@{HOST}: ")

    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Conectando em {HOST}...")
    ssh.connect(HOST, port=22, username=USER, password=senha, timeout=20)
    print("Conectado. Nada sera alterado — todos os comandos sao de leitura.\n")

    linhas_relatorio = []
    for titulo, comando, dica in CHECAGENS:
        cabecalho = f"\n{'=' * 78}\n{titulo}\n{'-' * 78}"
        print(cabecalho)
        print(f"(o que olhar: {dica})\n")
        _, stdout, stderr = ssh.exec_command(comando, timeout=90)
        saida = stdout.read().decode("utf-8", "ignore").strip()
        erro = stderr.read().decode("utf-8", "ignore").strip()
        corpo = saida or "(sem saida)"
        if erro and "sudo" not in erro.lower():
            corpo += f"\n[stderr] {erro[:400]}"
        print(corpo)
        linhas_relatorio.append(f"{cabecalho}\n(o que olhar: {dica})\n\n{corpo}")

    ssh.close()

    destino = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                           "diagnostico_resultado.txt")
    with open(destino, "w", encoding="utf-8") as f:
        f.write("\n".join(linhas_relatorio))
    print(f"\n\n{'=' * 78}\nResultado salvo em: {destino}\nMe mande esse arquivo.")


if __name__ == "__main__":
    main()
