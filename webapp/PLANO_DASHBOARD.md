# Plano do novo Painel (Dashboard) — Solo CMV

**Data:** 13/08/2026
**Decisões do Arquiteto:** painel em faixas (serve diretoria e gerência na mesma tela) · uma unidade por vez, com a visão REGIONAL consolidada prevista para depois · período padrão **mensal** · metas em tela própria, definidas pela diretoria (seção 7)

---

## 1. Diagnóstico — por que a tela atual não serve

O painel de hoje tem 64 linhas de JavaScript e mostra seis números:

| O que mostra | O que o gestor faz com isso |
|---|---|
| Produtos cadastrados: 244 | Nada |
| Fornecedores: 56 | Nada |
| Categorias: 12 | Nada |
| Movimentos lançados: 231 | Nada |
| Períodos de venda informados: 1 | Nada |
| Sessões de inventário abertas: 0 | Alguma coisa |

Cinco dos seis KPIs contam linhas de tabela. Eles respondem *"o sistema tem dados?"* — pergunta de quem instalou o sistema, não de quem administra o restaurante. Quem abre o painel de manhã quer saber **como está o CMV, quanto se perdeu e o que precisa ser feito hoje**.

Além disso:

- **O painel mente sobre o próprio sistema.** O gráfico de CMV exibe permanentemente *"Aguardando o motor de CMV (Fase 4)"*, e o card de rodapé repete a mesma frase vinda do backend (`routers/dashboard.py`, campo `cmv.implementado: False`). O motor está pronto e funcionando há semanas.
- **Datas em formato ISO.** O gráfico de faturamento rotula as barras como `2026-08-03 a 2026-08-10`.
- **Sem hierarquia visual.** Seis cartões idênticos, dois gráficos de mesmo peso, um card de texto. Nada se destaca porque tudo se destaca igual.
- **Beco sem saída.** Nenhum número leva a lugar nenhum. O painel não é porta de entrada da aplicação, é um cartaz.

---

## 2. Princípios do redesenho

1. **Uma pergunta por faixa.** Cada bloco horizontal responde uma pergunta única e declarada no título.
2. **Todo número é uma porta.** Clicar no CMV abre o Motor de CMV no mesmo período; clicar em perdas abre a lista filtrada. O painel vira o índice da aplicação.
3. **Estado vazio que ensina.** Sem faturamento lançado, não se escreve "sem dados" — escreve-se *"faturamento de agosto não lançado"* com o botão que resolve.
4. **Cor com significado, nunca decorativa.** Navy = neutro. Dourado = destaque. Vermelho = fora da meta ou exige ação. Verde = dentro da meta. Se um número está cinza, é porque é contexto.
5. **Densidade honesta.** Mais informação por centímetro, menos respiro vazio — mas com o número principal grande o suficiente para ser lido de pé, a três metros da tela.
6. **Auditável.** Todo indicador diz de onde veio. "CMV de agosto" sem dizer quais inventários foram usados é um número que ninguém consegue defender numa reunião.

---

## 3. Uma descoberta que muda o desenho: mês ≠ ciclo de inventário

Rodando o motor no mês cheio de agosto contra o banco real, o resultado foi:

```
período 01/08 → 31/08   CMV R$ 10.217,01   CMV 10,59%
período 03/08 → 10/08   CMV R$ 37.544,98   CMV 28,4%
aviso: "65 itens sem inventário de abertura — entraram com estoque
        inicial zero, o que reduz o CMV apurado deles."
```

A causa: **não existe inventário finalizado em 01/08**. Sem contagem de abertura, o motor entra com estoque inicial zero e a conta `0 + compras − estoque final` produz um CMV artificialmente baixo. O número não está errado — é exatamente o que os dados permitem — mas exibido como manchete seria desastroso: o dono leria "CMV 10,6%, ótimo" quando a realidade é 28,4%.

**Consequência para o plano:** o período mensal do painel não pode ser o mês do calendário cru. Ele precisa de uma regra de **encaixe no ciclo**:

