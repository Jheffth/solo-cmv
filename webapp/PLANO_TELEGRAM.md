# Bot do Telegram — estudo e plano de implementação

**Data:** 14/08/2026
**Objetivo:** lançar (contagem, perda, requisição, compra) e consultar (estoque, CMV, painel) pelo Telegram, sem duplicar nenhuma regra de negócio.

---

## 1. O que já está pronto — auditoria

Esta integração vem sendo preparada desde o início, e a verificação confirma que a fundação existe:

| Peça | Estado | Onde |
|---|---|---|
| Regra separada da tela | **pronto** | `servicos/` — contagem, perda, requisição, cmv, painel, relatórios, metas, escopo, regional |
| Marcação de origem | **pronto** | `ORIGEM_TELEGRAM = "TELEGRAM"` já existe em `contagem.py`, `perda.py`, `requisicao.py`; a coluna `origem` está gravada em `inventario_itens` |
| Rota que aceita identificação flexível | **pronto** | `POST /inventario/contagem` recebe *número* do inventário e *código* do produto, não só ids — foi escrita pensando neste bot |
| Código de 6 dígitos por item | **pronto** | `codigos.py` — é o que torna a digitação no celular viável |
| Fronteira de acesso por unidade | **pronto** | `auth/guarda_unidade.py` — middleware ASGI, vale para qualquer cliente HTTP |
| Escopo do usuário (unidades + Regional) | **pronto** | `servicos/escopo.py` |

**O que falta é só o canal.** Nenhuma regra precisa ser escrita de novo — e é isso que torna esta implementação viável em semanas, não meses.

---

## 2. Contexto atual do Telegram (agosto/2026)

Pesquisa feita para não planejar sobre memória:

- **Bot API 10.1**, publicada em 11/06/2026. Traz *Rich Messages* (texto estruturado com títulos, listas e divisores), comunicação bot-a-bot, e lista de acesso granular configurável pelo @BotFather.
- **Limites de envio:** 1 mensagem por segundo no mesmo chat, 30/s no total, 20/min no mesmo grupo. Updates recebidos (polling ou webhook) **não contam** nesse orçamento. Para o volume desta operação — dezenas de mensagens por dia — os limites são irrelevantes.
- **Mini Apps** tiveram a segurança endurecida em 20/07/2026: métodos de Mini App só funcionam a partir do domínio original do app.
- **Webhook × polling:** webhook entrega mais rápido e poupa servidor; polling longo (timeout de 30s) mantém uma conexão só e funciona atrás de NAT, sem precisar de domínio nem certificado.

---

## 3. As sete decisões de arquitetura

### 3.1 O bot é um cliente HTTP, não um módulo do servidor

Duas opções existiam:

**(a)** O bot importa `servicos/` e fala direto com o banco.
**(b)** O bot chama a mesma API que o navegador chama.

Parece que (a) é mais simples — menos latência, menos peças. Mas a fronteira de acesso por unidade é um **middleware HTTP** (`auth/guarda_unidade.py`). Com (a) o bot passaria por fora dela, e seria preciso reimplementar "quem pode ver qual unidade" numa segunda vez. Duas implementações da mesma regra é exatamente o defeito que este projeto veio corrigir na planilha.

**Decisão: (b).** O bot é um cliente como o navegador. Custo: uma chamada HTTP local, latência desprezível. Ganho: uma fronteira de segurança só, e o bot pode rodar em outro processo — se ele cair, o sistema web nem percebe.

```
Telegram  ──updates──>  bot (processo próprio)  ──HTTP──>  API Solo CMV
                              │                                  │
                        sessão do chat                    guarda de unidade
                        (quem, qual unidade,              papéis, escopo
                         modo ativo)                      servicos/*
```

### 3.2 Polling primeiro, webhook depois

Webhook exige domínio público com HTTPS válido apontando para o Comodo. Polling não exige nada — funciona atrás de NAT, sem certificado, sem abrir porta.

Com o volume desta operação, a diferença de latência entre os dois é de segundos que ninguém percebe contando batata na câmara fria.

**Decisão: começar com long polling** (timeout 30s). Migrar para webhook é trocar a inicialização — dez linhas — e vale a pena quando houver domínio configurado.

### 3.3 Identidade: pareamento, nunca senha no chat

O Telegram entrega `chat_id` (número estável) e `username` (que o dono pode trocar a qualquer momento). A chave é o `chat_id`.

**Como um `chat_id` vira "o gerente João":**

```
1. No sistema web, em Usuários, o Admin clica em "Vincular Telegram"
2. O sistema gera um código de 6 dígitos, válido por 10 minutos
3. A pessoa manda no bot:  /vincular 384912
4. O backend casa o código com o usuário e grava usuario.telegram_chat_id
5. O código é queimado
```

**Senha nunca trafega pelo chat.** Uma mensagem de Telegram fica no histórico do aparelho, no aparelho de quem receber um encaminhamento, e nos servidores do Telegram. Pedir login e senha ali seria entregar a credencial para três lugares que não controlamos.

O vínculo é **revogável** na mesma tela: perdeu o celular, o Admin desvincula e o `chat_id` para de valer na hora.

