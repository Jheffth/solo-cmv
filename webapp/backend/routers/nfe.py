"""
Importação automática de Nota Fiscal Eletrônica via certificado digital —
Fase 10 do plano de migração (evolução pós-lançamento comercial).
AINDA NÃO INICIADO. Estrutura de dados já modelada (CertificadoDigital e
NotaFiscalImportada em models.py) para receber esta integração no futuro.
"""
from fastapi import APIRouter, Depends

from auth.deps import get_current_user

router = APIRouter(prefix="/nfe", tags=["notas fiscais (em breve)"])


@router.get("/status")
def status_ainda_nao_implementado(usuario=Depends(get_current_user)):
    return {
        "implementado": False,
        "secao": "Importação de NF-e via certificado digital",
        "fase_plano": "Fase 10 (pós-lançamento)",
        "mensagem": "Integração com certificado digital (A1/A3) e leitura de XML da SEFAZ ainda não iniciadas. "
                    "Tabelas certificados_digitais e notas_fiscais_importadas já existem no banco.",
    }
