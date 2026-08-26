"""
A conversa com o Telegram — só isto, e nada de regra de negócio.

DEPENDÊNCIA ZERO DE PROPÓSITO
-----------------------------
`python-telegram-bot` é maduro e bem mantido, e ainda assim aqui não entra.
A Bot API é HTTP com JSON: getUpdates, sendMessage, answerCallbackQuery. São
três chamadas, e escrevê-las custa menos que carregar uma biblioteca com
loop de eventos próprio, modelo de handlers próprio e um ciclo de
atualizações que não é o nosso.

O ganho real não é tamanho, é teste: sem biblioteca, o teste troca esta
classe por uma que devolve updates de mentira, e a suíte inteira roda sem
rede — nem token, nem servidor do Telegram, nem espera.
"""
import json
import logging
import urllib.error
import urllib.parse
import urllib.request
from typing import List, Optional

log = logging.getLogger("bot.api")

# Long polling: uma conexão só, aberta por até 30 s, que devolve assim que
# chega mensagem. Sem domínio, sem certificado, sem porta aberta — o webhook
# entrega mais rápido, mas exige tudo isso, e a diferença é de segundos que
# ninguém percebe contando batata na câmara fria.
ESPERA_SEGUNDOS = 30


class ErroTelegram(Exception):
    pass


class TelegramAPI:
    def __init__(self, token: str, base: str = "https://api.telegram.org"):
        if not token:
            raise ErroTelegram(
                "BOT_TELEGRAM_TOKEN não definido. Crie o bot no @BotFather "
                "(/newbot) e cole o token no .env — ver bot/LEIAME.md.")
        self._url = f"{base}/bot{token}"

    # ------------------------------------------------------------------ base
    def _chamar(self, metodo: str, dados: Optional[dict] = None,
                timeout: int = 40) -> dict:
        corpo = json.dumps(dados or {}).encode("utf-8")
        pedido = urllib.request.Request(
            f"{self._url}/{metodo}", data=corpo,
            headers={"Content-Type": "application/json"})
        try:
            with urllib.request.urlopen(pedido, timeout=timeout) as resposta:
                carga = json.loads(resposta.read().decode("utf-8"))
        except urllib.error.HTTPError as erro:
            detalhe = erro.read().decode("utf-8", "replace")[:300]
            raise ErroTelegram(f"{metodo}: HTTP {erro.code} — {detalhe}")
        except urllib.error.URLError as erro:
            raise ErroTelegram(f"{metodo}: sem resposta — {erro.reason}")
        if not carga.get("ok"):
            raise ErroTelegram(f"{metodo}: {carga.get('description')}")
        return carga.get("result")

    # ---------------------------------------------------------------- leitura
    def quem_sou(self) -> dict:
        return self._chamar("getMe", timeout=15)

    def receber(self, desde: Optional[int] = None) -> List[dict]:
        dados = {"timeout": ESPERA_SEGUNDOS,
                 "allowed_updates": ["message", "callback_query"]}
        if desde is not None:
            dados["offset"] = desde
        # O timeout do socket precisa ser MAIOR que o do long polling. Igual,
        # a conexão morreria exatamente quando o Telegram fosse responder, e
        # o bot pareceria estar caindo sozinho a cada 30 segundos.
        return self._chamar("getUpdates", dados, timeout=ESPERA_SEGUNDOS + 15)

    # ----------------------------------------------------------------- escrita
    def enviar(self, chat_id: int, texto: str,
               botoes: Optional[List[List[dict]]] = None) -> dict:
        dados = {"chat_id": chat_id, "text": texto}
        if botoes:
            dados["reply_markup"] = {"inline_keyboard": botoes}
        return self._chamar("sendMessage", dados, timeout=20)

    def responder_botao(self, callback_id: str, texto: str = "") -> None:
        """Apaga o relógio girando no botão que a pessoa tocou.

        Sem isto o Telegram deixa o botão em estado de carregando por vários
        segundos — e a pessoa toca de novo, achando que não pegou.
        """
        try:
            self._chamar("answerCallbackQuery",
                         {"callback_query_id": callback_id, "text": texto[:200]},
                         timeout=10)
        except ErroTelegram:
            log.debug("answerCallbackQuery falhou; segue o jogo")


def botao(texto: str, dado: str) -> dict:
    """Um botão inline. `dado` volta como callback_data quando tocado.

    O Telegram corta callback_data em 64 bytes e não avisa: o botão
    simplesmente para de funcionar. Cortar aqui, sabendo, é melhor que
    descobrir na loja.
    """
    return {"text": texto[:64], "callback_data": dado[:64]}


def teclado(botoes: List[dict], por_linha: int = 2) -> List[List[dict]]:
    """Dois por linha é o que cabe na tela do celular sem apertar o vizinho."""
    return [botoes[i:i + por_linha] for i in range(0, len(botoes), por_linha)]
