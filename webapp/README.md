# Solo CMV — início do projeto

Sistema web de controle de estoque, compras e CMV, migrado das planilhas
"INVENTÁRIO E CMV JUNHO" (Josefina / Casa Josefina). Arquitetura baseada no
Solo Rotinas (FastAPI + SQLAlchemy + JWT + frontend HTML/CSS/JS vanilla).

Ver `Plano_Migracao_Solo_CMV.docx` (pasta acima) para o plano completo,
cronograma de fases e regras de negócio a preservar.

## Rodando localmente

Forma rápida (igual ao Solo Rotinas): dê duplo clique em **`INICIAR.bat`**,
nesta mesma pasta. Ele instala as dependências na primeira vez, roda o seed
do banco e já abre o navegador em `http://localhost:8095`.

Forma manual:

```bash
cd webapp/backend
python -m venv venv
venv\Scripts\activate        # Windows
pip install -r requirements.txt
python entrypoint.py
```

Acesse http://localhost:8095 — o backend serve o frontend automaticamente.

> **Porta:** o Solo CMV roda localmente na porta **8095**, só em
> `127.0.0.1` (só este computador acessa — é um servidor local mesmo, não
> exposto na rede). As portas 8000 e 8080 são do Solo Rotinas — não usar
> aqui. Para mudar a porta, copie `backend/.env.example` para `backend/.env`
> e ajuste `PORT`. Para liberar acesso pela rede local (ex.: um tablet na
> cozinha), defina `HOST=0.0.0.0` no mesmo arquivo.
>
> **Se der erro ao abrir a porta (`WinError 10013`):** não é falta de
> programa instalado — é o Windows recusando a conexão, geralmente por
> firewall/antivírus ou por uma faixa de portas reservada pelo Hyper-V/WSL.
> Troque `PORT` para outro valor (ex.: `8096`) no `.env` e rode de novo. Para
> conferir se a porta está reservada, no Prompt de Comando como
> Administrador: `netsh interface ipv4 show excludedportrange protocol=tcp`.

Na primeira execução, o sistema já cria:
- Empresa "Josefina Gastronomia" e as unidades **Josefina** e **Casa Josefina**;
- O usuário inicial com acesso irrestrito:
  - **Login:** `Jh3ffth` (ou o que estiver em `ARQUITETO_LOGIN`)
  - **Senha:** definida por você em `ARQUITETO_SENHA`, no `.env`. Se não
    definir, o sistema gera uma aleatória e **imprime no terminal, uma única
    vez**, no momento em que cria o usuário — anote na hora.
  - **Papel:** Arquiteto (todas as permissões, todas as empresas)

  > Senha de acesso não mora no código. Este repositório é versionado e o
  > sistema será instalado em vários restaurantes: uma senha escrita aqui
  > seria pública e seria a mesma em todas as instalações.
- O catálogo mestre importado das planilhas: 8 categorias, 56 fornecedores e
  244 produtos (`backend/seed_data.json`, gerado a partir das duas planilhas
  originais).

## Estrutura do projeto

```
webapp/
├── backend/
│   ├── main.py            # monta a API e serve o frontend
│   ├── models.py          # todo o modelo de dados (ver comentários no arquivo)
│   ├── schemas.py         # contratos de entrada/saída da API
│   ├── seed.py             # cria empresa/unidades/usuário Arquiteto e importa o catálogo
│   ├── seed_data.json      # categorias, fornecedores e produtos extraídos das planilhas
│   ├── auth/                # login, JWT, controle de papéis
│   └── routers/
│       ├── unidades.py, categorias.py, fornecedores.py, produtos.py, usuarios.py
│       │   (no frontend, os três cadastros aparecem juntos em "Cadastros")
│       ├── movimentos.py    # compras/contagens (equiv. macro FiltrarEAtualizarTabela)
│       ├── inventario.py    # abrir/fechar sessão (equiv. macros AbrirInventario/FecharInventario)
│       ├── vendas.py        # faturamento manual por unidade/período
│       ├── despesas.py      # despesas extra (limpeza, embalagens, marketing…)
│       ├── dashboard.py     # indicadores (cadastro real + operação real)
│       ├── cmv.py           # RESERVADO — Fase 4, motor de cálculo ainda não implementado
│       ├── relatorios.py    # RESERVADO — Fase 5, depende do motor de CMV
│       └── nfe.py           # RESERVADO — Fase 10, importação futura via certificado digital
└── frontend/
    ├── index.html          # login + shell do app (sidebar + topbar + área de conteúdo)
    ├── css/main.css
    ├── js/
    │   ├── icons.js         # biblioteca de ícones SVG (sem emoji em nenhuma tela)
    │   ├── api.js, auth.js, router.js, app.js
    │   └── pages/           # um módulo por seção do menu lateral
    └── assets/logos/        # logos Josefina e Casa Josefina
```

## O que já funciona

