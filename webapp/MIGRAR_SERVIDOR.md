# Levar o Solo CMV para outro servidor

Este documento existe para que a Rede Josefina possa sair de qualquer
provedor — inclusive do atual — sem depender de quem construiu o sistema.

**Você precisa de três coisas, e só delas:**

1. o repositório de código
2. um backup do banco
3. um servidor com Docker

Não há pasta de fotos para copiar, nem arquivo escondido em `/etc`. As fotos
de perfil moram no banco de propósito, justamente para que um dump seja o
estado completo do sistema.

---

## 1. Antes de qualquer coisa: pegue um backup e prove que ele presta

```bash
# no servidor atual
docker exec solo_cmv_backup python backup.py
docker exec solo_cmv_backup python backup.py --listar
```

O `backup.py` **restaura o arquivo num banco descartável e conta as linhas
tabela a tabela** antes de dá-lo por bom. Isso não é zelo excessivo: o
`pg_dump` termina com sucesso mesmo quando o disco enche no meio, e o
arquivo truncado só se revela inútil no dia em que alguém precisa dele.

Copie o arquivo para fora do servidor:

```bash
docker cp solo_cmv_backup:/backups/solo_cmv_AAAAMMDD_HHMMSS.dump .
```

> **Backup que fica no mesmo servidor é meio backup.** Se a máquina morrer,
> morrem os dois. Guarde uma cópia em outro lugar — o item 6 automatiza isso.

---

## 2. No servidor novo

```bash
# Docker
curl -fsSL https://get.docker.com | sh

# Código
git clone https://github.com/Jheffth/solo-cmv.git /var/www/solo-cmv
cd /var/www/solo-cmv/webapp
```

### O `.env`

Este arquivo **não** vem do backup, e não deveria vir: ele guarda a senha do
banco e a chave de assinatura, e as credenciais do servidor novo são outras.

```bash
cat > .env <<'FIM'
POSTGRES_USER=solo_cmv
POSTGRES_PASSWORD=<gere uma nova>
POSTGRES_DB=solo_cmv
DATABASE_URL=postgresql+psycopg://solo_cmv:<a mesma senha>@db:5432/solo_cmv
SECRET_KEY=<gere uma nova>
ACCESS_TOKEN_EXPIRE_MINUTES=480
AMBIENTE=prod
CORS_ORIGINS=https://<seu domínio>
WEB_CONCURRENCY=2
BACKUP_MANTER_DIAS=30
FIM
chmod 600 .env
```

Para gerar os dois segredos:

```bash
python3 -c "import secrets; print(secrets.token_hex(32))"
```

**A `SECRET_KEY` tem que ser nova.** Reaproveitar a do servidor antigo
carrega para o novo qualquer exposição que ela tenha tido. Trocá-la só
derruba as sessões abertas — todo mundo entra de novo e nada se perde.

A aplicação **recusa subir** com uma chave ausente, vazia, curta ou já
publicada. Se o container não subir, olhe o log: a mensagem diz exatamente
o que fazer.

---

## 3. Suba e restaure

```bash
docker compose up -d --build db      # só o banco, primeiro
sleep 10

docker compose run --rm -v $(pwd)/solo_cmv.dump:/tmp/b.dump app \
  python restaurar.py /tmp/b.dump             # simula
docker compose run --rm -v $(pwd)/solo_cmv.dump:/tmp/b.dump app \
  python restaurar.py /tmp/b.dump --aplicar   # grava

docker compose up -d --build         # tudo
```

O `restaurar.py` **simula por padrão**. E se o banco de destino já tiver
dados, ele para e lista o que seria apagado — "231 movimentos" faz pensar de
um jeito que "há dados" não faz. Só continua com `--forcar`.

---

## 4. Confira antes de apontar o domínio

```bash
curl -s http://localhost:8095/api/health
```

Depois entre no sistema e **abra o Painel de um mês que você conhece de cor.**
Um CMV diferente do esperado é o único teste que importa — os outros dizem
que o sistema subiu; este diz que os dados chegaram inteiros.

Referência da última migração conferida: CMV de agosto/2026 na Josefina =
**R$ 37.544,98**, estoque **R$ 12.155,06**, 244 produtos.

---

## 5. DNS e HTTPS

Aponte o domínio para o IP novo e ajuste o proxy reverso. Com Caddy:

```
seu-dominio.com.br {
    encode gzip zstd
    reverse_proxy 127.0.0.1:8095
}
```

O `encode gzip zstd` importa: o sistema já comprime as respostas da API,
mas o Caddy cobre o que ele serve direto.

**Só troque o DNS depois do item 4.** Domínio apontando para um sistema que
não subiu é o que transforma uma migração tranquila em uma noite ruim.

---

## 6. Cópia externa do backup

O serviço `backup` roda diariamente e guarda 30 dias no volume `backups`.
Isso protege contra erro humano e corrupção. **Não protege contra a máquina
morrer.**

Uma linha no cron do host resolve:

```bash
# diariamente às 4h, manda o backup mais recente para outro lugar
0 4 * * * docker cp solo_cmv_backup:/backups/$(docker exec solo_cmv_backup \
  ls -t /backups | head -1) /tmp/ && rclone copy /tmp/solo_cmv_*.dump remoto:backups/
```

Serve qualquer destino: outro VPS por `scp`, um bucket, um HD na loja. O que
não serve é ficar só onde está.

---

## 7. Desligar o servidor antigo

**Só depois de uma semana com o novo em produção.** O custo de manter os dois
por sete dias é irrelevante perto do custo de descobrir no oitavo dia que
algo ficou para trás.

Antes de desligar:

1. Um backup final do antigo, guardado fora dos dois servidores
2. Conferir que o novo vem recebendo lançamentos de verdade
3. Conferir que o backup automático rodou lá pelo menos uma vez:
   `docker exec solo_cmv_backup python backup.py --listar`

---

## O que fica para trás de propósito

**Sessões abertas.** Todos entram de novo. É consequência da chave nova, e é
desejável.

**O SQLite de desenvolvimento** (`solo_cmv.db`), que nunca foi produção.

**Os scripts de implantação** na raiz do projeto — `deploy_*.py`,
`check_*.py` e afins. Carregam credenciais do servidor antigo e estão fora
do repositório por isso. O caminho documentado é este arquivo.
