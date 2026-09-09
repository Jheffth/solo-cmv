"""
Ler a tabela de itens de uma FOTO de DANFE — e provar o que foi lido.

A REGRA QUE ORGANIZA ESTE ARQUIVO
---------------------------------
OCR erra. Isso não é problema desde que o erro não passe calado, e é aí que
quase toda leitura de nota por foto falha: devolve um número plausível, com
cara de certo, e alguém lança no estoque.

Medido na foto que motivou este código (nota da Suinoaves, celular, papel
rasgado, sombra do teclado), o OCR devolveu:

    COSTELA SALGADA .... 296,90  lido como  396,90     (R$ 100 a mais)
    PANCETA FOOD ....... 15,1000 lido como  1S,1000
    PE SALGADO ......... 5,0000  lido como  $,0000

Então aqui nada é aceito por ter sido lido. É aceito por FECHAR CONTA.

AS DUAS CONTAS QUE A PRÓPRIA NOTA OFERECE
-----------------------------------------
1. A soma dos valores dos itens = o total de produtos impresso na nota.
   Esta é a mais forte. Com os candidatos de cada linha, existe em geral UMA
   combinação que fecha no centavo — e achá-la confirma a coluna inteira de
   dinheiro sem depender de nenhuma leitura estar certa isoladamente.

   Na foto de referência: 129,90 + 296,90 + 467,95 + 54,95 = 949,70, e
   nenhuma outra combinação dos números lidos chega lá.

2. quantidade x valor unitário = valor do item. Confirma a quantidade, que é
   o número que vai virar estoque.

3. A COLUNA. A DANFE é uma tabela: quantidade, valor unitário e valor total
   ficam sempre nas mesmas três colunas, uma linha embaixo da outra. Guardar
   ONDE cada número estava dá identidade a todos de uma vez.

   Foi o que faltava na primeira versão. Ela lia os números certos — 296,90 e
   29,99 apareciam na tela, em botão — e deixava os campos vazios, porque não
   sabia qual era quantidade e qual era base de cálculo do ICMS. Oito números
   soltos numa linha são oito números.

   As colunas não são adivinhadas por posição fixa; foto torta move tudo.
   São eleitas pela conta: o trio certo é o que faz q x vu = total em mais
   linhas e cuja coluna de totais soma até o impresso sem estourar. Na nota de
   referência isso importou — a BC do ICMS era IGUAL ao valor do item na
   primeira linha, e só a soma da coluna inteira desempatou.

O QUE A COLUNA MUDOU NA POSTURA DO ARQUIVO
------------------------------------------
Com identidade, contas que antes eram chute viram aritmética. 296,90 dividido
pelo preço da MESMA linha dá a quantidade que ninguém conseguiu ler; e a
última linha sem valor sai da subtração, porque as outras três parcelas estão
numa coluna, não são "os maiores números de cada linha".

O que NÃO mudou é o que decide. Confirmado continua saindo de um jeito só:
três números lidos, cada um na sua coluna, e a multiplicação bate. Quantidade
deduzida por divisão é preenchida e MARCADA — ela responde "quanto teria que
ser", que não é a mesma pergunta que "quanto está escrito no papel".

E a régua final continua sendo a tela: o total impresso somando enquanto a
pessoa confirma. O ganho é que a pessoa agora confere doze números já no
lugar, em vez de digitá-los.
"""
import logging
import re
from dataclasses import dataclass, field
from itertools import combinations, product
from typing import List, Optional

from servicos import danfe

log = logging.getLogger("servicos.danfe_itens")

# Um centavo de folga por linha; a soma de quatro linhas acumula arredondamento.
TOLERANCIA = 0.02

# Acima disso o número quase nunca é valor de item — é base de cálculo,
# alíquota somada ou lixo de OCR. Corta o espaço de busca da combinação.
MAX_CANDIDATOS_POR_LINHA = 8

# Faixas da página onde procurar. A DANFE tem posição fixa por lei, mas foto
# torta e nota rasgada movem tudo — por isso são faixas largas e sobrepostas.
FAIXA_ITENS = (0.45, 0.64)
FAIXA_TOTAIS = (0.34, 0.50)

# Recorte e escala de cada passada. Mudar qualquer um dos dois faz o OCR
# acertar números DIFERENTES — é essa discordância que a coluna resolve.
PASSADAS = ((0.45, 0.64, 4), (0.47, 0.62, 3), (0.49, 0.61, 5))

# Meia largura de uma coluna, em fração da página. Colunas de DANFE ficam a
# ~0,055 uma da outra; 0,028 encosta na vizinha sem invadi-la.
RAIO_COLUNA = 0.028

# ==============================================================================
# A COLUNA DO CÓDIGO DO FORNECEDOR
# ==============================================================================
# A primeira coluna da tabela ("CÓDIGO PRODUTO") é o casamento mais forte que
# existe com o nosso cadastro: o fornecedor pode reescrever a descrição do
# produto a cada nota, mas o código dele não muda.
#
# Lida junto com o resto, ela sai errada: na largura cheia o OCR devolveu
# "AOS:" no lugar de 1105 e "35" no lugar de 25 — o miolo da tabela puxa a
# atenção do reconhecedor. Recortada sozinha e com whitelist de dígitos, as
# duas escalas juntas entregaram os quatro códigos da nota de referência:
#
#     y 0,286 -> 05 / 1105      y 0,482 -> 1077 / 10777 / 077
#     y 0,415 -> 44             y 0,546 -> 25
#
# Note que sai lixo junto ("16", "0", "8"). Não faz mal, e é o ponto: nada
# aqui é aceito por ter sido lido. Cada leitura vira CANDIDATA, e quem
# escolhe é o de-para do fornecedor — código que não bate com nada aprendido
# simplesmente não custa nada.
COLUNA_CODIGO = (0.09, 0.19)      # faixa horizontal, em fração da página
ESCALAS_CODIGO = (4, 6)

