FROM python:3.11-slim

WORKDIR /app

# pg_dump e pg_restore. A imagem python:3.11-slim não os traz, e sem eles
# não há backup nem restauração — só a promessa de que existem.
#
# A versão do cliente precisa acompanhar a do servidor (postgres:15 no
# compose). O bookworm entrega o 15, que casa. Se um dia o servidor subir
# para 16, este pacote sobe junto — senão o pg_dump recusa a conexão com
# "server version mismatch", e a rotina de backup para em silêncio.
#
# tesseract é a RESERVA da leitura de nota: quando o código de barras está
# amassado ou fora de foco, o sistema tenta os 44 dígitos impressos. O pacote
# de português melhora o reconhecimento do resto da página; os dígitos em si
# saem do modelo padrão.
#
# libgl1 e libglib2.0-0 são exigidos pelo OpenCV mesmo na versão headless —
# sem eles o import estoura com "libGL.so.1: cannot open shared object file",
# e o erro aparece só quando alguém manda a primeira foto.
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        postgresql-client \
        tesseract-ocr tesseract-ocr-por \
        libgl1 libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

COPY backend/requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY backend/ ./backend/
COPY frontend/ ./frontend/
# O bot vem na MESMA imagem, e não numa própria, por um motivo prático: as
# duas subiriam do mesmo commit de qualquer jeito, e duas imagens dobram o
# tempo de build a cada deploy para separar 20 KB de código. O que separa os
# dois é o processo — serviço próprio no compose, que cai sozinho sem levar
# o sistema web junto.
COPY bot/ ./bot/
COPY MIGRACAO_POSTGRES.md ./

WORKDIR /app/backend

CMD ["python", "entrypoint.py"]
