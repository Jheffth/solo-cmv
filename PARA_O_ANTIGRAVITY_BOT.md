# Subir o bot do Telegram — Solo CMV

Três commits prontos e testados esperando push. O bot já existe no Telegram
(`@solo_cmv_josefina_bot`), criado e configurado. Falta pôr dois valores no
`.env` do servidor e subir.

**Ordem importa:** `.env` primeiro. A aplicação recusa subir com chave ruim,
e o serviço do bot recusa subir sem token — os dois de propósito. Melhor
descobrir antes do build.

---

## 1. Push

```bash
cd "C:\JEFFERSON\PROJETOS\SOLO CMV"
git log --oneline origin/main..HEAD    # confira o que está pendente
git push origin main
```

Devem estar pendentes (ou já no remoto, se você adiantou):

| commit | o que faz |
|---|---|
| `04b1419` | Régua de capacidades — fecha as leituras de dinheiro para o Operador |
| `473454f` | Bot fases 1–4 + limite de tentativas no código de pareamento |
| `aa4a345` | Os oito comandos que faltavam + o laço de aprendizado da busca |

---

## 2. As duas variáveis novas no `.env` do servidor

```bash
ssh root@<servidor>
cd /var/www/solo-cmv/webapp
```

Acrescente ao `.env` (**não** recrie o arquivo — o resto tem que ficar):

```
BOT_TELEGRAM_TOKEN=<peça ao Jefferson>
BOT_SEGREDO=<gere: python3 -c "import secrets; print(secrets.token_hex(32))">
```

**Os dois são diferentes e não se confundem.** O `BOT_TELEGRAM_TOKEN` vem do
@BotFather e identifica o bot para o Telegram — quem tiver ele controla o bot.
O `BOT_SEGREDO` é nosso: identifica o processo do bot para a nossa API, e é
o que impede alguém de fora chamar `/api/telegram/vincular` na marra.

O token está na conversa do Jefferson com o @BotFather. **Não peça por chat
aberto e não coloque em commit nenhum** — `.env` é gitignored e tem que
continuar sendo.

```bash
chmod 600 .env
grep -c BOT_ .env      # tem que dar 2 (ou 3, com BOT_LOG)
```

---

## 3. Subir

```bash
docker compose up -d --build
docker compose ps      # app, db, backup e bot devem estar Up
```

O `preparar_banco.py` roda antes dos workers e aplica as migrações sob
`pg_advisory_lock`. As tabelas novas — `codigos_pareamento`,
`sessoes_telegram`, `updates_telegram`, `tentativas_vinculo`,
`sinonimos_produto` — o SQLAlchemy cria sozinho (`create_all` cria tabela
nova; o que ele não faz é alterar tabela existente, e essas alterações já
estão em `migracoes.py`).

Se o container `bot` reiniciar em laço, olhe o log antes de mexer:

```bash
docker logs solo_cmv_bot --tail 30
```

Ele foi escrito para parar com mensagem clara em erro irrecuperável (token
inválido) e apenas esperar e tentar de novo em erro de rede.

---

## 4. Conferir — na ordem, cada passo depende do anterior

**a) O canal está configurado**

```bash
docker exec solo_cmv_app python -c \
  "from config import BOT_SEGREDO as s; print('segredo:', len(s), 'caracteres')"
```

Zero significa que o `.env` não chegou no container `app` — e aí o
pareamento devolve 503 com a mensagem dizendo exatamente isso.

**b) O bot responde**

No Telegram, abra `t.me/solo_cmv_josefina_bot` e mande `/start`.
Resposta esperada: o texto explicando que o Telegram ainda não está ligado a
nenhuma conta, com os três passos para conectar.

Se não responder nada, o `BOT_TELEGRAM_TOKEN` está errado ou o container não
subiu — veja o log do item 3.

**c) O vínculo funciona de ponta a ponta**

1. No sistema web, Perfil › Telegram › **Vincular Telegram** → aparece um
   código de 6 dígitos, válido por 10 minutos
2. No bot: `/vincular 123456`
3. Esperado: "Pronto, <nome>. Você está conectado como <papel>."

**d) A ajuda diz a verdade**

Mande `/ajuda` como Arquiteto e depois como um Operador de teste. A lista do
Operador **não pode** conter `/cmv`, `/faturamento`, `/congelar` nem
`/atender` — e mandar qualquer um deles tem que responder "não está no seu
acesso", nunca "não conheço".

Essa é a verificação que mais importa: a lista e a recusa saem do mesmo
registro (`servicos/comandos.py`), e se divergirem é sinal de que alguma
coisa está lendo de outro lugar.

**e) O lançamento chega mesmo**

Com um inventário congelado, mande `/contar` pelo bot e lance um item. Ele
tem que aparecer na tela do inventário, com origem `TELEGRAM`. Se aparecer no
bot e não na tela, é o único tipo de falha que o usuário não percebe sozinho.

---

## 5. Duas armadilhas específicas deste deploy

**Um token, um processo.** Se você mantiver dois ambientes no ar (o Contabo e
qualquer outro) com o mesmo `BOT_TELEGRAM_TOKEN`, os dois vão buscar updates
do mesmo bot e **brigar pelas mensagens** — metade some, sem erro em lugar
nenhum. Só um `.env` pode ter o token.

**O `.env` nunca vai para o git.** Nem "temporariamente para testar". O
repositório é público.

---

## O que mudou de comportamento no sistema web

Não é só o bot. O commit `04b1419` fecha permissões que estavam abertas, e
isso **muda o que o Operador vê hoje**:

- perde acesso a Faturamento, Motor de CMV, Relatórios e Metas
- o Estoque continua com o saldo, mas sem as colunas de R$
- a tela inicial dele deixa de ser o painel de CMV e vira a fila de trabalho
  (inventário esperando contagem, requisição aberta)
- abrir e congelar inventário passam a ser de Gerente para cima

Se algum operador usava o painel para alguma coisa, ele vai notar. Vale o
Jefferson avisar antes, não depois.

---

## Estado dos testes

28 suítes passando (13 jsdom + 15 backend), SQLite e PostgreSQL. As de
backend estão em `webapp/backend/teste_*.py`; a do bot roda o app de verdade
por `TestClient`, com o Telegram trocado por um dublê — nenhuma regra é
simulada, só o canal.