### 3.4 O bot herda o escopo — não ganha um novo

Nada de "permissões do bot". O bot atua **como o usuário vinculado**: mesmas unidades, mesmo papel, mesma regra de Regional. Um operador da Josefina que mandar uma contagem para a Casa Josefina recebe o mesmo 403 que receberia no navegador.

Quem tem mais de uma unidade escolhe com `/unidade`, e a escolha fica na sessão do chat.

**Três ações ficam fora do bot, por decisão:**

| Ação | Por quê |
|---|---|
| Finalizar inventário | Aplica as contagens ao estoque real. É irreversível e precisa da tela, com o relatório de divergências à vista. |
| Cancelar inventário / requisição | Descarte de trabalho — merece confirmação em tela. |
| Definir metas | Ato de diretoria, com vigência e justificativa. |

Um celular perdido e destravado não pode derrubar um inventário.

### 3.5 Busca por nome é infraestrutura, não enfeite

O bot inteiro depende de transformar `"bata doce"` em `produto 111008`. Isso
não é detalhe da conversa — é uma peça que precisa existir no backend e ser
usada por todos os canais.

**Decisão: um endpoint de busca tolerante**, `GET /produtos/buscar?termo=`,
que normaliza acento e caixa, casa por palavra parcial e devolve os candidatos
ordenados por relevância. O mesmo endpoint serve o Lançador da tela (que hoje
usa `<select>` e ficaria melhor com busca), o bot e um futuro coletor.

Duas regras que a busca precisa respeitar:

- **Escopo do inventário.** Contando o inventário de Hortifruti, `"cerveja"`
  não deve nem aparecer como opção — o item está fora do escopo e seria
  recusado depois. Filtrar antes de oferecer evita a frustração.
- **Ordenar por probabilidade.** Item já contado neste inventário vai para o
  fim; item do escopo atual vem primeiro. Quem digita "batata" na contagem de
  Hortifruti quase nunca quer "Batata palha 800g" da Mercearia.

### 3.6 Como o bot se autentica na API — token de canal

Decidido que o bot é cliente HTTP (3.1), falta a peça que faltava no primeiro
rascunho: **com qual credencial ele chama a API?**

Três caminhos foram considerados:

| Caminho | Problema |
|---|---|
| Token de serviço + cabeçalho "atuar como usuário X" | cria uma porta de personificação: quem roubar o token do bot vira qualquer pessoa |
| Guardar login e senha do usuário no bot | senha em texto no servidor do bot; e volta a trafegar credencial |
| **Token de longa duração emitido no pareamento** | nenhum dos dois — e ganha uma propriedade a mais |

**Decisão: o pareamento emite um JWT de longa duração para aquele usuário**,
guardado só pelo processo do bot, com uma reivindicação a mais no payload:

```json
{ "sub": "12", "canal": "TELEGRAM", "exp": ... }
```

O `canal` é o detalhe que vale a decisão. Com ele, a regra "estas três ações
não existem no bot" (seção 3.4) deixa de ser disciplina do código do bot e
vira **verificação no backend**: finalizar inventário, cancelar e definir meta
recusam qualquer token com `canal = TELEGRAM`, venha de onde vier.

Regra que a experiência deste projeto já ensinou: controle que depende de o
cliente se comportar bem não é controle. Se amanhã alguém escrever um segundo
bot, ou um script, a fronteira continua de pé.

Desvincular o Telegram na tela invalida o token — o `chat_id` deixa de existir
no usuário e a checagem de vínculo passa a falhar antes do token ser sequer
lido.

### 3.7 Idempotência não é opcional

O Telegram **reentrega** updates que o servidor não confirmou. Sem proteção, uma queda de rede no momento errado vira contagem duplicada — e contagem duplicada estraga o inventário inteiro em silêncio.

**Decisão:** gravar `update_id` processado numa tabela e ignorar repetição. É barato e evita a classe inteira de erro.

---

## 4. O desenho da conversa

Esta é a parte que decide se o bot vai ser usado ou abandonado.

### 4.1 A premissa que muda tudo: quem conta não sabe código

O desenho por código está errado, e vale dizer por quê antes de descrever o certo.

Quem faz a contagem é o auxiliar de cozinha, o estoquista, o ajudante. Essa pessoa sabe **"batata doce, cinco quilos"**. Ela nunca vai saber que batata doce é 111008 — e obrigá-la a decorar 42 códigos, ou a consultar uma lista impressa a cada item, é reintroduzir exatamente o atrito que o bot veio eliminar.

O código existe para o *sistema*, não para a pessoa. **O bot tem que oferecer as opções.**

Isso reorganiza o desenho inteiro em torno de três modos, do mais guiado ao mais livre.

---

#### A regra vale para todo identificador, não só para o produto

O mesmo raciocínio que elimina o código do produto elimina o número do
inventário, o número da requisição e o nome do fornecedor. **Nenhum comando
começa perguntando um número.** Ele começa mostrando o que existe.

