"""
O que o bot responde — toda a conversa, e nenhuma regra de negócio.

A PREMISSA QUE ORGANIZA TUDO
----------------------------
Quem conta é o auxiliar de cozinha. Essa pessoa sabe "batata doce, cinco
quilos". Ela nunca vai decorar que batata doce é 111008, e obrigá-la a
consultar uma lista impressa a cada item é reintroduzir o atrito que o bot
veio eliminar.

Daí duas regras que valem para o arquivo inteiro:

  1. NENHUM COMANDO COMEÇA PEDINDO UM NÚMERO. Ele começa mostrando o que
     existe. Uma opção só não vira pergunta — entra direto e avisa qual foi.

  2. LISTA VAZIA É A RESPOSTA MAIS IMPORTANTE. É o momento em que a pessoa
     está na câmara fria com a prancheta e nada acontece. Dizer "nenhum
     resultado" a deixa achando que o sistema quebrou; dizer o que há, por
     que não serve e quem resolve transforma isso num recado.

ONDE MORA A DECISÃO
-------------------
Aqui não se decide quem pode o quê. `permitido()` pergunta ao registro de
comandos que veio da API, e a API recusa de novo se o bot errar. A ajuda sai
do mesmo lugar — ver servicos/comandos.py sobre por que ajuda escrita à mão
vira mentira.
"""
import logging
import re
from typing import List, Optional

from solo_api import ErroAPI
from telegram_api import botao, teclado

log = logging.getLogger("bot.conversa")

ITENS_POR_PAGINA = 8      # o que cabe na tela do celular sem rolar
MAX_CANDIDATOS = 6


# ==============================================================================
# LEITURA DO QUE A PESSOA ESCREVEU
# ==============================================================================
def ler_quantidade(texto: str) -> Optional[float]:
    """"12,5" e "12.5" são a mesma coisa. "12,5 kg" também.

    Aceitar a unidade digitada junto não é frescura: a pessoa acabou de ler
    "em quilos (Kg)" na pergunta, e repetir a unidade na resposta é o
    reflexo natural. Recusar isso por causa de duas letras seria pedir que
    ela aprenda a falar com a máquina.
    """
    if texto is None:
        return None
    limpo = str(texto).strip().lower()
    limpo = re.sub(r"[a-zà-ú%$/ ]+$", "", limpo).strip()
    limpo = limpo.replace(".", "").replace(",", ".") if limpo.count(",") == 1 \
        else limpo.replace(",", ".")
    try:
        valor = float(limpo)
    except (TypeError, ValueError):
        return None
    if valor < 0:
        return None
    return valor


def separar_nome_e_numero(texto: str):
    """"gengibre 8" → ("gengibre", 8.0). "gengibre" → ("gengibre", None).

    É o atalho de quem tem pressa: resolve o item numa mensagem só, sem
    esperar a pergunta da quantidade.
    """
    partes = str(texto or "").strip().rsplit(" ", 1)
    if len(partes) == 2:
        quantidade = ler_quantidade(partes[1])
        if quantidade is not None:
            return partes[0].strip(), quantidade
    return str(texto or "").strip(), None