> Ao escolher "Agosto/2026", o painel apura do **último inventário finalizado em ou antes de 01/08** até o **último inventário finalizado em ou antes de 31/08**, e escreve no cabeçalho: *"Agosto/2026 · apurado de INV-1002 (03/08) a INV-1003 (10/08)"*.

Quando não houver par válido dentro do mês, o painel não mostra zero: mostra o estado *"nenhum ciclo de inventário fechado em agosto"* com o caminho para abrir um. Zero silencioso é pior que ausência declarada.

Isso vale só para os indicadores derivados de inventário (CMV, estoque inicial/final). Faturamento, compras, perdas e requisições continuam recortados pelo mês do calendário, porque são eventos datados e não dependem de contagem.

---

## 4. Estrutura da tela — seis faixas

```
┌─ FAIXA 0 · CONTEXTO ────────────────────────────────────────────────┐
│  Agosto/2026  ◂ ▸    [ Mês ][ Ciclo ][ Personalizado ]              │
│  Apurado de INV-1002 (03/08) a INV-1003 (10/08) · custo médio       │
└─────────────────────────────────────────────────────────────────────┘

┌─ FAIXA 1 · O QUE EXIGE AÇÃO  (some quando não há nada) ─────────────┐
│  ⚠ 187 itens sem custo cadastrado         → Estoque                 │
│  ⚠ Faturamento de agosto não lançado      → Faturamento por Período │
│  ⚠ Inventário 04 aberto há 5 dias         → Inventários             │
└─────────────────────────────────────────────────────────────────────┘

┌─ FAIXA 2 · COMO ESTAMOS  (5 KPIs) ─────────────────────────────────┐
│  CMV %        CMV R$        Faturamento    Perdas       Estoque     │
│  28,4%        R$ 37.545     R$ 96.500      R$ 812       R$ 12.155   │
│  ▼0,6pp meta  ▲12% m.ant.   ▲8% m.ant.     2,2% do CMV  58 c/ saldo │
│  ▁▂▃▅▃▂▁      ▁▂▃▅▃▂▁       ▁▂▃▅▃▂▁                                 │
└─────────────────────────────────────────────────────────────────────┘

┌─ FAIXA 3 · PARA ONDE ESTAMOS INDO ─────────────┬───────────────────┐
│  CMV % × meta — últimos 6 ciclos               │ Composição do CMV │
│  (linha, com faixa da meta sombreada)          │ Comida × Bebida   │
│                                                │ (rosca + CMV% de  │
│                                                │  cada bloco)      │
└────────────────────────────────────────────────┴───────────────────┘

┌─ FAIXA 4 · ONDE ESTÁ O DINHEIRO ──────┬────────────┬───────────────┐
│  Top 10 itens por CMV                 │ Perdas por │ Estoque parado│
│  (barras horizontais, % do total)     │ motivo     │ (sem giro há  │
│                                       │ (rosca)    │  30+ dias)    │
└───────────────────────────────────────┴────────────┴───────────────┘

┌─ FAIXA 5 · ATIVIDADE RECENTE ──────────────────────────────────────┐
│  Últimos 10 lançamentos: data · tipo · documento · item · valor    │
└─────────────────────────────────────────────────────────────────────┘
```

### Faixa 0 — Contexto

Seletor de mês com setas de navegação, mais três modos: **Mês** (padrão), **Ciclo** (entre dois inventários, como o Motor de CMV) e **Personalizado**. Abaixo, em texto pequeno, a procedência: quais inventários, qual método de custo. A escolha fica no `localStorage`, junto com a unidade.

### Faixa 1 — O que exige ação

Não é uma lista de avisos decorativos: é a fila de trabalho. Cada item tem gravidade (atenção / urgente), texto curto e botão que leva à tela onde se resolve. **Some inteira quando não há pendência** — um painel que sempre mostra alertas ensina o usuário a ignorar alertas.