```
Operador:  /contar
Bot:       Inventários prontos para contagem · Josefina
           [nº 03 · Hortifruti · 42 itens]
           [nº 04 · Bar · 8 itens]

Operador:  /requisicao
Bot:       [REQ-07 · aberta hoje, 4 itens]
           [+ abrir nova requisição]
```

Três decisões dentro disso:

**Uma opção só não vira pergunta.** Se existe um único inventário aceitando
contagem, `/contar` entra nele direto e avisa qual é — "Inventário 03 ·
Hortifruti · vou passar item por item". Fazer alguém escolher entre uma coisa
é um toque cobrado por nada, e é o caso mais comum na operação real.

**A lista mostra só o que aceita a ação.** Inventário `ABERTO` não recebe
contagem — a fotografia do estoque precisa existir antes —, então não aparece
em `/contar`. Oferecer para depois recusar é o pior dos dois mundos.

**Lista vazia é a resposta mais importante.** É o momento em que a pessoa está
na câmara fria com a prancheta e nada acontece. Não pode ser "nenhum
resultado":

```
Operador:  /contar
Bot:       Nenhum inventário congelado na Josefina.
           O inventário nº 05 está aberto, mas ainda não foi congelado —
           é o gerente quem faz isso. Avise a Marina.
```

Diz o que há, por que não serve, e quem resolve. É a mesma escolha da tela
Equipe, onde o motivo do bloqueio aparece no lugar do botão morto.

**No backend, isso precisa de um ajuste pequeno e importante.**
`GET /inventario/sessoes?status=` aceita **um** status. A pergunta do bot é
"o que aceita contagem", que hoje são dois — `CONGELADO` e `EM_CONTAGEM`.
Filtrar por status obrigaria o bot a saber quais são, e essa lista já existe
no backend como `STATUS_ACEITA_CONTAGEM`. Duas cópias, e a segunda envelhece
no dia em que surgir um status novo.

Então o filtro é pelo **significado**, não pelo estado:

```
GET /inventario/sessoes?aceita_contagem=true
GET /requisicoes?aceita_itens=true          # hoje: INICIADA
```

O bot pergunta o que quer fazer; o backend responde o que serve. Mesma
disciplina do `/ajuda` (4.12) e da hierarquia: uma fonte por pergunta.

---

### 4.2 Modo guiado — o padrão, e o mínimo teórico de esforço

O inventário tem escopo definido: 42 itens de Hortifruti. É uma lista **conhecida e curta**. Então o bot conduz, e a pessoa só responde o número.

```
Operador:  /contar
Bot:       [Inventário 03 · Hortifruti]  [Inventário 04 · Bar]
                                              ← botões, sem digitar número

Operador:  [Inventário 03 · Hortifruti]
Bot:       Inventário 03 · Josefina · Hortifruti · 42 itens
           Vou passar item por item. Responda só a quantidade.
           "pular" salta · "faltam" mostra o que resta · /sair encerra

           ┌──────────────────────────┐
           │  1/42                    │
           │  Batata Doce             │
           │  em quilos (Kg)          │
           └──────────────────────────┘
                          [pular]  [não tem]

Operador:  12,5
Bot:       ✓ Batata Doce · 12,5 Kg

           ┌──────────────────────────┐
           │  2/42                    │
           │  Gengibre                │
           │  em quilos (Kg)          │
           └──────────────────────────┘

Operador:  8
Bot:       ✓ Gengibre · 8 Kg

           ┌──────────────────────────┐
           │  3/42                    │
           │  Cebola                  │
           │  em quilos (Kg)          │
           └──────────────────────────┘
```

**A pessoa digita apenas `12,5`.** Não há código, não há nome, não há comando. É menos esforço até do que anotar na prancheta — e o registro já entra no sistema.

Quatro detalhes que sustentam isso:

1. **A unidade de medida vem escrita.** "em quilos (Kg)" evita o erro mais caro do inventário: contar caixa onde o sistema espera quilo. É a mesma preocupação da coluna `Un.` que colocamos no Motor de CMV.
2. **Botão "não tem"** registra zero. Item zerado é informação — sem ele, o sistema não sabe se acabou ou se ninguém contou.
3. **Botão "pular"** manda o item para o fim da fila. A pessoa conta na ordem da prateleira, não na ordem do sistema.
4. **Sem mensagem de erro por digitar errado.** Se vier algo que não é número, o bot repete o item com um lembrete curto.

### 4.3 Modo busca — quando a pessoa está olhando para a cebola

O modo guiado dita a ordem, mas a realidade não obedece: a pessoa está na frente da prateleira das cebolas e quer lançar aquilo agora.

Então **a qualquer momento ela pode simplesmente escrever o nome**:

```
Operador:  cebola
Bot:       Três itens com "cebola":
           [Cebola Kg]  [Cebola roxa kg]  [Cebolinha]

Operador:  [Cebola Kg]
Bot:       Cebola · em quilos (Kg) — quanto tem?

Operador:  14
Bot:       ✓ Cebola · 14 Kg
           Voltando de onde parei: 3/42 · Cebola roxa
```

E quando o nome é único, resolve numa mensagem só:

```
Operador:  gengibre 8
Bot:       ✓ Gengibre · 8 Kg
```

