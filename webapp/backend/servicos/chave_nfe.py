"""
A chave de acesso da NF-e — 44 dígitos que já contam quase tudo.

O QUE ESTE ARQUIVO RESOLVE SEM PEDIR NADA A NINGUÉM
---------------------------------------------------
A chave não é um número opaco: ela é composta. Dentro dos 44 dígitos estão a
UF, o mês da emissão, o CNPJ de quem emitiu, o modelo, a série, o número da
nota e um dígito verificador. Tudo isso sai daqui, offline, antes de existir
qualquer consulta à SEFAZ ou certificado digital.

Na prática, isso significa que quem digita a chave já vê na tela "Suinoaves
Alimentos, nota 427.795, 08/09/2026" e sabe na hora se digitou a nota certa.

O DÍGITO VERIFICADOR É O QUE TORNA ISTO CONFIÁVEL
-------------------------------------------------
Quarenta e quatro dígitos digitados à mão, ou lidos por OCR de uma foto
amassada, erram. O dígito verificador (módulo 11) pega praticamente todo
erro de um dígito e toda troca de vizinhos — que são justamente os dois
erros que gente e OCR cometem.

É por isso que a leitura por foto (servicos/danfe.py) usa esta validação
como rede: candidato que não fecha o módulo 11 é descartado sem dó. Melhor
não achar nada do que achar a nota errada — a segunda é a que gera
lançamento silenciosamente errado no estoque.
"""
import re
from dataclasses import dataclass
from datetime import date
from typing import List, Optional

TAMANHO = 44

# O primeiro par de dígitos é o código IBGE da UF do emitente. Vale traduzir:
# "53" não diz nada; "Distrito Federal" confirma na hora que a nota é daqui.
UF_POR_CODIGO = {
    "11": "RO", "12": "AC", "13": "AM", "14": "RR", "15": "PA", "16": "AP",
    "17": "TO", "21": "MA", "22": "PI", "23": "CE", "24": "RN", "25": "PB",
    "26": "PE", "27": "AL", "28": "SE", "29": "BA", "31": "MG", "32": "ES",
    "33": "RJ", "35": "SP", "41": "PR", "42": "SC", "43": "RS", "50": "MS",
    "51": "MT", "52": "GO", "53": "DF",
}

MODELO_NFE = "55"
MODELO_NFCE = "65"


class ChaveInvalida(Exception):
    """Mensagem já pronta para a tela — quem lê é quem digitou a chave."""


@dataclass
class Chave:
    digitos: str
    uf: str
    ano: int
    mes: int
    cnpj_emitente: str
    modelo: str
    serie: str
    numero: int
    tipo_emissao: str
    codigo_numerico: str
    dv: str

    @property
    def formatada(self) -> str:
        """Em blocos de quatro, como vem impresso na DANFE."""
        return " ".join(self.digitos[i:i + 4] for i in range(0, TAMANHO, 4))

    @property
    def cnpj_formatado(self) -> str:
        c = self.cnpj_emitente
        return f"{c[:2]}.{c[2:5]}.{c[5:8]}/{c[8:12]}-{c[12:]}"

    @property
    def eh_nfe(self) -> bool:
        return self.modelo == MODELO_NFE

    def como_dicionario(self) -> dict:
        return {
            "chave": self.digitos,
            "formatada": self.formatada,
            "uf": self.uf,
            "competencia": f"{self.mes:02d}/{self.ano}",
            "cnpj_emitente": self.cnpj_emitente,
            "cnpj_formatado": self.cnpj_formatado,
            "modelo": self.modelo,
            "serie": self.serie,
            "numero": self.numero,
            "eh_nfe": self.eh_nfe,
        }


def apenas_digitos(bruto: str) -> str:
    return re.sub(r"\D", "", bruto or "")


def digito_verificador(base43: str) -> int:
    """Módulo 11 com pesos de 2 a 9, da direita para a esquerda.

    Resto 0 ou 1 vira dígito 0 — é a regra do manual da NF-e, e é o caso que
    quem implementa de memória erra: sem ela, cerca de uma chave em cada onze
    seria recusada por engano.
    """
    soma = 0
    peso = 2
    for caractere in reversed(base43):
        soma += int(caractere) * peso
        peso = 2 if peso == 9 else peso + 1
    resto = soma % 11
    return 0 if resto in (0, 1) else 11 - resto


