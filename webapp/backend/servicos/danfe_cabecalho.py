"""
Ler o CABEÇALHO da nota na foto — quem vendeu, qual nota, quando, quanto.

POR QUE ISTO NÃO É "MAIS OCR"
-----------------------------
A tabela de itens precisou de aritmética porque a foto é a única fonte: se o
OCR erra 296,90, nada na página desmente. O cabeçalho é outro problema, e mais
fácil, porque metade dele já está PROVADA antes de qualquer leitura.

A chave de acesso carrega, dentro dos 44 dígitos e protegida por dígito
verificador, o CNPJ do emitente, a série e o número da nota. Isso não é
palpite de leitura: é o documento se identificando. Então a regra deste
arquivo é uma frase:

    A CHAVE MANDA. O OCR SÓ PREENCHE O QUE A CHAVE NÃO SABE.

O que a chave não sabe são três coisas — a razão social do emitente (ela tem
o CNPJ, não o nome), o DIA da emissão (a chave só guarda mês e ano) e o valor
total da nota. Essas três vêm da foto, e cada uma tem uma trava:

  · o nome sai da frase que a lei obriga a estar impressa no canhoto,
    "RECEBEMOS DE <fornecedor> OS PRODUTOS ..." — âncora de texto, não
    posição, então nota torta não atrapalha;
  · a data só é aceita se o mês e o ano baterem com os da chave. Isso derruba
    de uma vez a data de saída, a do protocolo e qualquer número que pareça
    data;
  · o valor total só é aceito se for MAIOR OU IGUAL ao total dos produtos que
    a leitura da tabela apurou. Nota tem frete e imposto por cima; nunca por
    baixo.

E QUANDO OS DOIS DISCORDAM
--------------------------
Se o número que o OCR leu não bate com o da chave, a chave ganha — mas o
conflito é DITO. Discordância aí quase sempre significa que a foto e a chave
digitada são de notas diferentes, e é muito melhor descobrir isso antes de
lançar do que depois, procurando por que o estoque não fecha.
"""
import logging
import re
import unicodedata
from dataclasses import dataclass, field
from datetime import date
from typing import List, Optional

from servicos import chave_nfe, danfe
from servicos.danfe_itens import _ocr, _preparar

log = logging.getLogger("servicos.danfe_cabecalho")

# O cabeçalho ocupa o terço de cima. Faixas largas e sobrepostas porque o
# canhoto some quando alguém fotografa "a nota" e corta a borda superior.
#
# DUAS LISTAS, E NÃO UMA
# As principais são as duas que, medidas na foto de referência, respondem
# sozinhas por todos os campos: o canhoto em 4x traz o fornecedor e o total,
# o quadro do meio em 3x traz a data e o destinatário. As de reserva cobrem
# a foto pior — canhoto cortado, nota mais torta, luz de lado.
#
# Antes as três rodavam sempre, e a terceira não acrescentava nada em foto
# boa: 4,0s para entregar o que 2,0s já entregavam. Agora a reserva só é
# paga quando falta campo — que é quando ela serve para alguma coisa.
FAIXAS = ((0.08, 0.26, 4), (0.16, 0.34, 3))
FAIXAS_RESERVA = ((0.08, 0.26, 3), (0.14, 0.32, 4))

# Os campos que a foto precisa entregar. Faltando qualquer um, vale insistir.
ESSENCIAIS = ("emitente_nome", "data_emissao", "valor_nota")

# "RECEBEMOS" volta do OCR como "RECEIEMOsS", "RecEBEAtos", "RECEBEAIOS". O
# que sobrevive é o formato: R + miolo + S, seguido de DE e, mais adiante,
# PROD. É a frase que a legislação obriga a estar ali, então dá para ancorar
# nela sem depender de a nota ser de tal fornecedor.
_CANHOTO = re.compile(r"R\w{5,11}S\s+DE\s+(.{4,60}?)\s+[O0C]S\s+PROD")
_MARCA_DESTINATARIO = re.compile(r"DESTINAT\w{0,4}RIO")
# O quadro formal do meio da DANFE — o campo "RAZÃO SOCIAL" do destinatário.
_DESTINATARIO_FORMAL = re.compile(
    r"DESTINAT\w{0,4}RIO\s*/\s*REMETENTE(.{5,90})", re.S)