# Quão longe da primeira e da última linha de item um número ainda pode
# estar e ser código. Folgado de propósito: o que sobra de ruído é curto e
# cai para o fim da lista, mas um código legítimo que ficasse de fora não
# tem como voltar.
FORA_DA_TABELA = 0.10

_CODIGO = re.compile(r"^\d{1,8}$")

_NUMERO = re.compile(r"\d{1,3}(?:\.\d{3})*,\d{2,4}|\d+,\d{2,4}")


def _para_float(texto: str) -> Optional[float]:
    """"1.234,56" e "12,9900" viram float. Ponto é milhar, vírgula é decimal."""
    try:
        return float(texto.replace(".", "").replace(",", "."))
    except ValueError:
        return None


def _preparar(imagem, escala: int = 4):
    """Deixa o papel legível para o OCR.

    CLAHE antes de tudo: a foto de nota quase sempre tem sombra de um lado
    (a mão, o corpo, a luminária). Equalização GLOBAL estoura o lado claro
    para salvar o escuro; a local resolve os dois.

    Limiar adaptativo, e não Otsu: Otsu escolhe um corte único para a imagem
    inteira, e numa foto com gradiente de luz isso apaga metade da tabela.
    """
    cv2, _, _ = danfe._carregar()
    cinza = cv2.cvtColor(imagem, cv2.COLOR_BGR2GRAY)
    cinza = cv2.createCLAHE(clipLimit=2.5, tileGridSize=(8, 8)).apply(cinza)
    cinza = cv2.resize(cinza, None, fx=escala, fy=escala,
                       interpolation=cv2.INTER_CUBIC)
    # Bilateral em vez de blur comum: tira o ruído do papel sem borrar a
    # borda dos dígitos, que é justamente o que o OCR usa para distinguir
    # 5 de S e 0 de O.
    cinza = cv2.bilateralFilter(cinza, 5, 60, 60)
    return cv2.adaptiveThreshold(cinza, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
                                 cv2.THRESH_BINARY, 41, 12)


def _pytesseract():
    try:
        import pytesseract
    except ImportError:
        raise danfe.LeitorIndisponivel(
            "A leitura de itens por foto precisa do tesseract, que não está "
            "neste servidor. Use o XML da nota enquanto isso.")
    return pytesseract


def _ocr(imagem) -> str:
    try:
        return _pytesseract().image_to_string(imagem, config=danfe.CONFIG_OCR)
    except danfe.LeitorIndisponivel:
        raise
    except Exception as erro:
        log.exception("OCR da tabela falhou")
        raise danfe.LeitorIndisponivel(f"A leitura falhou: {erro}")


@dataclass
class LinhaOcr:
    """Uma linha física da imagem: o texto dela e ONDE cada número estava.

    A posição é a informação que a leitura por texto jogava fora — e é
    justamente ela que diz qual número é quantidade e qual é base de cálculo
    do ICMS. Sem ela, oito números numa linha são oito números.
    """
    y: float
    texto: str
    numeros: List[tuple] = field(default_factory=list)   # (x_centro, valor)


def _ocr_com_posicao(imagem) -> List[LinhaOcr]:
    """O OCR devolvendo também a coluna de cada número.

    Usa o agrupamento em linhas do próprio tesseract em vez de fatiar por
    coordenada: a foto de nota é sempre torta, e numa faixa inclinada o y de
    um número da ponta direita já invade a linha de baixo. O tesseract junta
    por linha de texto, que é o que interessa.
    """
    pt = _pytesseract()
    try:
        dados = pt.image_to_data(imagem, config=danfe.CONFIG_OCR,
                                 output_type=pt.Output.DICT)
    except Exception as erro:
        log.exception("OCR posicionado falhou")
        raise danfe.LeitorIndisponivel(f"A leitura falhou: {erro}")

    largura = max(1, imagem.shape[1])
    altura = max(1, imagem.shape[0])
    agrupadas = {}
    for i, bruto in enumerate(dados["text"]):
        palavra = (bruto or "").strip()
        if not palavra:
            continue
        chave = (dados["block_num"][i], dados["par_num"][i], dados["line_num"][i])
        linha = agrupadas.setdefault(chave, LinhaOcr(y=dados["top"][i] / altura,
                                                     texto=""))
        linha.texto = (linha.texto + " " + palavra).strip()
        centro = (dados["left"][i] + dados["width"][i] / 2) / largura
        for achado in _NUMERO.findall(palavra):
            valor = _para_float(achado)
            if valor is not None and valor > 0:
                linha.numeros.append((centro, round(valor, 4)))
    return sorted(agrupadas.values(), key=lambda l: l.y)