Pendências previstas, todas calculáveis com o que já existe:

| Pendência | Origem do dado | Gravidade |
|---|---|---|
| Itens sem custo cadastrado | `/estoque` → `resumo.itens_sem_custo` (hoje: **187**) | atenção |
| Faturamento do período não lançado | `VendaPeriodo` sem cobertura do mês | urgente |
| Períodos de faturamento sobrepostos | aviso que o motor já emite | urgente |
| Inventário aberto/congelado há mais de 3 dias | `SessaoInventario.data_abertura` | atenção |
| Requisições aguardando atendimento | `Requisicao.status` | atenção |
| Itens contados sem inventário de abertura | aviso do motor (hoje: **65**) | atenção |

### Faixa 2 — Como estamos

Cinco cartões, cada um com rótulo, valor grande, **variação contra o período anterior** e um sparkline dos últimos seis períodos. A variação é o que transforma número em informação: "CMV 28,4%" não diz nada; "28,4%, ▼0,6 pp abaixo da meta e caindo há três ciclos" diz tudo.

- **CMV %** — cor conforme a meta (verde dentro, vermelho fora). Clique → Motor de CMV.
- **CMV R$** — valor absoluto.
- **Faturamento** — total do período, com desdobramento comida/bebida no hover.
- **Perdas** — R$ e percentual do CMV. Clique → Perdas.
- **Valor em estoque** — hoje R$ 12.155,06, com "58 itens com saldo de 244". Clique → Estoque.

### Faixa 3 — Para onde estamos indo

- **CMV % × meta no tempo** (linha): últimos 6 ciclos ou meses, com a meta como faixa sombreada. Responde *"estamos melhorando?"*.
- **Composição do CMV** (rosca + números): Comida × Bebida, com CMV% de cada bloco ao lado. Responde *"onde está o problema?"*. Bebida com CMV 18% e comida com 34% é um diagnóstico imediato.

### Faixa 4 — Onde está o dinheiro

- **Top 10 itens por CMV**: barras horizontais com valor e participação. Em qualquer restaurante, 15 itens explicam 70% do custo — esta é a lista que o gestor negocia com fornecedor.
- **Perdas por motivo**: rosca com validade / quebra / furto / consumo interno. Dado já pronto em `/perdas/resumo`.
- **Estoque parado**: itens com saldo e sem movimento há mais de 30 dias, ordenados por valor imobilizado. Dinheiro dormindo na câmara fria.

### Faixa 5 — Atividade recente

Últimos dez movimentos, no mesmo formato da tela de Movimentações (data pt-BR, tipo, nº documento, item, valor). Serve para dois fins: dá a sensação de sistema vivo e permite flagrar um lançamento errado no minuto seguinte.

---

## 5. Backend — um endpoint, nenhuma regra duplicada

Hoje o painel faz duas chamadas e calcula na tela. Com seis faixas seriam oito chamadas e lógica de negócio no navegador. A proposta:

**`backend/servicos/painel.py`** — serviço novo que monta o resumo completo, orquestrando o que já existe:

```
servicos/painel.py
  ├── servicos/cmv.apurar()          → CMV, blocos, top itens, avisos
  ├── servicos/perda.resumo()        → perdas por motivo
  ├── calculo_estoque.saldos_por_produto() + ultimos_custos()
  ├── consultas curtas               → pendências, atividade recente
  └── série histórica                → apurar() em laço, N períodos
```

Nenhuma fórmula nova. O serviço **só compõe**; se o CMV mudar, muda num lugar só. E porque é serviço e não router, o futuro bot do Telegram manda o mesmo resumo por mensagem sem reimplementar nada.

**`GET /api/dashboard/painel`**

| Parâmetro | Uso |
|---|---|
| `unidade_id` | opcional — **quando ausente, consolida todas as unidades** (é o gancho da futura visão REGIONAL, já contemplado na assinatura) |
| `modo` | `MES` (padrão), `CICLO`, `PERSONALIZADO` |
| `referencia` | `2026-08` no modo mês |
| `data_inicio` / `data_fim` | no modo personalizado |
| `historico` | quantos períodos anteriores trazer (padrão 6) |