# O canhoto do topo, que repete o destinatário em letra menor.
_DESTINATARIO_CANHOTO = re.compile(
    r"DESTINAT\w{0,4}RIO[:\s.,|_]+([A-Z0-9\-.() ]{5,45})")
_DATA = re.compile(r"\b(\d{2})/(\d{2})/(\d{4})\b")
_VALOR_TOTAL = re.compile(r"VALOR\s+TOTAL[:\s]*R?[S$]?\s*(\d{1,3}(?:\.\d{3})*,\d{2})")
_NUMERO = re.compile(r"N[^\dA-Z]{0,4}(\d{1,3}[.:\s]\d{3}[.:\s]\d{3})\b")

# Nome de empresa que não sobra nada depois de tirar o lixo não é nome.
MINIMO_RAZAO_SOCIAL = 5


@dataclass
class Cabecalho:
    """O que se sabe da nota antes de olhar um item sequer."""
    emitente_nome: str = ""
    emitente_cnpj: str = ""
    numero: str = ""
    serie: str = ""
    data_emissao: Optional[date] = None
    valor_nota: Optional[float] = None
    destinatario_nome: str = ""
    # Tudo que o OCR viu perto da palavra DESTINATÁRIO, cru. Não é para
    # mostrar: é o palheiro onde a conferência da loja procura a agulha.
    # Uma passada lê "4322-CASA JOSEFINA LTDA" e outra "S325-CASA TORENT" —
    # exigir que UMA delas esteja limpa perderia a conferência inteira.
    destinatario_texto: str = ""

    # De onde veio cada campo: "chave" é prova, "foto" é leitura. A tela
    # precisa disso para saber o que pedir conferência e o que não.
    origem: dict = field(default_factory=dict)
    avisos: List[str] = field(default_factory=list)

    @property
    def identificada(self) -> bool:
        return bool(self.emitente_cnpj or self.emitente_nome)

    def como_dicionario(self) -> dict:
        return {
            "emitente_nome": self.emitente_nome,
            "emitente_cnpj": self.emitente_cnpj,
            "numero": self.numero,
            "serie": self.serie,
            "data_emissao": self.data_emissao.isoformat() if self.data_emissao else None,
            "valor_nota": self.valor_nota,
            "destinatario_nome": self.destinatario_nome,
            "origem": self.origem,
            "avisos": self.avisos,
        }


def _sem_acento(texto: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFD", texto)
                   if unicodedata.category(c) != "Mn")


def _so_digitos(bruto: str) -> str:
    return re.sub(r"\D", "", bruto or "")


def _limpar_razao_social(bruto: str) -> str:
    """Tira o que grudou no nome sem cortar o nome.

    A borda da tabela entra como pontuação e o OCR gruda letra solta na
    frente ("SQM) .(4322-CASA JOSEFINA LTDA"). O que não se pode fazer é
    cortar demais: "SUINOAVES ALIMENTOS LTDA" precisa chegar inteiro à busca,
    porque é ela que vai casar com o cadastro.

    O corte da frente usa a mesma régua da descrição de item: token sem vogal
    não é palavra de nome de empresa, é sujeira de borda.
    """
    limpo = re.sub(r"[^A-Z0-9&/\-. ]", " ", _sem_acento(bruto).upper())
    limpo = re.sub(r"\s{2,}", " ", limpo).strip(" .-")

    def tem_palavra(token: str) -> bool:
        letras = re.sub(r"[^A-Z]", "", token)
        return len(letras) >= 3 and bool(re.search(r"[AEIOU]", letras))

    tokens = limpo.split()
    while tokens and not tem_palavra(tokens[0]):
        tokens.pop(0)
    while tokens and not tem_palavra(tokens[-1]):
        tokens.pop()
    if not tokens:
        return ""
    nome = " ".join(tokens).strip(" .-")
    # Código do cliente colado no nome ("4322-CASA JOSEFINA") é numeração do
    # fornecedor, não parte da razão social.
    return re.sub(r"^\d{2,6}\s*[-.]\s*", "", nome)[:180]


def _ate_o_cnpj(bruto: str) -> str:
    """Corta o trecho onde começa o CNPJ — ali a razão social já acabou.

    O quadro do destinatário é RAZÃO SOCIAL | CNPJ | DATA DA EMISSÃO nessa
    ordem, e o OCR devolve os três grudados numa linha só.
    """
    corte = re.search(r"\d{2}[.,:\s]?\d{3}[.,:\s]?\d{3}\s?/", bruto)
    return bruto[:corte.start()] if corte else bruto