**A busca precisa ser tolerante**, porque o teclado do celular e a grafia real não colaboram:

| A pessoa escreve | Tem que achar |
|---|---|
| `mucarela`, `mussarela`, `muçarela` | Muçarela fatiada |
| `BATATA`, `batata` | as três batatas |
| `agriao`, `agrião` | Agrião und |
| `bata doce` | Batata Doce |

Isso é normalização de acento e caixa, mais casamento parcial por palavra. Barato de implementar e decisivo para a adoção — uma busca que exige grafia exata é uma busca que ninguém usa duas vezes.

### 4.4 Modo lista — para quem prefere tocar a digitar

Nem todo mundo quer escrever. O terceiro caminho é o teclado de botões, agrupado por família:

```
Operador:  /itens
Bot:       Escolha a família:
           [Hortifruti (42)]  [Carnes (12)]  [Bar (8)]

Operador:  [Hortifruti (42)]
Bot:       Hortifruti · página 1 de 6
           [Abacaxi]      [Acelga]
           [Agrião]       [Alface Crespa]
           [Alface Roxa]  [Alecrim]
           [Banana Nanica][Banana Terra]
                    [ próxima → ]

Operador:  [Agrião]
Bot:       Agrião · em unidades (Und) — quanto tem?
```

Oito por página é o que cabe na tela do celular sem rolagem.

### 4.5 O código continua existindo — como atalho, não como exigência

Quem já decorou os cinco itens que mais conta, ou quem está com a **folha de contagem cega impressa na mão** (que traz código e descrição), pode digitar `111008 12,5` e economizar um toque.

A diferença é essencial: **o código é atalho para quem quer, não pedágio para quem precisa.**

### 4.6 Resumo dos quatro caminhos

| Caminho | Quem usa | Esforço por item |
|---|---|---|
| **Guiado** (padrão) | quem conta o inventário inteiro | digitar o número |
| **Busca por nome** | quem conta fora de ordem | nome + toque + número |
| **Lista de botões** | quem prefere não digitar | dois toques + número |
| **Código** | quem tem a folha impressa | código + número |

Os quatro convivem no mesmo modo de contagem. A pessoa não escolhe um — ela usa o que for natural naquele momento, e o bot entende os quatro.

### 4.7 Correção, progresso e conferência

```
Operador:  /faltam
Bot:       38 de 42 itens sem contagem:
           Cebola · Couve Flor · Chuchu · Laranja Pera · Limão …
           [continuar de onde parei]

Operador:  /desfazer
Bot:       Desfeito: Gengibre voltou a "não contado".

Operador:  /resumo
Bot:       Inventário 03 · Josefina · Hortifruti
           4 de 42 contados · 38 faltando
           Última contagem: Cebola 14 Kg, há 2 minutos
```

Duas garantias que valem para os quatro caminhos:

- **O bot sempre confirma com o nome.** É a checagem de que a pessoa lançou no item certo — vale ainda mais no modo código, onde 111008 e 111080 são visualmente parecidos.
- **Recontar sobrescreve.** Quem conferiu de novo e achou outro número simplesmente manda de novo. É o que `registrar_contagem` já faz.

### 4.8 Perda — o mesmo princípio

Perda é o dado que a operação mais deixa de registrar, porque exige parar e abrir o sistema. Aqui também não se pede código:

```
Operador:  /perda
Bot:       Qual item?  (escreva o nome ou toque)
           [Batata Doce] [Muçarela] [Tomate] [Alface]
                              ↑ os mais perdidos nos últimos 30 dias

Operador:  batata doce
Bot:       Batata Doce · em quilos (Kg) — quanto foi perdido?

Operador:  3
Bot:       Por quê?
           [Vencimento] [Quebra] [Deterioração]
           [Erro de produção] [Furto] [Consumo interno]

Operador:  [Vencimento]
Bot:       ✓ Perda registrada · PER-0012
           Batata Doce · 3 Kg · R$ 31,44 · vencimento
           Saldo: 168,2 Kg → 165,2 Kg
```

Quem tem pressa faz numa linha: `/perda batata doce 3 validade`.

**Os botões de atalho são os itens mais perdidos nos últimos 30 dias** — na prática, três ou quatro itens respondem pela maioria das ocorrências, e deixá-los a um toque é o que faz a perda ser registrada em vez de esquecida.

O motivo continua obrigatório: é ele que transforma perda em informação útil. Sem motivo, "CMV subiu" e "jogamos fora R$ 4.000 de hortifruti vencido" viram o mesmo número.

### 4.9 Requisição

```
Operador:  /requisicao
Bot:       Requisição REQ-07 aberta e iniciada · Josefina
           Escreva o nome do item e a quantidade.
           /atender quando terminar.

Operador:  batata doce 20
Bot:       ✓ Batata Doce · 20 Kg   (saldo hoje: 168,2 → 148,2 ao atender)

Operador:  muçarela 5
Bot:       ✓ Muçarela fatiada · 5 Kg

Operador:  /atender
Bot:       ✓ REQ-07 atendida · 4 itens · R$ 482,10 baixados do estoque.
```

