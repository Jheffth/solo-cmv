FROM python:3.11-slim

WORKDIR /app

# pg_dump e pg_restore. A imagem python:3.11-slim não os traz, e sem eles
# não há backup nem restauração — só a promessa de que existem.
#
# A versão do cliente precisa acompanhar a do servidor (postgres:15 no
# compose). O bookworm entrega o 15, que casa. Se um dia o servidor subir
# para 16, este pacote sobe junto — senão o pg_dump recusa a conexão com
# "server version mismatch", e a rotina de backup para em silêncio.
RUN apt-get update \
    && apt-get install -y --no-install-recommends postgresql-client \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
COPY MIGRACAO_POSTGRES.md ./

WORKDIR /app/backend

CMD ["python", "entrypoint.py"]