Login/autenticação (JWT + papéis Arquiteto/Admin/Gerente/Operador), cadastro
de unidades, categorias, fornecedores e produtos, lançamento de compras e
contagens, sessões de inventário (abrir/fechar), registro manual de
faturamento por período, cadastro de usuários, e um painel com indicadores
reais de cadastro/operação.

### Cadastros

Produtos, Categorias e Fornecedores ficam juntos numa única entrada do menu,
em abas, cada uma mostrando a quantidade de registros. A aba fica na URL
(`#cadastros/fornecedores`), então dá para recarregar ou compartilhar o link
já na aba certa — e os links antigos (`#produtos`, `#categorias`,
`#fornecedores`) continuam funcionando, redirecionando para a aba
correspondente.

### Estoque e código do produto

Cada produto tem um **código único de 6 dígitos**, gerado automaticamente no
bloco da sua família. As faixas foram extraídas da coluna "Cod." das planilhas
originais, para manter a numeração que a operação já conhece:

| Família | Bloco |
|---|---|
| Mercearia | 100000+ |
| Hortifruti | 111000+ |
| Resfriados | 112000+ |
| Carnes | 130000+ |
| Peixes e Frutos do Mar | 140000+ |
| Cervejas | 150000+ |
| Bebidas sem álcool | 160000+ |
| Bar | 170000+ |
| (sem família definida) | 190000+ |

O código aparece em todas as listagens (Estoque, Cadastros > Produtos,
Compras e Contagens) e nos seletores do Lançador, e serve como termo de busca.

A tela **Estoque** lista todos os itens cadastrados com quantidade, último
custo e valor em estoque, com filtro por família, busca por nome/código e
opção de ver só o que tem saldo.

> **Como o saldo é calculado:** o modelo de CMV das planilhas não registra
> saídas (o consumo é implícito: EI + Compras − EF). Então o saldo é o saldo
> teórico desde a última contagem física: `última contagem + compras
> lançadas depois dela`. Item sem contagem e sem compra fica zerado — o
> estado inicial de todo produto recém-cadastrado.

### Inventários

Tela de listagem (**Nº | Descrição | Data | Status | Ações**) com filtros por
texto, status e período.

**Ciclo de vida**

```
Aberto ──congelar──> Congelado ──contagem──> Em Contagem ──finalizar──> Finalizado
   └──────────────────── Cancelado <────────────────────────┘
```

| Status | Significado |
|---|---|
| Aberto | criado e com escopo definido — **não recebe contagem ainda** |
| Congelado | estoque fotografado; a partir daqui aceita contagem |
| Em Contagem | já tem pelo menos uma contagem lançada |
| Finalizado | contagens aplicadas ao estoque; encerrado |
| Cancelado | descartado, mas segue consultável para análise |

**Abertura** — botão "Abrir Inventário" abre um modal flutuante (mesmas
características do Lançador: arrastável e não fecha ao clicar fora). Nele se
informa a descrição livre (ex.: `INV ROTATIVO CARNES`), o escopo (uma, várias
famílias ou *inventário geral* = todas) e uma observação opcional.

- O **número** é gerado automaticamente na sequência da unidade (01, 02, 03…).
  Números de inventários cancelados **não são reaproveitados**, porque eles
  continuam disponíveis para análise.
- **Não é possível abrir dois inventários ativos cobrindo o mesmo setor.** Um
  inventário geral conflita com qualquer outro ativo.

**Congelar** — fotografa o estoque de cada item do escopo (`inventario_itens`).
É esse retrato que permite medir a divergência no fim. Sem congelar, o
Lançador recusa a contagem.

**Finalizar** — as quantidades contadas passam a valer como estoque real:
cada item contado gera um movimento de `CONTAGEM_FINAL` na data de hoje.
Itens sem contagem **não são zerados** — ficam como estavam e aparecem no
relatório como "não contado". Um inventário **sem nenhuma contagem também
pode ser finalizado**: nesse caso nada é aplicado e o estoque fica como
estava — é um encerramento legítimo.

**Contagem** — lançada pelo Lançador (aba Inventário), que grava direto na
linha do inventário. Duas regras valem sempre:

- **Só itens do escopo.** Um inventário do Bar recusa um item de Hortifruti.
  A lista do Lançador já vem filtrada pelas famílias do inventário, e um
  código digitado fora do escopo é recusado com a explicação.
- **Contar não mexe no estoque.** A quantidade fica registrada na linha do
  inventário; o estoque só muda na finalização. É isso que permite conferir
  as divergências antes de valer.

Recontar o mesmo item sobrescreve o valor anterior, e a mensagem informa qual
era o número antigo.

