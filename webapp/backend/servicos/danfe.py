"""
Achar a chave de acesso numa foto de DANFE.

DOIS CAMINHOS, E O SEGUNDO EXISTE PORQUE O PRIMEIRO FALHA
---------------------------------------------------------
1. CÓDIGO DE BARRAS (Code-128). É o caminho exato: ou lê os 44 dígitos ou
   não lê nada. Nunca lê errado.
2. OCR dos dígitos impressos, logo abaixo do código. Entra quando o código
   está amassado, rasgado ou fora de foco — o caso comum de nota que passou
   o dia no bolso do estoquista.

Os dois passam pelo MESMO funil: só sai daqui candidato que fecha o dígito
verificador (ver servicos/chave_nfe.py). É isso que torna o OCR aceitável
aqui: ele erra, mas erro de OCR quase nunca fecha o módulo 11. O sistema
prefere dizer "não achei" a devolver a nota errada — a segunda opção vira
compra lançada em silêncio contra o fornecedor errado.

POR QUE RECORTAR E AMPLIAR, E NÃO SÓ LER A FOTO
-----------------------------------------------
Medido na foto real que motivou este arquivo (DANFE da Suinoaves,
900x1600, tirada de celular sobre a mesa): o leitor não acha nada na imagem
inteira, em nenhuma escala. Recortando a faixa do código e ampliando 4x, lê
na hora.

A razão é a densidade: um Code-128 de 44 dígitos tem mais de 400 barras, e
naquela foto elas ocupam ~370 pixels de largura — menos de um pixel por
barra. Ampliar não cria informação, mas dá ao decodificador subpixels com
que trabalhar.

Como não dá para saber de antemão onde a foto foi cortada, o código varre a
imagem em faixas sobrepostas, em várias escalas, e para no primeiro
resultado que fecha o verificador.
"""
import logging
from typing import List, Optional

from servicos import chave_nfe

log = logging.getLogger("servicos.danfe")

# Escalas tentadas na varredura. 4x foi o que leu a foto de referência; as
# outras cobrem fotos maiores (câmera melhor) e menores (WhatsApp comprime).
ESCALAS = (2, 3, 4, 6)

# A faixa do código de barras fica no terço superior da DANFE, à direita.
# Varremos uma área maior que isso porque foto torta e nota rasgada movem
# tudo de lugar — e porque uma varredura inútil custa milissegundos.
FAIXAS = (
    (0.00, 0.45),   # terço superior: onde o código está numa foto inteira
    (0.10, 0.60),
    (0.00, 1.00),   # a nota inteira, para foto já recortada no código
    (0.40, 1.00),
)


class LeitorIndisponivel(Exception):
    """As bibliotecas de imagem não estão instaladas neste servidor."""


def _carregar():
    """Importa cv2/zxing só quando alguém manda uma foto.

    No topo do arquivo, o import subiria em todo processo — inclusive no
    serviço de backup e no do bot, que nunca leem imagem. São dezenas de MB
    de biblioteca nativa carregados à toa.
    """
    try:
        import cv2
        import numpy as np
        import zxingcpp
        return cv2, np, zxingcpp
    except ImportError as erro:
        raise LeitorIndisponivel(
            "A leitura de foto precisa das bibliotecas de imagem "
            f"(opencv, zxing-cpp) e elas não estão neste servidor: {erro}. "
            "Digite a chave à mão enquanto isso — são os 44 números "
            "embaixo do código de barras."
        ) from erro


def _de_bytes(dados: bytes):
    cv2, np, _ = _carregar()
    imagem = cv2.imdecode(np.frombuffer(dados, np.uint8), cv2.IMREAD_COLOR)
    if imagem is None:
        raise ValueError("Não consegui abrir esse arquivo como imagem. "
                         "Mande JPG ou PNG.")
    return imagem


def _ler_codigos(imagem) -> List[str]:
    """Todos os textos de código de barras achados nesta imagem."""
    _, _, zxingcpp = _carregar()
    try:
        return [r.text for r in zxingcpp.read_barcodes(imagem) if r.text]
    except Exception:
        # Decodificador estourando em imagem estranha não pode derrubar o
        # pedido: o OCR ainda vem depois, e a digitação à mão sempre existe.
        log.exception("leitor de código de barras falhou")
        return []