# ==============================================================================
# LINHAS
# ==============================================================================
@dataclass
class LinhaLida:
    """Uma linha da tabela, com o que foi lido e o que foi PROVADO."""
    texto: str
    descricao: str
    candidatos: List[float] = field(default_factory=list)

    valor_total: Optional[float] = None
    quantidade: Optional[float] = None
    valor_unitario: Optional[float] = None

    # Tudo que a coluna do código devolveu para esta linha, lixo incluído.
    # É lista, e não um valor, porque nenhuma leitura sozinha é confiável —
    # quem escolhe entre elas é o de-para do fornecedor, adiante.
    codigos: List[str] = field(default_factory=list)

    # Só é `True` quando a aritmética fechou. Leitura sozinha nunca confirma.
    total_confirmado: bool = False
    quantidade_confirmada: bool = False

    @property
    def precisa_conferir(self) -> bool:
        return not (self.total_confirmado and self.quantidade_confirmada)

    def como_dicionario(self) -> dict:
        return {
            "descricao": self.descricao,
            "codigos": self.codigos,
            "quantidade": self.quantidade,
            "valor_unitario": self.valor_unitario,
            "valor_total": self.valor_total,
            "total_confirmado": self.total_confirmado,
            "quantidade_confirmada": self.quantidade_confirmada,
            "precisa_conferir": self.precisa_conferir,
            "lidos": self.candidatos[:MAX_CANDIDATOS_POR_LINHA],
        }


@dataclass
class RascunhoDaFoto:
    linhas: List[LinhaLida] = field(default_factory=list)
    total_produtos: Optional[float] = None
    total_nota: Optional[float] = None
    soma_confere: bool = False
    avisos: List[str] = field(default_factory=list)

    @property
    def campos_a_conferir(self) -> int:
        return sum(1 for l in self.linhas if l.precisa_conferir)

    def como_dicionario(self) -> dict:
        return {
            "linhas": [l.como_dicionario() for l in self.linhas],
            "total_produtos": self.total_produtos,
            "total_nota": self.total_nota,
            "soma_confere": self.soma_confere,
            "campos_a_conferir": self.campos_a_conferir,
            "avisos": self.avisos,
        }


def _limpar_descricao(bruto: str) -> str:
    """Tira o lixo de borda que o OCR põe na frente do nome do produto.

    A margem esquerda da DANFE tem linhas de tabela que viram "SSS AOS:",
    "=i £105.", "eee fag". Cortar até a primeira letra não basta — o lixo
    TEM letras.

    O que separa lixo de palavra é a vogal: "SSS" e "fag" não são nome de
    produto, "EMBUTIDO" é. Descartar tokens até achar um com vogal e três
    letras acerta em todas as linhas da nota de referência.
    """
    tokens = re.split(r"[\s|]+", bruto.strip())
    for i, token in enumerate(tokens):
        limpo = re.sub(r"[^A-Za-zÀ-ú]", "", token)
        if len(limpo) >= 3 and re.search(r"[AEIOUÀ-ú]", limpo, re.I):
            resto = " ".join(tokens[i:])
            # Corta no NCM/CFOP: a descrição acaba onde começam os códigos
            # fiscais (8 e 4 dígitos). Sem isso a linha arrasta "02032900}
            # 020. -St01 Ka" para dentro do nome do produto, e quem confere
            # perde tempo lendo lixo.
            corte = re.search(r"\s\d{4,}", resto)
            if corte:
                resto = resto[:corte.start()]
            return resto.strip(" .|-_:")[:120]
    return ""


def _linha_de_produto(bruta: str) -> Optional[LinhaLida]:
    """A linha vira item, ou não vira nada.

    O critério é ter ao menos três números com casas decimais e alguma letra
    — a linha do "Fonte IBPT" tem números mas é continuação, e o cabeçalho
    tem letras mas não tem valores.
    """
    limpa = bruta.strip()
    if len(limpa) < 12:
        return None
    numeros = [n for n in (_para_float(t) for t in _NUMERO.findall(limpa))
               if n is not None and n > 0]
    if len(numeros) < 3:
        return None
    # Descrição: o que vem antes do primeiro número longo, sem o código
    # do produto que abre a linha.
    descricao = _limpar_descricao(_NUMERO.split(limpa)[0])
    if len(descricao) < 4:
        return None
    # "Fonte IBPT", "pRedBC", "pIcmsSt" são continuação fiscal do item
    # acima, não itens novos.
    if re.search(r"IBPT|pRedBC|IcmsSt|CEST", limpa, re.I):
        return None
    return LinhaLida(texto=limpa, descricao=descricao[:120], candidatos=numeros)


def _linhas_com_produto(texto: str) -> List[LinhaLida]:
    """As linhas que parecem item, e não cabeçalho ou rodapé fiscal."""
    achadas = (_linha_de_produto(b) for b in texto.split("\n"))
    return [l for l in achadas if l is not None]


def _ler_itens_em_varias_passadas(imagem) -> List[LinhaLida]:
    """Lê a tabela algumas vezes e SOMA os números vistos em cada passada.

    O OCR é instável de um jeito específico: mudando a escala ou o recorte,
    ele acerta números diferentes. Medido na foto de referência, uma passada
    leu 54,95 e outra perdeu; uma leu 30,99 e outra devolveu 36,59.

    Nenhuma passada sozinha é confiável, e não há como saber qual acertou.
    Mas a UNIÃO dos candidatos quase sempre contém o número certo — e a
    conferência pela soma (adiante) sabe escolher qual é. Mais candidatos
    ruins não atrapalham: só entram na busca e são descartados por não
    fecharem a conta.
    """
    return _juntar_passadas(danfe.em_paralelo(_tarefas_de_itens(imagem)))


