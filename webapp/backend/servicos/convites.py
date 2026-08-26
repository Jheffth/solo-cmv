"""
Convites — a única porta de entrada para uma conta nova.

O cadastro é fechado. Ninguém cria a própria conta: alguém com autoridade
emite um convite JÁ COM o que a pessoa vai poder ver, e o convidado escolhe
apenas nome, login e senha.

A REGRA QUE SUSTENTA TUDO
-------------------------
O aceite é uma rota **pública** — quem a chama ainda não tem conta, logo não
tem token, logo o guarda de unidade não tem usuário para conferir contra. Se
papel e unidades viessem no corpo do pedido, qualquer um se concederia o que
quisesse, e o convite viraria uma porta lateral em volta de todo o controle
de acesso.

Por isso `aceitar()` recebe nome, login e senha, e mais nada. Papel, empresa,
unidades e regional saem **exclusivamente** do convite gravado, por quem tinha
autoridade no momento da emissão. Não é uma precaução: é o que separa este
desenho de um furo.

QUEM PODE CONCEDER O QUÊ
------------------------
· ARQUITETO está acima de todos e é o único que concede ARQUITETO.
· DIRETOR convida qualquer pessoa da empresa dele, com qualquer papel menos
  ARQUITETO.
· Ninguém concede unidade que não enxerga — a mesma função que decide o que a
  pessoa vê (`escopo.unidades_permitidas`) decide o que ela pode oferecer.
· Ninguém concede acesso Regional sem tê-lo.

ESCOPO: LISTA OU TODAS
----------------------
LISTA é fotografia: "estas duas lojas". Abrir a Asa Sul amanhã não muda nada.
TODAS é regra: acompanha as lojas que ainda não existem. É o que a tela chama
de convite Regional.

A diferença aparece meses depois, quando a loja nova abre — e é exatamente por
isso que precisa estar explícito no convite, e não deduzido de uma lista que
por acaso continha todas as unidades do dia.
"""
import re
import secrets
from datetime import datetime, timedelta
from typing import List, Optional

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (Convite, Empresa, EscopoUnidades, PapelUsuario,
                    PAPEIS_IRRESTRITOS, Unidade, Usuario)
from auth.security import hash_senha
from servicos import escopo as servico_escopo
from servicos import hierarquia

# Sem 0/O e sem 1/I/L. O código é ditado por telefone e colado de WhatsApp,
# onde esses pares viram chamado de suporte. Ideia emprestada do Solo Rotinas.
_ALFABETO = "ABCDEFGHJKMNPQRSTUVWXYZ23456789"

VALIDADE_PADRAO_DIAS = 7      # convite de trabalho: aceito na semana ou esquecido
SENHA_MINIMA = 10
_LOGIN_VALIDO = re.compile(r"^[A-Za-z0-9._-]{3,60}$")


# ==============================================================================
# EMISSÃO
# ==============================================================================
def _gerar_codigo(db: Session) -> str:
    for _ in range(40):
        bloco = lambda: "".join(secrets.choice(_ALFABETO) for _ in range(4))
        codigo = f"SOLO-{bloco()}-{bloco()}"
        if not db.query(Convite).filter(Convite.codigo == codigo).first():
            return codigo
    raise HTTPException(500, "Não foi possível gerar um código único.")


# A régua é a de `servicos/hierarquia.py`, e só ela. Estas duas funções
# continuam existindo porque o router e os testes já as chamam — mas
# delegam, para não haver duas respostas para a mesma pergunta.
#
# Antes daqui viviam regras próprias: "só a diretoria convida" e "Diretor
# concede tudo menos Arquiteto". Funcionavam, e teriam divergido no dia em
# que a hierarquia mudasse num arquivo só. Foi o que aconteceu com "quais
# unidades esta pessoa vê", que tinha três implementações.
def pode_convidar(usuario: Usuario) -> bool:
    return hierarquia.pode_convidar(usuario)


def papeis_concedidos(usuario: Usuario) -> List[PapelUsuario]:
    """Os papéis que este usuário pode entregar num convite — até o próprio."""
    if not hierarquia.pode_convidar(usuario):
        return []
    return hierarquia.papeis_concedidos(usuario)


def empresa_unica(db: Session) -> Optional[int]:
    """A empresa da instalação, quando só existe uma.

    O Solo CMV é instalado por rede: esta instalação é a Rede Josefina.
    Outra rede será outra instalação, com outro banco — não um segundo
    inquilino aqui dentro. Então "qual empresa?" é uma pergunta sem
    ambiguidade, e perguntar seria burocracia.
    """
    empresas = db.query(Empresa.id).limit(2).all()
    return empresas[0][0] if len(empresas) == 1 else None


