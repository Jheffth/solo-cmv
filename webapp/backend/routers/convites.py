"""
Rotas de convite.

Duas metades com naturezas opostas:

  · **Protegidas** — emitir, listar, revogar. Exigem Diretor ou Arquiteto.
  · **Públicas** — validar e aceitar. Quem as chama ainda não tem conta.

O corpo do aceite carrega apenas nome, login e senha. Papel, empresa,
unidades e regional saem do convite gravado. Ver o cabeçalho de
`servicos/convites.py` para o porquê — em resumo: sendo pública, esta rota
não tem usuário autenticado para o guarda de unidade conferir, e aceitar
permissão vinda do cliente seria deixar o convidado escrever a própria.
"""
from typing import List, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from database import get_db
from models import Convite, EscopoUnidades, PapelUsuario, Usuario
from auth.deps import get_current_user
from servicos import convites as servico
from servicos import escopo as servico_escopo

router = APIRouter(prefix="/convites", tags=["convites"])


# ==============================================================================
# ESQUEMAS
# ==============================================================================
class ConviteCriar(BaseModel):
    papel: PapelUsuario = PapelUsuario.OPERADOR
    escopo_unidades: EscopoUnidades = EscopoUnidades.LISTA
    # Nome do campo escolhido com cuidado: `unidade_ids` é interceptado pelo
    # guarda de unidade, que confere cada id contra o que o autor enxerga.
    # Aqui isso é desejado — é exatamente a regra que queremos aplicar.
    unidade_ids: List[int] = Field(default_factory=list)
    acesso_regional: bool = False
    empresa_id: Optional[int] = None      # obrigatório só para o Arquiteto
    nota: Optional[str] = None
    validade_dias: Optional[int] = servico.VALIDADE_PADRAO_DIAS


class ConviteAceitar(BaseModel):
    """Tudo que o convidado pode dizer sobre si.

    Repare no que NÃO está aqui: papel, unidades, empresa, regional. Mandar
    esses campos não causa erro — são simplesmente ignorados, porque o Pydantic
    descarta o que não declaramos. Coberto por teste.
    """
    codigo: str
    nome: str
    login: str
    senha: str


def _resumo(db: Session, c: Convite) -> dict:
    usado = c.usado_por
    return {
        "id": c.id,
        "codigo": c.codigo,
        "estado": c.estado,
        "papel": c.papel.value,
        "escopo_unidades": c.escopo_unidades.value,
        "todas_as_unidades": c.escopo_unidades == EscopoUnidades.TODAS,
        "acesso_regional": bool(c.acesso_regional),
        "empresa": c.empresa.nome if c.empresa else None,
        "unidades": [{"id": u.id, "nome": u.nome}
                     for u in servico.unidades_do_convite(db, c)],
        "nota": c.nota,
        "criado_por": c.criado_por.nome if c.criado_por else None,
        "usado_por": ({"id": usado.id, "nome": usado.nome, "login": usado.login}
                      if usado else None),
        "usado_em": c.usado_em.isoformat() if c.usado_em else None,
        "expira_em": c.expira_em.isoformat() if c.expira_em else None,
        "criado_em": c.criado_em.isoformat() if c.criado_em else None,
        "link": f"/#convite/{c.codigo}",
    }


# ==============================================================================
# PROTEGIDAS — quem tem autoridade
# ==============================================================================
@router.get("/opcoes")
def opcoes(db: Session = Depends(get_db), usuario: Usuario = Depends(get_current_user)):
    """O que este usuário pode oferecer num convite.

    A tela se monta a partir daqui em vez de repetir a regra em JavaScript.
    Regra duplicada é regra que diverge — e no lado do cliente ela é só
    decoração, porque quem manda é o backend.
    """
    if not servico.pode_convidar(usuario):
        return {"pode_convidar": False, "papeis": [], "unidades": [],
                "pode_regional": False, "precisa_escolher_empresa": False}

    unidades = servico_escopo.unidades_permitidas(db, usuario)
    return {
        "pode_convidar": True,
        "papeis": [p.value for p in servico.papeis_concedidos(usuario)],
        "unidades": [{"id": u.id, "nome": u.nome} for u in unidades],
        "pode_regional": servico_escopo.pode_ver_regional(usuario),
        "precisa_escolher_empresa": usuario.papel == PapelUsuario.ARQUITETO,
        "validade_padrao_dias": servico.VALIDADE_PADRAO_DIAS,
    }


@router.get("")
def listar(limite: int = Query(100, ge=1, le=500),
           db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    itens = [_resumo(db, c) for c in servico.listar(db, usuario, limite)]
    return {
        "convites": itens,
        "resumo": {
            "total": len(itens),
            "disponiveis": sum(1 for i in itens if i["estado"] == "DISPONIVEL"),
            "usados": sum(1 for i in itens if i["estado"] == "USADO"),
        },
    }


@router.post("", status_code=201)
def criar(dados: ConviteCriar, db: Session = Depends(get_db),
          usuario: Usuario = Depends(get_current_user)):
    convite = servico.gerar(
        db, usuario,
        papel=dados.papel,
        escopo_unidades=dados.escopo_unidades,
        unidade_ids=dados.unidade_ids,
        acesso_regional=dados.acesso_regional,
        empresa_id=dados.empresa_id,
        nota=dados.nota,
        validade_dias=dados.validade_dias,
    )
    return _resumo(db, convite)


@router.delete("/{convite_id}")
def revogar(convite_id: int, db: Session = Depends(get_db),
            usuario: Usuario = Depends(get_current_user)):
    return _resumo(db, servico.revogar(db, usuario, convite_id))


# ==============================================================================
# PÚBLICAS — quem ainda não tem conta
# ==============================================================================
@router.get("/validar/{codigo}")
def validar(codigo: str, db: Session = Depends(get_db)):
    """Confere o código antes de a pessoa preencher o formulário.

    Devolve 200 com `valido: false` em vez de erro: um convite vencido não é
    falha do sistema, é informação para a tela mostrar com calma.
    """
    from fastapi import HTTPException
    try:
        convite = servico.buscar_valido(db, codigo)
    except HTTPException as erro:
        return {"valido": False, "motivo": erro.detail}
    return servico.descrever(db, convite)


@router.post("/aceitar", status_code=201)
def aceitar(dados: ConviteAceitar, db: Session = Depends(get_db)):
    """Cria a conta e queima o convite. Sem autenticação, por definição."""
    usuario = servico.aceitar(db, codigo=dados.codigo, nome=dados.nome,
                              login=dados.login, senha=dados.senha)
    return {
        "ok": True,
        "usuario": {"id": usuario.id, "nome": usuario.nome,
                    "login": usuario.login, "papel": usuario.papel.value},
        "mensagem": "Conta criada. Entre com o login e a senha que você escolheu.",
    }