def _tarefas_de_itens(imagem):
    """As leituras da tabela, ainda por fazer.

    Devolve funções em vez de resultados para que quem chama decida QUANDO e
    COM QUEM rodá-las. É o que permite juntar estas três com a leitura do
    rodapé numa fila só — em vez de duas filas aninhadas, que dariam quatro
    processos de Tesseract ao mesmo tempo num servidor que não é só nosso.
    """
    def uma_passada(topo, base, escala):
        def ler_faixa():
            recorte = imagem[int(imagem.shape[0] * topo):
                             int(imagem.shape[0] * base), :]
            if recorte.size == 0:
                return None
            return _ocr_com_posicao(_preparar(recorte, escala))
        return ler_faixa

    return [uma_passada(topo, base, escala)
            for topo, base, escala in PASSADAS]


def _tarefas_de_codigos(imagem):
    """As leituras da coluna do código, ainda por fazer.

    Recorte estreito e whitelist de dígitos: sem o miolo da tabela por perto,
    e sem poder devolver letra, o reconhecedor acerta o que errava. Duas
    escalas porque cada uma acerta um código diferente — na nota de
    referência a 4x leu 44 e 1077, a 6x leu 1105, e só juntas leram os
    quatro.
    """
    altura, largura = imagem.shape[0], imagem.shape[1]
    topo, base = FAIXA_ITENS
    esquerda, direita = COLUNA_CODIGO

    def uma_escala(escala):
        def ler():
            recorte = imagem[int(altura * topo):int(altura * base),
                             int(largura * esquerda):int(largura * direita)]
            if recorte.size == 0:
                return []
            preparada = _preparar(recorte, escala)
            pt = _pytesseract()
            dados = pt.image_to_data(
                preparada,
                config=danfe.CONFIG_OCR + " -c tessedit_char_whitelist=0123456789",
                output_type=pt.Output.DICT)
            alto = max(1, preparada.shape[0])
            achados = []
            for i, bruto in enumerate(dados["text"]):
                texto = (bruto or "").strip()
                if _CODIGO.match(texto):
                    achados.append((dados["top"][i] / alto, texto))
            return achados
        return ler

    return [uma_escala(escala) for escala in ESCALAS_CODIGO]


def _atribuir_codigos(linhas: List[LinhaLida], fisicas_por_linha,
                      leituras) -> None:
    """Põe cada código lido na linha de item mais próxima em altura.

    Cada leitura vai para UMA linha, a mais próxima — e não para todas as que
    estiverem por perto. Espalhar seria conveniente e perigoso: o código
    certo de um item, oferecido também ao item de baixo, casaria com o
    produto errado com toda a confiança do mundo, que é o único jeito de
    esta via produzir um erro grave.

    Sobre a altura da linha do item: usamos a do TEXTO da descrição, que é a
    mesma faixa e a mesma normalização da coluna do código. Na nota de
    referência as quatro atribuições saem certas com folga.
    """
    alturas = []
    for linha, fisica in zip(linhas, fisicas_por_linha):
        alturas.append(fisica.y if fisica is not None else None)
    if not any(a is not None for a in alturas):
        return

    # O recorte da coluna pega um pedaço do que está ACIMA da tabela — o
    # rótulo "CÓDIGO PRODUTO", a caixa de QUANTIDADE do transporte. Aqueles
    # números são lidos com folga pelas duas escalas, e sem esta trava
    # entravam como candidatos bem votados de um item que fica logo abaixo.
    conhecidas = [a for a in alturas if a is not None]
    primeira, ultima = min(conhecidas), max(conhecidas)

    brutos = [[] for _ in linhas]
    for y, codigo in leituras:
        if y < primeira - FORA_DA_TABELA or y > ultima + FORA_DA_TABELA:
            continue
        melhor, distancia = None, 1.0
        for indice, altura in enumerate(alturas):
            if altura is None:
                continue
            if abs(altura - y) < distancia:
                melhor, distancia = indice, abs(altura - y)
        if melhor is not None:
            brutos[melhor].append(codigo)

    # A ORDEM DA LISTA É UM PALPITE, E VALE DIZER QUAL.
    #
    # A tela precisa de um código para propor quando ainda não há de-para —
    # na PRIMEIRA nota do fornecedor, que é justamente quando o aprendizado
    # acontece e quando um erro se eterniza. Duas evidências, nesta ordem:
    #
    #   1. quantas escalas leram o mesmo. Duas leituras iguais em imagens
    #      preparadas de formas diferentes raramente são o mesmo engano;
    #   2. quantas escalas leram o mesmo. Duas leituras iguais em imagens
    #      preparadas de formas diferentes raramente são o mesmo engano.
    #
    # O comprimento vem primeiro, e não a repetição, porque o ruído se repete
    # com facilidade: "16" e "0", do rótulo acima da tabela, apareciam nas
    # duas escalas e ganhavam de "1105", lido numa só.
    #
    # Medido na nota de referência, os quatro primeiros da lista são os
    # quatro códigos certos. Ainda assim a tela mostra a lista inteira e
    # deixa escolher: proposto não é confirmado.
    for linha, lidos in zip(linhas, brutos):
        linha.codigos = sorted(set(lidos),
                               key=lambda c: (-len(c), -lidos.count(c), c))


