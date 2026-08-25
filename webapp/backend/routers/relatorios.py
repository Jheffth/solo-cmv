"""
Relatórios gerenciais — sucessores das abas RESUMO e Relatório da planilha.

Quatro documentos, cada um respondendo uma pergunta:

    fechamento   · como fechou o período
    comparativo  · melhorou ou piorou
    curva-abc    · onde negociar primeiro
    familias     · qual setor está fora da meta

A regra vive em servicos/relatorios.py e o desenho do PDF em relatorio_pdf.py;
aqui só entra a tradução HTTP. Cada relatório atende em dois formatos pela
mesma rota: JSON para a tela, PDF para imprimir e enviar.
"""
from datetime import date as date_type, datetime
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from database import get_db
from auth.deps import get_current_user
from servicos.permissoes import Capacidade, requer
from servicos import relatorios as servico
from servicos import regional as servico_regional
from servicos import escopo as servico_escopo
from relatorio_pdf import GERADORES

router = APIRouter(prefix="/relatorios", tags=["relatórios"])


@router.get("")
def listar(usuario=Depends(requer(Capacidade.VER_CMV))):
    """Catálogo, para a tela montar as abas sem hardcode."""
    return [
        {"chave": "fechamento", "nome": "Fechamento do período",
         "descricao": "Estoque inicial, compras e estoque final consolidados, "
                      "com o CMV contra a meta."},
        {"chave": "comparativo", "nome": "Comparativo entre períodos",
         "descricao": "Período atual contra o anterior, e os itens que mais mudaram."},
        {"chave": "curva-abc", "nome": "Curva ABC de itens",
         "descricao": "Os poucos itens que explicam a maior parte do custo."},
        {"chave": "familias", "nome": "Consumo por família",
         "descricao": "Cada família contra a meta dela, com evolução no tempo."},
    ]


def _gerar(chave: str, db: Session, recorte, referencia: Optional[str],
           data_inicio: Optional[date_type], data_fim: Optional[date_type],
           empresa_id: Optional[int]) -> dict:
    if chave not in servico.RELATORIOS:
        raise HTTPException(404, f"Relatório '{chave}' não existe.")

    # A Regional tem versão própria de cada relatório: somar percentual não
    # é somar, e cada unidade é apurada no ciclo de inventário dela.
    if recorte.regional:
        funcao = servico_regional.RELATORIOS[chave]
        try:
            return funcao(db, recorte.unidades, referencia=referencia,
                          data_inicio=data_inicio, data_fim=data_fim,
                          empresa_id=empresa_id)
        except Exception as erro:
            raise HTTPException(409, f"Não foi possível gerar o relatório: {erro}")

    _, funcao = servico.RELATORIOS[chave]
    try:
        return funcao(db, unidade_id=recorte.unidade_id, referencia=referencia,
                      data_inicio=data_inicio, data_fim=data_fim,
                      empresa_id=empresa_id)
    except Exception as erro:
        raise HTTPException(409, f"Não foi possível gerar o relatório: {erro}")


@router.get("/{chave}")
def obter(chave: str,
          unidade_id: Optional[str] = Query(
              None, description='Id da unidade ou "REGIONAL"'),
          referencia: Optional[str] = Query(None, description="Mês no formato 2026-08"),
          data_inicio: Optional[date_type] = None,
          data_fim: Optional[date_type] = None,
          formato: str = Query("json", pattern="^(json|pdf)$"),
          db: Session = Depends(get_db),
          usuario=Depends(requer(Capacidade.VER_CMV))):
    recorte = servico_escopo.resolver(db, usuario, unidade_id)
    dados = _gerar(chave, db, recorte, referencia, data_inicio, data_fim,
                   usuario.empresa_id)
    if formato == "json":
        return dados

    gerador = GERADORES.get(chave)
    if not gerador:
        raise HTTPException(404, f"Relatório '{chave}' não tem versão em PDF.")
    buffer = gerador(dados)
    rotulo = (dados.get("cabecalho", {}).get("rotulo") or "").replace("/", "-")
    if not rotulo:
        rotulo = datetime.now().strftime("%Y-%m")
    nome = f"solo-cmv-{chave}-{rotulo}.pdf".replace(" ", "-")
    return StreamingResponse(
        buffer,
        media_type="application/pdf",
        headers={"Content-Disposition": f'inline; filename="{nome}"'},
    )