Mesma busca tolerante da contagem: nome ambíguo abre botões, nome único resolve
direto. E o bot mostra o saldo — pedir 20 kg de um item que tem 12 é o tipo de
erro que só aparece na hora de atender, quando já é tarde.

### 4.10 Compra

O caminho digitado existe, mas o interessante é a foto — seção 6.

```
Operador:  /compra
Bot:       Fornecedor? (lista com os 8 mais usados + "outro")
Operador:  [ASSAI]
Bot:       Nº da nota?
Operador:  1500
Bot:       Mande  nome quantidade custo  a cada item. /fechar para encerrar.
Operador:  batata doce 50 10,48
Bot:       ✓ Batata Doce · 50 Kg × R$ 10,48 = R$ 524,00
```

### 4.11 Consulta

```
/estoque batata     →  Batata Doce 165,2 Kg · R$ 1.731,50
                       Batata Baroa 34 Kg · R$ 315,79
                       Batata Inglesa 12 Kg · R$ 140,64
/cmv                →  Agosto/2026 · Josefina
                       CMV 28,4% · meta 29% ✓
                       INV-1002 (03/08) → INV-1003 (10/08)
/painel             →  resumo do dia + pendências
/inventarios        →  os cinco últimos, com status
```

### 4.12 `/ajuda` — a lista que não pode mentir

Um bot sem ajuda é um bot com manual: a pessoa pergunta ao colega qual é o
comando, o colega lembra errado, e o canal ganha fama de complicado. `/ajuda`
existe para que ninguém precise decorar nada.

Mas há uma armadilha específica aqui, e ela é a razão desta seção existir.

**Ajuda escrita à mão envelhece em silêncio.** O jeito óbvio — um texto por
papel, guardado no código do bot — cria uma segunda descrição das permissões,
paralela à que autoriza de verdade. No dia em que `congelar` subir para
Gerente, quem lembrar de mudar a rota vai esquecer do texto. E o resultado é
pior do que não ter ajuda: o operador lê que pode congelar, tenta, e leva um
403. A ajuda passa a ensinar o errado com toda a autoridade de ter vindo do
sistema.

É exatamente o defeito que `servicos/hierarquia.py` veio corrigir quando a
pergunta "posso dar este papel?" tinha duas respostas. A solução aqui é a
mesma:

**Um registro só, que autoriza e explica.**

```python
# servicos/comandos.py
COMANDOS = [
    Comando("/contar",     "Lançar contagem do inventário",
            papel_minimo=OPERADOR, exemplo="/contar"),
    Comando("/perda",      "Registrar perda com motivo",
            papel_minimo=OPERADOR, exemplo="/perda batata doce 3 validade"),
    Comando("/requisicao", "Pedir itens para a produção",
            papel_minimo=OPERADOR),
    Comando("/estoque",    "Consultar saldo de um item",
            papel_minimo=OPERADOR),
    Comando("/congelar",   "Fotografar o estoque e liberar a contagem",
            papel_minimo=GERENTE),
    Comando("/atender",    "Baixar do estoque os itens da requisição",
            papel_minimo=GERENTE),
    Comando("/cmv",        "CMV do período contra a meta",
            papel_minimo=GERENTE),
    Comando("/faturamento", "Lançar o faturamento do período",
            papel_minimo=DIRETOR),
]
```

O despachante do bot recusa o que não estiver liberado **neste mesmo
registro**. Então a ajuda não descreve a regra: ela *é* a regra, exibida.
Divergir deixa de ser possível.

Serve por `GET /api/telegram/comandos`, no mesmo espírito de
`GET /api/usuarios/poderes` — que já existe e é de onde a tela Equipe se
monta. Um lugar para perguntar "o que esta pessoa pode?", três canais
perguntando.

**O que o operador vê:**

```
Operador:  /ajuda
Bot:       Você é Operador · Josefina

           LANÇAR
           /contar       contagem do inventário
           /perda        registrar perda        ex: /perda batata doce 3 validade
           /requisicao   pedir itens para a produção

           CONSULTAR
           /estoque      saldo de um item       ex: /estoque batata

           DURANTE A CONTAGEM
           faltam · pular · não tem · /desfazer · /resumo

           /unidade  trocar de loja      /sair  encerrar

           Congelar inventário, atender requisição e ver CMV são do
           gerente para cima.
```

**O que o gerente vê:** as mesmas três primeiras seções, mais `/congelar`,
`/atender`, `/cmv` e `/painel`. Nenhum comando aparece para quem vai levar um
403 ao tentar.

Quatro decisões dentro dessa tela:

1. **Agrupado por verbo, não por papel.** "Lançar" e "Consultar" é como a
   pessoa pensa. "Comandos de Operador" seria como o sistema pensa.

2. **A última linha diz o que falta — e é uma linha, não uma segunda lista.**
   O princípio é o mesmo da tela Equipe: botão morto não ensina, mas o motivo
   ensina. Quem lê sabe a quem pedir em vez de concluir que o sistema está
   quebrado. Duas listas do mesmo tamanho, porém, transformariam a ajuda numa
   rolagem — e a metade útil ficaria no fim.

