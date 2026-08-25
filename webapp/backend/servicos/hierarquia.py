"""
A régua da hierarquia — quem pode fazer o quê com quem.

DUAS REGRAS, E ELAS NÃO SÃO A MESMA COISA
-----------------------------------------
**Conceder** vai até o próprio nível. O Diretor promove alguém a Diretor,
o Gerente promove alguém a Gerente. Ninguém cria alguém acima de si — seria
uma escada para fora da própria autoridade.

**Mexer** só vale para quem está estritamente abaixo. Um Diretor não rebaixa
outro Diretor.

Por que a segunda é mais apertada que a primeira: se iguais pudessem se
rebaixar, qualquer Diretor poderia derrubar todos os outros, e quem fosse
rebaixado não teria como reverter — o poder de desfazer estaria justamente
com quem acabou de perdê-lo. Com a regra estrita, dois Diretores convivem,
e um erro entre eles sobe para o Arquiteto, que está acima dos dois.

Consequência aceita de propósito: promover alguém ao próprio nível é uma via
de mão única para quem promoveu. Desfazer exige alguém mais acima. É o preço
de não ter briga de igual para igual, e é barato porque o Arquiteto existe.

AS OUTRAS TRÊS FRONTEIRAS
-------------------------
· Ninguém mexe em si mesmo — nem para promover, nem para se desativar. Sem
  isso, o último Diretor da empresa poderia se rebaixar e trancar todo mundo
  do lado de fora.
· Ninguém sai da própria empresa. O Arquiteto atravessa; é o que o define.
· Papel que não existe não é concedido — o enum já barra, mas o erro daqui
  explica.

ESTE ARQUIVO É A ÚNICA FONTE
----------------------------
A mesma pergunta ("posso dar este papel?") era respondida em `convites.py` e
em `usuarios.py`, cada um do seu jeito. Duas respostas para uma pergunta é
uma que envelhece sem ninguém perceber — já aconteceu neste projeto com
"quais unidades esta pessoa vê", que tinha três implementações e passou a
discordar no dia em que surgiu o escopo TODAS.
"""
from typing import List, Optional

from fastapi import HTTPException

from models import PapelUsuario, Usuario

# Do mais amplo ao mais restrito. O número não vai para o banco — é só a
# ordem, e mantê-lo aqui evita comparar strings por engano.
NIVEL = {
    PapelUsuario.ARQUITETO: 40,
    PapelUsuario.DIRETOR: 30,
    PapelUsuario.ADMIN: 20,
    PapelUsuario.GERENTE: 10,
    PapelUsuario.OPERADOR: 0,
}

ROTULO = {
    PapelUsuario.ARQUITETO: "Arquiteto",
    PapelUsuario.DIRETOR: "Diretor",
    PapelUsuario.ADMIN: "Administrador",
    PapelUsuario.GERENTE: "Gerente",
    PapelUsuario.OPERADOR: "Operador",
}


def nivel(papel: PapelUsuario) -> int:
    return NIVEL.get(papel, 0)


def papeis_concedidos(autor: Usuario) -> List[PapelUsuario]:
    """Os papéis que este usuário pode entregar — até o próprio nível.

    Ordenado do mais alto para o mais baixo, que é como a tela lista.
    """
    teto = nivel(autor.papel)
    return sorted((p for p in PapelUsuario if nivel(p) <= teto),
                  key=nivel, reverse=True)


def pode_conceder(autor: Usuario, papel: PapelUsuario) -> bool:
    return nivel(papel) <= nivel(autor.papel)


def pode_convidar(autor: Usuario) -> bool:
    """Quem tem alguém abaixo pode chamar gente para esse lugar.

    O Operador é o piso: pode conceder OPERADOR pela régua, mas convidar
    outro Operador não é delegação, é só multiplicar o mesmo nível sem
    ninguém responsável. Convite é ato de quem responde por alguém.
    """
    return nivel(autor.papel) > NIVEL[PapelUsuario.OPERADOR]


