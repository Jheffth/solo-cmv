"""
Motor de CMV — apuração e configuração.

A regra vive em servicos/cmv.py. Aqui só entram a tradução HTTP e a
configuração por unidade (famílias de bebida, método de custo, meta).
"""
from datetime import date
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import (
    Categoria, ConfiguracaoCMV, MetodoCusto, ModoApuracao, PapelUsuario,
)
from auth.deps import get_current_user, exigir_papeis
from servicos.cmv import apurar, obter_configuracao

router = APIRouter(prefix="/cmv", tags=["cmv"])


class ConfiguracaoCMVOut(BaseModel):
    unidade_id: int
    metodo_custo: MetodoCusto
    modo_apuracao: ModoApuracao
    meta_percentual: float
    familias_bebida: List[dict]


class ConfiguracaoCMVUpdate(BaseModel):
    metodo_custo: Optional[MetodoCusto] = None
    modo_apuracao: Optional[ModoApuracao] = None
    meta_percentual: Optional[float] = None
    familias_bebida_ids: Optional[List[int]] = None


def _config_out(cfg: ConfiguracaoCMV) -> ConfiguracaoCMVOut:
    return ConfiguracaoCMVOut(
        unidade_id=cfg.unidade_id,
        metodo_custo=cfg.metodo_custo,
        modo_apuracao=cfg.modo_apuracao,
        meta_percentual=cfg.meta_percentual,
        familias_bebida=[{"id": c.id, "nome": c.nome} for c in cfg.familias_bebida],
    )


@router.get("/configuracao", response_model=ConfiguracaoCMVOut)
def ler_configuracao(unidade_id: int, db: Session = Depends(get_db), usuario=Depends(get_current_user)):
    return _config_out(obter_configuracao(db, unidade_id, usuario.empresa_id))


@router.put("/configuracao", response_model=ConfiguracaoCMVOut)
def salvar_configuracao(unidade_id: int, dados: ConfiguracaoCMVUpdate,
                        db: Session = Depends(get_db),
                        usuario=Depends(exigir_papeis(PapelUsuario.ADMIN, PapelUsuario.GERENTE))):
    cfg = obter_configuracao(db, unidade_id, usuario.empresa_id)

    if dados.metodo_custo is not None:
        cfg.metodo_custo = dados.metodo_custo
    if dados.modo_apuracao is not None:
        cfg.modo_apuracao = dados.modo_apuracao
    if dados.meta_percentual is not None:
        if not 0 < dados.meta_percentual < 1:
            raise HTTPException(status_code=400, detail="A meta deve ser uma fração entre 0 e 1 (ex.: 0,29 para 29%).")
        cfg.meta_percentual = dados.meta_percentual
    if dados.familias_bebida_ids is not None:
        cfg.familias_bebida = db.query(Categoria).filter(
            Categoria.id.in_(dados.familias_bebida_ids)).all()

    db.commit()
    db.refresh(cfg)
    return _config_out(cfg)


@router.get("/apuracao")
def apuracao(
    unidade_id: int,
    data_inicio: date,
    data_fim: date,
    modo: Optional[ModoApuracao] = None,
    metodo_custo: Optional[MetodoCusto] = None,
    limite_linhas: int = 100,
    db: Session = Depends(get_db),
    usuario=Depends(get_current_user),
):
    """Apura o CMV do período.

    `modo` e `metodo_custo` sobrepõem a configuração da unidade quando
    informados — é o que permite ao usuário alternar na tela sem
    salvar a preferência.
    """
    if data_fim < data_inicio:
        raise HTTPException(status_code=400, detail="A data final não pode ser anterior à inicial.")

    cfg = obter_configuracao(db, unidade_id, usuario.empresa_id)
    r = apurar(
        db, unidade_id, data_inicio, data_fim,
        modo=modo or cfg.modo_apuracao,
        metodo_custo=metodo_custo or cfg.metodo_custo,
        empresa_id=usuario.empresa_id,
    )

    linhas = [{
        "produto_id": l.produto_id,
        "codigo": l.codigo,
        "produto": l.nome,
        "categoria": l.categoria,
        "unidade_medida": l.unidade_medida,
        "eh_bebida": l.eh_bebida,
        "qtd_inicial": round(l.qtd_inicial, 3),
        "valor_inicial": round(l.valor_inicial, 2),
        "qtd_comprada": round(l.qtd_comprada, 3),
        "valor_comprado": round(l.valor_comprado, 2),
        "qtd_final": round(l.qtd_final, 3),
        "valor_final": round(l.valor_final, 2),
        "qtd_consumida": l.qtd_consumida,
        "custo_unitario": round(l.custo_final, 4),
        "cmv": l.cmv,
        "final_estimado": l.final_estimado,
        "inventario_inicial": l.inicial.numero if l.inicial else None,
        "inventario_final": l.final.numero if l.final else None,
    } for l in r.linhas[:max(1, min(limite_linhas, 1000))]]

    return {
        "periodo": {
            "data_inicio": data_inicio.isoformat(),
            "data_fim": data_fim.isoformat(),
            "modo": (modo or cfg.modo_apuracao).value,
            "metodo_custo": (metodo_custo or cfg.metodo_custo).value,
        },
        "geral": r.geral.como_dict(),
        "comida": r.comida.como_dict(),
        "bebida": r.bebida.como_dict(),
        "meta": r.meta,
        "lacuna": r.lacuna,
        "linhas": linhas,
        "total_linhas": len(r.linhas),
        "avisos": r.avisos,
        # Quais inventários abriram e fecharam o período — a origem do número
        "inventarios": {
            "abertura": r.inventarios_iniciais,
            "fechamento": r.inventarios_finais,
        },
    }