3. **Exemplo real onde o formato não é óbvio.** `/perda batata doce 3 validade`
   ensina mais que qualquer descrição da sintaxe. Comandos sem argumento não
   levam exemplo: ruído.

4. **A ajuda muda conforme o momento.** Dentro de uma contagem, `/ajuda`
   abre pelo bloco "durante a contagem" — é o que a pessoa procura estando
   ali. A `SessaoTelegram` já guarda o `modo`; é ele que decide a ordem.

E `/start`, `/ajuda` e qualquer coisa que o bot não entenda caem no mesmo
lugar. Quem digita `/contagem` em vez de `/contar` recebe a lista, não um
"comando inválido" — a correção custa o mesmo e o desamparo, não.

---

### 4.13 Onde o Mini App entra — e onde não entra

A pesquisa confirma o que a prática sugere: **bot para conversa e comando; Mini App para interface rica**. O padrão recomendado é híbrido — bot como porta de entrada, Mini App para o que precisa de tela.

**Decisão:**

- **Lançar continua no chat.** Um Mini App para digitar código+quantidade seria mais lento que a linha de texto: abrir o app, esperar carregar, tocar no campo. O chat vence por larga margem no caso de maior volume.
- **Ver vira Mini App.** Gráfico de CMV, curva ABC e painel não cabem em texto. O Mini App reaproveita o frontend que já existe, autenticado pelo `initData` do Telegram.

Ou seja: o Mini App é a **fase 5**, não a fase 1. Entregar o lançamento primeiro é o que resolve a dor real.

---

## 5. Modelo de dados — o que precisa ser criado

Pouca coisa, e nada que mexa no que já existe:

```python
# Vínculo entre pessoa e conta de Telegram
Usuario.telegram_chat_id      # BigInteger, único, nulo
Usuario.telegram_username     # String, só para exibir na tela (muda)
Usuario.telegram_vinculado_em # DateTime

class CodigoPareamento:       # código de 6 dígitos, 10 min de validade
    usuario_id, codigo, expira_em, usado_em

class SessaoTelegram:         # o "onde eu estava" de cada chat
    chat_id, usuario_id, unidade_id
    modo                      # CONTAGEM | REQUISICAO | COMPRA | LIVRE
    contexto                  # json: sessao_inventario_id, requisicao_id…
    ultimo_lancamento         # para o /desfazer
    atualizado_em

class UpdateProcessado:       # idempotência
    update_id, processado_em

class SinonimoProduto:        # "como esta pessoa/nota chama este produto"
    produto_id
    termo                     # "bata doce", "TOMATE ITAL CX 20KG"
    fornecedor_id             # nulo = sinônimo geral, não de um fornecedor
    fator_conversao           # 20 quando a nota vem em caixa de 20 Kg
    usos                      # quantas vezes confirmado — ordena a busca
```

Duas observações:

- `UpdateProcessado` cresce sem parar. Limpar o que tem mais de 7 dias resolve — o Telegram não reentrega nada mais velho que isso.
- `SinonimoProduto` serve a dois propósitos que parecem diferentes e são o mesmo: aprender que **a pessoa** chama batata doce de "bata doce", e que **a nota do ASSAI** chama de "TOMATE ITAL CX 20KG". Nos dois casos é um apelido que aponta para um produto. Com `fornecedor_id` nulo vale para a busca do bot; preenchido, vale para a importação de nota.

---

## 6. Foto da nota fiscal — o estudo separado

Você levantou isso há algumas semanas. O estudo confirma três caminhos, e a diferença entre eles é grande.

### Caminho 1 · QR Code da DANFE → XML na SEFAZ ★ recomendado

Toda nota fiscal impressa traz a chave de acesso de 44 dígitos em QR Code. Ler o QR da foto e buscar o XML na SEFAZ devolve **os itens exatos**: descrição, quantidade, unidade, valor unitário, CNPJ do emitente.

- **Precisão:** total. Não é interpretação, é o documento oficial.
- **Depende de:** certificado digital A1 (já previsto no plano original, e a estrutura `CertificadoDigital` já existe no modelo).
- **Falha quando:** o QR está amassado, rasgado ou fora de foco. Nesse caso o operador digita a chave.

### Caminho 2 · XML direto

Se o fornecedor manda o XML por e-mail, dispensa a foto inteira. É o caminho perfeito, e vale negociar com os fornecedores maiores.

### Caminho 3 · OCR da foto — fallback

Funciona, mas erra em nota amassada, borrada ou em papel térmico desbotado. Serve como último recurso, **sempre com tela de conferência antes de gravar**.

### O gargalo real não é ler a nota — é o de-para

`"TOMATE ITAL CX 20KG"` na nota precisa virar `100002 — TOMATE`. Isso não sai de OCR nem de XML: é conhecimento da operação.

**Solução:** a mesma `SinonimoProduto` da busca do bot, agora com `fornecedor_id` preenchido. Ela **aprende**.

```
Primeira nota do ASSAI:
  Bot: "TOMATE ITAL CX 20KG" — qual produto?
       [Tomate] [Tomate Cereja] [buscar…]
  Operador: [Tomate]
  → grava: ASSAI + "TOMATE ITAL CX 20KG" = produto 100002, fator 20

Notas seguintes do ASSAI: acerta sozinho.
```

