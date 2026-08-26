"""
Rotas para integração do WhatsApp via Evolution API v2 no Solo CMV.
"""
from typing import Optional, Dict, Any

from fastapi import APIRouter, Depends, HTTPException, Request, BackgroundTasks
from pydantic import BaseModel
from sqlalchemy.orm import Session

from database import get_db
from models import Usuario
from auth.deps import get_current_user, exigir_canal_web, exigir_papeis
from servicos import whatsapp as servico
from servicos.evolution_cliente import cliente_evolution

router = APIRouter(prefix="/whatsapp", tags=["whatsapp"])


@router.get("/status")
def status(db: Session = Depends(get_db),
           usuario: Usuario = Depends(get_current_user)):
    """Status do WhatsApp para o usuário atual e estado da instância."""
    return servico.status(db, usuario)


@router.post("/codigo")
def gerar_codigo(db: Session = Depends(get_db),
                 usuario: Usuario = Depends(exigir_canal_web)):
    """Gera código de 6 dígitos para o usuário vincular seu WhatsApp."""
    return servico.gerar(db, usuario)


@router.delete("/vinculo")
def desvincular(db: Session = Depends(get_db),
                usuario: Usuario = Depends(get_current_user)):
    """Desvincula o WhatsApp da conta do usuário atual."""
    return servico.desvincular(db, usuario)


@router.get("/qrcode")
def obter_qrcode(numero: Optional[str] = None,
                 db: Session = Depends(get_db),
                 usuario: Usuario = Depends(exigir_papeis(["ARQUITETO", "DIRETOR"]))):
    """
    Obtém o QR Code atual ou código de pareamento para o número fornecido.
    Exclusivo para Arquiteto e Diretores.
    """
    res = cliente_evolution.obter_qrcode(numero_telefone=numero)
    if not res.get("sucesso"):
        raise HTTPException(502, f"Erro ao conectar com Evolution API: {res.get('erro')}")
    return res


@router.post("/conectar")
@router.post("/reiniciar")
def reiniciar_conexao(db: Session = Depends(get_db),
                      usuario: Usuario = Depends(exigir_papeis(["ARQUITETO", "DIRETOR"]))):
    """Reinicia e recria a instância de WhatsApp na Evolution API para novo QR Code."""
    cliente_evolution.recriar_instancia()
    return cliente_evolution.obter_qrcode()


@router.post("/webhook")
async def webhook_evolution(request: Request,
                            background_tasks: BackgroundTasks,
                            db: Session = Depends(get_db)):
    """
    Webhook público que recebe eventos da Evolution API v2.
    Processa mensagens em background para responder com rapidez.
    """
    try:
        payload = await request.json()
    except Exception:
        return {"status": "invalido"}

    evento = payload.get("event") or ""
    # Processa mensagens recebidas
    if evento in ("messages.upsert", "messages.update", ""):
        # Executa síncrono ou background
        servico.atender_webhook(db, payload)

    return {"status": "ok"}
