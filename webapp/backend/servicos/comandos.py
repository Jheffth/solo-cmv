"""
Os comandos do bot — a lista que autoriza É a lista que se exibe.

A ARMADILHA QUE ISTO EVITA
--------------------------
O jeito óbvio de fazer `/ajuda` é escrever um texto por papel no código do
bot. Isso cria uma segunda descrição das permissões, paralela à que recusa de
verdade. No dia em que `congelar` subir para Gerente — como acabou de subir —
quem lembrar da rota vai esquecer do texto.

E o resultado é PIOR do que não ter ajuda: o operador lê que pode congelar,
tenta, e leva 403. A ajuda passa a ensinar o errado com toda a autoridade de
ter vindo do sistema.

É o mesmo defeito que `hierarquia.py` corrigiu quando "posso dar este papel?"
tinha duas respostas, e que `permissoes.py` corrigiu quando cada rota
carregava sua lista de papéis. A solução é sempre a mesma: uma fonte.

Aqui, o despachante do bot recusa pelo mesmo `COMANDOS` de onde o `/ajuda` se
monta. Divergir deixa de ser possível — não por disciplina, por construção.

POR QUE ISTO VIVE NO BACKEND, E NÃO NO BOT
------------------------------------------
Porque a capacidade vive aqui. Se a lista morasse no processo do bot, ele
precisaria saber o piso de cada papel — terceira cópia da régua. Assim ele
pergunta `GET /telegram/comandos` e desenha o que vier, do mesmo jeito que a
tela faz com `/sessao`.
"""
from dataclasses import dataclass, field
from typing import List, Optional

from models import Usuario
from servicos.permissoes import Capacidade, pode


@dataclass(frozen=True)
class Comando:
    nome: str                       # "/contar"
    descricao: str                  # "contagem do inventário"
    grupo: str                      # "LANÇAR" | "CONSULTAR" | "SESSÃO"
    exige: Optional[Capacidade] = None
    exemplo: Optional[str] = None   # só onde o formato não é óbvio
    # Comandos que só fazem sentido dentro de um modo (contagem, perda…).
    # Não somem da ajuda: mudam de lugar. Ver `ajuda_para`.
    modo: Optional[str] = None


# A ordem aqui é a ordem na tela. Agrupado por VERBO, não por papel:
# "Lançar" e "Consultar" é como a pessoa pensa; "Comandos de Operador" é
# como o sistema pensa.
COMANDOS: List[Comando] = [
    # ---------------------------------------------------------------- lançar
    Comando("/contar", "contagem do inventário", "LANÇAR",
            exige=Capacidade.CONTAR),
    Comando("/perda", "registrar perda", "LANÇAR",
            exige=Capacidade.LANCAR_PERDA,
            exemplo="/perda batata doce 3 validade"),
    Comando("/requisicao", "pedir itens para a produção", "LANÇAR",
            exige=Capacidade.ABRIR_REQUISICAO),
    Comando("/compra", "lançar nota de compra", "LANÇAR",
            exige=Capacidade.LANCAR_COMPRA),
    Comando("/congelar", "congelar o inventário e liberar a contagem", "LANÇAR",
            exige=Capacidade.CONGELAR_INVENTARIO),
    Comando("/atender", "baixar do estoque os itens da requisição", "LANÇAR",
            exige=Capacidade.ATENDER_REQUISICAO),
    Comando("/faturamento", "lançar o faturamento do período", "LANÇAR",
            exige=Capacidade.LANCAR_FATURAMENTO),

    # ------------------------------------------------------------- consultar
    Comando("/estoque", "saldo de um item", "CONSULTAR",
            exemplo="/estoque batata"),
    Comando("/inventarios", "os últimos inventários e seus status", "CONSULTAR"),
    Comando("/cmv", "CMV do período contra a meta", "CONSULTAR",
            exige=Capacidade.VER_CMV),
    # Sem `exige`, e não por descuido: o backend já devolve uma coisa
    # diferente para cada um. Quem vê dinheiro recebe CMV, faturamento e
    # pendências; quem não vê recebe a própria fila de trabalho — inventário
    # esperando contagem, requisição aberta.
    #
    # Recusar seria pior do que filtrar aqui. Este é o comando de "e agora,
    # o que eu faço?", e negá-lo justamente a quem executa o trabalho
    # deixaria a pergunta mais útil do bot sem dono.
    Comando("/painel", "o que precisa da sua atenção agora", "CONSULTAR"),

    # ---------------------------------------------------- dentro da contagem
    Comando("faltam", "o que ainda não foi contado", "DURANTE A CONTAGEM",
            exige=Capacidade.CONTAR, modo="CONTAGEM"),
    Comando("pular", "manda o item para o fim da fila", "DURANTE A CONTAGEM",
            exige=Capacidade.CONTAR, modo="CONTAGEM"),
    Comando("/desfazer", "reverte o último lançamento", "DURANTE A CONTAGEM",
            exige=Capacidade.CONTAR, modo="CONTAGEM"),
    Comando("/resumo", "quanto já foi contado", "DURANTE A CONTAGEM",
            exige=Capacidade.CONTAR, modo="CONTAGEM"),

    # ----------------------------------------------------------------- sessão
    Comando("/unidade", "trocar de loja", "SESSÃO"),
    Comando("/ajuda", "esta lista", "SESSÃO"),
    Comando("/sair", "encerrar o que estiver em curso", "SESSÃO"),
]