def _resolver_empresa(db: Session, autor: Usuario, empresa_id: Optional[int]) -> int:
    """A empresa do convidado — decidida pelo que se SABE, não pelo papel.

    Antes isto olhava para o papel: sendo ARQUITETO, exigia a escolha, mesmo
    quando o próprio Arquiteto já pertencia a uma empresa e ela era a única
    do sistema. Perguntava algo que já sabia, e o campo "id da empresa" na
    tela de convite era o sintoma.

    A ordem agora é a do conhecimento disponível:

      1. o autor tem empresa       → é essa
      2. só existe uma no sistema  → é essa
      3. duas ou mais, sem escolha → aí sim, pergunta

    Hoje o passo 1 responde tudo. O passo 3 nunca acontece nesta instalação,
    e continua escrito porque custa três linhas e evita que a regra precise
    ser reinventada se um dia a situação mudar.
    """
    da_instalacao = autor.empresa_id or empresa_unica(db)

    if empresa_id and da_instalacao and empresa_id != da_instalacao:
        raise HTTPException(403, "Você só convida para a sua própria empresa.")

    escolhida = empresa_id or da_instalacao
    if not escolhida:
        raise HTTPException(
            400, "Não há empresa cadastrada nesta instalação. Rode o seed antes "
                 "de convidar alguém.")

    if not db.query(Empresa.id).filter(Empresa.id == escolhida).first():
        raise HTTPException(400, "Empresa não encontrada.")
    return escolhida


def gerar(db: Session, autor: Usuario, papel: PapelUsuario,
          escopo_unidades: EscopoUnidades = EscopoUnidades.LISTA,
          unidade_ids: Optional[List[int]] = None,
          acesso_regional: bool = False,
          empresa_id: Optional[int] = None,
          nota: Optional[str] = None,
          validade_dias: Optional[int] = VALIDADE_PADRAO_DIAS) -> Convite:
    """Emite um convite. Levanta 403 quando o autor concede além do que tem."""
    if not pode_convidar(autor):
        raise HTTPException(
            403, "Operador não emite convites — convidar é ato de quem "
                 "responde por alguém.")

    # A mesma régua da promoção: concede-se até o próprio nível. A mensagem
    # de erro sai de lá, já explicando o porquê.
    hierarquia.exigir_conceder(autor, papel)

    empresa = _resolver_empresa(db, autor, empresa_id)

    if acesso_regional and not servico_escopo.pode_ver_regional(autor):
        raise HTTPException(403, "Você não tem acesso Regional, então não pode concedê-lo.")

    unidades: List[Unidade] = []
    if escopo_unidades == EscopoUnidades.LISTA and papel not in PAPEIS_IRRESTRITOS:
        pedidas = set(unidade_ids or [])
        if not pedidas:
            raise HTTPException(400, "Escolha ao menos uma unidade, ou marque o "
                                     "acesso a todas.")

        # A mesma função que decide o que o autor VÊ decide o que ele OFERECE.
        # Se fossem duas listas diferentes, uma envelheceria sem a outra.
        permitidas = {u.id: u for u in servico_escopo.unidades_permitidas(db, autor)}
        alheias = pedidas - set(permitidas)
        if alheias:
            raise HTTPException(403, "Você não pode conceder acesso a unidade que "
                                     "não enxerga.")

        de_outra_empresa = [permitidas[i] for i in pedidas
                            if permitidas[i].empresa_id != empresa]
        if de_outra_empresa:
            raise HTTPException(400, "As unidades escolhidas não são da empresa do "
                                     "convite.")
        unidades = [permitidas[i] for i in sorted(pedidas)]

    convite = Convite(
        codigo=_gerar_codigo(db),
        empresa_id=empresa,
        criado_por_id=autor.id,
        papel=papel,
        escopo_unidades=escopo_unidades,
        acesso_regional=bool(acesso_regional),
        nota=(nota or None),
        expira_em=(datetime.utcnow() + timedelta(days=validade_dias)
                   if validade_dias else None),
    )
    convite.unidades = unidades
    db.add(convite)
    db.commit()
    db.refresh(convite)
    return convite


def revogar(db: Session, autor: Usuario, convite_id: int) -> Convite:
    convite = db.query(Convite).filter(Convite.id == convite_id).first()
    if not convite or not _pode_ver(autor, convite):
        raise HTTPException(404, "Convite não encontrado.")
    if convite.usado_por_id:
        raise HTTPException(400, "Convite já utilizado — revogar não desfaz a conta. "
                                 "Para tirar o acesso, desative o usuário.")
    convite.revogado = True
    db.commit()
    db.refresh(convite)
    return convite


def _pode_ver(usuario: Usuario, convite: Convite) -> bool:
    """Arquiteto vê tudo; Diretor vê os da empresa dele, não só os que criou."""
    if usuario.papel == PapelUsuario.ARQUITETO:
        return True
    if usuario.papel == PapelUsuario.DIRETOR:
        return convite.empresa_id == usuario.empresa_id
    return convite.criado_por_id == usuario.id


def listar(db: Session, autor: Usuario, limite: int = 100) -> List[Convite]:
    query = db.query(Convite)
    if autor.papel == PapelUsuario.DIRETOR:
        query = query.filter(Convite.empresa_id == autor.empresa_id)
    elif autor.papel != PapelUsuario.ARQUITETO:
        query = query.filter(Convite.criado_por_id == autor.id)
    return query.order_by(Convite.criado_em.desc()).limit(limite).all()