O `fator` resolve o segundo gargalo, que já discutimos: a nota vem em caixa, o inventário conta em quilo. Guardar o fator de conversão **por fornecedor e por descrição** é o que faz 1 CX virar 20 Kg automaticamente.

**Sem esse aprendizado, importar nota por foto vira digitação com passos extras.** Com ele, a segunda nota de cada fornecedor já entra sozinha.

---

## 7. Fases de execução

| # | Entrega | Verificação |
|---|---|---|
| 1 | Vínculo de identidade: modelo, código de pareamento, `/vincular`, token de canal, tela de vínculo em Usuários | Chat não vinculado não faz nada; vínculo revogado para de valer na hora; token com `canal=TELEGRAM` é recusado ao finalizar inventário |
| 2 | Esqueleto do bot: polling, sessão de chat, idempotência, `/unidade`, **registro único de comandos + `/ajuda`** | Update reentregue não duplica lançamento; a ajuda do operador não lista nenhum comando que ele leve 403 ao usar — verificado papel a papel, contra o registro |
| 3 | **Busca tolerante** — `GET /produtos/buscar` e `SinonimoProduto`, sem acento, sem caixa, parcial, com escopo; **e os filtros por significado** (`aceita_contagem`, `aceita_itens`) que alimentam as listas de escolha | "mucarela", "MUÇARELA" e "bata doce" acham o produto certo; apelido confirmado é lembrado |
| 4 | **Contagem** — modo guiado (item a item), busca por nome, lista de botões, código como atalho | A pessoa conta 42 itens digitando só números; contagem aparece no relatório com origem TELEGRAM |
| 5 | **Perda e requisição** — sempre por nome, motivo em botões | Perda sem motivo é recusada; requisição baixa o estoque igual à tela |
| 6 | **Consulta** — `/estoque`, `/cmv`, `/painel` | Números idênticos aos da tela, no mesmo período |
| 7 | **Compra digitada** + tabela de sinônimos por fornecedor | Segunda nota do mesmo fornecedor reconhece as descrições |
| 8 | **Nota por foto** — QR → SEFAZ, com conferência antes de gravar | Nota real importada bate item a item com a nota impressa |
| 9 | **Mini App** de consulta (painel, CMV, curva ABC) | Mesmos números da web, autenticado por `initData` |

As fases 1 a 4 já entregam valor sozinhas: contagem é a atividade de maior volume e a que mais sofre com o atrito da tela. A busca tolerante vem antes da contagem porque é ela que torna possível conversar por nome — sem ela, o bot volta a exigir código.

---

## 8. E o PostgreSQL? — a pergunta da ordem

**Resposta curta: não, migrar para PostgreSQL não é pré-requisito do bot.**
E a razão é a decisão 3.1.

### Por que não bloqueia

O medo legítimo com SQLite é o **escritor único**: dois processos gravando ao
mesmo tempo produzem "database is locked". Se o bot escrevesse direto no
banco, seria um segundo escritor e a migração viraria pré-requisito.

Mas o bot **chama a API**. Verificando o que existe hoje:

```
entrypoint.py     uvicorn.run("main:app", ...)   ← um worker, um processo
database.py       SQLite, journal_mode=delete
banco             228 KB, 231 movimentos
```

Continua havendo **um escritor só** — o processo do FastAPI. O bot entra na
fila do mesmo jeito que o navegador. O volume, aliás, não chega perto de
incomodar: um inventário inteiro são 42 escritas espaçadas por segundos.

### Dois ajustes que valem agora, e custam pouco

1. **Ligar o WAL** (`PRAGMA journal_mode=WAL`). Hoje está em `delete`. Com WAL,
   leitura e escrita deixam de se bloquear — o painel abrindo enquanto alguém
   conta no Telegram fica mais suave. É uma linha na inicialização.
2. **Subir o `busy_timeout`** de 5 s para 15 s. Se houver disputa, espera em
   vez de falhar.

### Quando o PostgreSQL passa a ser necessário

| Gatilho | Por quê |
|---|---|
| Mais de um worker do uvicorn | aí sim viram vários escritores |
| Acesso de fora do servidor (tablet na cozinha, celular fora da rede) | expõe o banco a concorrência real |
| Terceira, quarta unidade com uso simultâneo | volume de escrita cruza o confortável |
| Vender para um segundo cliente | multiempresa em arquivo único é frágil |

Nenhum desses gatilhos é o bot.

### Três incompatibilidades que a migração vai encontrar

Levantei conferindo o código — vale registrar agora para não descobrir no dia:

**1. `BOOLEAN DEFAULT 0` não existe no PostgreSQL.** Duas migrações usam:

```python
"geral": "BOOLEAN DEFAULT 0 NOT NULL"                          # migracoes.py:60
"ALTER TABLE usuarios ADD COLUMN acesso_regional BOOLEAN DEFAULT 0 NOT NULL"
```

No PostgreSQL precisa ser `DEFAULT FALSE`. Falha na hora, é fácil de achar.

