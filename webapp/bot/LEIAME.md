# O bot do Telegram — como ligar

O código está pronto. Falta o que só você pode fazer: criar o bot no
Telegram e colar dois valores no `.env`.

---

## 1. Criar o bot (2 minutos, no seu Telegram)

Abra uma conversa com **@BotFather** e mande:

```
/newbot
```

Ele pergunta duas coisas:

| Pergunta | O que responder |
|---|---|
| **Name** | `Solo CMV Josefina` — é o que aparece no topo da conversa |
| **Username** | precisa terminar em `bot` e ser único. Ex.: `solo_cmv_josefina_bot` |

No fim ele devolve uma linha assim:

```
Use this token to access the HTTP API:
1234567890:AAF-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
```

**Esse token é uma senha.** Quem tiver ele controla o bot. Não mande por
WhatsApp, não cole em chat, não comite. Ele vai direto para o `.env` do
servidor, e só.

Se vazar: `/revoke` no @BotFather gera outro e mata o antigo na hora.

### Enquanto está no @BotFather, vale fazer mais dois ajustes

```
/setdescription   → Lançamento de inventário, perdas e requisições da Rede Josefina.
/setprivacy       → Enable
```

O `setprivacy` importa se um dia o bot entrar num grupo: com privacidade
ligada, ele só lê mensagens dirigidas a ele. Sem isso, ele receberia toda a
conversa do grupo — que não é dele e não serve para nada.

---

## 2. Os dois valores no `.env`

No servidor, em `/var/www/solo-cmv/webapp/.env`:

```bash
BOT_TELEGRAM_TOKEN=1234567890:AAF-xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
BOT_SEGREDO=<gere abaixo>
```

Para gerar o segundo:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**O que cada um é:**

O `BOT_TELEGRAM_TOKEN` é como o bot fala com o Telegram.

O `BOT_SEGREDO` é como o processo do bot se identifica na nossa API. Ele
existe para o bot **não guardar credencial de ninguém**: em vez de manter os
tokens dos usuários num arquivo, ele apresenta esse segredo junto do
`chat_id` e recebe um token que morre naquele pedido.

O raciocínio inteiro está em `backend/config.py`, na seção BOT_SEGREDO —
inclusive o que isso custa, dito em voz alta.

---

## 3. Subir

```bash
cd /var/www/solo-cmv/webapp
docker compose up -d --build bot
docker compose logs -f bot
```

Deve aparecer:

```
INFO bot: conectado como @solo_cmv_josefina_bot
```

Se não aparecer, o log diz o motivo e o que fazer. O bot **não sobe pela
metade** de propósito: um bot no ar que não responde é pior que um que não
subiu, porque ninguém vai olhar o log de um container que está "rodando".

---

## 4. Cada pessoa conecta o próprio Telegram

Uma vez, por pessoa:

1. entra no sistema pelo navegador
2. **Perfil › Vincular Telegram** → aparece um código de 6 dígitos
3. no Telegram, manda para o bot: `/vincular 123456`

O código vale **10 minutos** e serve **uma vez**.

**Senha nunca passa pelo chat** — nem para o bot. Mensagem de Telegram fica
no aparelho de quem mandou, no de quem receber um encaminhamento, e nos
servidores do Telegram. Três lugares que não controlamos.

### Celular perdido

Qualquer gerente para cima desvincula pela tela de Equipe, e o acesso morre
**no pedido seguinte** — não quando o token vencer.

---

## O que o bot faz, e o que não faz

Ele atua **como a pessoa vinculada**: mesmas lojas, mesmo papel, mesmas
regras. Um operador que mandar contagem para uma loja que não é dele recebe
o mesmo 403 que receberia no navegador.

Cada um vê o próprio menu com `/ajuda` — e a lista sai do mesmo registro que
autoriza, então ela não tem como listar algo que vai ser recusado.

**Três coisas não existem por aqui, e a recusa é do servidor:**

| Ação | Por quê |
|---|---|
| Finalizar inventário | aplica as contagens ao estoque real, e é irreversível |
| Cancelar inventário ou requisição | descarte de trabalho |
| Definir metas | ato de diretoria, com vigência |

Escrito só no código do bot, isso seria disciplina — bastaria um segundo bot
ou um script para a regra sumir. Está no backend: o token do canal carrega
`canal: TELEGRAM`, e essas rotas recusam esse canal venha de onde vier.

Um celular perdido e destravado não derruba um inventário.

---

## Contando pelo bot

```
Operador:  /contar
Bot:       Inventário 03 · 42 itens
           Vou passar item por item. Responda só a quantidade.

           1/42
           Batata Doce
           em Kg
                              [pular]  [não tem]
Operador:  12,5
Bot:       ✓ Batata Doce · 12,5 Kg
```

**A pessoa digita só o número.** Quatro caminhos convivem: o guiado acima,
o nome solto (`cebola`, ou `gengibre 8` de uma vez), os botões, e o código
para quem tem a folha de contagem impressa na mão.

Nenhum comando começa pedindo um número de inventário — o bot mostra o que
existe. E quando não há nada para contar, ele diz de quem depende:

```
Nenhum inventário congelado aqui ainda.
O inventário nº 05 está aberto, mas ainda não foi congelado — é o
gerente quem faz isso. Avise ele.
```