def por_codigo_de_barras(imagem) -> Optional[str]:
    """Varre a imagem em faixas e escalas até um código fechar o verificador."""
    cv2, _, _ = _carregar()
    altura, largura = imagem.shape[:2]
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)

    for topo, base in FAIXAS:
        recorte = cinza[int(altura * topo):int(altura * base), :]
        if recorte.size == 0:
            continue
        for escala in ESCALAS:
            # Acima de ~4000px de largura o ganho some e o custo cresce.
            if recorte.shape[1] * escala > 4200:
                continue
            ampliado = cv2.resize(recorte, None, fx=escala, fy=escala,
                                  interpolation=cv2.INTER_CUBIC)
            for texto in _ler_codigos(ampliado):
                for candidato in chave_nfe.extrair_de_texto(texto):
                    return candidato
            # Preto-e-branco puro ajuda quando o papel está acinzentado por
            # sombra — o caso de foto tirada em cima da mesa, sob a luminária.
            binario = cv2.threshold(ampliado, 0, 255,
                                    cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1]
            for texto in _ler_codigos(binario):
                for candidato in chave_nfe.extrair_de_texto(texto):
                    return candidato
    return None


def por_ocr(imagem) -> Optional[str]:
    """Lê os 44 dígitos impressos. Só entra se o código de barras falhou."""
    cv2, _, _ = _carregar()
    try:
        import pytesseract
    except ImportError:
        return None

    altura, largura = imagem.shape[:2]
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)

    for topo, base in FAIXAS[:2]:
        recorte = cinza[int(altura * topo):int(altura * base), :]
        if recorte.size == 0:
            continue
        ampliado = cv2.resize(recorte, None, fx=3, fy=3,
                              interpolation=cv2.INTER_CUBIC)
        versoes = [
            ampliado,
            cv2.threshold(ampliado, 0, 255,
                          cv2.THRESH_BINARY + cv2.THRESH_OTSU)[1],
            cv2.adaptiveThreshold(ampliado, 255,
                                  cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                  cv2.THRESH_BINARY, 31, 10),
        ]
        for versao in versoes:
            try:
                # Só dígitos e espaço na lista branca: a chave é impressa em
                # blocos de quatro, e liberar letras faz o OCR devolver "S"
                # onde há 5 e "O" onde há 0 — os dois erros clássicos.
                texto = pytesseract.image_to_string(
                    versao,
                    config="--psm 6 -c tessedit_char_whitelist=0123456789 ")
            except Exception:
                log.exception("OCR falhou")
                return None
            for candidato in chave_nfe.extrair_de_texto(texto):
                return candidato
    return None


def achar_chave(dados: bytes) -> dict:
    """A chave que está nesta foto, e por qual caminho ela apareceu.

    Devolver a ORIGEM não é enfeite: código de barras é exato e OCR é
    palpite conferido. A tela mostra a diferença, e quem confere sabe onde
    olhar duas vezes.
    """
    imagem = _de_bytes(dados)

    achado = por_codigo_de_barras(imagem)
    if achado:
        return {"encontrada": True, "chave": achado, "origem": "CODIGO_BARRAS",
                "confianca": "alta",
                "dados": chave_nfe.validar(achado).como_dicionario()}

    achado = por_ocr(imagem)
    if achado:
        return {"encontrada": True, "chave": achado, "origem": "OCR",
                "confianca": "media",
                "dados": chave_nfe.validar(achado).como_dicionario()}

    # A dica é específica de propósito. "Não encontrado" faria a pessoa
    # tirar a mesma foto de novo; dizer o que mudar faz a segunda tentativa
    # ter chance.
    return {
        "encontrada": False,
        "mensagem": "Não achei a chave nessa foto.",
        "dica": "Tente uma foto só do código de barras, de perto e com a "
                "nota esticada — ou digite os 44 números à mão, que ficam "
                "logo abaixo dele.",
    }