> **Preparado para outros canais (bot do Telegram, coletor, integrações).**
> Toda a regra de contagem vive em `backend/servicos/contagem.py`, fora do
> router. O endpoint `POST /api/inventario/contagem` aceita identificação
> flexível — inventário por id **ou** por número + unidade; produto por id
> **ou** por código de 6 dígitos — que é exatamente o que um bot tem à mão
> ao receber "INV 01, código 170009, 12". Cada canal só traduz a entrada e
> trata o erro do seu jeito (HTTP na API, texto no bot); o campo `origem`
> (`WEB`, `TELEGRAM`, `API`) fica gravado na linha para auditoria.

**Folha de contagem cega (PDF A4)** — botão "Folha" na linha. Traz apenas
**código, descrição e unidade**, com espaço em branco para anotar à caneta,
agrupado por família (o contador percorre setor a setor). A quantidade do
sistema é deliberadamente omitida: quem enxerga o número esperado tende a
confirmá-lo em vez de contar, e a divergência real nunca apareceria. Tem duas
colunas — *Contagem* e *Recontagem* — e campos de "Contado por", "Conferido
por", data e hora.

> **Controle antifraude:** a folha só é emitida com o inventário **Aberto**,
> antes do congelamento. Nos demais status (Congelado, Em Contagem,
> Finalizado, Cancelado) a emissão é recusada — assim ninguém tira uma
> segunda via depois que o estoque foi fotografado, nem imprime folha de
> inventário encerrado. Como nesse momento ainda não existem linhas de
> inventário, a folha é montada a partir do escopo escolhido na abertura.

**Relatório PDF** — botão "Relatório" na linha (disponível a partir do
congelamento). Traz ficha do inventário, resumo financeiro e análise item a
item: estoque anterior, contado, divergência e valor da divergência, com
perdas em vermelho e sobras em verde.

### Requisições

Retirada de itens do estoque, hoje sempre com destino à **produção**. É o
contrapeso das compras: sem requisição o estoque só entraria e nunca sairia.

**Ciclo de vida**

```
Aberta ──iniciar──> Iniciada ──atender──> Atendida
   └──────────── Cancelada <──────┘
```

| Status | Significado |
|---|---|
| Aberta | criada — **ainda não recebe itens** |
| Iniciada | aceita o lançamento dos itens pelo Lançador |
| Atendida | itens baixados do estoque e enviados à produção |
| Cancelada | descartada, mas segue consultável |

- **Sem escopo por família:** ao contrário do inventário, o requisitante pede
  qualquer item cadastrado.
- **Numeração própria** por unidade (01, 02…), sem reaproveitar número de
  cancelada.
- **Lançar item não mexe no estoque.** A baixa acontece de uma vez no
  atendimento, gerando um movimento de `REQUISICAO` por item. Isso permite
  montar o pedido com calma e conferir antes de efetivar.
- O Lançador mostra o **saldo disponível** do item escolhido e avisa quando a
  quantidade pedida supera o estoque — mas **não bloqueia**: na prática o
  estoque teórico costuma estar defasado, e travar a produção seria pior do
  que registrar o negativo (que aliás é sinal de que falta inventário).

Isso mudou a fórmula do estoque, que agora tem saída explícita:

```
saldo = última contagem + compras posteriores − requisições posteriores
```

### Lançador (janela flutuante)

No menu, logo abaixo do Painel. Abre como janela flutuante **arrastável pelo
cabeçalho** (mouse e toque) e **não fecha ao clicar fora** — só pelo X. Como
não usa fundo escurecido, dá para continuar navegando no sistema com ele
aberto. A posição escolhida é lembrada ao reabrir.

Quatro modos, em abas:

| Aba | O que lança |
|---|---|
| Compras | Compra avulsa de um produto (atualiza o último custo) |
| Notas Fiscais | Nota inteira com vários itens, total somado ao vivo |
| Inventário | Quantidade contada (contagem inicial ou final) |
| Vendas | Faturamento do período, com abertura opcional comida/bebida |

A aba **Vendas** só aparece para Arquiteto/Admin/Gerente, acompanhando a
permissão do endpoint `/vendas` (o Operador não vê a aba, em vez de tomar
erro de permissão ao tentar lançar).

## O que está reservado (visível no menu, com aviso "Em breve")

- **Motor de CMV** (Fase 4) — cálculo automático de CMV Real/CMV % a partir
  dos lançamentos já registrados. Precisa de validação das fórmulas com o
  Arquiteto antes de codar (ver seção 3.4 do plano de migração).
- **Relatórios** (Fase 5) — resumo mensal e relatório semanal comparativo.
  Depende do motor de CMV.
- **Notas Fiscais / NF-e** (Fase 10) — importação automática via certificado
  digital. Tabelas já existem no banco (`CertificadoDigital`,
  `NotaFiscalImportada`); integração ainda não iniciada.

## Hospedagem

Preparado para rodar primeiro no servidor próprio (Comodo) do Arquiteto, com
configuração via variáveis de ambiente (`backend/.env.example`) para migrar
depois para o servidor que cada estabelecimento cliente contratar, sem
alteração de código — ver seção 5.6 do plano de migração.