Resposta, em blocos que espelham as faixas:

```json
{
  "periodo":     { "rotulo": "Agosto/2026", "data_inicio": "...", "data_fim": "...",
                   "inventario_abertura": "1002", "inventario_fechamento": "1003",
                   "encaixado_no_ciclo": true },
  "pendencias":  [ { "chave": "itens_sem_custo", "gravidade": "atencao",
                     "texto": "187 itens sem custo cadastrado",
                     "rota": "estoque", "quantidade": 187 } ],
  "kpis":        { "cmv_percentual": {...}, "cmv_valor": {...}, "faturamento": {...},
                   "perdas": {...}, "estoque": {...} },
  "historico":   [ { "rotulo": "Mar", "cmv_percentual": 0.31, "faturamento": 88000 } ],
  "composicao":  { "comida": {...}, "bebida": {...} },
  "top_itens":   [ { "codigo": "111008", "produto": "Batata Doce",
                     "unidade_medida": "Kg", "cmv": 1840.22, "participacao": 0.049 } ],
  "perdas":      { "valor_total": 812.0, "por_motivo": [...] },
  "estoque_parado": [ { "codigo": "...", "produto": "...", "dias": 47, "valor": 320.0 } ],
  "atividade":   [ { "data": "...", "tipo": "COMPRA", "documento": "NF 1500", ... } ],
  "avisos":      [ "65 itens sem inventário de abertura…" ]
}
```

Cada KPI vem no formato `{ valor, valor_anterior, variacao, direcao, serie: [] }`, para que o cartão desenhe seta, cor e sparkline sem calcular nada.

O endpoint antigo `/dashboard/resumo` permanece respondendo (nada quebra), mas sai do painel e perde a mensagem mentirosa sobre a "Fase 4".

---

## 6. Frontend

**Arquivos**

- `frontend/js/pages/dashboard.js` — reescrito do zero, em módulos por faixa
- `frontend/css/dashboard.css` — novo, para não inchar o `main.css` (que já passa de 400 linhas)
- Chart.js 4.4.3 já está embarcado em `js/vendor/` — sem CDN, sem dependência de internet

**Decisões técnicas**

- **Sparklines em SVG inline**, não em Chart.js. Cinco instâncias de gráfico só para desenhar cinco linhas de 40px seria desperdício de memória e de tempo de render. SVG gerado por função pura, 15 linhas de código.
- **Três instâncias de Chart.js apenas**: linha do CMV, rosca da composição, rosca das perdas. O Top 10 é barra horizontal em CSS puro (`width: %`) — mais leve, mais fácil de tornar clicável e acessível.
- **Skeleton de carregamento**: a estrutura cinza aparece imediatamente e os blocos preenchem conforme chegam, em vez de um "Carregando…" centralizado. A tela parece o dobro mais rápida pelo mesmo tempo de resposta.
- **Destruição de gráficos** ao re-renderizar (o bug clássico de Chart.js em SPA), com um registro único de instâncias.
- **Responsividade**: 5 KPIs → 3 → 2 → 1; faixas 3 e 4 empilham abaixo de 900px. A rolagem interna do `#conteudo`, corrigida agora há pouco, já garante que o menu não some.

**Paleta** — usa o que já existe, sem inventar:

| Uso | Cor |
|---|---|
| Estrutura, títulos, valores neutros | `--navy #1F3B57` |
| Destaque, séries principais | `--gold #B08D3E` |
| Fora da meta, perdas, urgente | `--red #A6231F` |
| Dentro da meta | `#1C7A3C` (já usado no botão Finalizar) |
| Bebida (contraste com comida) | `#4A7CA6` (novo, derivado do navy) |

---

## 7. Metas — tela própria, definida pela diretoria

