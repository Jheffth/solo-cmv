# Motor de CMV — especificação extraída das planilhas

Documento levantado a partir das fórmulas reais de
`INVENTÁRIO E CMV JUNHO - JOSEFINA.xlsm` e `- CASA JOSEFINA.xlsm`.
É a referência para implementar o motor no Solo CMV.

---

## 1. Estrutura da planilha

| Aba | Papel |
|---|---|
| `SEM01`…`SEM06` | Uma tabela por semana do mês. É onde o CMV nasce. |
| `RESUMO` | Consolida as semanas no mês e faz o desdobramento comida/bebida. |
| `Relatório` | Só apresentação: puxa números do RESUMO com `HLOOKUP`. |

Cada aba semanal tem 4 blocos de colunas por produto:

| Bloco | Qtd | Custo un. | Valor |
|---|---|---|---|
| Contagem Inicial | F | G | **H = F × G** |
| Compras | I | J | **K = I × J** |
| Contagem Final | L | M | **N = L × M** |
| CMV Real | O | P | **Q = (H + K) − N** |

Fórmulas exatas de uma linha de produto:

```
H = Qtd_inicial × Custo_inicial
K = SE(Qtd_compra=""; ""; Qtd_compra × Custo_compra)
N = Qtd_final × Custo_final
O = SE((Qtd_inicial + Qtd_compra) − Qtd_final = 0; " "; (Qtd_inicial + Qtd_compra) − Qtd_final)
P = Custo_final          ← o custo do CMV é sempre o da contagem final
Q = SEERRO((H + K) − N; " ")
```

### Totais da semana

```
Estoque Inicial = SOMA(H)
Compras         = SOMA(K)
Estoque Final   = SOMA(N)
CMV Real        = SOMA(Q)
Faturamento     = informado à mão na célula G1
CMV %           = CMV Real ÷ Faturamento
```

---

## 2. Consolidação mensal (RESUMO)

```
CMV Real do mês = soma dos CMV Real das semanas
CMV % do mês    = CMV Real do mês ÷ Faturamento do mês
LACUNA          = Meta − CMV %          (meta na célula A10; hoje 29%)
Dif. semana     = CMV % da semana anterior − CMV % da semana atual
```

### Desdobramento comida × bebida

```
EI Bebida  = SOMASE(família; "*Bebidas bar*"; coluna H)
C  Bebida  = SOMASE(família; "*Bebidas bar*"; coluna K)
EF Bebida  = SOMASE(família; "*Bebidas bar*"; coluna N)
CMV Bebida = EI Bebida + C Bebida − EF Bebida

EI Comida  = EI total − EI Bebida        ← comida é "tudo que não é bebida"
C  Comida  = C total  − C Bebida
EF Comida  = EF total − EF Bebida
CMV Comida = EI Comida + C Comida − EF Comida

Fat. Bebida = informado à mão
Fat. Comida = Faturamento total − Fat. Bebida
CMV Comida % = CMV Comida ÷ Fat. Comida
CMV Bebida % = CMV Bebida ÷ Fat. Bebida
```

---

## 3. Despesas de ajuste — **não entram no CMV**

As caixas no topo de cada aba semanal (consumo interno, material de limpeza,
embalagens, testes/mkt, outras despesas) são somadas no RESUMO sob o rótulo
**"PARA DRE"**. Conferi as fórmulas: nenhuma delas é subtraída do CMV Real.

Ou seja, hoje elas são apenas segregadas para a DRE — o CMV é bruto.

---

## 4. Problemas encontrados na planilha

### 4.1 O desdobramento bebida está quebrado (crítico)

O `SOMASE` procura a família `"*Bebidas bar*"`, mas **nenhuma família tem
esse nome**. As famílias reais são:

```
Bar · Bebidas sem álcool · Carnes · Cervejas · Defumados
Hortifruti · Mercearia · Peixes e Frutos do Mar · Resfriados
```

Resultado nas duas planilhas, em todas as semanas:

```
CMV Bebida   = 0,00
CMV Bebida % = #DIV/0!
CMV Comida   = 100% do CMV
```

O indicador de bebida nunca funcionou. Provavelmente a família se chamava
"Bebidas bar" numa versão antiga e foi desmembrada em Cervejas / Bebidas sem
álcool / Bar sem atualizar a fórmula.

