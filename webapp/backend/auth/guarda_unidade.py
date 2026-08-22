"""
Guarda de unidade — um único ponto por onde todo pedido passa.

POR QUE MIDDLEWARE, E NÃO UMA CHECAGEM EM CADA ROTA
---------------------------------------------------
`unidade_id` aparece em 95 lugares, espalhados por doze routers. Validar de
um em um funciona até alguém acrescentar a rota número treze e esquecer —
e um controle de acesso que depende de ninguém esquecer não é controle de
acesso.

Aqui a verificação acontece antes de qualquer rota existir: se o pedido
carrega uma unidade na URL ou no corpo, o usuário precisa ter acesso a ela.
Rota nova nasce protegida sem que ninguém precise lembrar.

O QUE ESTE GUARDA NÃO COBRE
---------------------------
Rotas que identificam o registro por id próprio (`/inventario/sessoes/12`)
não trazem `unidade_id` no pedido — a unidade está no registro. Esses casos
são validados dentro da própria rota, ao carregar o objeto.
"""
import json
from typing import Optional, Set
from urllib.parse import parse_qs

from fastapi.responses import JSONResponse
from jose import JWTError

from auth.security import decodificar_access_token
from database import SessionLocal
from models import Usuario, Unidade, PapelUsuario, PAPEIS_IRRESTRITOS

# Rotas que não falam de unidade nenhuma
ISENTAS = ("/api/auth", "/api/health", "/docs", "/openapi.json", "/redoc")

# O sentinela da Regional viaja no mesmo parâmetro; quem trata dele é a
# rota, que sabe se aceita consolidação. Aqui só se deixa passar.
REGIONAL = "REGIONAL"


def _unidades_do_usuario(db, usuario: Usuario) -> Set[int]:
    """Delega a `servicos.escopo` — mesma resposta que as rotas usam.

    Antes esta função tinha cópia própria da regra, e as duas cópias
    envelheceram separadas: quando surgiu o escopo TODAS, as rotas passaram a
    enxergar as lojas novas e o guarda continuou barrando. A pessoa recebia
    403 numa unidade que o próprio sistema dizia que ela podia ver.

    A importação é feita aqui dentro, e não no topo, porque `servicos.escopo`
    importa `auth.deps`, que importa este módulo. No topo seria ciclo.
    """
    from servicos import escopo as servico_escopo
    return {u.id for u in servico_escopo.unidades_permitidas(db, usuario)}


def _pode_regional(usuario: Usuario) -> bool:
    from servicos import escopo as servico_escopo
    return servico_escopo.pode_ver_regional(usuario)


def _extrair_do_corpo(corpo: bytes) -> Set[str]:
    """Procura unidade_id no JSON, inclusive dentro de listas de itens."""
    if not corpo:
        return set()
    try:
        dados = json.loads(corpo)
    except (ValueError, UnicodeDecodeError):
        return set()

    encontrados: Set[str] = set()

    def varrer(no):
        if isinstance(no, dict):
            for chave, valor in no.items():
                if chave == "unidade_id" and valor is not None:
                    encontrados.add(str(valor))
                elif chave == "unidade_ids" and isinstance(valor, list):
                    # Vínculo de usuário: quem cria não pode dar acesso a
                    # unidade que ele mesmo não enxerga.
                    encontrados.update(str(v) for v in valor if v is not None)
                else:
                    varrer(valor)
        elif isinstance(no, list):
            for item in no:
                varrer(item)

    varrer(dados)
    return encontrados


class GuardaDeUnidade:
    """Middleware ASGI puro.

    Não é BaseHTTPMiddleware de propósito: aquele reconstrói o canal de
    entrada, e o corpo lido aqui não chegaria à rota adiante. Em ASGI puro
    o `receive` repassado é escolhido por nós — dá para ler o corpo,
    conferir e devolvê-lo intacto.
    """

    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            return await self.app(scope, receive, send)

        caminho = scope.get("path", "")
        metodo = scope.get("method", "GET")
        if metodo == "OPTIONS" or caminho.startswith(ISENTAS):
            return await self.app(scope, receive, send)

        pedidas: Set[str] = set()

        consulta = parse_qs((scope.get("query_string") or b"").decode("latin-1"))
        for valor in consulta.get("unidade_id", []):
            if valor:
                pedidas.add(valor)

        # Lê o corpo inteiro e guarda os pedaços para repassar sem perda
        pedacos = []
        if metodo in ("POST", "PUT", "PATCH"):
            while True:
                evento = await receive()
                if evento["type"] == "http.disconnect":
                    pedacos.append(evento)
                    break
                pedacos.append(evento)
                if not evento.get("more_body"):
                    break
            corpo = b"".join(e.get("body", b"") for e in pedacos)
            pedidas |= _extrair_do_corpo(corpo)

        if pedacos:
            fila = list(pedacos)

            async def receber():
                if fila:
                    return fila.pop(0)
                return await receive()
        else:
            receber = receive

        if not pedidas:
            return await self.app(scope, receber, send)

        cabecalhos = {k.decode("latin-1").lower(): v.decode("latin-1")
                      for k, v in scope.get("headers", [])}
        autorizacao = cabecalhos.get("authorization", "")
        if not autorizacao.lower().startswith("bearer "):
            # Sem token a rota devolve 401, que é a resposta certa
            return await self.app(scope, receber, send)

        negado = self._negar(autorizacao, pedidas)
        if negado is not None:
            return await negado(scope, receber, send)
        return await self.app(scope, receber, send)

    def _negar(self, autorizacao: str, pedidas: Set[str]) -> Optional[JSONResponse]:
        """Devolve a resposta 403 quando o acesso não é permitido."""
        db = SessionLocal()
        try:
            try:
                payload = decodificar_access_token(autorizacao.split(" ", 1)[1])
                usuario_id = int(payload.get("sub"))
            except (JWTError, TypeError, ValueError):
                return None                      # token inválido: a rota devolve 401

            usuario = db.query(Usuario).filter(Usuario.id == usuario_id).first()
            if usuario is None or not usuario.ativo:
                return None

            permitidas = _unidades_do_usuario(db, usuario)
            for pedida in pedidas:
                if str(pedida).upper() == REGIONAL:
                    if not _pode_regional(usuario):
                        return JSONResponse(
                            status_code=403,
                            content={"detail": "Você não tem acesso à visão Regional."})
                    continue
                try:
                    numero = int(pedida)
                except (TypeError, ValueError):
                    continue                     # a rota valida o formato
                if numero not in permitidas:
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "Você não tem acesso a esta unidade."})
            return None
        finally:
            db.close()