**Decisões do Arquiteto:** novo papel **DIRETOR**, acima do Admin · metas **visíveis a todos**, editáveis só por Diretor e Arquiteto · quatro grupos de meta: CMV (geral, comida, bebida), CMV por família, perdas e faturamento.

### 7.1 O papel DIRETOR

Hierarquia nova:

```
ARQUITETO   dono do sistema, acesso irrestrito
DIRETOR     define metas e enxerga todo o financeiro          ← novo
ADMIN       administra empresa, unidades, usuários e cadastros
GERENTE     lança, aprova e vê relatórios da unidade
OPERADOR    lança compras, contagens e perdas no dia a dia
```

Diretor faz tudo que o Admin faz, **mais** definir metas. Nenhum usuário existente muda de papel; a migração só acrescenta o valor ao enum. Se depois você quiser um diretor que veja números mas não crie usuários, é estreitar a matriz — não refazer nada.

Sobre visibilidade: gerente e operador **veem** a meta no Painel e no Motor de CMV ("CMV 28,4% · meta 29%", com a cor de dentro/fora), mas a aba Metas não aparece para eles. Meta escondida não cobra ninguém; meta editável por qualquer um não vale nada.

### 7.2 A decisão que estrutura tudo: meta tem vigência

Hoje a meta é um campo solto — `ConfiguracaoCMV.meta_percentual = 0.29`. Se a diretoria mudar a meta de 29% para 27% em setembro, **o gráfico "CMV × meta" passa a julgar março, abril e maio contra uma meta que não existia naquela época**. O histórico é reescrito em silêncio, e a série de acompanhamento perde o sentido.

Por isso a meta não é um campo: é um **registro com vigência**.

```
Meta
  unidade_id        null = vale para todas as unidades (gancho da REGIONAL)
  tipo              CMV_GERAL · CMV_COMIDA · CMV_BEBIDA · CMV_FAMILIA
                    PERDAS · FATURAMENTO
  categoria_id      só em CMV_FAMILIA
  valor + formato   PERCENTUAL ou REAIS
  periodicidade     MENSAL ou SEMANAL (faturamento e perdas em R$)
  vigencia_inicio   a partir de quando vale
  vigencia_fim      null = vigente hoje
  usuario_id        quem definiu
  observacao        por quê
```

**Nunca se edita uma meta.** Definir um valor novo fecha a vigência do anterior e abre outra. O histórico sai de graça, a auditoria também, e cada período do gráfico é comparado contra a meta que valia naquele período.

A meta atual (29%) é migrada como uma linha `CMV_GERAL` com vigência desde o primeiro movimento do banco, para que nada no passado fique órfão.

### 7.3 Herança — ninguém precisa preencher doze famílias

As metas se resolvem em cascata:

```
CMV_FAMILIA (Hortifruti)  →  se não houver, herda de
CMV_COMIDA / CMV_BEBIDA   →  se não houver, herda de
CMV_GERAL
```

Assim a diretoria pode começar com **um único número** e ir refinando. A tela mostra a diferença de forma explícita: meta definida aparece em preto, meta herdada aparece em cinza com a etiqueta *"herdado de Comida"*. Sem isso, ninguém sabe se o 34% da carne foi decidido ou é reflexo de outra coisa.

### 7.4 A tela

Nem formulário de campos soltos, nem planilha. A ideia é que **definir meta seja um ato informado**: cada meta aparece ao lado do que está sendo realizado hoje.

