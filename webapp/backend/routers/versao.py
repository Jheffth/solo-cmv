"""
Endpoint de versão — retorna versão semântica, git SHA, ambiente e timestamp.
Atualizado automaticamente a cada commit/deploy pelo GitHub Actions.
"""
import os
import pathlib
import subprocess
from datetime import datetime, timezone
from fastapi import APIRouter

router = APIRouter(prefix="/versao", tags=["sistema"])

def _obter_sha() -> str:
    """Obtém o SHA do commit atual: via arquivo COMMIT_SHA ou via git."""
    # 1. Arquivo gravado no deploy
    raiz_backend = pathlib.Path(__file__).parent.parent
    commit_file = raiz_backend / "COMMIT_SHA"
    if commit_file.exists():
        conteudo = commit_file.read_text(encoding="utf-8").strip()
        if conteudo:
            return conteudo[:7]
            
    # 2. Variável de ambiente
    env_sha = os.getenv("GIT_COMMIT_SHA") or os.getenv("COMMIT_SHA")
    if env_sha:
        return env_sha[:7]

    # 3. Comando git local
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            stderr=subprocess.DEVNULL,
            cwd=raiz_backend.parent
        ).decode().strip()
    except Exception:
        return "latest"

def _obter_versao() -> str:
    raiz_projeto = pathlib.Path(__file__).parent.parent.parent
    arq_version = raiz_projeto / "VERSION"
    if arq_version.exists():
        return arq_version.read_text(encoding="utf-8").strip()
    try:
        from config import APP_VERSION
        return APP_VERSION
    except Exception:
        return "0.1.0"

@router.get("/", summary="Versão e diagnóstico do sistema")
def versao():
    """Retorna versão semântica, git commit SHA, ambiente e horário do servidor."""
    return {
        "versao": _obter_versao(),
        "sha": _obter_sha(),
        "ambiente": os.getenv("AMBIENTE", "prod"),
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
