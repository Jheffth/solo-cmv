"""
O que cada papel PODE FAZER — a régua de capacidades.

POR QUE CAPACIDADE E NÃO PAPEL
------------------------------
Até aqui cada rota listava os papéis aceitos à mão:

    Depends(exigir_papeis(ADMIN, GERENTE, OPERADOR))

Funciona, e falha de dois jeitos. O primeiro é conhecido: um papel novo
obriga a revisitar todas as rotas, e a que ficar de fora não avisa. O
segundo é o que nos mordeu de verdade — a lista não diz **o que está sendo
protegido**. Ler `(ADMIN, GERENTE, OPERADOR)` não responde se aquilo é
dinheiro, é estoque ou é gente. E o que não se nomeia, não se confere.

Aqui a pergunta muda de "quem é você?" para "isto é permitido?". A rota
declara a capacidade; este arquivo decide quem a tem.

O BURACO QUE ISSO FECHA
-----------------------
Descoberto conferindo o código, não em teoria: **toda escrita estava
guardada e quase nenhuma leitura estava.** `POST /vendas` exigia Gerente;
`GET /vendas` exigia só estar logado. O mesmo em `/cmv/apuracao`,
`/relatorios`, `/dashboard/painel` e nos valores de `/estoque`.

A assimetria não é descuido de quem escreveu — é como a atenção funciona.
Gravar parece perigoso e chama a guarda; ler parece inofensivo. Mas quem
disse "o pessoal de base não vê faturamento" estava falando de leitura, e
era exatamente ali que não havia trava nenhuma.

DINHEIRO NÃO É TUDO OU NADA
---------------------------
`VER_DINHEIRO` separa quantidade de valor, e a diferença é operacional. O
operador **precisa** do saldo — pedir 20 kg de um item que tem 12 é erro que
só aparece na hora de atender. O que ele não precisa é do R$ ao lado.

Por isso o estoque e o painel **filtram** em vez de recusar: 403 numa tela
que a pessoa usa todo dia ensina que o sistema está quebrado. Some a coluna,
fica a informação.

A LINHA É O AGREGADO, NÃO O NÚMERO
----------------------------------
O operador continua vendo o custo da nota que ele digita, e a perda que ele
acabou de lançar. Não é inconsistência: **ele já teve esse papel na mão.**
Esconder um valor impresso na nota à frente dele seria teatro, e jogaria a
digitação para o gerente — gargalo no recebimento, em troca de nada.

O que ele não vê é o que só o sistema sabe: CMV, faturamento, valor total do
estoque, perdas somadas por motivo. Por isso `/estoque` esconde o custo item
a item mesmo sendo "um número por vez" — com 244 linhas na tela, somar é
trivial, e o total é justamente o que se quis proteger.

ONDE ESTA RÉGUA NÃO MANDA
-------------------------
Em nada que envolva um alvo. "Posso rebaixar o João?" depende do João, e
mora em `hierarquia.py`. Aqui só existem perguntas sem complemento — pode
congelar, pode ver dinheiro —, e as duas fontes não se sobrepõem.
"""
import enum
from typing import Dict, List

from fastapi import HTTPException

from models import PapelUsuario, Usuario
from servicos.hierarquia import NIVEL, ROTULO, nivel


