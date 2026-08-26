import os
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from config import APP_NAME, APP_VERSION
from auth.guarda_unidade import GuardaDeUnidade
from preparar_banco import preparar

# Routers
from auth.router import router as auth_router
from routers.sessao import router as sessao_router
from routers.unidades import router as unidades_router
from routers.categorias import router as categorias_router
from routers.fornecedores import router as fornecedores_router
from routers.produtos import router as produtos_router
from routers.usuarios import router as usuarios_router
from routers.convites import router as convites_router
from routers.perfil import router as perfil_router
from routers.telegram import router as telegram_router
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
from routers.versao import router as versao_router

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

# Compressão. Acrescentado por último = camada mais externa, então vale para
# tudo: JSON das rotas, JS, CSS e as respostas de erro.
#
# Por que importa mais aqui do que num sistema comum: o servidor está a ~250 ms
# de distância de quem usa (medido: 258 ms contra 37 ms do Google), e a 250 ms
# de ida e volta cada quilobyte a menos aparece na tela. Sem isto, o
# chart.umd.js viaja 205 KB crus e a lista de estoque, 66 KB de JSON — os dois
# comprimem para perto de um quarto do tamanho.
#
# minimum_size=500: abaixo disso o cabeçalho do gzip custa mais que a economia.
app.add_middleware(GZipMiddleware, minimum_size=500, compresslevel=6)


@app.on_event("startup")
def on_startup():
    # Isto roda uma vez POR PROCESSO. Com --workers 4 são quatro execuções
    # simultâneas — daí a preparação viver em preparar_banco.py, atrás de uma
    # trava do próprio banco. Ver o cabeçalho daquele arquivo.
    #
    # Em produção o docker-compose já chamou `python preparar_banco.py` antes
    # de subir os workers, e aqui não sobra o que fazer. A chamada continua
    # para quem sobe a aplicação direto, sem passar pelo compose.
    preparar(verboso=False)


# ==============================================================================
# API ROUTES
# ==============================================================================
@app.get("/api/health", tags=["sistema"])
def health():
    return {"status": "ok", "app": APP_NAME, "version": APP_VERSION}


app.include_router(auth_router, prefix="/api")
app.include_router(sessao_router, prefix="/api")   # abertura em uma viagem só
app.include_router(unidades_router, prefix="/api")
app.include_router(categorias_router, prefix="/api")
app.include_router(fornecedores_router, prefix="/api")
app.include_router(produtos_router, prefix="/api")
app.include_router(usuarios_router, prefix="/api")
app.include_router(convites_router, prefix="/api")   # cadastro fechado por convite
app.include_router(perfil_router, prefix="/api")     # o que a própria pessoa edita
app.include_router(telegram_router, prefix="/api")   # pareamento e comandos do bot
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
app.include_router(versao_router, prefix="/api")          # versão e commit SHA do sistema

# ==============================================================================
# FRONTEND ESTÁTICO
# ==============================================================================
FRONTEND_DIR = Path(__file__).resolve().parent.parent / "frontend"

UMA_HORA = 3600


class EstaticosComCache(StaticFiles):
    """StaticFiles dizendo por quanto tempo o navegador pode reusar o arquivo.

    Sem `Cache-Control` o navegador decide sozinho por heurística — hoje ele
    acerta, mas não é garantia, e uma revalidação custa os mesmos ~250 ms de
    ida e volta que baixar o arquivo. Com 31 arquivos na página, é meio
    segundo desperdiçado só para ouvir "não mudou".

    Uma hora é o meio-termo: ninguém revalida durante o expediente, e um
    deploy chega a todo mundo no mesmo dia.

    (O parâmetro `max_age` existe no StaticFiles a partir do Starlette 0.37;
    esta subclasse funciona em qualquer versão, inclusive a do servidor.)
    """

    def file_response(self, *args, **kwargs):
        resposta = super().file_response(*args, **kwargs)
        resposta.headers.setdefault("Cache-Control", f"public, max-age={UMA_HORA}")
        return resposta


if FRONTEND_DIR.exists():
    app.mount("/assets", EstaticosComCache(directory=FRONTEND_DIR / "assets"), name="assets")
    app.mount("/css", EstaticosComCache(directory=FRONTEND_DIR / "css"), name="css")
    app.mount("/js", EstaticosComCache(directory=FRONTEND_DIR / "js"), name="js")

    @app.get("/", include_in_schema=False)
    def index():
        return FileResponse(FRONTEND_DIR / "index.html")