**2. Enums viram tipo nativo.** SQLAlchemy cria `ENUM` de verdade no
PostgreSQL. Acrescentar um valor — como fizemos com `DIRETOR` e `PERDA` —
deixa de ser trivial e passa a exigir `ALTER TYPE ... ADD VALUE`. Alternativa:
declarar os enums como `String` com validação na aplicação. Vale decidir isso
**antes** de migrar, porque depois cada valor novo custa uma migração.

**3. `ilike` não resolve acento em nenhum dos dois.** Isso encosta na fase 3:
`"mucarela"` não acha `"Muçarela"` nem no SQLite nem no PostgreSQL sem ajuda.
No PostgreSQL a solução é elegante — extensões `unaccent` e `pg_trgm` dão
busca sem acento e por similaridade de graça. No SQLite, a normalização é
feita em Python.

Com 244 produtos, normalizar em Python é instantâneo — carrega tudo, compara,
devolve. **Então a busca não precisa esperar o PostgreSQL**, mas quando ele
chegar, vale reescrever a busca para usar `unaccent` e `pg_trgm`: aí ela passa
a tolerar erro de digitação de verdade ("gengibri" achando "Gengibre"), o que a
comparação em Python não faz sem complicar.

### Recomendação de ordem

```
agora        →  WAL + busy_timeout       (uma linha, hoje)
fases 1–6    →  bot sobre SQLite         (funciona, testado, sem risco novo)
depois       →  PostgreSQL               (com os três ajustes acima)
então        →  busca com unaccent/pg_trgm
```

Migrar antes do bot atrasaria o que resolve dor real para eliminar um risco
que a arquitetura já eliminou.

---

## 9. Riscos, e o que fazer com cada um

**A mensagem passa por servidor de terceiro.** Custo e estoque não são dado pessoal, mas são dado estratégico. Mitigação: o bot nunca envia lista completa de custos por iniciativa própria; responde ao que foi perguntado. Vale registrar a decisão por escrito com a diretoria.

**Celular perdido = acesso ao lançamento.** Mitigação em três camadas: escopo herdado (só as unidades da pessoa), ações destrutivas fora do bot, e desvinculação imediata pela tela.

**Reentrega de update duplica lançamento.** Resolvido pela tabela de idempotência (seção 3.7). É o risco mais provável e o mais silencioso — por isso entra já na fase 2.

**Contagem sem sinal na câmara fria.** Aqui o Telegram é *melhor* que uma tela web: ele enfileira a mensagem e envia quando o sinal volta. Um formulário web perderia o preenchimento. Ponto genuinamente a favor do canal.

**Item errado escolhido.** No modo por nome o risco muda de natureza: em vez de digitar um código errado, a pessoa toca no botão errado — "Batata Doce" quando queria "Batata Baroa". Mitigação: o bot confirma com o nome completo e a unidade, `/desfazer` reverte, e a lista de candidatos vem ordenada por probabilidade (itens do escopo atual primeiro, já contados por último).

**Produto sem nome claro no cadastro.** A busca só é boa se o cadastro for. Nomes como "Nata Frimesa 300G" ou "Massa de Pastel Especial kg (500G)" confundem quem procura. Não é problema do bot — é do cadastro, e vale uma limpeza antes da fase 4. O bot só torna o problema visível.

**Dependência de biblioteca.** `python-telegram-bot` é a opção madura e mantida. Fica isolada no processo do bot — se ela quebrar numa atualização, o sistema web continua de pé.

---

## 10. O que este bot muda na prática

Hoje, registrar uma perda de 3 kg de batata custa: parar, achar um computador, entrar no sistema, escolher a unidade, abrir o Lançador, achar a aba, digitar. O custo é alto o bastante para que a perda simplesmente **não seja registrada** — e o CMV suba sem explicação.

Depois:

```
/perda  →  [Batata Doce]  →  3  →  [Vencimento]
```

Três toques e um número, de dentro da câmara fria. Sem código, sem decorar nada.

O mesmo vale para a contagem. O bot pergunta "Batata Doce, em quilos — quanto tem?" e a pessoa responde `12,5`. Sem prancheta, sem transcrever depois, e sem a digitação em lote no dia seguinte — que é onde os erros nascem.

E é por isso que o desenho por código estava errado: ele funcionaria para quem construiu o sistema, e falharia para quem precisa usá-lo.

**A integração não adiciona uma funcionalidade. Ela remove o atrito que faz os dados não existirem.**

---

## Fontes consultadas

- [Bot API changelog — core.telegram.org](https://core.telegram.org/bots/api-changelog)
- [Telegram Bot API — core.telegram.org](https://core.telegram.org/bots/api)
- [Telegram Bot API Rate Limits Explained (2026) — Bot Name Finder](https://botnamefinder.com/blog/telegram-bot-rate-limits-explained)
- [Telegram Bot vs Telegram Mini App: The Difference and What to Choose in 2026 — Redigix](https://www.redigix.com/en/blog/telegram-bot-vs-mini-app-2026)
- [Telegram mini apps vs. Telegram bots: which should you choose? — Innowise](https://innowise.com/blog/telegram-bot-vs-mini-app/)
