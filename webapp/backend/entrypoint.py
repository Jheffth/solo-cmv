import os
import uvicorn

# 8000 e 8080 sao do Solo Rotinas - nao usar aqui. 8095 e o padrao do Solo CMV;
# se o Windows recusar a porta (WinError 10013 - comum com Hyper-V/WSL
# reservando faixas de porta, ou firewall/antivirus), troque o valor de PORT
# no .env ou na variavel de ambiente e tente outra (ex.: 8096, 5090).
port = int(os.environ.get("PORT", 8095))

# 127.0.0.1 = só este computador acessa (servidor local de verdade).
# Para liberar na rede local (ex.: tablet na cozinha), defina HOST=0.0.0.0.
host = os.environ.get("HOST", "127.0.0.1")

print(f"[ENTRYPOINT] Solo CMV iniciando em {host}:{port}")

uvicorn.run(
    "main:app",
    host=host,
    port=port,
    log_level="info",
)