# ==============================================================================
# VALIDAÇÃO E ACEITE — o lado público
# ==============================================================================
def buscar_valido(db: Session, codigo: str) -> Convite:
    """O convite utilizável, ou HTTPException com o motivo exato."""
    codigo = (codigo or "").strip().upper()
    convite = db.query(Convite).filter(Convite.codigo == codigo).first()
    if not convite:
        raise HTTPException(400, "Código de convite não encontrado.")

    estado = convite.estado
    if estado == "REVOGADO":
        raise HTTPException(400, "Este convite foi cancelado.")
    if estado == "USADO":
        raise HTTPException(400, "Este convite já foi utilizado.")
    if estado == "EXPIRADO":
        raise HTTPException(400, "Este convite expirou. Peça um novo.")
    return convite


def unidades_do_convite(db: Session, convite: Convite) -> List[Unidade]:
    """As unidades que o convite concede, resolvendo a regra quando é TODAS."""
    if (convite.escopo_unidades == EscopoUnidades.TODAS
            or convite.papel in PAPEIS_IRRESTRITOS):
        return (db.query(Unidade)
                  .filter(Unidade.empresa_id == convite.empresa_id)
                  .order_by(Unidade.nome).all())
    return sorted(convite.unidades or [], key=lambda u: u.nome)


def descrever(db: Session, convite: Convite) -> dict:
    """O que a tela pública mostra antes de a pessoa aceitar.

    Mostrar o que está sendo concedido é parte do aceite: ninguém deveria
    criar uma conta sem saber o que ela dá. Não expõe nada que o código já
    não implique — e o código só chega a quem foi convidado.
    """
    autor = convite.criado_por
    unidades = unidades_do_convite(db, convite)
    return {
        "valido": True,
        "codigo": convite.codigo,
        "convidado_por": autor.nome if autor else None,
        "empresa": convite.empresa.nome if convite.empresa else None,
        "papel": convite.papel.value,
        "escopo_unidades": convite.escopo_unidades.value,
        "todas_as_unidades": (convite.escopo_unidades == EscopoUnidades.TODAS
                              or convite.papel in PAPEIS_IRRESTRITOS),
        "unidades": [{"id": u.id, "nome": u.nome} for u in unidades],
        "acesso_regional": bool(convite.acesso_regional
                                or convite.papel in PAPEIS_IRRESTRITOS),
        "nota": convite.nota,
        "expira_em": convite.expira_em.isoformat() if convite.expira_em else None,
        "senha_minima": SENHA_MINIMA,
    }


def aceitar(db: Session, codigo: str, nome: str, login: str, senha: str) -> Usuario:
    """Cria a conta a partir do convite.

    NÃO recebe papel, empresa, unidades nem regional — de propósito. Esta rota
    é pública: aceitar esses campos do cliente seria deixar o convidado
    escrever a própria permissão. Tudo vem do convite.
    """
    convite = buscar_valido(db, codigo)
    if convite.papel == PapelUsuario.ARQUITETO:
        raise HTTPException(400, "Não é permitido criar contas com o papel de Arquiteto. O papel de Arquiteto é único no sistema.")

    nome = (nome or "").strip()
    login = (login or "").strip()
    if len(nome) < 2:
        raise HTTPException(400, "Informe seu nome.")
    if not _LOGIN_VALIDO.match(login):
        raise HTTPException(400, "Login deve ter de 3 a 60 caracteres, usando "
                                 "apenas letras, números, ponto, hífen ou sublinhado.")
    if len(senha or "") < SENHA_MINIMA:
        raise HTTPException(400, f"A senha precisa ter ao menos {SENHA_MINIMA} caracteres.")

    if db.query(Usuario).filter(Usuario.login == login).first():
        raise HTTPException(400, "Este login já está em uso. Escolha outro.")

    usuario = Usuario(
        empresa_id=convite.empresa_id,
        nome=nome,
        login=login,
        senha_hash=hash_senha(senha),
        papel=convite.papel,
        escopo_unidades=convite.escopo_unidades,
        acesso_regional=bool(convite.acesso_regional),
        ativo=True,
    )
    # Com TODAS, a lista fica vazia de propósito: quem manda é a regra, e uma
    # lista gravada aqui viraria uma segunda verdade, desatualizada na primeira
    # loja nova.
    if convite.escopo_unidades == EscopoUnidades.LISTA:
        usuario.unidades = list(convite.unidades or [])

    db.add(usuario)
    db.flush()

    # Queima o convite no mesmo commit da criação: ou nascem os dois, ou
    # nenhum. Em transações separadas, uma falha no meio deixaria o convite
    # gasto sem conta, ou a conta criada com o convite ainda valendo.
    convite.usado_por_id = usuario.id
    convite.usado_em = datetime.utcnow()

    db.commit()
    db.refresh(usuario)
    return usuario
