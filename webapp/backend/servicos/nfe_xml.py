"""
O XML da NF-e virando itens de compra — com o custo que o CMV precisa.

O VALOR UNITÁRIO DA NOTA NÃO É O CUSTO DO PRODUTO
--------------------------------------------------
É a armadilha central deste arquivo, e ela é silenciosa: importar `vUnCom`
como custo dá um número plausível, que ninguém questiona, e um CMV
subestimado para sempre.

Na nota que motivou este código (Suinoaves, 08/09/2026):

    soma dos itens ......... 949,70
    + ICMS ST ..............   9,77
    = total da nota ........ 959,47

O ST de R$ 9,77 é inteiro de UM item, o embutido de frango. O custo real
dele não é R$ 12,99 a bandeja:

    129,90 + 9,77 = 139,67  ->  R$ 13,97 por bandeja, 7,5% acima

Sete e meio por cento num item some dentro de uma planilha e reaparece como
"o CMV subiu e não sei por quê". Por isso o custo daqui é sempre o
DESEMBOLSO: produto, menos desconto, mais ST, frete, seguro, IPI e despesas
acessórias.

RATEIO: PRIMEIro O QUE ESTÁ NO ITEM, DEPOIS O QUE ESTÁ NA CAPA
--------------------------------------------------------------
Frete e desconto podem vir por item (`det/prod/vFrete`) ou só no total da
nota. Quando vêm no item, usa-se o do item — é o número exato. Quando só há
o total, rateia-se proporcional ao valor de cada produto, que é a
aproximação padrão e a única possível sem inventar informação.

A UNIDADE DA NOTA MUITAS VEZES JÁ TRAZ A CONVERSÃO
--------------------------------------------------
O XML tem duas unidades por item: a comercial (`uCom`, como o fornecedor
vende — BD, CX, FD) e a tributável (`uTrib`, quase sempre a física — KG, L,
UN). Quando as duas diferem, `qTrib / qCom` É o fator de conversão, dado de
graça pelo próprio emitente.

Dez bandejas de 500 g viram 5 kg sem ninguém precisar cadastrar nada. É o
gargalo que mais assusta na importação de nota, e na maioria das vezes ele
já vem resolvido dentro do arquivo.
"""
import re
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional

NS = {"n": "http://www.portalfiscal.inf.br/nfe"}


class XmlInvalido(Exception):
    """Mensagem pronta para a tela."""


# ==============================================================================
# LEITURA CRUA
# ==============================================================================
def _texto(no, caminho: str) -> Optional[str]:
    if no is None:
        return None
    achado = no.find(caminho, NS)
    return achado.text.strip() if achado is not None and achado.text else None


def _numero(no, caminho: str, padrao: float = 0.0) -> float:
    bruto = _texto(no, caminho)
    if bruto is None:
        return padrao
    try:
        return float(bruto)
    except ValueError:
        return padrao


def _soma_em(no, *caminhos) -> float:
    """Soma o mesmo campo em qualquer lugar da subárvore.

    O ICMS troca de nome conforme a tributação (ICMS00, ICMS10, ICMS60,
    ICMSSN201…), e o valor do ST aparece dentro do grupo que vier. Procurar
    por `.//n:vICMSST` acha em todos sem enumerar os catorze grupos — que é
    o tipo de lista que envelhece a cada nota técnica da SEFAZ.
    """
    total = 0.0
    for caminho in caminhos:
        for achado in no.iterfind(caminho, NS):
            if achado.text:
                try:
                    total += float(achado.text)
                except ValueError:
                    pass
    return total