def validar(bruto: str) -> Chave:
    """Devolve a chave decomposta, ou explica o que está errado.

    As mensagens dizem o que fazer, e não só que deu errado: quem está com a
    nota na mão consegue conferir o dígito apontado sem sair da tela.
    """
    digitos = apenas_digitos(bruto)

    if not digitos:
        raise ChaveInvalida("Digite os 44 números da chave de acesso — ela fica "
                            "embaixo do código de barras, na DANFE.")
    if len(digitos) != TAMANHO:
        falta = TAMANHO - len(digitos)
        if falta > 0:
            raise ChaveInvalida(
                f"A chave tem 44 números e você digitou {len(digitos)}. "
                f"Faltam {falta}.")
        raise ChaveInvalida(
            f"A chave tem 44 números e você digitou {len(digitos)} — "
            f"{-falta} a mais. Confira se não repetiu um bloco.")

    esperado = digito_verificador(digitos[:43])
    if str(esperado) != digitos[43]:
        # O erro quase sempre é um dígito trocado no meio, não o último. Dizer
        # "o verificador não fecha" manda a pessoa reconferir a chave inteira,
        # que é o certo — mudar o último dígito para "fechar" daria uma chave
        # válida de OUTRA nota.
        raise ChaveInvalida(
            "Essa chave não passa na conferência: algum número está trocado. "
            "Confira os 44 dígitos com a nota — o erro costuma ser um dígito "
            "no meio, não o último.")

    modelo = digitos[20:22]
    if modelo not in (MODELO_NFE, MODELO_NFCE):
        raise ChaveInvalida(
            f"Esse documento é do modelo {modelo}, que não é nota fiscal de "
            f"mercadoria. Compras entram por NF-e (modelo 55).")

    codigo_uf = digitos[0:2]
    if codigo_uf not in UF_POR_CODIGO:
        raise ChaveInvalida(
            f"Os dois primeiros números ({codigo_uf}) não são de nenhum "
            f"estado. Confira o começo da chave.")

    ano = 2000 + int(digitos[2:4])
    mes = int(digitos[4:6])
    if not 1 <= mes <= 12:
        raise ChaveInvalida(
            f"O mês da emissão saiu como {digitos[4:6]}, que não existe. "
            f"Confira do 3º ao 6º número.")

    return Chave(
        digitos=digitos,
        uf=UF_POR_CODIGO[codigo_uf],
        ano=ano, mes=mes,
        cnpj_emitente=digitos[6:20],
        modelo=modelo,
        serie=digitos[22:25],
        numero=int(digitos[25:34]),
        tipo_emissao=digitos[34:35],
        codigo_numerico=digitos[35:43],
        dv=digitos[43],
    )


def eh_valida(bruto: str) -> bool:
    try:
        validar(bruto)
        return True
    except ChaveInvalida:
        return False


def extrair_de_texto(texto: str) -> List[str]:
    """Toda sequência de 44 dígitos válidos dentro de um texto qualquer.

    Serve ao OCR da foto e ao campo onde alguém cola a mensagem inteira do
    fornecedor. A DANFE imprime a chave em blocos de quatro, então os
    espaços somem antes da busca.

    A janela deslizante existe porque a página tem outros números longos —
    o protocolo de autorização tem 15 dígitos e costuma vir colado. Só o
    dígito verificador separa o que é chave do que é vizinhança.
    """
    somente = apenas_digitos(texto)
    achados, vistos = [], set()
    for i in range(0, max(0, len(somente) - TAMANHO + 1)):
        candidato = somente[i:i + TAMANHO]
        if candidato in vistos:
            continue
        if eh_valida(candidato):
            vistos.add(candidato)
            achados.append(candidato)
    return achados


def data_provavel(chave: Chave) -> Optional[date]:
    """Primeiro dia da competência. A chave guarda mês e ano, nunca o dia.

    Serve para conferência ("é a nota de setembro mesmo?"), nunca como data
    do movimento — essa vem do XML, e usar esta aqui jogaria toda compra do
    mês para o dia 1º, distorcendo qualquer apuração por período.
    """
    try:
        return date(chave.ano, chave.mes, 1)
    except ValueError:
        return None