### 4.2 Fórmulas sobrescritas por valores digitados

Em `SEM02`, as linhas 52 (*Manteiga de garrafa*) e 57 (*Nhoque 500g*) têm a
célula de CMV com um `0` digitado no lugar da fórmula. Os blocos de estoque e
compra seguem preenchidos, então o CMV do item some:

| Linha | Produto | EI | Compras | EF | Deveria ser | Está |
|---|---|---|---|---|---|---|
| 52 | Manteiga de garrafa | 0,00 | 37,00 | 26,80 | 10,20 | 0,00 |
| 57 | Nhoque 500g | 11,90 | 71,40 | 23,80 | 59,50 | 0,00 |

Efeito: o CMV da semana 02 fica **R$ 69,70 abaixo** do correto.

### 4.3 Estoque inicial e final do mês somam as semanas

No RESUMO, `EI do mês` e `EF do mês` somam as cinco semanas. Conceitualmente
o EI do mês é o da **primeira** semana e o EF do mês é o da **última** — que
é justamente como as linhas de comida e bebida fazem (`H13 = C13`,
`H15 = G15`). As linhas gerais ficaram diferentes das linhas do desdobramento.

Isso não afeta o CMV do mês, porque ele é calculado como soma dos CMVs
semanais (onde os estoques intermediários se cancelam). Mas os campos "EI do
mês" e "EF do mês" exibidos hoje não significam o que o rótulo diz.

### 4.4 Faturamento de bebida nunca preenchido

A linha `Fat. Bebida` está vazia em todas as semanas das duas planilhas, o
que deixaria `CMV Bebida %` sem denominador mesmo que o item 4.1 fosse
corrigido.

---

## 5. Como fica no Solo CMV

### O inventário substitui as colunas de contagem

Na planilha, "contagem inicial" e "contagem final" eram duas colunas
digitadas na aba da semana. No sistema elas são **dois inventários**:

```
estoque inicial = inventário finalizado até a data de início
estoque final   = inventário finalizado até a data de fim
compras         = notas lançadas entre os dois inventários
```

Quantidade **e custo** vêm da linha do inventário — o custo é o que estava
congelado quando ele foi fechado. Assim o relatório do inventário e o CMV
falam do mesmo número por construção.

A busca é **por produto**, não pelo inventário inteiro: se o Hortifruti foi
contado dia 10 e as Carnes dia 12, cada item usa o seu próprio par de
contagens. É o que faz o inventário rotativo funcionar.

Consequência prática: **não existe lançamento avulso de contagem**. A API
recusa um movimento de contagem fora de inventário, e a tela antes chamada
"Compras e Contagens" virou apenas **Compras** — ela lança compra e mostra o
livro-razão (compras, contagens vindas de inventários e requisições).
Manter os dois caminhos criaria duas fontes de verdade para o mesmo número,
que é justamente o problema que o inventário veio resolver.

A tela de CMV mostra de qual inventário veio cada ponta, para o número ter
origem rastreável.

O sistema já tem as peças: `Movimento` (compras e contagens), `VendaPeriodo`
(faturamento), `Categoria` (famílias) e `MetaCMV`.

```
Por produto, no período:
    valor_estoque_inicial = qtd_contagem_inicial × custo_contagem_inicial
    valor_compras         = Σ (qtd × custo) das compras do período
    valor_estoque_final   = qtd_contagem_final × custo_contagem_final
    cmv_item              = valor_estoque_inicial + valor_compras − valor_estoque_final

No período:
    CMV Real = Σ cmv_item
    CMV %    = CMV Real ÷ faturamento informado
    Lacuna   = meta − CMV %
```

O desdobramento comida/bebida passa a se apoiar em **quais famílias são
bebida**, configurável — e não num texto fixo na fórmula. Assim o problema
4.1 não se repete quando uma família for criada ou renomeada.

Diferenças estruturais que eliminam os problemas acima:

| Problema na planilha | No sistema |
|---|---|
| Fórmula sobrescrita por valor digitado (4.2) | Impossível: o cálculo é código, não célula |
| Família some do filtro ao ser renomeada (4.1) | Vínculo por id da família, não por texto |
| EI/EF do mês somando semanas (4.3) | EI = primeira contagem; EF = última contagem |
| Semana fixa em abas SEM01..SEM06 | Período livre (semana, mês, qualquer intervalo) |

