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
import os
from typing import List, Optional

from servicos import chave_nfe

log = logging.getLogger("servicos.danfe")

# ==============================================================================
# DUAS LINHAS QUE VALEM MAIS QUE TODO O RESTO DESTE ARQUIVO
# ==============================================================================
# Medido na foto de referência: a leitura da nota levava 28 segundos, e o
# tratamento de imagem inteiro — CLAHE, redimensionamento, filtro bilateral,
# limiar adaptativo — respondia por 0,1 deles. Todo o tempo era do Tesseract.
# Duas configurações dele explicam três quartos do custo:
#
# OMP_THREAD_LIMIT=1
#   O Tesseract usa OpenMP para paralelizar internamente, e em imagem de
#   página o custo de coordenar as threads é maior que o ganho. Medido aqui,
#   numa passada: 3,67s com o padrão, 1,63s com uma thread só. Não é
#   intuitivo — "menos paralelismo, mais rápido" — mas é reprodutível e
#   conhecido. Fica em `setdefault` para o servidor poder discordar.
#
# tessedit_do_invert=0
#   Quando a confiança sai baixa, o Tesseract REFAZ a leitura na imagem
#   invertida, procurando texto branco em fundo preto. A nossa já chega
#   binarizada em preto sobre branco pelo `_preparar`: a segunda passada não
#   tem chance de achar nada e cobra o preço inteiro. Medido: 4,60s -> 2,77s.
#
# As duas juntas: 4,60s -> ~1,3s por passada, sem tocar em um pixel e sem
# mudar um caractere do que é lido.
os.environ.setdefault("OMP_THREAD_LIMIT", "1")

# `--psm 6` = um bloco de texto uniforme, que é o que uma faixa de DANFE é.
CONFIG_OCR = "--psm 6 -c tessedit_do_invert=0"

# Quantas passadas de OCR podem rodar ao mesmo tempo.
#
# Duas, e não "quantos núcleos houver", porque este servidor não é só nosso:
# o Solo Rotinas e o Solo Finances rodam na mesma máquina, e uma importação
# de nota não pode derrubar a resposta dos outros dois. Duas também não é
# regressão de consumo — antes UMA chamada do Tesseract se espalhava por
# todos os núcleos via OpenMP; agora cada uma usa um só, e duas juntas
# custam o mesmo que aquela uma custava.
LEITURAS_SIMULTANEAS = int(os.environ.get("OCR_SIMULTANEO", "2"))


def em_paralelo(tarefas, limite: int = None):
    """Roda as leituras ao mesmo tempo, preservando a ordem das respostas.

    Vale a pena porque o pytesseract não é Python: ele chama o executável do
    Tesseract em outro processo, e a espera por esse processo solta a GIL.
    Threads aqui são paralelismo de verdade, não concorrência de mentira.

    Uma tarefa que estoura devolve None em vez de derrubar as outras — é a
    mesma política das passadas isoladas, e pelo mesmo motivo: perder uma
    leitura degrada o resultado, perder todas o inviabiliza.
    """
    from concurrent.futures import ThreadPoolExecutor

    tarefas = list(tarefas)
    if not tarefas:
        return []
    limite = limite or LEITURAS_SIMULTANEAS
    if limite <= 1 or len(tarefas) == 1:
        return [_com_rede(t) for t in tarefas]
    with ThreadPoolExecutor(max_workers=min(limite, len(tarefas))) as pool:
        return list(pool.map(_com_rede, tarefas))


def _com_rede(tarefa):
    try:
        return tarefa()
    except LeitorIndisponivel:
        raise
    except Exception:
        log.exception("uma passada de OCR falhou; as outras seguem")
        return None

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
                    config=CONFIG_OCR + " -c tessedit_char_whitelist=0123456789 ")
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