def _juntar_passadas(resultados):
    """Une o que as passadas viram, com a mais completa servindo de esqueleto."""
    passadas = []
    for fisicas in resultados:
        if not fisicas:
            continue
        itens = [(_linha_de_produto(f.texto), f) for f in fisicas]
        itens = [(l, f) for l, f in itens if l is not None]
        if itens:
            passadas.append((itens, fisicas))

    if not passadas:
        return [], [], []

    # A passada com MAIS linhas vira o esqueleto: perder um item é pior que
    # ler um número a mais, porque item que não aparece não é conferido.
    itens_base, _ = max(passadas, key=lambda p: len(p[0]))
    base = [l for l, _ in itens_base]
    # A linha física de cada item do esqueleto, para saber a ALTURA dele —
    # é por ela que o código da primeira coluna acha o seu dono.
    fisicas_base = [f for _, f in itens_base]
    for itens, _ in passadas:
        if itens is itens_base or len(itens) != len(base):
            continue
        for principal, (extra, _f) in zip(base, itens):
            principal.candidatos.extend(extra.candidatos)
    for linha in base:
        linha.candidatos = sorted({round(v, 2) for v in linha.candidatos},
                                  reverse=True)
    return base, fisicas_base, [fisicas for _, fisicas in passadas]


# ==============================================================================
# A ARITMÉTICA
# ==============================================================================
def _combinar_para_o_total(linhas: List[LinhaLida],
                           total_produtos: float) -> Optional[List[float]]:
    """Um valor por linha cuja soma bata no total impresso da nota.

    É a prova mais forte disponível: não depende de nenhuma leitura estar
    certa sozinha, só de existir UMA combinação que fecha. Quando existem
    duas, nada é confirmado — ambiguidade não é confirmação.

    O produto cartesiano é seguro aqui porque a nota do dia a dia tem poucos
    itens e cada linha traz poucos candidatos plausíveis. Acima de um limite
    a busca é abandonada em vez de travar o pedido.
    """
    opcoes = []
    for linha in linhas:
        # Ordenados do maior para o menor: o valor do item costuma ser o
        # maior número da linha, então a combinação certa aparece cedo.
        unicos = sorted({round(v, 2) for v in linha.candidatos
                         if 0 < v <= total_produtos + 1}, reverse=True)
        opcoes.append(unicos[:MAX_CANDIDATOS_POR_LINHA])

    espaco = 1
    for o in opcoes:
        espaco *= max(1, len(o))
    if not opcoes or espaco > 200_000:
        return None

    solucoes = []
    for combo in product(*opcoes):
        if abs(sum(combo) - total_produtos) < TOLERANCIA:
            solucoes.append(combo)
            if len(solucoes) > 1:
                return None      # ambíguo: melhor não confirmar nada
    return list(solucoes[0]) if solucoes else None


def _total_plausivel(linhas: List[LinhaLida],
                     candidatos: List[float]) -> Optional[float]:
    """O maior número do rodapé que pode ser o total dos produtos.

    "Pode ser" tem um piso: nenhum total é menor que o maior item da nota.
    Sem esse piso a busca elegeu 40,00 — que era o peso bruto.
    """
    if not linhas or not candidatos:
        return None
    maior_item = max((max(l.candidatos) for l in linhas if l.candidatos),
                     default=0)
    soma_grosseira = sum(max(l.candidatos) for l in linhas if l.candidatos)
    for alvo in candidatos:
        if alvo >= maior_item and alvo <= soma_grosseira * 1.5:
            return alvo
    return None


def _fechar_por_multiplicacao(linha: LinhaLida) -> bool:
    """Procura na linha o trio que fecha: quantidade x preço = total.

    Quando acha, os três estão provados entre si. `min`/`max` decide qual é
    quantidade e qual é preço porque nota de fornecedor de alimento é
    ~sempre "10 caixas a R$ 12", e não "12 caixas a R$ 10".
    """
    for a in linha.candidatos:
        for b in linha.candidatos:
            if a is b or a <= 0 or b <= 0:
                continue
            produto = round(a * b, 2)
            for c in linha.candidatos:
                if c in (a, b):
                    continue
                if abs(produto - c) < 0.015:
                    linha.quantidade, linha.valor_unitario = min(a, b), max(a, b)
                    linha.valor_total = c
                    linha.quantidade_confirmada = True
                    linha.total_confirmado = True
                    return True
    return False