# ==============================================================================
# O DESPACHANTE
# ==============================================================================
class Conversa:
    """Atende uma mensagem. Sem estado próprio — tudo vem e volta pela API."""

    def __init__(self, telegram, solo, segredo: str):
        self.tg = telegram
        self.solo = solo          # cliente sem token, para /vincular e /sessao
        self.segredo = segredo

    # ------------------------------------------------------------- utilidades
    def _sessao(self, chat_id: int) -> dict:
        return self.solo.post("/api/telegram/sessao", {"chat_id": chat_id})

    def _gravar(self, chat_id: int, **campos) -> None:
        self.solo.put("/api/telegram/sessao", {"chat_id": chat_id, **campos})

    def _pode(self, estado: dict, capacidade: str) -> bool:
        return capacidade in (estado.get("capacidades") or [])

    # ==========================================================================
    # PONTO DE ENTRADA
    # ==========================================================================
    def atender(self, chat_id: int, texto: str, username: Optional[str] = None,
                callback: Optional[str] = None) -> None:
        texto = (texto or "").strip()

        try:
            estado = self._sessao(chat_id)
        except ErroAPI as erro:
            self.tg.enviar(chat_id, f"O sistema não respondeu: {erro.mensagem}")
            return

        if not estado.get("vinculado"):
            self._nao_vinculado(chat_id, texto, username)
            return

        api = self.solo.como(estado["token"])
        dado = callback or texto

        try:
            self._rotear(chat_id, dado, estado, api, veio_de_botao=bool(callback))
        except ErroAPI as erro:
            # A mensagem do backend já diz o que fazer ("É de Gerente para
            # cima", "Congele o inventário para poder lançar"). Trocá-la por
            # "erro 403" aqui jogaria fora o trabalho de escrevê-la.
            self.tg.enviar(chat_id, erro.mensagem)
        except Exception:
            log.exception("falha atendendo chat %s", chat_id)
            self.tg.enviar(
                chat_id, "Alguma coisa quebrou do meu lado. O que você "
                         "mandou NÃO foi registrado — pode tentar de novo.")

    # ==========================================================================
    # ANTES DO VÍNCULO
    # ==========================================================================
    def _nao_vinculado(self, chat_id: int, texto: str,
                       username: Optional[str]) -> None:
        partes = texto.split()
        comando = partes[0].lower() if partes else ""

        if comando in ("/vincular", "/start") and len(partes) > 1:
            try:
                r = self.solo.post("/api/telegram/vincular", {
                    "codigo": partes[1], "chat_id": chat_id,
                    "username": username})
            except ErroAPI as erro:
                self.tg.enviar(chat_id, erro.mensagem)
                return
            self.tg.enviar(
                chat_id,
                f"Pronto, {r['nome']}. Você está conectado como "
                f"{r['papel'].capitalize()}.\n\nMande /ajuda para ver o que "
                f"dá para fazer por aqui.")
            return

        # Tudo o mais cai aqui, inclusive quem só digitou "oi". Explicar o
        # caminho inteiro é mais barato que um "não entendi": a pessoa que
        # chega aqui perdida não tem como adivinhar que precisa de um código.
        self.tg.enviar(
            chat_id,
            "Este Telegram ainda não está ligado a nenhuma conta do Solo CMV.\n\n"
            "Para conectar:\n"
            "1. Entre no sistema pelo navegador\n"
            "2. Abra seu Perfil e toque em “Vincular Telegram”\n"
            "3. Volte aqui e mande:  /vincular 123456\n\n"
            "O código vale 10 minutos. Nunca mande sua senha por aqui — nem "
            "para mim: mensagem de chat fica guardada em lugares que a gente "
            "não controla.")

    # ==========================================================================
    # ROTEAMENTO
    # ==========================================================================
    def _rotear(self, chat_id, dado, estado, api, veio_de_botao=False):
        sessao = estado.get("sessao") or {}
        modo = sessao.get("modo") or "LIVRE"

        # Botões carregam ação estruturada: "inv:5", "prod:112", "pular".
        if veio_de_botao and ":" in dado:
            acao, _, valor = dado.partition(":")
            return self._acao_de_botao(chat_id, acao, valor, estado, api)

        palavras = dado.split()
        comando = palavras[0].lower() if palavras else ""
        resto = " ".join(palavras[1:]).strip()

        if comando in ("/ajuda", "/start", "/help"):
            return self.tg.enviar(chat_id, estado["ajuda"])

        if comando == "/vincular":
            # Quem JÁ está vinculado e manda /vincular caía no genérico, e o
            # código digitado ficava intacto — pronto para ser usado por
            # outro chat, movendo o vínculo sem ninguém perceber. Agora a
            # resposta diz o estado atual e o caminho para trocar.
            atual = estado.get("usuario") or {}
            return self.tg.enviar(
                chat_id,
                f"Este Telegram já está ligado à conta de {atual.get('nome')} "
                f"({(atual.get('papel') or '').capitalize()}).\n\n"
                f"Para ligar a outra conta, desvincule antes: no sistema, "
                f"Perfil › Telegram › Desvincular.")

        if comando == "/sair":
            self._gravar(chat_id, modo="LIVRE", contexto={}, ultimo_lancamento={})
            return self.tg.enviar(chat_id, "Encerrado. Mande /ajuda quando precisar.")

        if comando == "/unidade":
            return self._escolher_unidade(chat_id, estado, api)

        if comando == "/contar":
            return self._iniciar_contagem(chat_id, estado, api)

        if comando == "/inventarios":
            return self._listar_inventarios(chat_id, api)

        if comando == "/estoque":
            return self._consultar_estoque(chat_id, resto, estado, api)

        if comando in ("/faltam", "faltam"):
            return self._faltam(chat_id, estado, api)

        if comando in ("/resumo", "resumo"):
            return self._resumo(chat_id, estado, api)

        if comando == "/desfazer":
            return self._desfazer(chat_id, estado, api)

        if comando in ("pular", "/pular"):
            return self._pular(chat_id, estado, api)

        if comando == "zero":
            # "não tem" registra ZERO, e zero é informação: sem ele o sistema
            # não sabe se o item acabou ou se ninguém passou por ele.
            contexto = (estado.get("sessao") or {}).get("contexto") or {}
            if contexto.get("aguardando"):
                return self._registrar(chat_id, contexto["aguardando"], 0.0,
                                       contexto, estado, api)
            return self.tg.enviar(chat_id, "Não há item aguardando quantidade.")

        # QUALQUER comando barrado ANTES do modo de contagem.
        #
        # Estava depois, e o efeito era feio: dentro de uma contagem, "/cmv"
        # virava busca de produto e a pessoa recebia "não achei nada com
        # /cmv neste inventário". A resposta certa é dizer que o comando não
        # é dela — o que ela pediu não tem nada a ver com o item da prateleira.
        if comando.startswith("/"):
            return self._comando_desconhecido(chat_id, comando, estado)

        # Dentro da contagem, texto solto é resposta — número é a quantidade
        # do item da vez, nome é uma busca. É o que permite responder só
        # "12,5", que é o mínimo de esforço possível.
        if modo == "CONTAGEM":
            return self._texto_na_contagem(chat_id, dado, estado, api)

        return self.tg.enviar(chat_id, estado["ajuda"])

    def _comando_desconhecido(self, chat_id, comando, estado):
        """Separa "não existe" de "não é seu" — são conselhos diferentes.

        Quem digita /contagem em vez de /contar precisa da lista. Quem digita
        /cmv sem poder ver CMV precisa saber a quem pedir; mostrar a lista
        para essa pessoa não responde nada, porque o que ela quer não está
        lá justamente por ser dela que se está falando.
        """
        fora = {c["nome"]: c["descricao"]
                for c in (estado.get("comandos_fora") or [])}
        if comando in fora:
            return self.tg.enviar(
                chat_id,
                f"{comando} não está no seu acesso ({fora[comando]}). "
                f"Fale com seu gerente.")
        # Quem digita /contagem em vez de /contar recebe a lista, não um
        # "comando inválido". A correção custa o mesmo; o desamparo, não.
        return self.tg.enviar(
            chat_id, f"Não conheço “{comando}”.\n\n{estado['ajuda']}")

    # ==========================================================================
    # UNIDADE
    # ==========================================================================
    def _unidade_atual(self, chat_id, estado, api) -> Optional[int]:
        """A loja em que se está trabalhando — perguntando só quando precisa.

        Quem tem uma loja só nunca vê essa pergunta. Fazer alguém escolher
        entre uma coisa é um toque cobrado por nada, e é o caso mais comum.
        """
        sessao = estado.get("sessao") or {}
        if sessao.get("unidade_id"):
            return sessao["unidade_id"]

        escopo = api.get("/api/unidades/escopo")
        unidades = escopo.get("unidades") or []
        if len(unidades) == 1:
            uid = unidades[0]["id"]
            self._gravar(chat_id, unidade_id=uid)
            return uid
        if not unidades:
            self.tg.enviar(chat_id, "Sua conta não tem nenhuma loja liberada. "
                                    "Fale com quem administra os acessos.")
            return None

        self._escolher_unidade(chat_id, estado, api)
        return None

    def _escolher_unidade(self, chat_id, estado, api):
        escopo = api.get("/api/unidades/escopo")
        unidades = escopo.get("unidades") or []
        if not unidades:
            return self.tg.enviar(chat_id, "Nenhuma loja liberada para você.")
        if len(unidades) == 1:
            self._gravar(chat_id, unidade_id=unidades[0]["id"])
            return self.tg.enviar(
                chat_id, f"Você só tem a {unidades[0]['nome']} — já está nela.")
        botoes = [botao(u["nome"], f"uni:{u['id']}") for u in unidades]
        return self.tg.enviar(chat_id, "Em qual loja?", teclado(botoes))

    # ==========================================================================
    # CONTAGEM
    # ==========================================================================
    def _iniciar_contagem(self, chat_id, estado, api):
        """Mostra o que existe. Nunca pede o número do inventário.

        O filtro é por SIGNIFICADO (`aceita_contagem`), e não por status: a
        lista de status que serve mora no backend, que é quem recusa. Aqui
        seria uma segunda cópia, envelhecendo em silêncio.
        """
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return

        prontos = api.get("/api/inventario/sessoes", unidade_id=unidade,
                          aceita_contagem="true") or []

        if not prontos:
            return self._nada_para_contar(chat_id, unidade, api)

        if len(prontos) == 1:
            return self._entrar_no_inventario(chat_id, prontos[0], estado, api)

        botoes = [botao(f"nº {s['numero_documento']} · {s.get('descricao') or 'geral'}",
                        f"inv:{s['id']}") for s in prontos]
        return self.tg.enviar(chat_id, "Inventários prontos para contagem:",
                              teclado(botoes, por_linha=1))

    def _nada_para_contar(self, chat_id, unidade, api):
        """A resposta mais importante do bot.

        É o momento em que a pessoa está na câmara fria e nada acontece.
        "Nenhum resultado" a deixa achando que o sistema quebrou. Dizer o que
        há, por que não serve e de quem depende transforma isso num recado
        para outra pessoa.
        """
        abertos = api.get("/api/inventario/sessoes", unidade_id=unidade,
                          status="ABERTO") or []
        if abertos:
            numeros = ", ".join(f"nº {s['numero_documento']}" for s in abertos)
            return self.tg.enviar(
                chat_id,
                f"Nenhum inventário congelado aqui ainda.\n\n"
                f"O inventário {numeros} está aberto, mas ainda não foi "
                f"congelado — é o gerente quem faz isso, e a contagem libera "
                f"depois. Avise ele.")
        return self.tg.enviar(
            chat_id,
            "Não há inventário para contar nesta loja agora.\n\n"
            "Quem abre e congela é o gerente. Assim que ele congelar, "
            "mande /contar de novo.")

    def _entrar_no_inventario(self, chat_id, sessao_inv, estado, api):
        detalhe = api.get(f"/api/inventario/sessoes/{sessao_inv['id']}")
        itens = detalhe.get("itens") or []
        fila = [i["produto_id"] for i in itens if i.get("quantidade_contada") is None]

        # O catálogo do inventário viaja no contexto, compacto: [id, nome, un].
        # A primeira versão buscava /api/produtos a cada item — 244 produtos
        # por pergunta, 42 vezes por inventário. Funciona e é desperdício
        # visível: são dados que não mudam durante a contagem.
        catalogo = {str(i["produto_id"]): [i.get("produto") or "?",
                                           i.get("unidade_medida") or ""]
                    for i in itens}
        contexto = {"inventario_id": sessao_inv["id"],
                    "numero": sessao_inv["numero_documento"],
                    "fila": fila, "total": len(itens),
                    "catalogo": catalogo,
                    "aguardando": None}
        self._gravar(chat_id, modo="CONTAGEM", contexto=contexto,
                     ultimo_lancamento={})

        contados = len(itens) - len(fila)
        cabecalho = (f"Inventário {sessao_inv['numero_documento']} · "
                     f"{len(itens)} itens")
        if contados:
            cabecalho += f" · {contados} já contados"
        self.tg.enviar(
            chat_id,
            f"{cabecalho}\n"
            f"Vou passar item por item. Responda só a quantidade.\n"
            f"“pular” salta · “faltam” mostra o que resta · /sair encerra")
        return self._proximo_item(chat_id, contexto, api)

    def _proximo_item(self, chat_id, contexto, api):
        fila = contexto.get("fila") or []
        if not fila:
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(
                chat_id,
                f"Inventário {contexto['numero']}: todos os {contexto['total']} "
                f"itens contados.\n\nQuem finaliza é o gerente, pela tela — é "
                f"lá que dá para conferir as divergências antes de aplicar ao "
                f"estoque.")

        catalogo = contexto.get("catalogo") or {}
        dados = catalogo.get(str(fila[0]))
        if dados is None:
            # Item sem nome no catálogo do contexto (sessão antiga, formato
            # anterior). Pular é melhor que travar a fila inteira.
            contexto["fila"] = fila[1:]
            return self._proximo_item(chat_id, contexto, api)
        nome, unidade = dados[0], dados[1]

        contexto["aguardando"] = fila[0]
        self._gravar(chat_id, contexto=contexto)

        posicao = contexto["total"] - len(fila) + 1
        botoes = [botao("pular", "pular"), botao("não tem", "zero")]
        # A UNIDADE DE MEDIDA VEM ESCRITA. Evita o erro mais caro do
        # inventário: contar caixa onde o sistema espera quilo.
        return self.tg.enviar(
            chat_id,
            f"{posicao}/{contexto['total']}\n"
            f"{nome}\n"
            f"em {unidade or 'unidades'}",
            [botoes])

    def _texto_na_contagem(self, chat_id, texto, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("inventario_id"):
            return self.tg.enviar(chat_id, "Mande /contar para começar.")

        # Só um número: é a quantidade do item da vez. Este é o caminho de
        # menor esforço que existe — a pessoa digita "12,5" e nada mais.
        quantidade = ler_quantidade(texto)
        if quantidade is not None and contexto.get("aguardando"):
            return self._registrar(chat_id, contexto["aguardando"], quantidade,
                                   contexto, estado, api)

        # Nome + número numa linha só: "gengibre 8".
        nome, quantidade = separar_nome_e_numero(texto)
        candidatos = self._buscar(api, nome, contexto["inventario_id"])

        if not candidatos:
            return self.tg.enviar(
                chat_id,
                f"Não achei nada com “{nome}” neste inventário.\n"
                f"Tente outro pedaço do nome, ou responda só o número para "
                f"contar o item que eu perguntei.")

        if len(candidatos) == 1:
            escolhido = candidatos[0]
            if quantidade is not None:
                return self._registrar(chat_id, escolhido["produto_id"],
                                       quantidade, contexto, estado, api)
            contexto["aguardando"] = escolhido["produto_id"]
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(
                chat_id, f"{escolhido['nome']} · em "
                         f"{escolhido.get('unidade_medida') or 'unidades'} — quanto tem?")

        # Ambíguo: oferece. E a lista já vem ordenada por probabilidade —
        # item do escopo primeiro, já contado por último.
        botoes = [botao(c["nome"] + (" ✓" if c.get("ja_contado") else ""),
                        f"prod:{c['produto_id']}")
                  for c in candidatos[:MAX_CANDIDATOS]]
        contexto["pendente_quantidade"] = quantidade
        self._gravar(chat_id, contexto=contexto)
        return self.tg.enviar(chat_id, f"Qual deles?", teclado(botoes, por_linha=1))

    def _buscar(self, api, termo, inventario_id) -> List[dict]:
        try:
            r = api.get("/api/produtos/buscar", termo=termo,
                        sessao_inventario_id=inventario_id)
        except ErroAPI:
            return []
        return r.get("itens") or []

    def _registrar(self, chat_id, produto_id, quantidade, contexto, estado, api):
        """Grava a contagem e confirma COM O NOME.

        A confirmação pelo nome é a checagem de que a pessoa lançou no item
        certo — vale ainda mais quando ela chegou por botão, onde "Batata
        Doce" e "Batata Baroa" ficam a um dedo de distância.
        """
        resultado = api.post("/api/inventario/contagem", {
            "sessao_id": contexto["inventario_id"],
            "produto_id": produto_id,
            "quantidade": quantidade,
            "origem": "TELEGRAM",
        })
        item = resultado.get("item") or {}
        nome = item.get("produto") or "item"
        unidade = item.get("unidade_medida") or ""

        contexto["fila"] = [p for p in (contexto.get("fila") or [])
                            if p != produto_id]
        contexto["aguardando"] = None
        contexto.pop("pendente_quantidade", None)
        self._gravar(chat_id, contexto=contexto,
                     ultimo_lancamento={"produto_id": produto_id,
                                        "nome": nome,
                                        "inventario_id": contexto["inventario_id"],
                                        "anterior": resultado.get("valor_anterior")})

        self.tg.enviar(chat_id, f"✓ {nome} · {_numero(quantidade)} {unidade}".strip())
        return self._proximo_item(chat_id, contexto, api)

    # ------------------------------------------------------------------ botões
    def _acao_de_botao(self, chat_id, acao, valor, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}

        if acao == "uni":
            self._gravar(chat_id, unidade_id=int(valor))
            return self.tg.enviar(chat_id, "Loja trocada. Mande /contar para começar.")

        if acao == "inv":
            sessoes = api.get("/api/inventario/sessoes",
                              unidade_id=(estado.get("sessao") or {}).get("unidade_id"),
                              aceita_contagem="true") or []
            alvo = next((s for s in sessoes if str(s["id"]) == valor), None)
            if alvo is None:
                return self.tg.enviar(chat_id, "Esse inventário não aceita mais "
                                               "contagem. Mande /contar de novo.")
            return self._entrar_no_inventario(chat_id, alvo, estado, api)

        if acao == "prod":
            produto_id = int(valor)
            pendente = contexto.get("pendente_quantidade")
            if pendente is not None:
                return self._registrar(chat_id, produto_id, pendente, contexto,
                                       estado, api)
            contexto["aguardando"] = produto_id
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(chat_id, "Quanto tem?")

        return self.tg.enviar(chat_id, estado["ajuda"])

    def _pular(self, chat_id, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        fila = contexto.get("fila") or []
        if not fila:
            return self.tg.enviar(chat_id, "Não há item na fila.")
        # Vai para o FIM, não some: a pessoa conta na ordem da prateleira, e
        # o item pulado ainda precisa ser contado antes de fechar.
        contexto["fila"] = fila[1:] + [fila[0]]
        contexto["aguardando"] = None
        return self._proximo_item(chat_id, contexto, api)

    def _faltam(self, chat_id, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("inventario_id"):
            return self.tg.enviar(chat_id, "Mande /contar para começar.")
        detalhe = api.get(f"/api/inventario/sessoes/{contexto['inventario_id']}")
        pendentes = [i["produto"] for i in (detalhe.get("itens") or [])
                     if i.get("quantidade_contada") is None]
        if not pendentes:
            return self.tg.enviar(chat_id, "Nada faltando — tudo contado.")
        amostra = " · ".join(pendentes[:12])
        extra = f"\n… e mais {len(pendentes) - 12}" if len(pendentes) > 12 else ""
        return self.tg.enviar(
            chat_id, f"{len(pendentes)} sem contagem:\n{amostra}{extra}")

    def _resumo(self, chat_id, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("inventario_id"):
            return self.tg.enviar(chat_id, "Mande /contar para começar.")
        detalhe = api.get(f"/api/inventario/sessoes/{contexto['inventario_id']}")
        r = detalhe.get("resumo") or {}
        # Contados e faltando; nada de valor. Este resumo é do trabalho, não
        # do dinheiro — e para quem não vê R$ o backend nem manda.
        return self.tg.enviar(
            chat_id,
            f"Inventário {contexto['numero']}\n"
            f"{r.get('itens_contados', 0)} de {r.get('total_itens', 0)} contados · "
            f"{r.get('itens_nao_contados', 0)} faltando")

    def _desfazer(self, chat_id, estado, api):
        ultimo = (estado.get("sessao") or {}).get("ultimo_lancamento")
        if not ultimo:
            return self.tg.enviar(chat_id, "Não tenho nada recente para desfazer.")
        anterior = ultimo.get("anterior")
        if anterior is None:
            # Não havia contagem antes: o certo seria remover a linha, e a API
            # não expõe isso. Dizer a verdade é melhor que fingir que desfez.
            return self.tg.enviar(
                chat_id,
                f"{ultimo['nome']} não tinha contagem anterior — não dá para "
                f"voltar ao estado de “não contado” por aqui. Recontar com o "
                f"número certo resolve: é só mandar o nome e a quantidade.")
        api.post("/api/inventario/contagem", {
            "sessao_id": ultimo["inventario_id"],
            "produto_id": ultimo["produto_id"],
            "quantidade": anterior,
            "origem": "TELEGRAM",
        })
        self._gravar(chat_id, ultimo_lancamento={})
        return self.tg.enviar(
            chat_id, f"Desfeito: {ultimo['nome']} voltou para {_numero(anterior)}.")

    # ==========================================================================
    # CONSULTA
    # ==========================================================================
    def _listar_inventarios(self, chat_id, api):
        sessoes = api.get("/api/inventario/sessoes", limite=5) or []
        if not sessoes:
            return self.tg.enviar(chat_id, "Nenhum inventário registrado ainda.")
        linhas = [f"nº {s['numero_documento']} · {s['status'].lower()}"
                  for s in sessoes[:5]]
        return self.tg.enviar(chat_id, "Últimos inventários:\n" + "\n".join(linhas))

    def _consultar_estoque(self, chat_id, termo, estado, api):
        if not termo:
            return self.tg.enviar(chat_id, "Qual item?  ex: /estoque batata")
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return
        dados = api.get("/api/estoque", unidade_id=unidade, busca=termo)
        itens = [i for i in (dados.get("itens") or [])][:8]
        if not itens:
            return self.tg.enviar(chat_id, f"Não achei nada com “{termo}”.")

        # `com_valores` vem do servidor. O bot não decide quem vê dinheiro —
        # ele mostra o que chegou. Para o operador, o R$ simplesmente não vem.
        com_valores = dados.get("com_valores") is not False
        linhas = []
        for i in itens:
            linha = f"{i['nome']}: {_numero(i['quantidade'])} {i.get('unidade_medida') or ''}".strip()
            if com_valores and i.get("valor_em_estoque"):
                linha += f" · {_brl(i['valor_em_estoque'])}"
            linhas.append(linha)
        return self.tg.enviar(chat_id, "\n".join(linhas))


def _numero(valor) -> str:
    """Formato pt-BR sem casas inúteis: 8 e não 8,000."""
    try:
        v = float(valor)
    except (TypeError, ValueError):
        return str(valor)
    texto = f"{v:.3f}".rstrip("0").rstrip(".")
    return texto.replace(".", ",") or "0"


def _brl(valor) -> str:
    return "R$ " + f"{float(valor):,.2f}".replace(",", "@").replace(".", ",").replace("@", ".")