def pode_gerenciar(autor: Usuario, alvo: Usuario) -> bool:
    """Se `autor` pode promover, rebaixar, suspender ou excluir `alvo`."""
    if autor.id == alvo.id:
        return False
    if nivel(alvo.papel) >= nivel(autor.papel):
        return False
    # O Arquiteto atravessa empresas; qualquer outro para na própria.
    if autor.papel != PapelUsuario.ARQUITETO:
        if not autor.empresa_id or alvo.empresa_id != autor.empresa_id:
            return False
    return True


# ==============================================================================
# As mesmas regras, agora levantando o erro certo
# ==============================================================================
def exigir_conceder(autor: Usuario, papel: PapelUsuario) -> None:
    if pode_conceder(autor, papel):
        return
    raise HTTPException(
        403,
        f"Você é {ROTULO.get(autor.papel, autor.papel)} e não pode conceder o "
        f"papel de {ROTULO.get(papel, papel)}. Cada pessoa concede até o "
        f"próprio nível.")


def exigir_gerenciar(autor: Usuario, alvo: Usuario) -> None:
    if pode_gerenciar(autor, alvo):
        return

    # Mensagens diferentes porque os três casos pedem ações diferentes de
    # quem leu. "Sem permissão" mandaria a pessoa procurar no lugar errado.
    if autor.id == alvo.id:
        raise HTTPException(
            400, "Você não pode alterar o próprio acesso. Peça a alguém acima "
                 "de você.")
    if autor.papel != PapelUsuario.ARQUITETO and alvo.empresa_id != autor.empresa_id:
        raise HTTPException(403, "Este usuário é de outra empresa.")
    if nivel(alvo.papel) == nivel(autor.papel):
        raise HTTPException(
            403,
            f"{ROTULO.get(alvo.papel, alvo.papel)} não mexe em "
            f"{ROTULO.get(alvo.papel, alvo.papel)}. Só alguém acima dos dois "
            f"pode resolver isso.")
    raise HTTPException(
        403, f"{ROTULO.get(alvo.papel, alvo.papel)} está acima de você.")


def descrever_poderes(autor: Usuario) -> dict:
    """O que este usuário pode fazer — para a tela se montar a partir daqui.

    A tela não repete a regra em JavaScript: pergunta. Regra duplicada é
    regra que diverge, e a do navegador é só decoração — quem recusa de
    verdade é o servidor.
    """
    concedidos = papeis_concedidos(autor)
    return {
        "papel": autor.papel.value,
        "rotulo": ROTULO.get(autor.papel, autor.papel.value),
        "nivel": nivel(autor.papel),
        "pode_convidar": pode_convidar(autor),
        "papeis_que_concede": [
            {"valor": p.value, "rotulo": ROTULO[p], "nivel": nivel(p)}
            for p in concedidos
        ],
        # O que NÃO pode, dito em voz alta: some da tela a tentativa de fazer
        # algo que vai ser negado, e explica antes de a pessoa tentar.
        "papeis_fora_do_alcance": [
            {"valor": p.value, "rotulo": ROTULO[p]}
            for p in sorted(PapelUsuario, key=nivel, reverse=True)
            if nivel(p) > nivel(autor.papel)
        ],
        "mexe_em": "quem está abaixo de "
                   + ROTULO.get(autor.papel, autor.papel.value),
    }


def acoes_possiveis(autor: Usuario, alvo: Usuario) -> dict:
    """As ações liberadas para esta linha da lista.

    Devolvido por usuário para a tela não ter que recalcular a hierarquia —
    e para o motivo do bloqueio aparecer como texto, não como botão morto.
    """
    pode = pode_gerenciar(autor, alvo)
    motivo = None
    if not pode:
        if autor.id == alvo.id:
            motivo = "é você"
        elif nivel(alvo.papel) == nivel(autor.papel):
            motivo = "mesmo nível que o seu"
        elif nivel(alvo.papel) > nivel(autor.papel):
            motivo = "acima de você"
        else:
            motivo = "de outra empresa"

    return {
        "pode_gerenciar": pode,
        "motivo": motivo,
        "papeis_disponiveis": (
            [{"valor": p.value, "rotulo": ROTULO[p], "nivel": nivel(p)}
             for p in papeis_concedidos(autor)]
            if pode else []
        ),
    }