```
┌─ Metas · Josefina ─────────────────────────────────────────────────┐
│  Vigentes desde 01/09/2026        [ Ver histórico ]  [ Nova vigência ]│
└─────────────────────────────────────────────────────────────────────┘

┌─ CMV ──────────────────────────────────────────────────────────────┐
│                 meta      realizado (ago)                           │
│  Geral         29,0 %  ●━━━━━━━━━━━━━━━━━━━━━○         28,4 %  ✓   │
│  Comida        34,0 %  ●━━━━━━━━━━━━━━━━━━━━━━━━━○     34,1 %  ✓   │
│  Bebida        22,0 %  ●━━━━━━━━━━━○                   18,7 %  ✓   │
│                                                                     │
│  ⓘ Comida 34% e bebida 22%, no mix atual de faturamento (78/22),   │
│    dão 31,4% — acima da meta geral de 29%. Revisar?                │
└─────────────────────────────────────────────────────────────────────┘

┌─ Por família ────────────────────────── [ mostrar herdadas ] ──────┐
│  Hortifruti     12,0 %   realizado 11,4 %   ✓      [usar realizado]│
│  Carnes         38,0 %   realizado 41,2 %   ✗      [usar realizado]│
│  Mercearia       —  herdado de Comida (34%)        [definir]       │
└─────────────────────────────────────────────────────────────────────┘

┌─ Perdas ──────────────────┬─ Faturamento ──────────────────────────┐
│  Máximo 2,0 % do CMV      │  R$ 110.000 / mês                      │
│  realizado 2,2 %  ✗       │  realizado R$ 96.500 · 87,7 %          │
└───────────────────────────┴────────────────────────────────────────┘
```

Quatro decisões de interface que fazem a tela funcionar:

1. **Meta e realizado lado a lado, sempre.** Definir 25% de CMV para carne quando a operação roda em 41% é fantasia. O número real ao lado transforma a meta em conversa.
2. **Botão "usar realizado".** Preenche a meta com o valor apurado do último período — ponto de partida honesto para quem está começando a definir metas.
3. **Barra visual em vez de só número.** O olho lê a distância entre meta e realizado antes de ler o algarismo.
4. **Aviso de coerência.** Comida e bebida, ponderadas pelo mix de faturamento do período, precisam convergir para a meta geral. Quando não convergem, a tela avisa — sem bloquear, porque pode ser intencional durante uma transição.

Editar é clicar no número, digitar e confirmar. Ao salvar, a tela pergunta **a partir de quando vale** (padrão: hoje) e permite uma justificativa curta, que fica no histórico.

### 7.5 Histórico

Painel lateral ou modal, em ordem cronológica:

```
01/09/2026  CMV geral  29,0 % → 27,0 %   Jefferson (Arquiteto)
            "meta do 2º semestre, após renegociar carnes"
15/07/2026  CMV bebida     —  → 22,0 %   Jefferson (Arquiteto)
```

### 7.6 Onde isso encosta no resto do sistema

- **`backend/servicos/metas.py`** — função `meta_vigente(unidade_id, tipo, data, categoria_id)` que resolve vigência e herança. Único ponto de verdade.
- **Motor de CMV** — passa a pedir a meta ao serviço, com a data do período apurado, em vez de ler o campo fixo. A `ConfiguracaoCMV.meta_percentual` fica só como semente da migração.
- **Painel** — a faixa 2 usa a meta vigente do período exibido; o gráfico da faixa 3 desenha a **linha de meta em degraus**, mudando junto com a vigência. É o detalhe que prova que o histórico é honesto.
- **Menu lateral** — item **Metas**, visível apenas para Arquiteto e Diretor.
- **Faixa 1 do painel** — nova pendência: *"CMV por família sem meta definida em 9 de 12 famílias"*, para Diretor e Arquiteto apenas.

---

## 8. Fases de execução

