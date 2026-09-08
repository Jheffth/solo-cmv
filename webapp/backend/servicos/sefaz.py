"""
A consulta à SEFAZ — e a verdade sobre o que ela exige.

LEIA ISTO ANTES DE ESPERAR QUE O BOTÃO "CONSULTAR" TRAGA OS ITENS
-----------------------------------------------------------------
Não existe caminho gratuito e automático para obter os ITENS de uma nota a
partir da chave. Isso não é limitação nossa; é como a Fazenda decidiu:

  · Consulta pública (portal, sem certificado): devolve só o RESUMO —
    emitente, destinatário, valor total, situação. Sem itens, sem NCM, sem
    impostos. Assim desde o Ajuste SINIEF 16/2018, em vigor desde 07/2020.
    E o portal tem captcha, que não se contorna.

  · NFeDistribuicaoDFe com certificado do DESTINATÁRIO: devolve o XML
    completo. Mas só depois da manifestação do destinatário — "Ciência da
    Operação". Antes dela, também só o resumo.

Ou seja, o caminho real tem dois passos, não um: manifestar, depois baixar.
É por isso que este arquivo tem `manifestar_ciencia` — sem ela, a consulta
volta com um resumo que não serve para lançar compra.

POR QUE ESTE ARQUIVO EXISTE SE AINDA NÃO HÁ CERTIFICADO
--------------------------------------------------------
Para que o dia em que o certificado chegar seja um dia de configuração, e
não de programação. Toda a estrutura — modelo, tela, parser, conferência,
importação — funciona hoje pelo XML de arquivo. Falta só a origem.

E, principalmente, para NÃO FINGIR. Um `consultar()` que devolvesse dados
inventados, ou que silenciosamente não fizesse nada, seria pior que a
ausência dele: alguém confiaria. Aqui ele recusa, e a recusa diz exatamente
o que falta e quem resolve.
"""
import logging
import os
from dataclasses import dataclass
from typing import Optional

log = logging.getLogger("servicos.sefaz")

# Ambiente nacional da distribuição de DF-e. Fica aqui, e não espalhado,
# porque muda de endereço a cada nota técnica.
URL_DISTRIBUICAO = os.getenv(
    "SEFAZ_DISTRIBUICAO_URL",
    "https://www1.nfe.fazenda.gov.br/NFeDistribuicaoDFe/NFeDistribuicaoDFe.asmx")

CERTIFICADO_CAMINHO = os.getenv("NFE_CERTIFICADO_PFX", "")
CERTIFICADO_SENHA = os.getenv("NFE_CERTIFICADO_SENHA", "")
CNPJ_DESTINATARIO = os.getenv("NFE_CNPJ_DESTINATARIO", "")


class SefazIndisponivel(Exception):
    """Falta configuração ou a Fazenda não respondeu. Mensagem pronta."""


@dataclass
class Configuracao:
    tem_certificado: bool
    tem_cnpj: bool
    caminho: str
    cnpj: str

    @property
    def pronto(self) -> bool:
        return self.tem_certificado and self.tem_cnpj

    def como_dicionario(self) -> dict:
        return {
            "pronto": self.pronto,
            "tem_certificado": self.tem_certificado,
            "tem_cnpj": self.tem_cnpj,
            "explicacao": explicacao(self),
        }


def configuracao() -> Configuracao:
    caminho = CERTIFICADO_CAMINHO
    return Configuracao(
        tem_certificado=bool(caminho) and os.path.exists(caminho),
        tem_cnpj=len("".join(c for c in CNPJ_DESTINATARIO if c.isdigit())) == 14,
        caminho=caminho,
        cnpj=CNPJ_DESTINATARIO,
    )


def explicacao(cfg: Optional[Configuracao] = None) -> str:
    """O que falta, em português, para quem vai resolver.

    Escrito para o Diretor ler na tela e saber a quem pedir — não para o
    programador ler no log.
    """
    cfg = cfg or configuracao()
    if cfg.pronto:
        return ("Certificado configurado. A consulta busca o XML completo na "
                "SEFAZ, manifestando a ciência da operação antes.")

    faltando = []
    if not cfg.tem_certificado:
        faltando.append("o certificado digital A1 da empresa (arquivo .pfx)")
    if not cfg.tem_cnpj:
        faltando.append("o CNPJ do destinatário")

    return (
        "A consulta automática ainda não está ligada — falta "
        + " e ".join(faltando) + ".\n\n"
        "Sem certificado, a SEFAZ devolve apenas o resumo da nota (emitente, "
        "valor total, situação) e NÃO os itens. Isso é regra fiscal, não "
        "limitação do sistema.\n\n"
        "Enquanto isso, use o XML: peça ao contador o arquivo da nota e "
        "mande aqui — o resto do processo é idêntico."
    )


def consultar_por_chave(chave: str) -> dict:
    """O XML completo da nota, quando houver certificado.

    Recusa explícita enquanto não houver. Nunca devolve dado parcial fingindo
    ser completo: meia nota importada é pior que nenhuma, porque entra no
    estoque e ninguém confere de novo.
    """
    cfg = configuracao()
    if not cfg.pronto:
        raise SefazIndisponivel(explicacao(cfg))

    # A partir daqui é implementação de SOAP + assinatura XML com o A1.
    # Deliberadamente não escrita às cegas: sem um certificado de verdade
    # para testar contra o ambiente da Fazenda, o código passaria a impressão
    # de estar pronto e falharia no primeiro uso real, que é justamente o dia
    # em que alguém está contando com ele.
    #
    # A sequência, para quem for escrever:
    #   1. carregar o .pfx (cryptography) e extrair chave + certificado
    #   2. montar <envEvento> de "Ciência da Operação" (tpEvento 210210)
    #      e assiná-lo — sem isso a distribuição devolve só o resumo
    #   3. enviar a NFeRecepcaoEvento
    #   4. montar <distDFeInt> com <consChNFe><chNFe>…</chNFe></consChNFe>
    #   5. o retorno vem em <docZip> comprimido em gzip e base64
    #   6. descomprimir e devolver o XML — daqui em diante,
    #      servicos/nfe_xml.py já faz todo o resto
    raise SefazIndisponivel(
        "O certificado está configurado, mas a consulta automática ainda não "
        "foi ligada nesta versão. Use o XML do contador por enquanto — a "
        "importação é a mesma daqui em diante."
    )