def _ler_texto(imagem, faixas) -> str:
    """O cabeçalho lido algumas vezes, tudo junto.

    Não vale a pena separar as passadas aqui: diferente da tabela, onde a
    posição de cada número importa, aqui só se procura por âncora de texto —
    e âncora só precisa aparecer UMA vez em qualquer passada. Por isso o
    resultado é um texto só, e por isso as passadas podem rodar juntas.
    """
    altura = imagem.shape[0]

    def uma_faixa(topo, base, escala):
        def ler():
            recorte = imagem[int(altura * topo):int(altura * base), :]
            if recorte.size == 0:
                return ""
            return _ocr(_preparar(recorte, escala))
        return ler

    partes = danfe.em_paralelo(
        [uma_faixa(topo, base, escala) for topo, base, escala in faixas])
    return "\n".join(p for p in partes if p)


def _mais_repetido(achados: List[str]) -> str:
    """O que mais passadas leram igual. Empate fica com o primeiro."""
    if not achados:
        return ""
    return max(achados, key=lambda a: (achados.count(a), -achados.index(a)))


def transcrever(dados: bytes, chave: Optional[chave_nfe.Chave] = None) -> str:
    """Só o OCR do cabeçalho — a parte lenta, e a única que não depende de nada.

    Existe separada de `interpretar` por um motivo de relógio: esta parte
    pode rodar AO MESMO TEMPO que a leitura da tabela de itens, e a outra
    não, porque precisa do total dos produtos que a tabela apura. Separando,
    a espera das duas passa a ser a da mais lenta, e não a soma.

    Lê as faixas principais e SÓ INSISTE se faltar campo. Em foto boa isso
    corta o tempo pela metade sem tirar nada do resultado; em foto ruim as
    passadas de reserva continuam lá, que é quando elas servem para algo.
    """
    imagem = danfe._de_bytes(dados)
    texto = _sem_acento(_ler_texto(imagem, FAIXAS)).upper()

    # A conferência do que falta é feita sem o total dos produtos, e não faz
    # falta: o total só serve de piso para o valor da nota, nunca decide se
    # um campo existe.
    parcial = _extrair(texto, chave, None)
    faltando = [c for c in ESSENCIAIS if not getattr(parcial, c)]
    if not faltando:
        return texto

    log.info("cabeçalho incompleto (%s); indo para as faixas de reserva",
             ", ".join(faltando))
    return texto + "\n" + _sem_acento(_ler_texto(imagem, FAIXAS_RESERVA)).upper()


def interpretar(texto: str, chave: Optional[chave_nfe.Chave] = None,
                valor_produtos: Optional[float] = None) -> Cabecalho:
    """O cabeçalho que este texto sustenta — com a chave mandando."""
    return _extrair(texto, chave, valor_produtos)


def ler(dados: bytes, chave: Optional[chave_nfe.Chave] = None,
        valor_produtos: Optional[float] = None) -> Cabecalho:
    """Quem vendeu, qual nota, quando e quanto. As duas partes, em ordem."""
    return _extrair(transcrever(dados, chave), chave, valor_produtos)