@dataclass
class ItemNota:
    numero: int
    codigo_fornecedor: str
    descricao: str
    ncm: str
    cfop: str
    ean: Optional[str]

    unidade_comercial: str
    quantidade_comercial: float
    valor_unitario_comercial: float
    valor_produto: float

    unidade_tributavel: Optional[str] = None
    quantidade_tributavel: float = 0.0

    desconto: float = 0.0
    frete: float = 0.0
    seguro: float = 0.0
    outras: float = 0.0
    icms_st: float = 0.0
    ipi: float = 0.0

    @property
    def custo_total(self) -> float:
        """O desembolso por este item. É isto que entra no estoque."""
        return round(self.valor_produto - self.desconto + self.frete
                     + self.seguro + self.outras + self.icms_st + self.ipi, 2)

    @property
    def custo_unitario(self) -> float:
        if not self.quantidade_comercial:
            return 0.0
        return round(self.custo_total / self.quantidade_comercial, 6)

    @property
    def fator_para_tributavel(self) -> Optional[float]:
        """Quantas unidades tributáveis cabem numa comercial.

        `None` quando as unidades são iguais ou quando falta o dado — e aí
        a conversão vira pergunta na tela, em vez de palpite.
        """
        if not self.quantidade_tributavel or not self.quantidade_comercial:
            return None
        if not self.unidade_tributavel:
            return None
        if self.unidade_tributavel.upper() == self.unidade_comercial.upper():
            return None
        return round(self.quantidade_tributavel / self.quantidade_comercial, 6)

    @property
    def acrescimos(self) -> float:
        """Quanto o custo passou do valor de tabela. É o que a tela destaca."""
        return round(self.custo_total - self.valor_produto, 2)

    def como_dicionario(self) -> dict:
        return {
            "numero": self.numero,
            "codigo_fornecedor": self.codigo_fornecedor,
            "descricao": self.descricao,
            "ncm": self.ncm, "cfop": self.cfop, "ean": self.ean,
            "unidade": self.unidade_comercial,
            "quantidade": self.quantidade_comercial,
            "valor_unitario": self.valor_unitario_comercial,
            "valor_produto": round(self.valor_produto, 2),
            "desconto": round(self.desconto, 2),
            "frete": round(self.frete, 2),
            "icms_st": round(self.icms_st, 2),
            "ipi": round(self.ipi, 2),
            "acrescimos": self.acrescimos,
            "custo_total": self.custo_total,
            "custo_unitario": self.custo_unitario,
            "unidade_tributavel": self.unidade_tributavel,
            "quantidade_tributavel": self.quantidade_tributavel or None,
            "fator_sugerido": self.fator_para_tributavel,
        }


@dataclass
class NotaLida:
    chave: str
    numero: str
    serie: str
    emissao: Optional[date]
    emitente_cnpj: str
    emitente_nome: str
    destinatario_cnpj: str
    destinatario_nome: str
    valor_produtos: float
    valor_nota: float
    itens: List[ItemNota] = field(default_factory=list)
    avisos: List[str] = field(default_factory=list)

    @property
    def soma_dos_custos(self) -> float:
        return round(sum(i.custo_total for i in self.itens), 2)

    def como_dicionario(self) -> dict:
        return {
            "chave": self.chave,
            "numero": self.numero, "serie": self.serie,
            "emissao": self.emissao.isoformat() if self.emissao else None,
            "emitente": {"cnpj": self.emitente_cnpj, "nome": self.emitente_nome},
            "destinatario": {"cnpj": self.destinatario_cnpj,
                             "nome": self.destinatario_nome},
            "valor_produtos": round(self.valor_produtos, 2),
            "valor_nota": round(self.valor_nota, 2),
            "soma_dos_custos": self.soma_dos_custos,
            "itens": [i.como_dicionario() for i in self.itens],
            "avisos": self.avisos,
        }