class Capacidade(str, enum.Enum):
    """Cada valor é uma frase que se responde com sim ou não, sem alvo."""

    # ---- dinheiro -----------------------------------------------------------
    VER_DINHEIRO = "VER_DINHEIRO"              # custo, valor em estoque, R$
    VER_CMV = "VER_CMV"                        # apuração, painel, relatórios
    VER_FATURAMENTO = "VER_FATURAMENTO"
    LANCAR_FATURAMENTO = "LANCAR_FATURAMENTO"
    CONFIGURAR_CMV = "CONFIGURAR_CMV"          # método de custo, modo de apuração
    DEFINIR_META = "DEFINIR_META"

    # ---- inventário ---------------------------------------------------------
    ABRIR_INVENTARIO = "ABRIR_INVENTARIO"      # define o escopo do fechamento
    CONGELAR_INVENTARIO = "CONGELAR_INVENTARIO"
    CONTAR = "CONTAR"
    FINALIZAR_INVENTARIO = "FINALIZAR_INVENTARIO"

    # ---- movimento ----------------------------------------------------------
    LANCAR_COMPRA = "LANCAR_COMPRA"
    LANCAR_PERDA = "LANCAR_PERDA"
    ESTORNAR_PERDA = "ESTORNAR_PERDA"
    ABRIR_REQUISICAO = "ABRIR_REQUISICAO"
    ATENDER_REQUISICAO = "ATENDER_REQUISICAO"  # baixa do estoque de verdade

    # ---- cadastro e acesso --------------------------------------------------
    CADASTRAR = "CADASTRAR"                    # produto, fornecedor, categoria
    CRIAR_UNIDADE = "CRIAR_UNIDADE"
    ADMINISTRAR_ACESSO = "ADMINISTRAR_ACESSO"


# O piso de cada capacidade. Quem está nesse nível ou acima, pode.
#
# Duas escolhas que valem explicação:
#
# LANCAR_COMPRA é do Operador, e ele vê o custo do que digita. Parece
# contradizer "base não vê dinheiro", e não contradiz: quem recebe a
# mercadoria tem a nota na mão. Esconder dele um número que está impresso no
# papel à sua frente seria teatro, e jogaria a digitação para o gerente, que
# vira gargalo no recebimento. O que ele não vê é o agregado — CMV,
# faturamento, valor total do estoque.
#
# CONTAR é do Operador e ABRIR/CONGELAR não são. Abrir define quais famílias
# entram no fechamento; congelar tira a fotografia que serve de referência
# para tudo depois. São decisões de quem responde pelo número final. Contar é
# o trabalho.
PISO: Dict[Capacidade, PapelUsuario] = {
    Capacidade.VER_DINHEIRO:        PapelUsuario.GERENTE,
    Capacidade.VER_CMV:             PapelUsuario.GERENTE,
    Capacidade.VER_FATURAMENTO:     PapelUsuario.GERENTE,
    Capacidade.LANCAR_FATURAMENTO:  PapelUsuario.GERENTE,
    Capacidade.CONFIGURAR_CMV:      PapelUsuario.GERENTE,
    Capacidade.DEFINIR_META:        PapelUsuario.DIRETOR,

    Capacidade.ABRIR_INVENTARIO:    PapelUsuario.GERENTE,
    Capacidade.CONGELAR_INVENTARIO: PapelUsuario.GERENTE,
    Capacidade.CONTAR:              PapelUsuario.OPERADOR,
    Capacidade.FINALIZAR_INVENTARIO: PapelUsuario.GERENTE,

    Capacidade.LANCAR_COMPRA:       PapelUsuario.OPERADOR,
    Capacidade.LANCAR_PERDA:        PapelUsuario.OPERADOR,
    Capacidade.ESTORNAR_PERDA:      PapelUsuario.GERENTE,
    Capacidade.ABRIR_REQUISICAO:    PapelUsuario.OPERADOR,
    Capacidade.ATENDER_REQUISICAO:  PapelUsuario.GERENTE,

    Capacidade.CADASTRAR:           PapelUsuario.OPERADOR,
    Capacidade.CRIAR_UNIDADE:       PapelUsuario.ADMIN,
    Capacidade.ADMINISTRAR_ACESSO:  PapelUsuario.GERENTE,
}

