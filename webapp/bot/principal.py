"""
O laço do bot. Recebe update, confirma, atende — nessa ordem, e importa.

A ORDEM É A PROTEÇÃO
--------------------
O Telegram reentrega qualquer update que o servidor não confirmou. Se o bot
atendesse primeiro e marcasse depois, uma queda entre as duas coisas viraria
lançamento duplicado na volta. Marcando ANTES, o pior caso é uma mensagem
perdida — e mensagem perdida a pessoa percebe e reenvia; contagem duplicada
não dá erro, não avisa ninguém, e estraga o inventário em silêncio.

Trocar um erro invisível por um erro visível é quase sempre o negócio certo.

FALHA DE REDE NÃO DERRUBA O PROCESSO
------------------------------------
O bot roda ao lado do sistema web, e o `restart: always` do compose o reergue
se ele cair. Mas cair a cada oscilação de rede faria o container reiniciar em
laço, e um bot que reinicia em laço perde updates de verdade. Então erro de
rede espera e tenta de novo; só o que é irrecuperável — token inválido —
para o processo, e com uma mensagem que diz o que fazer.
"""
import logging
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from conversa import Conversa                            # noqa: E402
from solo_api import ErroAPI, SoloAPI                    # noqa: E402
from telegram_api import ErroTelegram, TelegramAPI       # noqa: E402

logging.basicConfig(
    level=os.getenv("BOT_LOG", "INFO").upper(),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")

ESPERA_APOS_FALHA = 5      # segundos
ESPERA_MAXIMA = 60


def _extrair(update: dict):
    """(chat_id, texto, username, callback_data, callback_id) do update."""
    if "message" in update:
        msg = update["message"]
        chat = (msg.get("chat") or {}).get("id")
        de = msg.get("from") or {}
        return chat, msg.get("text") or "", de.get("username"), None, None
    if "callback_query" in update:
        cb = update["callback_query"]
        msg = cb.get("message") or {}
        chat = (msg.get("chat") or {}).get("id")
        de = cb.get("from") or {}
        return chat, "", de.get("username"), cb.get("data") or "", cb.get("id")
    return None, "", None, None, None


def rodar(telegram, solo, segredo, limite_de_voltas=None):
    """O laço. `limite_de_voltas` existe para o teste poder terminar."""
    conversa = Conversa(telegram, solo, segredo)
    proximo = None
    voltas = 0
    espera = ESPERA_APOS_FALHA

    while limite_de_voltas is None or voltas < limite_de_voltas:
        voltas += 1
        try:
            updates = telegram.receber(desde=proximo)
            espera = ESPERA_APOS_FALHA
        except ErroTelegram as erro:
            log.warning("getUpdates falhou (%s); esperando %ss", erro, espera)
            time.sleep(espera)
            # Recuo progressivo: se o Telegram está fora do ar, insistir de
            # segundo em segundo não acelera a volta dele e enche o log.
            espera = min(espera * 2, ESPERA_MAXIMA)
            continue

        for update in updates or []:
            update_id = update.get("update_id")
            # O offset avança SEMPRE, inclusive para update que deu erro.
            # Sem isso, uma mensagem que o bot não consegue processar seria
            # reentregue para sempre e travaria a fila de todo mundo.
            proximo = update_id + 1

            try:
                novo = solo.post("/api/telegram/update",
                                 {"update_id": update_id}).get("novo")
            except ErroAPI as erro:
                log.error("não deu para marcar o update %s: %s", update_id, erro)
                continue
            if not novo:
                log.info("update %s reentregue — ignorado", update_id)
                continue

            chat, texto, username, callback, callback_id = _extrair(update)
            if chat is None:
                continue
            if callback_id:
                telegram.responder_botao(callback_id)
            conversa.atender(chat, texto, username=username, callback=callback)


def main():
    token = os.getenv("BOT_TELEGRAM_TOKEN", "").strip()
    segredo = os.getenv("BOT_SEGREDO", "").strip()
    base = os.getenv("SOLO_API", "http://app:8095").strip()

    if not segredo:
        print("BOT_SEGREDO não definido no .env. O bot e a aplicação precisam "
              "do MESMO valor — é ele que identifica o processo do bot na "
              "API.", file=sys.stderr)
        return 2

    try:
        telegram = TelegramAPI(token)
        eu = telegram.quem_sou()
    except ErroTelegram as erro:
        print(f"Não consegui falar com o Telegram: {erro}", file=sys.stderr)
        print("Confira BOT_TELEGRAM_TOKEN no .env — ver bot/LEIAME.md.",
              file=sys.stderr)
        return 2

    log.info("conectado como @%s", eu.get("username"))
    solo = SoloAPI(base, segredo=segredo)
    rodar(telegram, solo, segredo)
    return 0


if __name__ == "__main__":
    sys.exit(main())
