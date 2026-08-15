import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import APP_NAME, APP_VERSION
from database import criar_tabelas
from migracoes import aplicar_migracoes
from auth.guarda_unidade import GuardaDeUnidade
from seed import popular_banco

# Routers
from auth.router import router as auth_router
from routers.unidades import router as unidades_router
from routers.categorias import router as categorias_router
from routers.fornecedores import router as fornecedores_router
from routers.produtos import router as produtos_router
from routers.usuarios import router as usuarios_router
from routers.movimentos import router as movimentos_router
from routers.inventario import router as inventario_router
from routers.vendas import router as vendas_router
from routers.estoque import router as estoque_router
from routers.requisicoes import router as requisicoes_router
from routers.perdas import router as perdas_router
from routers.metas import router as metas_router
from routers.despesas import router as despesas_router
from routers.dashboard import router as dashboard_router
from routers.cmv import router as cmv_router
from routers.relatorios import router as relatorios_router
from routers.nfe import router as nfe_router

# ==============================================================================
# APP
# ==============================================================================
app = FastAPI(
    title=APP_NAME,
    version=APP_VERSION,
    description="Solo CMV — Controle de Estoque, Compras e CMV",
    docs_url="/api/docs",
    redoc_url="/api/redoc",
)

# CORS: em produção, restrinja aos domínios reais via env CORS_ORIGINS
_origins_env = os.getenv("CORS_ORIGINS", "").strip()
_ambiente = os.getenv("AMBIENTE", "dev").lower()
if _origins_env:
    _origins = [o.strip() for o in _origins_env.split(",") if o.strip()]
elif _ambiente in ("prod", "producao", "production"):
    raise RuntimeError("CORS_ORIGINS não definida em produção — defina os domínios permitidos.")
else:
    _origins = ["http://localhost:8095", "http://127.0.0.1:8095"]
    print(f"[CONFIG] CORS de desenvolvimento: {_origins}")

app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Fronteira única de acesso por unidade: nenhum pedido chega às rotas
# carregando uma unidade que o usuário não pode ver (ver auth/guarda_unidade.py).
app.add_middleware(GuardaDeUnidade)


@app.on_event("startup")
def on_startup():
    criar_tabelas()
    aplicar_migracoes()   # ajusta bancos que já existiam antes de mudanças de schema
    popular_banco()


# ==============================================================================
# API ROUTES
# ==============================================================================
@app.get("/api/health", tags=["sistema"])
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


app.include_router(auth_router, prefix="/api")
app.include_router(unidades_router, prefix="/api")
app.include_router(categorias_router, prefix="/api")
app.include_router(fornecedores_router, prefix="/api")
app.include_router(produtos_router, prefix="/api")
app.include_router(usuarios_router, prefix="/api")
app.include_router(movimentos_router, prefix="/api")
app.include_router(inventario_router, prefix="/api")
app.include_router(vendas_router, prefix="/api")
app.include_router(estoque_router, prefix="/api")
app.include_router(requisicoes_router, prefix="/api")
app.include_router(perdas_router, prefix="/api")
app.include_router(metas_router, prefix="/api")
app.include_router(despesas_router, prefix="/api")
app.include_router(dashboard_router, prefix="/api")
app.include_router(cmv_router, prefix="/api")           # seção reservada — ver routers/cmv.py
app.include_router(relatorios_router, prefix="/api")     # seção reservada — ver routers/relatorios.py
app.include_router(nfe_router, prefix="/api")             # seção reservada — ver routers/nfe.py

# ==============================================================================
# FRONTEND ESTÁTICO
# ==============================================================================
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

if FRONTEND_DIR.exists():
    app.mount("/assets", StaticFiles(directory=FRONTEND_DIR / "assets"), name="assets")
    app.mount("/css", StaticFiles(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", StaticFiles(directory=FRONTEND_DIR / "js"), name="js")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