# ==============================================================================
# AS COLUNAS
# ==============================================================================
# Por que isto existe:
#
# A conferência por multiplicação prova UMA linha quando ela tem os três
# números certos. Na foto de referência isso valeu para uma de quatro. As
# outras três tinham os números legíveis na tela — 296,90 e 29,99 estavam ali,
# em botão — e mesmo assim os campos ficavam vazios, porque nada dizia QUAL
# número era quantidade e qual era base de cálculo do ICMS.
#
# A DANFE diz. Ela é uma tabela: quantidade, valor unitário e valor total
# ficam sempre nas mesmas três colunas, uma linha embaixo da outra. Descobrir
# essas três colunas resolve a identidade de todo mundo de uma vez.
#
# E as colunas não são adivinhadas por posição fixa — foto torta move tudo.
# São escolhidas pela conta: o trio de colunas certo é o que faz
# quantidade x preço = total em mais linhas, e cuja coluna de totais soma até
# o total impresso sem estourar. Continua valendo a regra da casa: a posição
# sugere, a aritmética decide.
# ==============================================================================
def _casar_linhas(linhas: List[LinhaLida], fisicas: List[LinhaOcr]) -> List[Optional[int]]:
    """Para cada linha física do OCR, de qual item ela é — ou None.

    Primeiro pelos valores: a linha física que repete dois números de um item
    é aquele item. Depois pela ordem: uma linha física órfã espremida entre o
    item 1 e o item 3 só pode ser o item 2. A ordem das linhas na página é
    fixa, então usá-la para tapar buraco não inventa nada.

    Sem o segundo passo, a linha da COSTELA se perdia numa das passadas — e
    era justamente a passada que tinha lido o 29,99 certo.
    """
    def perto(a, b):
        return abs(a - b) <= max(0.02, abs(b) * 0.005)

    alvos: List[Optional[int]] = []
    for fisica in fisicas:
        pontos = [sum(1 for _x, v in fisica.numeros
                      if any(perto(v, c) for c in linha.candidatos))
                  for linha in linhas]
        melhor = max(range(len(linhas)), key=lambda i: pontos[i]) if linhas else 0
        alvos.append(melhor if linhas and pontos[melhor] >= 2 else None)

    for i, alvo in enumerate(alvos):
        if alvo is not None or len(fisicas[i].numeros) < 2:
            continue
        anterior = max([a for a in alvos[:i] if a is not None], default=-1)
        seguinte = min([a for a in alvos[i + 1:] if a is not None],
                       default=len(linhas))
        if seguinte - anterior == 2:      # só cabe um item no buraco
            alvos[i] = anterior + 1
    return alvos


def _grade_de_celulas(linhas: List[LinhaLida],
                      passadas: List[List[LinhaOcr]]):
    """(colunas, grade) — o que cada passada leu em cada coluna de cada item.

    A célula é um CONJUNTO, não um valor: três passadas discordam, e guardar
    a discordância é o que permite a aritmética escolher depois. Foi assim que
    o 30,99 do PANCETA sobreviveu — duas passadas leram 30,59 e 30,95.
    """
    por_linha = [{} for _ in linhas]
    for fisicas in passadas:
        for fisica, alvo in zip(fisicas, _casar_linhas(linhas, fisicas)):
            if alvo is None:
                continue
            for x, valor in fisica.numeros:
                por_linha[alvo].setdefault(x, set()).add(valor)

    todos_x = sorted(x for celulas in por_linha for x in celulas)
    if not todos_x:
        return [], []
    colunas, grupo = [], [todos_x[0]]
    for x in todos_x[1:]:
        if x - grupo[-1] < RAIO_COLUNA:
            grupo.append(x)
        else:
            colunas.append(sum(grupo) / len(grupo))
            grupo = [x]
    colunas.append(sum(grupo) / len(grupo))

    grade = [[sorted({v for x, vs in celulas.items()
                      if abs(x - c) < RAIO_COLUNA for v in vs})
              for c in colunas]
             for celulas in por_linha]
    return colunas, grade


def _escolher_colunas(grade, total_impresso: Optional[float]):
    """Quais três colunas são quantidade, valor unitário e valor total.

    Duas provas, nesta ordem:

    1. Em quantas linhas existe q x vu = total entre os números daquelas três
       colunas. Tolerância larga (1,2%) porque aqui a conta é indício, não
       veredicto — o valor exato é escolhido depois.
    2. Empate desfeito pela soma da coluna de totais. Na nota de referência a
       base de cálculo do ICMS era IGUAL ao valor do item na primeira linha,
       então as duas colunas empatavam na prova 1; a soma separou (894,75
       contra 397,60, para um total impresso de 949,70).

    A ordem das colunas na página entra como restrição: na DANFE a quantidade
    vem antes do preço, que vem antes do total. Isso derruba sozinho a maioria
    dos trios absurdos.
    """
    melhor = None
    for a, b, c in combinations(range(len(grade[0]) if grade else 0), 3):
        votos = sum(1 for linha in grade
                    if any(abs(q * u - t) <= max(TOLERANCIA, t * 0.012)
                           for q in linha[a] for u in linha[b] for t in linha[c]))
        if not votos:
            continue
        soma = sum(max(linha[c]) for linha in grade if linha[c])
        # Estourar o total impresso desclassifica: coluna de item nenhuma
        # soma mais que a nota inteira.
        if total_impresso and soma > total_impresso * 1.02:
            votos -= 5
        if melhor is None or (votos, soma) > melhor[0]:
            melhor = ((votos, soma), (a, b, c))
    return melhor[1] if melhor else None


def _quantidade_mais_simples(total: float, preco: float):
    """A quantidade mais REDONDA que, vezes o preço, dá o total no centavo.

    Existe quase sempre mais de uma resposta: 296,90 / 39,55 = 7,507 fecha
    tão bem quanto 296,90 / 29,99 = 9,9. O que separa as duas é que nota de
    fornecedor não vende 7,507 caixas de nada.

    Então a busca vai de zero casas para cima e para na primeira que fecha —
    e é isso que faz o preço certo ganhar do preço mal lido, sem precisar
    saber qual dos dois o OCR errou.
    """
    if not preco or preco <= 0 or not total or total <= 0:
        return None, 99
    for casas in (0, 1, 2, 3, 4):
        quantidade = round(total / preco, casas)
        if quantidade > 0 and abs(quantidade * preco - total) <= 0.015:
            return quantidade, casas
    return None, 99


