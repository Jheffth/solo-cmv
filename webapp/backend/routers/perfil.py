"""
Perfil — o que a própria pessoa mantém sobre si.

A FRONTEIRA QUE DEFINE ESTA TELA
--------------------------------
Aqui se edita **identidade**: nome, apelido, telefone, foto, senha.
Não se edita **poder**: papel, unidades e acesso Regional ficam na tela de
Equipe, e só alguém acima muda.

A separação não é organizacional, é de segurança. Se o perfil aceitasse
`papel`, qualquer Operador se promoveria a Arquiteto editando os próprios
dados — a hierarquia inteira viraria decoração. É a mesma armadilha do
aceite de convite, e a defesa é a mesma: o corpo do pedido só carrega o que
pode ser mudado, e nada além disso é lido.

TROCAR A SENHA EXIGE A ATUAL
----------------------------
Mesmo com a sessão aberta. Sessão aberta prova que alguém entrou; não prova
que é a pessoa certa agora — computador destravado no balcão do restaurante
é o cenário comum, não o exótico.

E trocar a senha derruba as outras sessões: quem trocou porque desconfiou
de acesso indevido esperaria exatamente isso.
"""
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario
from auth.deps import get_current_user
from auth.security import hash_senha, verificar_senha
from servicos import escopo as servico_escopo
from servicos import hierarquia

router = APIRouter(prefix="/perfil", tags=["perfil"])

SENHA_MINIMA = 10

# Uma foto de 256×256 em JPEG dá 20–40 KB; em base64, um terço a mais.
# 300 KB é folgado para isso e aperta o suficiente para barrar quem tentar
# subir a foto original de 4 MB direto da câmera — que a tela já evita, mas
# a tela é decoração: quem recusa de verdade é aqui.
AVATAR_MAXIMO_BYTES = 300 * 1024

_FORMATOS = ("data:image/jpeg;base64,", "data:image/png;base64,",
             "data:image/webp;base64,")

_TELEFONE = re.compile(r"^[0-9()+\-\s]{8,30}$")


class PerfilAtualizar(BaseModel):
    """Só o que a pessoa pode mudar em si mesma.

    Repare no que NÃO está aqui: papel, unidades, acesso_regional, ativo,
    login. Mandar esses campos não dá erro — o Pydantic descarta o que não
    declaramos. Coberto por teste.
    """
    nome: str
    apelido: str | None = None
    telefone: str | None = None
    avatar_url: str | None = None


class SenhaAtualizar(BaseModel):
    senha_atual: str
    senha_nova: str


def _resposta(db: Session, usuario: Usuario) -> dict:
    """O perfil e, ao lado, o que ele NÃO edita — para a tela poder mostrar."""
    unidades = servico_escopo.unidades_permitidas(db, usuario)
    return {
        "id": usuario.id,
        "nome": usuario.nome,
        "apelido": usuario.apelido,
        "login": usuario.login,
        "telefone": usuario.telefone,
        "avatar_url": usuario.avatar_url,
        "criado_em": usuario.criado_em.isoformat() if usuario.criado_em else None,
        # Somente leitura. Aparece porque a pessoa tem o direito de saber o
        # que pode ver e com que papel — mas mudar isso é ato de quem está
        # acima, na tela de Equipe.
        "acesso": {
            "papel": usuario.papel.value,
            "papel_rotulo": hierarquia.ROTULO.get(usuario.papel, usuario.papel.value),
            "unidades": [{"id": u.id, "nome": u.nome} for u in unidades],
            "todas_as_unidades": usuario.escopo_unidades.value == "TODAS",
            "acesso_regional": servico_escopo.pode_ver_regional(usuario),
        },
        "senha_minima": SENHA_MINIMA,
        "avatar_maximo_kb": AVATAR_MAXIMO_BYTES // 1024,
    }


def _validar_avatar(valor: str | None) -> str | None:
    if not valor:
        return None
    valor = valor.strip()
    if not valor.startswith(_FORMATOS):
        raise HTTPException(
            400, "Formato de imagem não aceito. Use JPEG, PNG ou WebP.")
    if len(valor.encode("utf-8")) > AVATAR_MAXIMO_BYTES:
        raise HTTPException(
            400, f"A imagem passou de {AVATAR_MAXIMO_BYTES // 1024} KB. "
                 f"Escolha uma menor — a tela reduz automaticamente, então "
                 f"isto normalmente indica que algo deu errado no envio.")
    return valor


@router.get("")
def ver(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    return _resposta(db, usuario)


@router.put("")
def atualizar(dados: PerfilAtualizar, db: Session = Depends(get_db),
              usuario: Usuario = Depends(get_current_user)):
    nome = (dados.nome or "").strip()
    if len(nome) < 2:
        raise HTTPException(400, "Informe seu nome.")

    telefone = (dados.telefone or "").strip() or None
    if telefone and not _TELEFONE.match(telefone):
        raise HTTPException(
            400, "Telefone inválido. Use apenas números, espaços, parênteses, "
                 "hífen e o sinal de mais.")

    usuario.nome = nome
    usuario.apelido = (dados.apelido or "").strip() or None
    usuario.telefone = telefone
    usuario.avatar_url = _validar_avatar(dados.avatar_url)

    db.commit()
    db.refresh(usuario)
    return _resposta(db, usuario)


@router.delete("/foto")
def remover_foto(db: Session = Depends(get_db),
                 usuario: Usuario = Depends(get_current_user)):
    """Tirar a foto é ação própria, não um campo vazio no formulário.

    Salvar o formulário sem escolher arquivo não deve apagar a foto que já
    existe — seria o tipo de perda silenciosa que ninguém entende depois.
    """
    usuario.avatar_url = None
    db.commit()
    db.refresh(usuario)
    return _resposta(db, usuario)


@router.put("/senha")
def trocar_senha(dados: SenhaAtualizar, db: Session = Depends(get_db),
                 usuario: Usuario = Depends(get_current_user)):
    if not verificar_senha(dados.senha_atual, usuario.senha_hash):
        raise HTTPException(400, "A senha atual não confere.")

    nova = dados.senha_nova or ""
    if len(nova) < SENHA_MINIMA:
        raise HTTPException(
            400, f"A senha nova precisa ter ao menos {SENHA_MINIMA} caracteres.")
    if nova == dados.senha_atual:
        raise HTTPException(400, "A senha nova precisa ser diferente da atual.")

    usuario.senha_hash = hash_senha(nova)
    db.commit()
    return {
        "ok": True,
        "mensagem": "Senha alterada. Entre de novo com a senha nova.",
        # A tela desconecta em seguida. Quem trocou a senha por desconfiar de
        # acesso indevido espera justamente que as outras sessões caiam — e
        # como o token não guarda a senha, derrubar a própria sessão é o
        # sinal honesto de que a troca valeu.
        "encerrar_sessao": True,
    }