def _extrair(texto: str, chave: Optional[chave_nfe.Chave],
             valor_produtos: Optional[float]) -> Cabecalho:
    """O cabeçalho que este texto sustenta. Sem OCR: só leitura e travas."""
    cabecalho = Cabecalho()

    # ---------------------------------------------------------------- nome
    nomes = [_limpar_razao_social(n) for n in _CANHOTO.findall(texto)]
    nomes = [n for n in nomes if len(n) >= MINIMO_RAZAO_SOCIAL]
    cabecalho.emitente_nome = _mais_repetido(nomes)
    if cabecalho.emitente_nome:
        cabecalho.origem["emitente_nome"] = "foto"

    # O destinatário aparece no canhoto E no quadro do meio, e as duas
    # leituras vêm sujas de jeitos diferentes. Guardar as duas inteiras é
    # mais útil que escolher uma.
    vizinhancas = [texto[m.start():m.start() + 140]
                   for m in _MARCA_DESTINATARIO.finditer(texto)]
    cabecalho.destinatario_texto = " | ".join(vizinhancas)
    # Para MOSTRAR, o quadro formal ganha do canhoto. Os dois trazem o mesmo
    # destinatário, mas o canhoto é impresso menor e volta pior: nesta nota
    # ele deu "S325-CASA TORENT LTDA" contra "4322-CASA JOSEFINA LTDA" do
    # quadro. Só cai no canhoto quando o quadro não sai.
    formais = [_limpar_razao_social(_ate_o_cnpj(t))
               for t in _DESTINATARIO_FORMAL.findall(texto)]
    canhotos = [_limpar_razao_social(d)
                for d in _DESTINATARIO_CANHOTO.findall(texto)]
    for opcoes in (formais, canhotos):
        validos = [d for d in opcoes if len(d) >= MINIMO_RAZAO_SOCIAL]
        if validos:
            cabecalho.destinatario_nome = _mais_repetido(validos)
            break

    # ----------------------------------------------- o que a chave PROVA
    #
    # O CNPJ só sai daqui pela chave, nunca pela foto — e esta é a decisão
    # mais importante do arquivo. Ele é a identidade do fornecedor no
    # cadastro; um dígito errado cria um segundo cadastro do mesmo
    # fornecedor, e ninguém percebe até o relatório por fornecedor vir
    # partido ao meio.
    #
    # Medido nesta nota: a chave diz 03.425.088/0001-81 e o OCR leu
    # 03.415.088/0001-81 no quadro do emitente. Um dígito. A chave tem
    # dígito verificador sobre os 44 números; o quadro impresso não tem
    # nada. Sem a chave, o campo fica VAZIO, que é uma pergunta honesta.
    if chave is not None:
        cabecalho.emitente_cnpj = chave.cnpj_emitente
        cabecalho.numero = str(chave.numero)
        cabecalho.serie = str(int(chave.serie))
        cabecalho.origem.update(emitente_cnpj="chave", numero="chave",
                                serie="chave")
    else:
        numeros = [_so_digitos(n) for n in _NUMERO.findall(texto)]
        numero = _mais_repetido([n for n in numeros if 3 <= len(n) <= 9])
        if numero:
            cabecalho.numero = str(int(numero))
            cabecalho.origem["numero"] = "foto"

    # A discordância entre a foto e a chave é o achado mais valioso daqui:
    # quase sempre quer dizer que a chave digitada e a foto são de notas
    # diferentes. Vale muito mais descobrir agora do que no fechamento.
    if chave is not None:
        lidos = {int(_so_digitos(n)) for n in _NUMERO.findall(texto)
                 if _so_digitos(n).isdigit()}
        if lidos and chave.numero not in lidos:
            cabecalho.avisos.append(
                f"A chave diz que esta é a nota nº {chave.numero}, e na foto "
                f"eu li outro número. Confira se a foto e a chave são da "
                f"mesma nota antes de seguir.")

    # ---------------------------------------------------------------- data
    # Só a data cujo mês e ano batem com a chave. Sem essa trava entram a
    # data de saída, a do protocolo de autorização e a do recebimento.
    datas = []
    for dia, mes, ano in _DATA.findall(texto):
        try:
            achada = date(int(ano), int(mes), int(dia))
        except ValueError:
            continue
        if chave is not None and (achada.month != chave.mes
                                  or achada.year != chave.ano):
            continue
        datas.append(achada)
    if datas:
        # A menor: a emissão vem antes da saída e antes do protocolo.
        cabecalho.data_emissao = min(datas)
        cabecalho.origem["data_emissao"] = "foto"

    # --------------------------------------------------------------- valor
    # Nota tem frete e imposto POR CIMA dos produtos, nunca por baixo. Um
    # "total" menor que a soma dos itens é outro número qualquer da página.
    valores = sorted({float(v.replace(".", "").replace(",", "."))
                      for v in _VALOR_TOTAL.findall(texto)})
    piso = (valor_produtos or 0) - 0.02
    plausiveis = [v for v in valores if v >= piso and v > 0]
    if plausiveis:
        cabecalho.valor_nota = plausiveis[0]
        cabecalho.origem["valor_nota"] = "foto"
    elif valores and valor_produtos:
        cabecalho.avisos.append(
            f"Li R$ {valores[-1]:.2f} como total da nota, mas os itens somam "
            f"R$ {valor_produtos:.2f}. Como o total não pode ser menor, "
            f"deixei em branco — confira no papel.")

    if not cabecalho.identificada:
        cabecalho.avisos.append(
            "Não consegui identificar o fornecedor nesta foto. Escolha na "
            "lista ou digite a chave de acesso, que traz o CNPJ.")
    return cabecalho