# Frase curta, na voz de quem lê a recusa. Serve à mensagem de erro, ao
# `/ajuda` do bot e à tela — os três dizendo a mesma coisa porque leem daqui.
DESCRICAO: Dict[Capacidade, str] = {
    Capacidade.VER_DINHEIRO:        "ver custos e valores em R$",
    Capacidade.VER_CMV:             "ver o CMV e os relatórios",
    Capacidade.VER_FATURAMENTO:     "ver o faturamento",
    Capacidade.LANCAR_FATURAMENTO:  "lançar o faturamento do período",
    Capacidade.CONFIGURAR_CMV:      "mudar o método de cálculo do CMV",
    Capacidade.DEFINIR_META:        "definir metas",

    Capacidade.ABRIR_INVENTARIO:    "abrir um inventário",
    Capacidade.CONGELAR_INVENTARIO: "congelar o inventário",
    Capacidade.CONTAR:              "lançar contagem",
    Capacidade.FINALIZAR_INVENTARIO: "finalizar o inventário",

    Capacidade.LANCAR_COMPRA:       "lançar compras",
    Capacidade.LANCAR_PERDA:        "registrar perdas",
    Capacidade.ESTORNAR_PERDA:      "estornar uma perda",
    Capacidade.ABRIR_REQUISICAO:    "abrir requisições e pedir itens",
    Capacidade.ATENDER_REQUISICAO:  "atender a requisição (baixa do estoque)",

    Capacidade.CADASTRAR:           "cadastrar produtos e fornecedores",
    Capacidade.CRIAR_UNIDADE:       "criar unidades",
    Capacidade.ADMINISTRAR_ACESSO:  "administrar os acessos da equipe",
}


# ==============================================================================
# A PERGUNTA
# ==============================================================================
def pode(usuario: Usuario, capacidade: Capacidade) -> bool:
    piso = PISO.get(capacidade)
    if piso is None:
        # Capacidade não registrada é erro de programação, e o padrão seguro é
        # negar. Liberar o desconhecido é como buracos entram em produção.
        return False
    return nivel(usuario.papel) >= NIVEL[piso]


def ve_dinheiro(usuario: Usuario) -> bool:
    """Atalho do caso mais usado — aparece em quase toda listagem."""
    return pode(usuario, Capacidade.VER_DINHEIRO)


def exigir(usuario: Usuario, capacidade: Capacidade) -> None:
    """Recusa dizendo o que falta e a quem pedir.

    "Você não tem permissão" faz a pessoa procurar suporte. "É o gerente quem
    congela" faz ela procurar o gerente — que é o caminho que resolve.
    """
    if pode(usuario, capacidade):
        return
    piso = PISO[capacidade]
    raise HTTPException(
        403,
        f"Você é {ROTULO.get(usuario.papel, usuario.papel)} e não pode "
        f"{DESCRICAO.get(capacidade, capacidade.value)}. "
        f"É de {ROTULO.get(piso, piso)} para cima.",
    )


def requer(capacidade: Capacidade):
    """Versão para `Depends(...)`, quando a rota inteira depende da capacidade.

    Dentro da função, use `exigir` — é o caso de quando só um pedaço da
    resposta depende dela.
    """
    from fastapi import Depends                      # local: evita import cíclico
    from auth.deps import get_current_user

    def checador(usuario: Usuario = Depends(get_current_user)) -> Usuario:
        exigir(usuario, capacidade)
        return usuario

    return checador


# ==============================================================================
# A RESPOSTA INTEIRA — para a tela e para o /ajuda do bot
# ==============================================================================
def concedidas(usuario: Usuario) -> List[str]:
    return [c.value for c in Capacidade if pode(usuario, c)]


def descrever(usuario: Usuario) -> dict:
    """Tudo que este usuário pode e não pode, com o motivo.

    A tela não recalcula a régua em JavaScript e o bot não a repete em Python:
    os dois perguntam. Regra copiada é regra que diverge — já aconteceu neste
    projeto com "quais unidades esta pessoa vê", que tinha três implementações
    e passou a discordar no dia em que surgiu o escopo TODAS.
    """
    pode_lista, nao_pode = [], []
    for c in Capacidade:
        item = {"chave": c.value, "descricao": DESCRICAO.get(c, c.value)}
        if pode(usuario, c):
            pode_lista.append(item)
        else:
            piso = PISO[c]
            item["exige"] = ROTULO.get(piso, piso)
            nao_pode.append(item)
    return {"pode": pode_lista, "nao_pode": nao_pode,
            "ve_dinheiro": ve_dinheiro(usuario)}
