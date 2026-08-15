# Migração para PostgreSQL — o que mudou e como executar

**Data:** 14/08/2026
**Estado:** código pronto e verificado. O Solo CMV roda igual em SQLite e PostgreSQL.

---

## 1. O que foi feito

Quatro mudanças no código, todas verificadas com um PostgreSQL 16 de verdade:

| Arquivo | Mudança | Por quê |
|---|---|---|
| `models.py` | Enums viram **texto**, não tipo nativo | Acrescentar valor deixa de exigir migração |
| `database.py` | Pool com `pre_ping`, e **WAL** no SQLite | Conexão morta não estoura na cara do usuário |
| `migracoes.py` | SQL sensível ao dialeto | `BOOLEAN DEFAULT 0` não existe no PostgreSQL |
| `requirements.txt` | `psycopg[binary]` no lugar de `psycopg2-binary` | psycopg 3 tem wheel para Windows também |

Mais o script de transferência: `backend/migrar_para_postgres.py`.

---

## 2. As três armadilhas, e como cada uma foi resolvida

### 2.1 Enum nativo torna cada valor novo uma migração

Com `Enum(PapelUsuario)` puro, o SQLAlchemy cria um `TYPE` de verdade no
PostgreSQL. Acrescentar um valor passa a exigir `ALTER TYPE ... ADD VALUE`.

Só neste projeto já acrescentamos `DIRETOR`, `PERDA`, `DISTRIBUICAO` e seis
tipos de meta. Com enum nativo, cada um desses teria custado uma migração.

**Resolvido** com um helper único em `models.py`:

```python
def Enumerado(enum_classe, **kwargs):
    return Enum(enum_classe, native_enum=False, create_constraint=False,
                length=40, validate_strings=True, **kwargs)
```

A coluna vira `VARCHAR(40)`. O SQLAlchemy continua validando na entrada e na
saída — valor fora do enum levanta erro em Python, que é onde o erro deve
aparecer. As 14 colunas de enum do sistema usam esse helper.

Efeito colateral bom: como os dois bancos guardam texto, a transferência de
dados vira cópia direta.

### 2.2 `BOOLEAN DEFAULT 0` não existe no PostgreSQL

Duas migrações usavam. O PostgreSQL quer `DEFAULT FALSE`. Resolvido com uma
constante no topo de `migracoes.py`:

```python
EH_POSTGRES = engine.dialect.name == "postgresql"
FALSO = "FALSE" if EH_POSTGRES else "0"
```

Aproveitei para trocar `DATETIME` (que também não existe no PostgreSQL) por
`TIMESTAMP`, que vale nos dois.

### 2.3 As sequências não avançam sozinhas

No PostgreSQL o `id` vem de uma sequência. Inserindo com id explícito — que é
o que a transferência faz — a sequência **não avança**. O primeiro cadastro
novo tentaria usar o id 1 e colidiria com o que acabou de entrar.

É o erro clássico deste tipo de migração, e o pior: ele só aparece depois, na
cara do usuário. O script reposiciona todas as sequências no fim e o teste
confere criando um fornecedor de verdade.

---

## 3. Como executar

### 3.1 No servidor — criar banco e usuário

```sql
-- como postgres
CREATE USER solo_cmv WITH PASSWORD 'senha-forte-so-letras-e-numeros';
CREATE DATABASE solo_cmv OWNER solo_cmv;
```

Usuário e banco **próprios**, separados do que Solo Rotinas e Solo Finances
usam. Nenhuma tabela compartilhada, nenhuma permissão cruzada.

### 3.2 Transferir os dados

O script roda **duas vezes**: primeiro simulando, depois valendo.

```bash
cd backend

# 1. Simula — lê tudo, mostra o que faria, não grava nada
python migrar_para_postgres.py \
  --destino "postgresql+psycopg://solo_cmv:SENHA@localhost:5432/solo_cmv"

# 2. Grava
python migrar_para_postgres.py \
  --destino "postgresql+psycopg://solo_cmv:SENHA@localhost:5432/solo_cmv" \
  --aplicar
```

Simular é o padrão de propósito: migração de banco não deve ser um comando
que roda por acidente.

**Três proteções embutidas:**

- Recusa gravar em banco que já tenha dados (misturar registros quebraria as
  chaves estrangeiras)
- Confere linha a linha no fim, tabela por tabela
- Reposiciona as sequências e informa o próximo id de cada tabela

### 3.3 Apontar a aplicação

No `.env`:

```
DATABASE_URL=postgresql+psycopg://solo_cmv:SENHA@localhost:5432/solo_cmv
```

Reinicie. As migrações rodam sozinhas na subida e são idempotentes.

### 3.4 Conferir

```bash
python teste_postgres_api.py
```

Deve terminar em "Tudo certo". A mesma suíte roda contra SQLite — é assim que
se prova que a migração não mudou comportamento.

---

## 4. Verificação já feita

Contra PostgreSQL 16.2, com o banco real:

```
1051 linhas transferidas e conferidas em 22 tabelas
30/30 rotas respondendo
```

Os números batem exatamente com o SQLite:

| Indicador | SQLite | PostgreSQL |
|---|---|---|
| CMV do período (03–10/08, Josefina) | R$ 37.544,98 | R$ 37.544,98 |
| Faturamento | R$ 96.500,00 | R$ 96.500,00 |
| Itens apurados | 65 | 65 |
| CMV consolidado da rede | R$ 39.044,98 · 35,02% | R$ 39.044,98 · 35,02% |
| Valor em estoque | R$ 12.155,06 | R$ 12.155,06 |

E as seis suítes de backend passam nos dois bancos, sem mudar uma expectativa
sequer. No PostgreSQL cada suíte roda num banco próprio criado por `TEMPLATE`
— o equivalente à cópia do arquivo que se fazia no SQLite.

---

## 5. Para quem for implantar

O que o Solo CMV precisa no servidor:

- **Python 3.11+**, PostgreSQL 14 ou mais novo
- **Um processo** de uvicorn (`entrypoint.py`), escutando em `127.0.0.1`
- **nginx na frente**, com o domínio e o certificado — a aplicação não precisa
  ficar exposta
- `.env` com `DATABASE_URL`, `SECRET_KEY` (gere uma nova!) e `CORS_ORIGINS`
  apontando para o domínio real

Três coisas que merecem atenção porque o servidor já tem projetos rodando:

1. **Porta.** O padrão é 8095; 8000 e 8080 são do Solo Rotinas. Confirme que
   8095 está livre antes.
2. **Um worker só.** Se subir com `--workers N`, os N processos escrevem no
   mesmo banco — o que o PostgreSQL aguenta, mas exige revisar se algum estado
   em memória (não há hoje) atrapalharia.
3. **`SECRET_KEY` nova.** A do `.env.example` é pública. Trocar invalida os
   tokens existentes, o que em produção nova não custa nada.

Backup: `pg_dump solo_cmv` cobre tudo. O arquivo `solo_cmv.db` do SQLite pode
ser guardado como ponto de retorno da migração.