| # | Entrega | Verificação |
|---|---|---|
| ~~1~~ | ~~Papel DIRETOR, modelo `Meta` com vigência, `servicos/metas.py` e migração da meta atual (29%)~~ **FEITO em 14/08/2026** | Meta vigente resolvida corretamente para datas passadas e futuras; herança família → bloco → geral |
| ~~2~~ | ~~Tela **Metas** (CMV, famílias, perdas, faturamento, histórico)~~ **FEITO em 14/08/2026** | Só Arquiteto e Diretor editam; salvar cria vigência nova e fecha a anterior, sem apagar nada |
| ~~3~~ | ~~`servicos/painel.py` + `GET /dashboard/painel`, com a regra de encaixe no ciclo~~ **FEITO em 14/08/2026** | Agosto encaixa em INV-1002 → INV-1003 e bate com o Motor de CMV |
| ~~4~~ | ~~Faixas 0, 1 e 2 (contexto, pendências, KPIs)~~ **FEITO em 14/08/2026** | 5 KPIs com variação e sparkline; pendências somem quando a lista vem vazia |
| ~~5~~ | ~~Faixa 3 (CMV × meta no tempo com linha em degraus, composição)~~ **FEITO em 14/08/2026** | A meta muda de patamar na data da vigência (`stepped: true`) |
| ~~6~~ | ~~Faixas 4 e 5 (top itens, perdas, estoque parado, atividade)~~ **FEITO em 14/08/2026** | Top 10 em barras CSS; estoque parado e atividade recente |
| ~~7~~ | ~~Polimento: skeleton, responsividade, estados vazios~~ **FEITO em 14/08/2026** | Esqueleto de carregamento, 3 pontos de quebra, ausência declarada em vez de zero |

As metas vieram antes do painel de propósito: a faixa de KPIs e o gráfico de tendência dependem de saber qual meta valia em cada período. Construir o painel primeiro significaria refazê-lo depois.

**Medição de desempenho (fase 3):** o painel com 5 períodos de histórico responde em ~60 ms contra o banco real; com 12 períodos, ~65 ms. O cache previsto na seção 9 não foi implementado porque não é necessário — otimizar antes de medir teria sido trabalho perdido.

Cada fase deixa o painel **utilizável ao fim dela** — nada de tela quebrada entre etapas.

---

## 9. Riscos e como tratá-los

**A série histórica pode ficar lenta.** Seis períodos = seis execuções do motor a cada abertura do painel. Medir na fase 1; se passar de ~300 ms, guardar o resultado por `(unidade, período)` e invalidar quando um inventário for finalizado. Não otimizar antes de medir.

**Mês do calendário distorce o CMV.** Já demonstrado na seção 3. Mitigado pelo encaixe no ciclo e pela procedência escrita no cabeçalho. Se o par de inventários não existir, o painel declara a ausência em vez de mostrar zero.

**Mudar a meta reescreve o passado.** Resolvido pela vigência (seção 7.2), mas vale o alerta: se as metas fossem campos simples, cada ajuste da diretoria falsificaria retroativamente todo o histórico de acompanhamento. É o tipo de erro que ninguém percebe até uma reunião em que os números não fecham com a ata do trimestre anterior.

**Metas incoerentes entre si.** Comida a 34% e bebida a 22%, no mix real de faturamento, podem não convergir para a meta geral. A tela avisa, mas não bloqueia — durante uma transição de cardápio a divergência pode ser deliberada.

**Faturamento incompleto envenena o CMV %.** Com um único período de faturamento lançado no banco, o percentual do mês é frágil. Por isso o "faturamento não lançado" é pendência **urgente** na faixa 1, e o KPI de CMV % aparece marcado quando a cobertura do período estiver incompleta.

**REGIONAL no futuro.** A assinatura do endpoint já aceita ausência de `unidade_id` como sinal de consolidação. Quando a visão regional chegar, ela é uma tela nova consumindo o mesmo serviço — não uma reescrita do painel.

---

## 10. O que este painel passa a responder

Antes: *"o sistema tem 244 produtos cadastrados."*

Depois, em cinco segundos de olhar:

- O CMV do mês está em 28,4%, abaixo da meta de 29% — e vem caindo há três ciclos.
- R$ 812 viraram perda, 2,2% do CMV, e mais da metade por validade vencida.
- Batata doce, contrafilé e muçarela respondem por 31% de todo o custo do mês.
- R$ 3.400 estão parados em itens sem giro há mais de 30 dias.
- Falta lançar o faturamento de agosto, e 187 itens estão sem custo — os dois pendurando a confiabilidade de tudo acima.