---

## 6. Decisões tomadas (implementadas)

| Ponto | Decisão |
|---|---|
| **Famílias de bebida** | *Bar* + *Cervejas* = "Bebidas". Configurável por unidade em `ConfiguracaoCMV`, por id da família. |
| **Método de custo** | Alternável na tela: **Custo médio** (padrão) ou **Último custo** (reproduz a planilha). |
| **Modo de apuração** | Alternável na tela: **Período** isolado ou **Acumulado** desde o início do controle. |
| **Faturamento** | Lançado por período; no modo acumulado o sistema soma os períodos automaticamente. |
| **Despesas de ajuste** | Seguem fora do CMV, como na planilha. |

### Item que zera o estoque

```
contagem inicial 10 · sem compras · contagem final 0
CMV = 10 + 0 − 0 = 10 unidades
```

Estoque final zero **não** anula o custo — pelo contrário, joga o saldo
inteiro para dentro do CMV, porque tudo o que havia foi consumido. Se
houvesse compra de 5 e o final fosse 0, o CMV seria 15.

### Uma contagem serve a duas semanas

Na operação real, a contagem feita no fim de uma semana é a **mesma** que
abre a semana seguinte — ninguém conta duas vezes o mesmo estoque. Uma
contagem no dia 10/08 é, ao mesmo tempo:

- o **estoque final** da semana de 03 a 10/08;
- o **estoque inicial** da semana de 10 a 17/08.

O motor já trabalha assim: o estoque inicial de um período é a última
contagem até a data de início, e o final é a última contagem até a data de
fim. Não é preciso lançar a contagem duas vezes.

### Item sem contagem no fechamento

Se o item não for contado no fim do período, não há como saber o que sobrou.
Nesse caso o estoque final é o **saldo teórico**
(`inicial + compras − requisições`), de modo que o CMV do item reflita apenas
as saídas já registradas, em vez de fingir que tudo foi consumido. Esses
itens aparecem marcados como *estimado* na tela e contam num aviso.

Foi essa regra que fez os dois modos fecharem: a **soma dos períodos** passou
a bater exatamente com o **acumulado**, porque os estoques intermediários se
cancelam — a mesma propriedade que a planilha usa no RESUMO.

---

## 7. Achados adicionais na conferência do rodapé

O bloco final de cada aba semanal é uma cadeia de referências:

```
C(n)   Estoque Inicial   = H(total da tabela)
C(n+1) Compras           = K(total)
C(n+2) Estoque Final     = N(total)
C(n+3) CMV Real          = Q(total)
C(n+4) Faturamento       = G1        ← digitado à mão, sobrescrito a cada semana
C(n+5) CMV/Faturamento   = SEERRO(CMV ÷ Faturamento; "")
```

Conferindo essa cadeia nas duas planilhas, apareceram mais dois problemas:

### 7.1 O encadeamento das semanas quebra na Josefina

O estoque final de uma semana deveria ser o inicial da seguinte. Na **Casa
Josefina** isso acontece certinho. Na **Josefina**, não:

| Semana | Estoque final | Estoque inicial da seguinte | |
|---|---|---|---|
| SEM01 → SEM02 | 9.111,51 | 9.337,44 | quebra |
| SEM02 → SEM03 | 14.554,68 | 14.040,32 | quebra |
| SEM03 → SEM04 | 15.042,67 | 15.294,94 | quebra |

### 7.2 O RESUMO foi remendado com valores digitados

Nas duas planilhas, a linha "Estoque inicial" do RESUMO tem **fórmula apenas
na primeira semana**; as demais são números digitados à mão — justamente os
valores encadeados corretos, mascarando a quebra acima.

Pior: na Casa Josefina, o valor digitado para a SEM03 é **5.757,82**, mas o
estoque final real da SEM02 é **5.767,82**. Um dígito trocado, R$ 10,00 de
diferença que ninguém veria.

No sistema isso não acontece: o encadeamento é consequência do dado, não de
alguém digitar o número certo na célula certa.
