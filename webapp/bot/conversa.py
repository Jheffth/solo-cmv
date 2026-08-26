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
    """"gengibre 8" → ("gengibre", 8.0, "SOMAR"). "gengibre = 12" → ("gengibre", 12.0, "SUBSTITUIR")."""
    txt = str(texto or "").strip()
    if "=" in txt:
        partes = txt.split("=", 1)
        termo = partes[0].strip()
        qtd = ler_quantidade(partes[1])
        if qtd is not None:
            return termo, qtd, "SUBSTITUIR"
    if txt.lower().startswith("corrigir "):
        resto = txt.split(maxsplit=1)[1].strip()
        partes = resto.rsplit(" ", 1)
        if len(partes) == 2:
            qtd = ler_quantidade(partes[1])
            if qtd is not None:
                return partes[0].strip(), qtd, "SUBSTITUIR"
    partes = txt.rsplit(" ", 1)
    if len(partes) == 2:
        qtd = ler_quantidade(partes[1])
        if qtd is not None:
            return partes[0].strip(), qtd, "SOMAR"
    return txt, None, "CONSULTAR"


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

        # A PORTEIRA VEM ANTES DE TUDO.
        #
        # Estava no fim, como parte do "não conheço esse comando", e
        # funcionava enquanto os comandos restritos não tinham
        # implementação — caíam no fallback e eram recusados de raspão. No
        # dia em que /cmv ganhou um handler, ele passou a ser atendido: o
        # operador recebeu o rótulo do período em vez da recusa.
        #
        # A ordem era o que segurava a regra, e ordem não segura regra. Agora
        # a recusa é a primeira coisa que acontece, e lê do MESMO registro de
        # onde a ajuda é montada — que é o ponto inteiro de ter um registro.
        fora = {c["nome"]: c["descricao"]
                for c in (estado.get("comandos_fora") or [])}
        if comando in fora:
            return self.tg.enviar(
                chat_id,
                f"{comando} não está no seu acesso ({fora[comando]}). "
                f"Fale com seu gerente.")

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

        if comando == "/congelar":
            return self._congelar(chat_id, estado, api)

        if comando == "/perda":
            return self._iniciar_perda(chat_id, resto, estado, api)

        if comando == "/requisicao":
            return self._iniciar_requisicao(chat_id, estado, api)

        if comando == "/atender":
            return self._atender(chat_id, estado, api)

        if comando == "/compra":
            return self._iniciar_compra(chat_id, estado, api)

        if comando == "/fechar":
            return self._fechar_compra(chat_id, estado, api)

        if comando == "/faturamento":
            return self._faturamento(chat_id, resto, estado, api)

        if comando == "/inventarios":
            return self._listar_inventarios(chat_id, api)

        if comando == "/estoque":
            return self._consultar_estoque(chat_id, resto, estado, api)

        if comando == "/cmv":
            return self._cmv(chat_id, estado, api)

        if comando == "/painel":
            return self._painel(chat_id, estado, api)

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

        # Texto solto é resposta ao que o modo estava perguntando. É o que
        # permite responder só "12,5" na contagem, ou "batata doce 3" na
        # perda — sem repetir de que assunto se está falando.
        if modo == "CONTAGEM":
            return self._texto_na_contagem(chat_id, dado, estado, api)
        if modo == "PERDA":
            return self._texto_na_perda(chat_id, dado, estado, api)
        if modo == "REQUISICAO":
            return self._texto_na_requisicao(chat_id, dado, estado, api)
        if modo == "COMPRA":
            return self._texto_na_compra(chat_id, dado, estado, api)

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

        # Só um número: é a quantidade do item da vez.
        nome, quantidade, modo = separar_nome_e_numero(texto)
        if not nome and quantidade is not None and contexto.get("aguardando"):
            return self._registrar(chat_id, contexto["aguardando"], quantidade,
                                   contexto, estado, api, modo=modo)

        # Nome + número numa linha só: "gengibre 8" ou "tomate = 12".
        candidatos = self._buscar(api, nome, contexto["inventario_id"])

        if not candidatos:
            return self.tg.enviar(
                chat_id,
                f"Não achei nada com “{nome}” neste inventário.\n"
                f"Tente outro pedaço do nome, ou responda só o número para "
                f"contar o item que eu perguntei.")

        escolhido = self._resolvido(candidatos)
        if escolhido is not None:
            if quantidade is not None:
                return self._registrar(chat_id, escolhido["produto_id"],
                                       quantidade, contexto, estado, api, modo=modo)
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
        contexto["termo"] = nome
        contexto["pendente_quantidade"] = quantidade
        contexto["pendente_modo"] = modo
        self._gravar(chat_id, contexto=contexto)
        return self.tg.enviar(chat_id, f"Qual deles?", teclado(botoes, por_linha=1))

    def _aprender(self, api, produto_id, termo):
        """Grava que ESTE texto significa ESTE produto — depois da escolha."""
        if not termo or len(termo.strip()) < 2:
            return
        try:
            api.post("/api/produtos/apelido",
                     {"produto_id": produto_id, "termo": termo.strip()})
        except ErroAPI:
            log.info("apelido não gravado para %s", produto_id)

    @staticmethod
    def _resolvido(candidatos):
        """O candidato a usar sem perguntar, ou None se houver dúvida real."""
        if not candidatos:
            return None
        if len(candidatos) == 1:
            return candidatos[0]
        exatos = [c for c in candidatos if c.get("exato")]
        return exatos[0] if len(exatos) == 1 else None

    def _buscar(self, api, termo, inventario_id) -> List[dict]:
        try:
            r = api.get("/api/produtos/buscar", termo=termo,
                        sessao_inventario_id=inventario_id)
        except ErroAPI:
            return []
        return r.get("itens") or []

    def _registrar(self, chat_id, produto_id, quantidade, contexto, estado, api, modo="SOMAR"):
        """Grava a contagem e confirma COM O NOME."""
        acumular = (modo == "SOMAR")
        resultado = api.post("/api/inventario/contagem", {
            "sessao_id": contexto["inventario_id"],
            "produto_id": produto_id,
            "quantidade": quantidade,
            "origem": "TELEGRAM",
            "acumular": acumular,
        })
        item = resultado.get("item") or {}
        nome = item.get("produto") or "item"
        unidade = item.get("unidade_medida") or ""
        msg = resultado.get("mensagem")

        contexto["fila"] = [p for p in (contexto.get("fila") or [])
                            if p != produto_id]
        contexto["aguardando"] = None
        contexto.pop("pendente_quantidade", None)
        contexto.pop("pendente_modo", None)
        self._gravar(chat_id, contexto=contexto,
                     ultimo_lancamento={"produto_id": produto_id,
                                        "nome": nome,
                                        "inventario_id": contexto["inventario_id"],
                                        "anterior": resultado.get("valor_anterior")})

        if msg:
            self.tg.enviar(chat_id, msg)
        else:
            self.tg.enviar(chat_id, f"✓ {nome} · {_numero(item.get('quantidade_contada', quantidade))} {unidade}".strip())
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
            self._aprender(api, produto_id, contexto.get("termo"))
            pendente = contexto.get("pendente_quantidade")
            if pendente is not None:
                return self._registrar(chat_id, produto_id, pendente, contexto,
                                       estado, api)
            contexto["aguardando"] = produto_id
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(chat_id, "Quanto tem?")

        if acao == "cong":
            abertos = api.get("/api/inventario/sessoes",
                              unidade_id=contexto.get("unidade_id")
                              or (estado.get("sessao") or {}).get("unidade_id"),
                              status="ABERTO") or []
            alvo = next((s for s in abertos if str(s["id"]) == valor), None)
            if alvo is None:
                return self.tg.enviar(
                    chat_id, "Esse inventário não está mais aberto. "
                             "Mande /congelar de novo.")
            return self._congelar_agora(chat_id, alvo, api)

        # ---- perda
        if acao == "pperda":
            self._aprender(api, int(valor), contexto.get("termo"))
            item = self._item_por_id(api, int(valor))
            if item is None:
                return self.tg.enviar(chat_id, "Não achei esse item. "
                                               "Mande /perda de novo.")
            return self._perda_com_item(chat_id, item, contexto, api)

        if acao == "mot":
            contexto["motivo"] = valor
            self._gravar(chat_id, contexto=contexto)
            if contexto.get("quantidade") is None:
                return self.tg.enviar(chat_id, f"Quanto de {contexto.get('nome')} "
                                               f"foi perdido?")
            return self._perda_gravar(chat_id, contexto, api)

        # ---- requisição
        if acao == "req":
            if valor == "nova":
                unidade = (estado.get("sessao") or {}).get("unidade_id")
                return self._abrir_requisicao(chat_id, unidade, estado, api)
            abertas = api.get("/api/requisicoes",
                              unidade_id=(estado.get("sessao") or {}).get("unidade_id"),
                              aceita_itens="true") or []
            alvo = next((r for r in abertas if str(r["id"]) == valor), None)
            if alvo is None:
                return self.tg.enviar(chat_id, "Essa requisição não aceita mais "
                                               "itens. Mande /requisicao de novo.")
            return self._entrar_na_requisicao(
                chat_id, alvo, (estado.get("sessao") or {}).get("unidade_id"), api)

        if acao == "preq":
            produto_id = int(valor)
            self._aprender(api, produto_id, contexto.get("termo"))
            pendente = contexto.get("quantidade_pendente")
            if pendente not in (None, True):
                return self._req_lancar(chat_id, produto_id, pendente,
                                        contexto, api)
            item = self._item_por_id(api, produto_id)
            contexto.update({"produto_id": produto_id,
                             "nome": (item or {}).get("nome"),
                             "unidade_medida": (item or {}).get("unidade_medida"),
                             "quantidade_pendente": True})
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(chat_id, "Quanto?")

        if acao == "atend":
            return self._atender_agora(chat_id, int(valor), api)

        # ---- compra
        if acao == "forn":
            contexto["fornecedor_id"] = int(valor)
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(chat_id, "Número da nota?")

        if acao == "pcomp":
            self._aprender(api, int(valor), contexto.get("termo"))
            pendente = contexto.get("pendente") or {}
            if not pendente:
                return self.tg.enviar(chat_id, "Perdi a quantidade. Mande a "
                                               "linha de novo: nome qtd custo")
            item = self._item_por_id(api, int(valor))
            return self._compra_lancar(chat_id, int(valor),
                                       pendente["quantidade"], pendente["custo"],
                                       contexto, api,
                                       nome=(item or {}).get("nome"))

        return self.tg.enviar(chat_id, estado["ajuda"])

    def _item_por_id(self, api, produto_id) -> Optional[dict]:
        """O produto no formato da busca, a partir do id que veio do botão.

        O botão carrega só o id — cabe 64 bytes no callback do Telegram, e
        nome não cabe sempre. Reconsultar é uma chamada barata e evita
        carregar o nome dentro do dado do botão, onde ele ficaria truncado
        justamente nos nomes longos, que são os que mais se confundem.
        """
        try:
            produtos = api.get("/api/produtos") or []
        except ErroAPI:
            return None
        p = next((x for x in produtos if x.get("id") == produto_id), None)
        if p is None:
            return None
        return {"produto_id": p.get("id"), "nome": p.get("nome"),
                "unidade_medida": p.get("unidade_medida")}

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
    # CONGELAR — o ato que libera a contagem
    # ==========================================================================
    def _congelar(self, chat_id, estado, api):
        """Fotografa o estoque e libera a contagem. Gerente para cima.

        Existe no bot, ao contrário de finalizar, e a diferença é o que cada
        um faz. Congelar ABRE trabalho e é reversível na prática (cancela-se
        o inventário e abre outro). Finalizar APLICA as contagens ao estoque,
        não volta atrás, e precisa do relatório de divergências à vista —
        por isso continua só na tela.
        """
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return

        abertos = api.get("/api/inventario/sessoes", unidade_id=unidade,
                          status="ABERTO") or []
        if not abertos:
            prontos = api.get("/api/inventario/sessoes", unidade_id=unidade,
                              aceita_contagem="true") or []
            if prontos:
                numeros = ", ".join(f"nº {s['numero_documento']}" for s in prontos)
                return self.tg.enviar(
                    chat_id,
                    f"Nada para congelar: o inventário {numeros} já está "
                    f"congelado e aceitando contagem. Mande /contar.")
            return self.tg.enviar(
                chat_id,
                "Nenhum inventário aberto nesta loja.\n\n"
                "Abrir é pela tela — é lá que se escolhe quais famílias "
                "entram no fechamento, e essa escolha decide o que vai ser "
                "contado e o que fica de fora do CMV.")

        if len(abertos) == 1:
            return self._congelar_agora(chat_id, abertos[0], api)

        botoes = [botao(f"nº {s['numero_documento']} · {s.get('descricao') or 'geral'}",
                        f"cong:{s['id']}") for s in abertos]
        return self.tg.enviar(chat_id, "Qual inventário congelar?",
                              teclado(botoes, por_linha=1))

    def _congelar_agora(self, chat_id, sessao_inv, api):
        detalhe = api.post(f"/api/inventario/sessoes/{sessao_inv['id']}/congelar")
        total = len((detalhe or {}).get("itens") or [])
        return self.tg.enviar(
            chat_id,
            f"✓ Inventário {sessao_inv['numero_documento']} congelado · "
            f"{total} itens.\n\nA contagem está liberada — quem for contar "
            f"pode mandar /contar agora.")

    # ==========================================================================
    # PERDA — o dado que a operação mais deixa de registrar
    # ==========================================================================
    def _iniciar_perda(self, chat_id, resto, estado, api):
        """`/perda`, `/perda batata doce 3` ou `/perda batata doce 3 validade`.

        Perda é o lançamento que mais se perde, e por um motivo mecânico: dá
        trabalho parar, achar um computador e abrir o sistema. O custo é alto
        o bastante para a perda simplesmente não ser registrada — e o CMV
        sobe sem explicação.

        Por isso os três formatos. Quem tem pressa resolve numa linha; quem
        não tem é conduzido.
        """
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return

        motivos = api.get("/api/perdas/motivos") or []
        contexto = {"unidade_id": unidade,
                    "motivos": {m["valor"]: m["rotulo"] for m in motivos},
                    "produto_id": None, "nome": None,
                    "unidade_medida": None, "quantidade": None}

        if not resto:
            self._gravar(chat_id, modo="PERDA", contexto=contexto)
            return self.tg.enviar(
                chat_id,
                "Qual item foi perdido? Escreva o nome.\n"
                "Com pressa, tudo numa linha:  batata doce 3 validade")

        # "/perda batata doce 3 validade" — o motivo é a última palavra, se
        # ela for um motivo conhecido. Tirar o motivo ANTES de separar o
        # número evita que "validade" vire parte do nome do produto.
        termo, motivo = self._separar_motivo(resto, contexto["motivos"])
        contexto["motivo"] = motivo
        nome, quantidade = separar_nome_e_numero(termo)
        contexto["quantidade"] = quantidade
        self._gravar(chat_id, modo="PERDA", contexto=contexto)
        return self._perda_escolher_item(chat_id, nome, contexto, api)

    @staticmethod
    def _separar_motivo(texto, motivos):
        """Tira o motivo do fim da frase, aceitando o rótulo ou a chave.

        A pessoa escreve "validade", "vencimento" ou "VALIDADE" — todas as
        três querem dizer a mesma coisa, e recusar duas delas seria pedir que
        ela decore o vocabulário do banco de dados.
        """
        palavras = str(texto or "").strip().split()
        if not palavras:
            return "", None
        ultima = palavras[-1].lower()
        for chave, rotulo in (motivos or {}).items():
            alvos = {chave.lower(), rotulo.lower()}
            alvos |= {p.lower() for p in rotulo.replace("/", " ").split()}
            if ultima in alvos:
                return " ".join(palavras[:-1]).strip(), chave
        return " ".join(palavras).strip(), None

    def _texto_na_perda(self, chat_id, texto, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        motivos = contexto.get("motivos") or {}

        # Já tem item e falta a quantidade: um número basta.
        if contexto.get("produto_id") and contexto.get("quantidade") is None:
            quantidade = ler_quantidade(texto)
            if quantidade is None:
                return self.tg.enviar(
                    chat_id, f"Quanto de {contexto['nome']} foi perdido? "
                             f"Responda só o número.")
            if quantidade <= 0:
                # Perda zero não é perda. Aceitar criaria movimento vazio no
                # histórico, que depois alguém tenta explicar.
                return self.tg.enviar(chat_id, "Perda de zero não é perda. "
                                               "Quanto foi, de verdade?")
            contexto["quantidade"] = quantidade
            self._gravar(chat_id, contexto=contexto)
            return self._perda_pedir_motivo(chat_id, contexto, api)

        termo, motivo = self._separar_motivo(texto, motivos)
        if motivo:
            contexto["motivo"] = motivo
        nome, quantidade = separar_nome_e_numero(termo)
        if quantidade is not None:
            contexto["quantidade"] = quantidade
        if not nome:
            return self.tg.enviar(chat_id, "Qual item? Escreva o nome.")
        self._gravar(chat_id, contexto=contexto)
        return self._perda_escolher_item(chat_id, nome, contexto, api)

    def _perda_escolher_item(self, chat_id, nome, contexto, api):
        candidatos = self._buscar(api, nome, None)
        if not candidatos:
            return self.tg.enviar(
                chat_id, f"Não achei nada com “{nome}”. Tente outro pedaço "
                         f"do nome.")
        escolhido = self._resolvido(candidatos)
        if escolhido is None:
            contexto["termo"] = nome
            self._gravar(chat_id, contexto=contexto)
            botoes = [botao(c["nome"], f"pperda:{c['produto_id']}")
                      for c in candidatos[:MAX_CANDIDATOS]]
            return self.tg.enviar(chat_id, "Qual deles?",
                                  teclado(botoes, por_linha=1))
        return self._perda_com_item(chat_id, escolhido, contexto, api)

    def _perda_com_item(self, chat_id, item, contexto, api):
        contexto["produto_id"] = item["produto_id"]
        contexto["nome"] = item["nome"]
        contexto["unidade_medida"] = item.get("unidade_medida") or ""
        self._gravar(chat_id, contexto=contexto)

        if contexto.get("quantidade") is None:
            return self.tg.enviar(
                chat_id,
                f"{item['nome']} · em "
                f"{item.get('unidade_medida') or 'unidades'} — quanto foi perdido?")
        return self._perda_pedir_motivo(chat_id, contexto, api)

    def _perda_pedir_motivo(self, chat_id, contexto, api):
        if contexto.get("motivo"):
            return self._perda_gravar(chat_id, contexto, api)
        motivos = contexto.get("motivos") or {}
        botoes = [botao(rotulo, f"mot:{chave}") for chave, rotulo in motivos.items()]
        # O motivo é obrigatório, e não por burocracia: sem ele "o CMV subiu"
        # e "jogamos fora R$ 4.000 de hortifruti vencido" viram o mesmo
        # número, e ninguém sabe onde agir.
        return self.tg.enviar(
            chat_id,
            f"{contexto['nome']} · {_numero(contexto['quantidade'])} "
            f"{contexto.get('unidade_medida') or ''}\nPor quê?".strip(),
            teclado(botoes, por_linha=2))

    def _perda_gravar(self, chat_id, contexto, api):
        resultado = api.post("/api/perdas", {
            "unidade_id": contexto["unidade_id"],
            "produto_id": contexto["produto_id"],
            "quantidade": contexto["quantidade"],
            "motivo": contexto["motivo"],
            "origem": "TELEGRAM",
        })
        rotulo = (contexto.get("motivos") or {}).get(
            contexto["motivo"], contexto["motivo"])

        linhas = [f"✓ Perda registrada · {contexto['nome']} · "
                  f"{_numero(contexto['quantidade'])} "
                  f"{contexto.get('unidade_medida') or ''} · {rotulo}".strip()]

        # O saldo depois é o que dá noção de tamanho: "3 kg" não diz nada;
        # "168 → 165" diz. Vem só se o backend mandou — para quem não vê
        # dinheiro, o valor da perda simplesmente não chega, e a linha some.
        saldo = (resultado or {}).get("saldo_atual")
        anterior = (resultado or {}).get("saldo_anterior")
        if saldo is not None:
            medida = contexto.get("unidade_medida") or ""
            if anterior is not None:
                linhas.append(f"Saldo: {_numero(anterior)} → "
                              f"{_numero(saldo)} {medida}".strip())
            else:
                linhas.append(f"Saldo agora: {_numero(saldo)} {medida}".strip())
        valor = ((resultado or {}).get("perda") or {}).get("valor_total")
        if valor:
            linhas.append(_brl(valor))

        # Volta para LIVRE: perda é um ato avulso, não uma sessão. Deixar o
        # modo aberto faria o próximo "12" virar outra perda sem querer.
        self._gravar(chat_id, modo="LIVRE", contexto={},
                     ultimo_lancamento={})
        return self.tg.enviar(chat_id, "\n".join(linhas))

    # ==========================================================================
    # REQUISIÇÃO — o que sai do estoque para a produção
    # ==========================================================================
    def _iniciar_requisicao(self, chat_id, estado, api):
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return

        # Filtro por SIGNIFICADO: "onde eu posso lançar itens agora". Quais
        # status servem é conhecimento do backend, que é quem recusa.
        abertas = api.get("/api/requisicoes", unidade_id=unidade,
                          aceita_itens="true") or []

        if len(abertas) == 1:
            return self._entrar_na_requisicao(chat_id, abertas[0], unidade, api)
        if abertas:
            botoes = [botao(f"{r['numero']} · {r.get('descricao') or 'sem descrição'}",
                            f"req:{r['id']}") for r in abertas]
            botoes.append(botao("+ abrir nova", "req:nova"))
            return self.tg.enviar(chat_id, "Requisições em aberto:",
                                  teclado(botoes, por_linha=1))
        return self._abrir_requisicao(chat_id, unidade, estado, api)

    def _abrir_requisicao(self, chat_id, unidade, estado, api):
        usuario = estado.get("usuario") or {}
        nova = api.post("/api/requisicoes", {
            "unidade_id": unidade,
            "solicitante": usuario.get("nome"),
            "descricao": "pelo Telegram",
        })
        # Quem inicia é `_entrar_na_requisicao`, e só ele. Iniciar aqui
        # TAMBÉM foi o primeiro desenho, e o efeito é uma requisição já
        # iniciada levando "só é possível iniciar uma requisição aberta" na
        # cara de quem acabou de criá-la.
        return self._entrar_na_requisicao(chat_id, nova, unidade, api,
                                          recem_criada=True)

    def _entrar_na_requisicao(self, chat_id, req, unidade, api,
                              recem_criada=False):
        if req.get("status") == "ABERTA":
            api.post(f"/api/requisicoes/{req['id']}/iniciar")
        contexto = {"requisicao_id": req["id"], "numero": req["numero"],
                    "unidade_id": unidade, "itens": 0,
                    "produto_id": None, "nome": None, "unidade_medida": None}
        self._gravar(chat_id, modo="REQUISICAO", contexto=contexto,
                     ultimo_lancamento={})
        abertura = ("Requisição {n} aberta" if recem_criada
                    else "Requisição {n}").format(n=req["numero"])
        return self.tg.enviar(
            chat_id,
            f"{abertura}.\n"
            f"Mande o nome e a quantidade, um por linha:  batata doce 20\n"
            f"/atender quando terminar · /sair para deixar para depois")

    def _texto_na_requisicao(self, chat_id, texto, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("requisicao_id"):
            return self.tg.enviar(chat_id, "Mande /requisicao para começar.")

        if contexto.get("produto_id") and contexto.get("quantidade_pendente"):
            quantidade = ler_quantidade(texto)
            if quantidade is None:
                return self.tg.enviar(chat_id, f"Quanto de {contexto['nome']}?")
            return self._req_lancar(chat_id, contexto["produto_id"], quantidade,
                                    contexto, api)

        nome, quantidade = separar_nome_e_numero(texto)
        candidatos = self._buscar(api, nome, None)
        if not candidatos:
            return self.tg.enviar(
                chat_id, f"Não achei nada com “{nome}”. Tente outro pedaço "
                         f"do nome.")
        escolhido = self._resolvido(candidatos)
        if escolhido is None:
            contexto["termo"] = nome
            contexto["quantidade_pendente"] = quantidade
            self._gravar(chat_id, contexto=contexto)
            botoes = [botao(c["nome"], f"preq:{c['produto_id']}")
                      for c in candidatos[:MAX_CANDIDATOS]]
            return self.tg.enviar(chat_id, "Qual deles?",
                                  teclado(botoes, por_linha=1))

        if quantidade is None:
            contexto.update({"produto_id": escolhido["produto_id"],
                             "nome": escolhido["nome"],
                             "unidade_medida": escolhido.get("unidade_medida"),
                             "quantidade_pendente": True})
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(
                chat_id, f"{escolhido['nome']} · em "
                         f"{escolhido.get('unidade_medida') or 'unidades'} — quanto?")
        return self._req_lancar(chat_id, escolhido["produto_id"], quantidade,
                                contexto, api)

    def _req_lancar(self, chat_id, produto_id, quantidade, contexto, api):
        resultado = api.post("/api/requisicoes/item", {
            "requisicao_id": contexto["requisicao_id"],
            "produto_id": produto_id,
            "quantidade": quantidade,
            "origem": "TELEGRAM",
        })
        item = (resultado or {}).get("item") or {}
        nome = item.get("produto") or contexto.get("nome") or "item"
        unidade_medida = item.get("unidade_medida") or ""

        contexto["itens"] = (contexto.get("itens") or 0) + 1
        contexto.update({"produto_id": None, "nome": None,
                         "quantidade_pendente": None})
        self._gravar(chat_id, contexto=contexto)

        linha = f"✓ {nome} · {_numero(quantidade)} {unidade_medida}".strip()

        # O SALDO AO LADO. Pedir 20 kg de um item que tem 12 é o erro que só
        # aparece na hora de atender, quando já é tarde e alguém precisa
        # refazer a conta com a produção parada.
        saldo = (resultado or {}).get("saldo_disponivel")
        if saldo is not None and saldo < quantidade:
            linha += (f"\n⚠ o estoque tem {_numero(saldo)} {unidade_medida}. "
                      f"Vai faltar na hora de atender.")
        elif saldo is not None:
            linha += f"  (tem {_numero(saldo)})"
        return self.tg.enviar(chat_id, linha)

    def _atender(self, chat_id, estado, api):
        sessao = estado.get("sessao") or {}
        contexto = sessao.get("contexto") or {}
        req_id = contexto.get("requisicao_id")

        if not req_id:
            unidade = self._unidade_atual(chat_id, estado, api)
            if unidade is None:
                return
            abertas = api.get("/api/requisicoes", unidade_id=unidade,
                              aceita_itens="true") or []
            if not abertas:
                return self.tg.enviar(
                    chat_id, "Nenhuma requisição em preenchimento nesta loja.")
            if len(abertas) > 1:
                botoes = [botao(f"{r['numero']}", f"atend:{r['id']}")
                          for r in abertas]
                return self.tg.enviar(chat_id, "Qual requisição atender?",
                                      teclado(botoes, por_linha=1))
            req_id = abertas[0]["id"]

        return self._atender_agora(chat_id, req_id, api)

    def _atender_agora(self, chat_id, req_id, api):
        detalhe = api.post(f"/api/requisicoes/{req_id}/atender")
        req = (detalhe or {}).get("requisicao") or {}
        resumo = (detalhe or {}).get("resumo") or {}
        linhas = [f"✓ Requisição {req.get('numero', '')} atendida · "
                  f"{resumo.get('total_itens', 0)} itens baixados do estoque."]
        if resumo.get("valor_total"):
            linhas.append(_brl(resumo["valor_total"]))
        self._gravar(chat_id, modo="LIVRE", contexto={}, ultimo_lancamento={})
        return self.tg.enviar(chat_id, "\n".join(linhas))

    # ==========================================================================
    # COMPRA
    # ==========================================================================
    def _iniciar_compra(self, chat_id, estado, api):
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return
        fornecedores = api.get("/api/fornecedores") or []
        if not fornecedores:
            return self.tg.enviar(
                chat_id, "Não há fornecedor cadastrado ainda. O primeiro "
                         "cadastro é pela tela, em Fornecedores.")
        contexto = {"unidade_id": unidade, "fornecedor_id": None,
                    "documento": None, "itens": 0, "valor": 0.0}
        self._gravar(chat_id, modo="COMPRA", contexto=contexto,
                     ultimo_lancamento={})
        botoes = [botao(f["nome"], f"forn:{f['id']}") for f in fornecedores[:12]]
        return self.tg.enviar(chat_id, "De qual fornecedor?",
                              teclado(botoes, por_linha=2))

    def _texto_na_compra(self, chat_id, texto, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("fornecedor_id"):
            return self.tg.enviar(chat_id, "Escolha o fornecedor nos botões "
                                           "acima, ou mande /compra de novo.")

        if not contexto.get("documento"):
            contexto["documento"] = texto.strip()[:40]
            self._gravar(chat_id, contexto=contexto)
            return self.tg.enviar(
                chat_id,
                f"Nota {contexto['documento']}.\n"
                f"Agora mande cada item assim:  nome quantidade custo\n"
                f"ex: batata doce 50 10,48\n"
                f"/fechar quando terminar")

        # "batata doce 50 10,48" — nome, quantidade, custo unitário.
        partes = texto.strip().rsplit(" ", 2)
        if len(partes) < 3:
            return self.tg.enviar(
                chat_id, "Faltou alguma coisa. O formato é:  nome quantidade "
                         "custo\nex: batata doce 50 10,48")
        nome, bruto_qtd, bruto_custo = partes
        quantidade = ler_quantidade(bruto_qtd)
        custo = ler_quantidade(bruto_custo)
        if quantidade is None or custo is None or quantidade <= 0:
            return self.tg.enviar(
                chat_id, "Não entendi a quantidade e o custo. "
                         "ex: batata doce 50 10,48")

        candidatos = self._buscar(api, nome, None)
        if not candidatos:
            return self.tg.enviar(chat_id, f"Não achei nada com “{nome}”.")
        escolhido = self._resolvido(candidatos)
        if escolhido is None:
            contexto["termo"] = nome
            contexto["pendente"] = {"quantidade": quantidade, "custo": custo}
            self._gravar(chat_id, contexto=contexto)
            botoes = [botao(c["nome"], f"pcomp:{c['produto_id']}")
                      for c in candidatos[:MAX_CANDIDATOS]]
            return self.tg.enviar(chat_id, "Qual deles?",
                                  teclado(botoes, por_linha=1))
        return self._compra_lancar(chat_id, escolhido["produto_id"],
                                   quantidade, custo, contexto, api,
                                   nome=escolhido["nome"])

    def _compra_lancar(self, chat_id, produto_id, quantidade, custo, contexto,
                       api, nome=None):
        api.post("/api/movimentos", {
            "unidade_id": contexto["unidade_id"],
            "produto_id": produto_id,
            "tipo": "COMPRA",
            "quantidade": quantidade,
            "custo_unitario": custo,
            "fornecedor_id": contexto["fornecedor_id"],
            "numero_documento": contexto["documento"],
        })
        total = round(quantidade * custo, 2)
        contexto["itens"] = (contexto.get("itens") or 0) + 1
        contexto["valor"] = round((contexto.get("valor") or 0) + total, 2)
        contexto.pop("pendente", None)
        self._gravar(chat_id, contexto=contexto)

        # O nome vem de quem escolheu o produto, não da resposta: o
        # movimento devolve `produto_id`, não o nome — e confirmar com "item"
        # anula a checagem que a confirmação existe para fazer.
        nome = nome or contexto.get("nome") or "item"
        # O custo aparece aqui, e não é incoerência com "base não vê dinheiro":
        # a nota está na mão dela. Esconder um número impresso no papel à sua
        # frente seria teatro. O que ela não vê é o agregado — CMV, estoque
        # total, faturamento.
        return self.tg.enviar(
            chat_id,
            f"✓ {nome} · {_numero(quantidade)} × {_brl(custo)} = {_brl(total)}")

    def _fechar_compra(self, chat_id, estado, api):
        contexto = (estado.get("sessao") or {}).get("contexto") or {}
        if not contexto.get("documento"):
            return self.tg.enviar(chat_id, "Não há compra em andamento.")
        itens = contexto.get("itens") or 0
        if not itens:
            self._gravar(chat_id, modo="LIVRE", contexto={})
            return self.tg.enviar(
                chat_id, f"Nota {contexto['documento']} encerrada sem itens — "
                         f"nada foi gravado.")
        self._gravar(chat_id, modo="LIVRE", contexto={})
        return self.tg.enviar(
            chat_id,
            f"✓ Nota {contexto['documento']} encerrada · {itens} itens · "
            f"{_brl(contexto.get('valor') or 0)}")

    # ==========================================================================
    # FATURAMENTO
    # ==========================================================================
    def _faturamento(self, chat_id, resto, estado, api):
        """`/faturamento 96500` lança o mês corrente até hoje.

        Sem data por escolha: pedir início e fim no chat seria quatro trocas
        de mensagem para o caso que responde por quase tudo. E o período
        aparece escrito na confirmação, então um engano é visível na hora —
        que é o que importa, já que a API recusa períodos sobrepostos e
        excluir é pela tela.
        """
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return

        valor = ler_quantidade(resto)
        if valor is None or valor <= 0:
            return self.tg.enviar(
                chat_id,
                "Quanto foi o faturamento do mês até hoje?\n"
                "ex: /faturamento 96500")

        import datetime as _dt
        hoje = _dt.date.today()
        inicio = hoje.replace(day=1)
        api.post("/api/vendas", {
            "unidade_id": unidade,
            "data_inicio": inicio.isoformat(),
            "data_fim": hoje.isoformat(),
            "faturamento_total": valor,
            "observacao": "lançado pelo Telegram",
        })
        return self.tg.enviar(
            chat_id,
            f"✓ Faturamento de {inicio.strftime('%d/%m')} a "
            f"{hoje.strftime('%d/%m')} · {_brl(valor)}")

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

    def _cmv(self, chat_id, estado, api):
        """O CMV do período, encaixado no ciclo — não no calendário.

        Os números saem do painel, e não de uma conta feita aqui. CMV nasce
        de inventário: apurar 01/08 a 31/08 quando o inventário mais próximo
        é de 03/08 faz dezenas de itens entrarem com estoque inicial zero, e
        o percentual despenca sem nada de errado ter acontecido. O serviço já
        sabe encaixar; repetir isso no bot seria a segunda implementação de
        uma conta difícil.
        """
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return
        painel = api.get("/api/dashboard/painel", unidade_id=str(unidade))
        periodo = painel.get("periodo") or {}
        kpis = painel.get("kpis") or {}

        if periodo.get("sem_ciclo"):
            return self.tg.enviar(
                chat_id,
                f"{periodo.get('rotulo', 'Este período')}: nenhum ciclo de "
                f"inventário fechado ainda, então o CMV não pode ser apurado.\n\n"
                f"Falta finalizar um inventário para delimitar o período.")

        pct = kpis.get("cmv_percentual") or {}
        valor = kpis.get("cmv_valor") or {}
        faturamento = kpis.get("faturamento") or {}

        linhas = [f"{periodo.get('rotulo', '')}".strip()]
        if pct.get("valor") is not None:
            linha = f"CMV {_pct(pct['valor'])}"
            if pct.get("meta") is not None:
                dentro = "✓" if pct.get("dentro_da_meta") else "✗"
                linha += f" · meta {_pct(pct['meta'])} {dentro}"
            linhas.append(linha)
        if valor.get("valor") is not None:
            linhas.append(f"CMV {_brl(valor['valor'])}")
        if faturamento.get("valor") is not None:
            linhas.append(f"Faturamento {_brl(faturamento['valor'])}")

        # De onde o número veio. Um CMV sem a procedência é um número que
        # ninguém sabe conferir — e o primeiro reflexo de quem estranha é
        # não acreditar no sistema.
        if periodo.get("inventario_abertura"):
            linhas.append(
                f"de INV-{periodo['inventario_abertura']} a "
                f"INV-{periodo.get('inventario_fechamento', '—')}")
        return self.tg.enviar(chat_id, "\n".join(l for l in linhas if l))

    def _painel(self, chat_id, estado, api):
        unidade = self._unidade_atual(chat_id, estado, api)
        if unidade is None:
            return
        painel = api.get("/api/dashboard/painel", unidade_id=str(unidade))

        # Quem não vê dinheiro recebe a fila de trabalho, e o backend já
        # decide isso. O bot só desenha o que chegou — se decidisse aqui,
        # seria a régua de permissão escrita uma segunda vez.
        if painel.get("operacional"):
            tarefas = painel.get("tarefas") or []
            if not tarefas:
                return self.tg.enviar(chat_id, "Nada esperando por você agora.")
            linhas = [f"• {t['titulo']} — {t['detalhe']}" for t in tarefas]
            espera = painel.get("aguardando_congelamento") or []
            if espera:
                numeros = ", ".join(f"nº {s['numero']}" for s in espera)
                linhas.append(f"\nInventário {numeros} aberto, aguardando o "
                              f"gerente congelar.")
            return self.tg.enviar(chat_id, "O que espera por você:\n"
                                  + "\n".join(linhas))

        periodo = painel.get("periodo") or {}
        kpis = painel.get("kpis") or {}
        pendencias = painel.get("pendencias") or []

        linhas = [periodo.get("rotulo", "")]
        pct = kpis.get("cmv_percentual") or {}
        if pct.get("valor") is not None:
            linhas.append(f"CMV {_pct(pct['valor'])}"
                          + (f" · meta {_pct(pct['meta'])}"
                             if pct.get("meta") is not None else ""))
        for chave in ("faturamento", "perdas", "estoque"):
            k = kpis.get(chave) or {}
            if k.get("valor") is not None:
                linhas.append(f"{chave.capitalize()} {_brl(k['valor'])}")

        if pendencias:
            linhas.append("\nPendências:")
            linhas += [f"• {p['texto']}" for p in pendencias[:5]]
        else:
            linhas.append("\nNenhuma pendência.")
        return self.tg.enviar(chat_id, "\n".join(l for l in linhas if l))


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