# ==============================================================================
# O PARSER
# ==============================================================================
def ler(xml: str) -> NotaLida:
    try:
        raiz = ET.fromstring(xml.encode("utf-8") if isinstance(xml, str) else xml)
    except ET.ParseError as erro:
        raise XmlInvalido(f"Esse arquivo não é um XML válido: {erro}")

    # O XML vem embrulhado de três jeitos conforme a origem: <nfeProc> (com o
    # protocolo, o mais comum), <NFe> solto, ou já o <infNFe>. Procurar o
    # miolo em vez do invólucro aceita os três sem ramificar.
    inf = raiz.find(".//n:infNFe", NS)
    if inf is None:
        raise XmlInvalido(
            "Não achei a nota dentro desse XML. Confira se é o arquivo da "
            "NF-e e não o do evento (cancelamento, carta de correção).")

    chave = re.sub(r"\D", "", inf.get("Id") or "")
    ide = inf.find("n:ide", NS)
    emit = inf.find("n:emit", NS)
    dest = inf.find("n:dest", NS)
    total = inf.find(".//n:ICMSTot", NS)

    emissao = None
    bruto = _texto(ide, "n:dhEmi") or _texto(ide, "n:dEmi")
    if bruto:
        try:
            emissao = datetime.fromisoformat(bruto[:19]).date() \
                if "T" in bruto else datetime.strptime(bruto[:10], "%Y-%m-%d").date()
        except ValueError:
            emissao = None

    nota = NotaLida(
        chave=chave,
        numero=_texto(ide, "n:nNF") or "",
        serie=_texto(ide, "n:serie") or "",
        emissao=emissao,
        emitente_cnpj=re.sub(r"\D", "", _texto(emit, "n:CNPJ") or ""),
        emitente_nome=_texto(emit, "n:xNome") or "",
        destinatario_cnpj=re.sub(r"\D", "", _texto(dest, "n:CNPJ")
                                 or _texto(dest, "n:CPF") or ""),
        destinatario_nome=_texto(dest, "n:xNome") or "",
        valor_produtos=_numero(total, "n:vProd"),
        valor_nota=_numero(total, "n:vNF"),
    )

    for det in inf.iterfind("n:det", NS):
        prod = det.find("n:prod", NS)
        if prod is None:
            continue
        imposto = det.find("n:imposto", NS)

        item = ItemNota(
            numero=int(det.get("nItem") or 0),
            codigo_fornecedor=_texto(prod, "n:cProd") or "",
            descricao=_texto(prod, "n:xProd") or "",
            ncm=_texto(prod, "n:NCM") or "",
            cfop=_texto(prod, "n:CFOP") or "",
            ean=(_texto(prod, "n:cEAN") or "").strip() or None,
            unidade_comercial=_texto(prod, "n:uCom") or "UN",
            quantidade_comercial=_numero(prod, "n:qCom"),
            valor_unitario_comercial=_numero(prod, "n:vUnCom"),
            valor_produto=_numero(prod, "n:vProd"),
            unidade_tributavel=_texto(prod, "n:uTrib"),
            quantidade_tributavel=_numero(prod, "n:qTrib"),
            desconto=_numero(prod, "n:vDesc"),
            frete=_numero(prod, "n:vFrete"),
            seguro=_numero(prod, "n:vSeg"),
            outras=_numero(prod, "n:vOutro"),
        )
        if imposto is not None:
            item.icms_st = _soma_em(imposto, ".//n:vICMSST")
            item.ipi = _soma_em(imposto, ".//n:vIPI")
        nota.itens.append(item)

    if not nota.itens:
        raise XmlInvalido("Esse XML não tem nenhum item de produto.")

    _ratear_o_que_so_veio_no_total(nota, total)
    _conferir(nota)
    return nota


def _ratear_o_que_so_veio_no_total(nota: NotaLida, total) -> None:
    """Distribui frete, seguro, desconto e despesas que só existem na capa.

    Proporcional ao valor de cada produto — é a regra usual e a única
    defensável sem inventar dado. Só entra quando o item NÃO trouxe o
    próprio valor: se o emitente já rateou, o número dele é melhor que o
    nosso, porque ele sabe o peso e o volume de cada caixa.
    """
    if total is None:
        return
    base = sum(i.valor_produto for i in nota.itens)
    if base <= 0:
        return

    for campo, caminho, rotulo in (
        ("frete", "n:vFrete", "frete"),
        ("seguro", "n:vSeg", "seguro"),
        ("outras", "n:vOutro", "despesas acessórias"),
        ("desconto", "n:vDesc", "desconto"),
    ):
        na_capa = _numero(total, caminho)
        if na_capa <= 0:
            continue
        if sum(getattr(i, campo) for i in nota.itens) > 0:
            continue     # o emitente já rateou; o dele vale mais

        # O resto vai no último item para a soma fechar no centavo. Sem isso
        # a diferença de arredondamento aparece como "a nota não bate" na
        # conferência, e some a confiança no número inteiro.
        acumulado = 0.0
        for item in nota.itens[:-1]:
            parte = round(na_capa * item.valor_produto / base, 2)
            setattr(item, campo, parte)
            acumulado += parte
        setattr(nota.itens[-1], campo, round(na_capa - acumulado, 2))
        nota.avisos.append(
            f"O {rotulo} de R$ {na_capa:.2f} veio só no total da nota e foi "
            f"rateado entre os itens, proporcional ao valor de cada um.")


def _conferir(nota: NotaLida) -> None:
    """Compara o que somamos com o que a nota declara.

    Um centavo de diferença é arredondamento e não interessa a ninguém. Mais
    que isso quer dizer que há um valor no XML que não estamos considerando —
    e é melhor a tela avisar do que o estoque receber um custo errado sem
    ninguém saber.
    """
    diferenca = round(nota.soma_dos_custos - nota.valor_nota, 2)
    if abs(diferenca) > 0.02:
        nota.avisos.append(
            f"A soma dos custos ({nota.soma_dos_custos:.2f}) difere do total "
            f"da nota ({nota.valor_nota:.2f}) em R$ {abs(diferenca):.2f}. "
            f"Confira antes de aprovar.")

    st = sum(i.icms_st for i in nota.itens)
    if st > 0:
        nota.avisos.append(
            f"Esta nota tem R$ {st:.2f} de ICMS ST, que ENTRA no custo dos "
            f"itens — por isso o custo unitário aqui é maior que o valor "
            f"unitário impresso na nota.")