def _preencher_por_coluna(linhas: List[LinhaLida], grade, trio) -> int:
    """Põe cada número no seu campo. Devolve quantas linhas fecharam a conta.

    Confirmado só sai daqui de um jeito: os três números foram LIDOS, cada um
    na sua coluna, e a multiplicação bate. Quantidade deduzida por divisão é
    preenchida, mas segue marcada para conferir — ela é a resposta certa para
    a pergunta "quanto teria que ser", que não é a mesma pergunta que "quanto
    está escrito no papel".
    """
    a, b, c = trio
    fechadas = 0
    for linha, celulas in zip(linhas, grade):
        quantidades, precos, totais = celulas[a], celulas[b], celulas[c]

        trinca = next(((q, u, t) for q in quantidades for u in precos
                       for t in totais if abs(q * u - t) < 0.015), None)
        if trinca:
            linha.quantidade, linha.valor_unitario, linha.valor_total = trinca
            linha.quantidade_confirmada = linha.total_confirmado = True
            fechadas += 1
            continue

        if precos and totais:
            candidatas = [(_quantidade_mais_simples(t, u), u, t)
                          for u in precos for t in totais]
            (quantidade, casas), preco, total = min(
                candidatas, key=lambda x: (x[0][1], -x[1]))
            if quantidade is not None:
                linha.quantidade = quantidade
                linha.valor_unitario, linha.valor_total = preco, total
                continue

        # Sem par que feche, o que foi lido ainda serve como ponto de partida.
        if linha.quantidade is None and quantidades:
            linha.quantidade = max(quantidades)
        if linha.valor_unitario is None and precos:
            linha.valor_unitario = max(precos)
        if linha.valor_total is None and totais:
            linha.valor_total = max(totais)
    return fechadas


def _fechar_o_que_falta(linhas: List[LinhaLida], total_impresso: float) -> bool:
    """A última linha sem valor sai da subtração — quando é UMA só.

    Isto era proibido antes, e por bom motivo: derivar um número que ninguém
    leu e apresentá-lo como conferido é exatamente o erro que este arquivo
    existe para evitar.

    O que mudou foi de onde vêm as outras parcelas. Agora cada uma está na
    coluna de totais, uma embaixo da outra — não são "os maiores números de
    cada linha". Com isso a subtração deixa de ser chute e vira o que sempre
    foi na conta de papel: a parcela que falta.

    E ela continua sem ser confirmada. Aparece no campo, marcada, para a
    pessoa bater com o papel — porque continua sendo a única linha da nota
    que ninguém leu.
    """
    sem_valor = [l for l in linhas if l.valor_total is None]
    if len(sem_valor) != 1 or not total_impresso:
        return False
    linha = sem_valor[0]
    resto = round(total_impresso
                  - sum(l.valor_total for l in linhas if l is not linha), 2)
    if resto <= 0:
        return False
    linha.valor_total = resto
    if linha.valor_unitario:
        quantidade, _casas = _quantidade_mais_simples(resto, linha.valor_unitario)
        if quantidade is not None:
            linha.quantidade = quantidade
    return True


