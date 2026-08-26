"""
O bot falando com o Solo CMV — como cliente HTTP, igual ao navegador.

POR QUE NÃO IMPORTAR OS SERVIÇOS DIRETO
---------------------------------------
Seria mais rápido e menos peças. Mas a fronteira de acesso por unidade é um
MIDDLEWARE HTTP (`auth/guarda_unidade.py`): ele intercepta `unidade_id` em
qualquer pedido e recusa o que não for permitido. Importando os serviços, o
bot passaria por fora dela, e "quem pode ver qual unidade" precisaria de uma
segunda implementação.

Duas implementações da mesma regra é exatamente o defeito que este projeto
veio corrigir na planilha. E já aconteceu aqui dentro, com essa mesma
pergunta: havia três respostas para "quais unidades esta pessoa vê", e elas
passaram a discordar no dia em que surgiu o escopo TODAS.

Custo da escolha: uma chamada HTTP local, latência desprezível.
Ganho: uma fronteira só — e o bot roda em outro processo, então se ele cair
o sistema web nem percebe.

O TOKEN É DO USUÁRIO, NÃO DO BOT
--------------------------------
Cada chat carrega o token daquela pessoa, emitido no pareamento, com
`canal: TELEGRAM` dentro. Não existe "token de serviço" nem cabeçalho
"atuar como fulano" — isso seria uma porta de personificação: quem roubasse
o token viraria qualquer pessoa.
"""
import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Optional


class ErroAPI(Exception):
    """Falha da API com a mensagem já pronta para o chat.

    O backend deste projeto escreve mensagens de erro que dizem o que fazer
    ("É de Gerente para cima", "Congele o inventário para poder lançar").
    Trocá-las por "erro 403" no caminho até o Telegram jogaria fora o
    trabalho de escrevê-las.
    """

    def __init__(self, status: int, mensagem: str):
        self.status = status
        self.mensagem = mensagem
        super().__init__(f"{status}: {mensagem}")


class SoloAPI:
    def __init__(self, base: str, token: Optional[str] = None,
                 segredo: Optional[str] = None):
        self.base = base.rstrip("/")
        self.token = token
        # O segredo identifica o PROCESSO do bot; o token identifica a PESSOA.
        # São coisas diferentes e viajam em cabeçalhos diferentes de
        # propósito: o segredo só abre as rotas de sessão e idempotência, que
        # não tocam em regra de negócio nenhuma.
        self.segredo = segredo

    def como(self, token: str) -> "SoloAPI":
        """Uma cópia falando como outra pessoa — um cliente por chat."""
        return SoloAPI(self.base, token, self.segredo)

    def _pedir(self, metodo: str, caminho: str,
               dados: Optional[dict] = None,
               parametros: Optional[dict] = None):
        url = self.base + caminho
        if parametros:
            limpos = {k: v for k, v in parametros.items() if v is not None}
            if limpos:
                url += "?" + urllib.parse.urlencode(limpos)

        corpo = json.dumps(dados).encode("utf-8") if dados is not None else None
        cabecalhos = {"Content-Type": "application/json"}
        if self.token:
            cabecalhos["Authorization"] = "Bearer " + self.token
        if self.segredo:
            cabecalhos["X-Bot-Segredo"] = self.segredo

        pedido = urllib.request.Request(url, data=corpo, headers=cabecalhos,
                                        method=metodo)
        try:
            with urllib.request.urlopen(pedido, timeout=30) as resposta:
                texto = resposta.read().decode("utf-8")
                return json.loads(texto) if texto else None
        except urllib.error.HTTPError as erro:
            bruto = erro.read().decode("utf-8", "replace")
            mensagem = bruto[:400]
            try:
                carga = json.loads(bruto)
                detalhe = carga.get("detail")
                if isinstance(detalhe, list) and detalhe:
                    # Erro de validação do FastAPI: a primeira mensagem é a
                    # única que interessa a quem está no chat.
                    mensagem = detalhe[0].get("msg", mensagem)
                elif detalhe:
                    mensagem = detalhe
            except (ValueError, AttributeError):
                pass
            raise ErroAPI(erro.code, mensagem)
        except urllib.error.URLError as erro:
            raise ErroAPI(0, f"O sistema não respondeu ({erro.reason}). "
                             f"Tente de novo em instantes.")

    def get(self, caminho, **parametros):
        return self._pedir("GET", caminho, parametros=parametros)

    def post(self, caminho, dados=None, **parametros):
        return self._pedir("POST", caminho, dados=dados or {}, parametros=parametros)

    def put(self, caminho, dados=None, **parametros):
        return self._pedir("PUT", caminho, dados=dados or {}, parametros=parametros)

    def delete(self, caminho, **parametros):
        return self._pedir("DELETE", caminho, parametros=parametros)