# Comandos que existem antes de haver alguém: quem ainda não vinculou não tem
# papel, e portanto não tem capacidade nenhuma. Sem esta lista o `/vincular`
# seria recusado pelo despachante e ninguém conseguiria entrar.
COMANDOS_PUBLICOS = {"/vincular", "/start", "/ajuda"}

POR_NOME = {c.nome: c for c in COMANDOS}


def permitido(usuario: Optional[Usuario], nome: str) -> bool:
    """A pergunta que o despachante faz antes de executar qualquer coisa."""
    if nome in COMANDOS_PUBLICOS:
        return True
    if usuario is None:
        return False
    comando = POR_NOME.get(nome)
    if comando is None:
        return False
    return comando.exige is None or pode(usuario, comando.exige)


def disponiveis(usuario: Usuario) -> List[Comando]:
    return [c for c in COMANDOS if permitido(usuario, c.nome)]


def _faltantes(usuario: Usuario) -> List[Comando]:
    return [c for c in COMANDOS if not permitido(usuario, c.nome)]


def ajuda_para(usuario: Usuario, modo: Optional[str] = None) -> str:
    """O texto do /ajuda, montado do mesmo registro que autoriza.

    `modo` reordena, não filtra: dentro de uma contagem, o bloco da contagem
    vem primeiro, porque é o que a pessoa procura estando ali. Esconder o
    resto seria pior — ela deixaria de saber que existe.
    """
    liberados = disponiveis(usuario)
    grupos = {}
    for c in liberados:
        grupos.setdefault(c.grupo, []).append(c)

    ordem = ["LANÇAR", "CONSULTAR", "DURANTE A CONTAGEM", "SESSÃO"]
    if modo == "CONTAGEM":
        ordem.remove("DURANTE A CONTAGEM")
        ordem.insert(0, "DURANTE A CONTAGEM")

    papel = usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel
    linhas = [f"Você é {papel.capitalize()}"]

    for grupo in ordem:
        itens = grupos.get(grupo)
        if not itens:
            continue
        linhas.append("")
        linhas.append(grupo)
        # "DURANTE A CONTAGEM" numa linha só: são quatro atalhos curtos, e
        # quatro linhas para eles empurrariam o resto da ajuda para fora da
        # tela do celular.
        if grupo == "DURANTE A CONTAGEM":
            linhas.append("  " + " · ".join(c.nome for c in itens))
            continue
        for c in itens:
            linha = f"  {c.nome:<14}{c.descricao}"
            if c.exemplo:
                linha += f"\n  {'':<14}ex: {c.exemplo}"
            linhas.append(linha)

    # O que falta cabe em UMA linha, e não numa segunda lista do mesmo
    # tamanho. O princípio é o da tela Equipe: botão morto não ensina, o
    # motivo ensina — quem lê sabe a quem pedir em vez de concluir que o
    # sistema está quebrado. Mas duas listas iguais virariam rolagem, e a
    # metade útil ficaria no fim.
    faltam = [c for c in _faltantes(usuario) if c.grupo in ("LANÇAR", "CONSULTAR")]
    if faltam:
        nomes = [c.descricao for c in faltam]
        if len(nomes) > 3:
            nomes = nomes[:3] + [f"e mais {len(faltam) - 3}"]
        linhas.append("")
        linhas.append(f"Fora do seu acesso: {', '.join(nomes)}. "
                      f"Fale com seu gerente.")

    return "\n".join(linhas)


def descrever(usuario: Usuario) -> dict:
    """A mesma informação em JSON, para o bot montar botões se quiser."""
    return {
        "papel": usuario.papel.value if hasattr(usuario.papel, "value") else usuario.papel,
        "comandos": [
            {"nome": c.nome, "descricao": c.descricao, "grupo": c.grupo,
             "exemplo": c.exemplo, "modo": c.modo}
            for c in disponiveis(usuario)
        ],
        "fora_do_alcance": [
            {"nome": c.nome, "descricao": c.descricao}
            for c in _faltantes(usuario)
        ],
        "texto": ajuda_para(usuario),
    }