# ==============================================================================
# ENTRADA
# ==============================================================================
def ler(dados: bytes) -> RascunhoDaFoto:
    """A tabela de itens desta foto, com cada campo marcado como provado ou não."""
    cv2, _, _ = danfe._carregar()
    imagem = danfe._de_bytes(dados)
    altura = imagem.shape[0]

    rascunho = RascunhoDaFoto()

    # O rodapé e a tabela de itens são faixas diferentes da página e não
    # dependem um do outro, então leem-se juntos. Era a leitura mais fácil de
    # esconder no caminho crítico: uma passada inteira esperando outra sem
    # nenhuma razão além da ordem em que o código foi escrito.
    topo, base = FAIXA_TOTAIS

    def ler_rodape():
        return _ocr(_preparar(
            imagem[int(altura * topo):int(altura * base), :], escala=3))

    # Uma fila só: o rodapé, as três passadas da tabela e as duas da coluna
    # do código. Nenhuma depende do resultado das outras, e a ordem em que
    # estavam no código não era uma dependência — era só a ordem em que
    # foram escritas.
    tarefas_itens = _tarefas_de_itens(imagem)
    tarefas_codigos = _tarefas_de_codigos(imagem)
    resposta = danfe.em_paralelo(
        [ler_rodape] + tarefas_itens + tarefas_codigos)
    texto_totais = resposta[0]
    lidas = resposta[1:1 + len(tarefas_itens)]
    lidos_codigos = resposta[1 + len(tarefas_itens):]

    numeros_do_rodape = _numeros_do_bloco(texto_totais or "")
    rascunho.linhas, fisicas_base, passadas = _juntar_passadas(lidas)

    # O código do fornecedor vai para a linha antes de qualquer conta: ele
    # não participa da aritmética, e quem vai julgá-lo é o de-para, não este
    # arquivo.
    _atribuir_codigos(rascunho.linhas, fisicas_base,
                      [par for lista in lidos_codigos if lista
                       for par in lista])

    if not rascunho.linhas:
        rascunho.avisos.append(
            "Não consegui separar os itens nessa foto. Tente enquadrar só a "
            "tabela de produtos, com a nota esticada.")
        return rascunho

    # O total impresso é a régua da tela: ela soma o que a pessoa confirma e
    # compara. Vem daqui já escolhido entre os números do rodapé — o maior
    # que seja compatível com os itens lidos.
    rascunho.total_produtos = _total_plausivel(rascunho.linhas, numeros_do_rodape)

    # PRIMEIRO a coluna: ela dá identidade a cada número, e sem identidade a
    # multiplicação tem que adivinhar quem é quem dentro da linha.
    colunas, grade = _grade_de_celulas(rascunho.linhas, passadas)
    trio = _escolher_colunas(grade, rascunho.total_produtos) if grade else None
    if trio:
        _preencher_por_coluna(rascunho.linhas, grade, trio)
        log.info("colunas da tabela: quantidade=%.3f unitário=%.3f total=%.3f",
                 *(colunas[i] for i in trio))
        _fechar_o_que_falta(rascunho.linhas, rascunho.total_produtos)

    # DEPOIS a multiplicação solta, para o que a coluna não alcançou: quando
    # três números da mesma linha fecham uma multiplicação, a chance de três
    # erros de OCR conspirarem é desprezível.
    for linha in rascunho.linhas:
        if not linha.quantidade_confirmada:
            _fechar_por_multiplicacao(linha)

    prontas = sum(1 for l in rascunho.linhas if l.quantidade_confirmada)
    if prontas:
        rascunho.avisos.append(
            f"{prontas} de {len(rascunho.linhas)} linha(s) fecharam sozinhas "
            f"(quantidade x preço bate com o total do item).")

    # A soma da COLUNA de totais contra o total impresso. É a prova mais
    # forte que existe nesta via: quatro valores lidos em passadas diferentes
    # baterem no centavo com um quinto número lido noutro canto da folha não
    # acontece por acaso.
    valores_da_coluna = [l.valor_total for l in rascunho.linhas]
    if (rascunho.total_produtos and all(v is not None for v in valores_da_coluna)
            and abs(sum(valores_da_coluna) - rascunho.total_produtos) < TOLERANCIA):
        rascunho.soma_confere = True
        for linha in rascunho.linhas:
            linha.total_confirmado = True
        rascunho.avisos.append(
            f"A soma dos itens fecha nos R$ {rascunho.total_produtos:.2f} "
            f"impressos na nota — os valores estão conferidos por conta, não "
            f"por leitura.")
        rascunho.avisos.append(
            "As quantidades vieram da coluna da nota; as que não fecharam "
            "sozinhas estão marcadas para você bater com o papel.")
        return _fechamento(rascunho)

    alvo, valores = _achar_total_que_fecha(rascunho.linhas, numeros_do_rodape)
    if alvo and valores:
        rascunho.soma_confere = True
        for linha, valor in zip(rascunho.linhas, valores):
            linha.valor_total, linha.total_confirmado = valor, True
        rascunho.avisos.append(
            f"A soma dos itens fecha nos R$ {alvo:.2f} impressos na nota — "
            f"os valores estão conferidos por conta, não por leitura.")
    elif rascunho.total_produtos:
        rascunho.avisos.append(
            f"A nota diz R$ {rascunho.total_produtos:.2f} em produtos. "
            f"Confirme os valores e a tela avisa quando a soma fechar.")
    else:
        rascunho.avisos.append(
            "Não achei o total impresso nesta foto, então não há conta para "
            "conferir. Confira cada linha contra o papel.")

    return _fechamento(rascunho)


def _fechamento(rascunho: RascunhoDaFoto) -> RascunhoDaFoto:
    faltando = rascunho.campos_a_conferir
    if faltando:
        rascunho.avisos.append(
            f"{faltando} linha(s) com quantidade não confirmada. O número que "
            f"aparece é sugestão — confira no papel antes de aprovar.")
    return rascunho


def _numeros_do_bloco(texto: str) -> List[float]:
    """Todos os números do bloco de totais, sem tentar saber qual é qual.

    POR QUE NÃO PROCURAR PELO RÓTULO
    A DANFE põe "V. TOTAL PRODUTOS" numa linha e o 949,70 na linha DE BAIXO —
    é uma tabela de cabeçalho e valores, não pares rótulo-valor. Casar as duas
    linhas por posição depois do OCR é frágil: basta a foto estar torta.

    Não é preciso. A soma dos itens só vai bater com UM número da página, e
    quando bate, esse número É o total dos produtos — por construção. Quatro
    valores lidos independentemente somarem exatamente a um quinto número
    lido em outro canto da folha não acontece por acaso.
    """
    numeros = []
    for bruta in texto.split("\n"):
        for achado in _NUMERO.findall(bruta):
            valor = _para_float(achado)
            if valor is not None and valor > 0:
                numeros.append(round(valor, 2))
    return sorted(set(numeros), reverse=True)


def _achar_total_que_fecha(linhas: List[LinhaLida], candidatos_totais: List[float]):
    """O total impresso em que a soma dos itens bate, e os valores que somam.

    Testa do maior para o menor: o total dos produtos é um dos maiores
    números da nota, então a resposta certa aparece nas primeiras tentativas.
    """
    # O total dos produtos NÃO PODE ser menor que o maior item da nota.
    # Sem esta trava, a busca "fechou" em 40,00 somando 20 + 20 — e 40,00
    # era o PESO BRUTO, lido do bloco de transporte. Um total inventado que
    # fecha a conta é o pior resultado possível: confirma o que não foi
    # conferido.
    maior_item = max((max(l.candidatos) for l in linhas if l.candidatos),
                     default=0)
    for alvo in candidatos_totais:
        if alvo < maior_item or alvo < 1:
            continue
        valores = _combinar_para_o_total(linhas, alvo)
        if valores:
            return alvo, valores
    return None, None
