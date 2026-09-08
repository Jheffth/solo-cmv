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

POR QUE A CONFERÊNCIA FINAL É NA TELA, E NÃO AQUI
-------------------------------------------------
A primeira versão tentava confirmar a nota inteira sozinha, achando a
combinação de valores que fecha no total impresso. Funciona quando o OCR lê
todos os valores — e não foi o caso: na foto de referência o 54,95 do PE
SALGADO não saiu em NENHUMA das três passadas, e sem ele nada fecha.

As saídas que sobraram eram piores que o problema:

  · derivar o que falta por subtração (949,70 - os outros = 54,95) inventa um
    número que ninguém leu e o marca como conferido;
  · afrouxar a busca até algo fechar. Testei: fechou em 40,00 somando 20+20,
    e 40,00 era o PESO BRUTO, lido do bloco de transporte.

Então a divisão de trabalho é outra. Aqui se entrega o que foi LIDO, com o
que a aritmética conseguiu provar marcado como provado. A tela mostra o total
impresso e vai somando enquanto a pessoa confirma — quando a soma fecha, a
nota fecha. A conta continua sendo feita; quem tem o papel na mão é que
fornece o dado que faltou.

O ganho real: em vez de digitar quatro descrições e doze números, a pessoa
escolhe entre números já lidos e vê a nota fechar na hora.
"""
import logging
import re
from dataclasses import dataclass, field
from itertools import product
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


def _ocr(imagem) -> str:
    try:
        import pytesseract
    except ImportError:
        raise danfe.LeitorIndisponivel(
            "A leitura de itens por foto precisa do tesseract, que não está "
            "neste servidor. Use o XML da nota enquanto isso.")
    try:
        return pytesseract.image_to_string(imagem, config="--psm 6")
    except Exception as erro:
        log.exception("OCR da tabela falhou")
        raise danfe.LeitorIndisponivel(f"A leitura falhou: {erro}")


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

    # Só é `True` quando a aritmética fechou. Leitura sozinha nunca confirma.
    total_confirmado: bool = False
    quantidade_confirmada: bool = False

    @property
    def precisa_conferir(self) -> bool:
        return not (self.total_confirmado and self.quantidade_confirmada)

    def como_dicionario(self) -> dict:
        return {
            "descricao": self.descricao,
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


def _linhas_com_produto(texto: str) -> List[LinhaLida]:
    """As linhas que parecem item, e não cabeçalho ou rodapé fiscal.

    O critério é ter ao menos três números com casas decimais e alguma letra
    — a linha do "Fonte IBPT" tem números mas é continuação, e o cabeçalho
    tem letras mas não tem valores.
    """
    achadas = []
    for bruta in texto.split("\n"):
        limpa = bruta.strip()
        if len(limpa) < 12:
            continue
        numeros = [n for n in (_para_float(t) for t in _NUMERO.findall(limpa))
                   if n is not None and n > 0]
        if len(numeros) < 3:
            continue
        # Descrição: o que vem antes do primeiro número longo, sem o código
        # do produto que abre a linha.
        antes = _NUMERO.split(limpa)[0]
        descricao = _limpar_descricao(antes)
        if len(descricao) < 4:
            continue
        # "Fonte IBPT", "pRedBC", "pIcmsSt" são continuação fiscal do item
        # acima, não itens novos.
        if re.search(r"IBPT|pRedBC|IcmsSt|CEST", limpa, re.I):
            continue
        achadas.append(LinhaLida(texto=limpa, descricao=descricao[:120],
                                 candidatos=numeros))
    return achadas


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
    passadas = []
    for topo, base, escala in ((0.45, 0.64, 4), (0.47, 0.62, 3), (0.49, 0.61, 5)):
        recorte = imagem[int(imagem.shape[0] * topo):int(imagem.shape[0] * base), :]
        if recorte.size == 0:
            continue
        try:
            linhas = _linhas_com_produto(_ocr(_preparar(recorte, escala)))
        except danfe.LeitorIndisponivel:
            raise
        except Exception:
            log.exception("passada de OCR falhou (escala %s)", escala)
            continue
        if linhas:
            passadas.append(linhas)

    if not passadas:
        return []

    # A passada com MAIS linhas vira o esqueleto: perder um item é pior que
    # ler um número a mais, porque item que não aparece não é conferido.
    base = max(passadas, key=len)
    for outra in passadas:
        if outra is base or len(outra) != len(base):
            continue
        for principal, extra in zip(base, outra):
            principal.candidatos.extend(extra.candidatos)
    for linha in base:
        linha.candidatos = sorted({round(v, 2) for v in linha.candidatos},
                                  reverse=True)
    return base


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
# ENTRADA
# ==============================================================================
def ler(dados: bytes) -> RascunhoDaFoto:
    """A tabela de itens desta foto, com cada campo marcado como provado ou não."""
    cv2, _, _ = danfe._carregar()
    imagem = danfe._de_bytes(dados)
    altura = imagem.shape[0]

    rascunho = RascunhoDaFoto()

    topo, base = FAIXA_TOTAIS
    texto_totais = _ocr(_preparar(imagem[int(altura * topo):int(altura * base), :],
                                  escala=3))
    numeros_do_rodape = _numeros_do_bloco(texto_totais)

    rascunho.linhas = _ler_itens_em_varias_passadas(imagem)

    if not rascunho.linhas:
        rascunho.avisos.append(
            "Não consegui separar os itens nessa foto. Tente enquadrar só a "
            "tabela de produtos, com a nota esticada.")
        return rascunho

    # O total impresso é a régua da tela: ela soma o que a pessoa confirma e
    # compara. Vem daqui já escolhido entre os números do rodapé — o maior
    # que seja compatível com os itens lidos.
    rascunho.total_produtos = _total_plausivel(rascunho.linhas, numeros_do_rodape)

    # Confirmação POR LINHA: quando três números da mesma linha fecham uma
    # multiplicação, a chance de três erros de OCR conspirarem é desprezível.
    # É a única confirmação automática que sobrevive à medição.
    for linha in rascunho.linhas:
        _fechar_por_multiplicacao(linha)

    prontas = sum(1 for l in rascunho.linhas if l.quantidade_confirmada)
    if prontas:
        rascunho.avisos.append(
            f"{prontas} de {len(rascunho.linhas)} linha(s) fecharam sozinhas "
            f"(quantidade x preço bate com o total do item).")

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
