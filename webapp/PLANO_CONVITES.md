# Convites no Solo CMV — o que precisa existir antes

Li o sistema do Solo Rotinas (`routers/convites.py`, `auth/registro_core.py`,
modelo `Convite` em `database.py`). O mecanismo é bom e vale copiar. As regras
não transferem: lá o convite carrega um nível; aqui precisa carregar **papel +
unidades + acesso regional**, que é justamente o que o Solo CMV protege.

---

## 1. O que vale copiar do Solo Rotinas

**O formato do código.** `SOLO-XXXX-XXXX`, alfabeto sem caracteres ambíguos —
sem `0/O`, sem `1/I/L`. O motivo está no comentário de lá: o código é ditado
por voz ou WhatsApp. É um detalhe pequeno que evita muito suporte.

**Os quatro estados derivados, não guardados:** `DISPONIVEL`, `USADO`,
`EXPIRADO`, `REVOGADO`. Calcular na hora, a partir de `revogado`,
`usado_por_id` e `expira_em`, evita estado que envelhece sozinho.

**A rota pública de validação** antes de enviar o formulário. Quem recebeu um
convite ruim descobre na hora, e não depois de digitar tudo.

**A queima do convite** no ato do registro: `usado_por_id` + `usado_em`, uso
único. E revogar só é permitido enquanto não foi usado.

**Regra concentrada num módulo só** (`registro_core.py` lá) para que os dois
caminhos de entrada não divirjam.

## 2. O que NÃO transfere

| Solo Rotinas | Solo CMV |
|---|---|
| Só o Arquiteto convida | Arquiteto **e** Diretor |
| `nivel_acesso` como texto livre | `PapelUsuario`, enum de verdade |
| Sem unidades, sem empresa | O convite **precisa** carregar as duas |
| Badges, auras, fragmentos, assinatura | Não existem aqui |

---

## 3. Pré-requisitos — o que precisa ser implementado

### 3.1 Modelo `Convite`

```
codigo            String(20) único, indexado
empresa_id        FK empresas          — a qual empresa o convidado pertence
criado_por_id     FK usuarios
papel             Enumerado(PapelUsuario)
acesso_regional   Boolean
nota              String(200)          — "para a Maria, do estoque"
expira_em         DateTime, nulo = não expira
revogado          Boolean
usado_por_id      FK usuarios, nulo
usado_em          DateTime, nulo
criado_em         DateTime
```

Mais uma tabela de vínculo `convite_unidade`, no mesmo padrão do
`usuario_unidade` que já existe. Preferi tabela a JSON pela integridade: se
uma unidade for removida, o convite não fica apontando para um fantasma.

### 3.2 Migração em `migracoes.py`

Seguindo o padrão do arquivo, sensível ao dialeto — a constante `FALSO`
(`FALSE` no PostgreSQL, `0` no SQLite) e `TIMESTAMP` em vez de `DATETIME`.
Duas tabelas novas, nada a alterar nas existentes.

### 3.3 As regras de autorização

É aqui que mora o valor. Escrito como você descreveu:

1. **Arquiteto está acima de todos** e é o único que pode conceder o papel de
   Arquiteto.
2. **Diretor convida qualquer pessoa** dentro da empresa dele, com qualquer
   papel **exceto** Arquiteto.
3. **O convite nasce na empresa de quem convida.** O Arquiteto tem
   `empresa_id` nulo — ele atravessa empresas —, então quando é ele quem
   convida, a empresa precisa ser escolhida explicitamente. Sem isso o
   convidado nasceria órfão.
4. **Ninguém concede unidade que não enxerga.** Já existe
   `servico_escopo.unidades_permitidas`; a mesma função decide o que pode ser
   oferecido no convite. Para o Diretor isso é toda a empresa dele.
5. **`acesso_regional` só é concedido por quem o tem** — já existe
   `pode_ver_regional`. É permissão à parte do papel, e continua sendo.
6. **Papéis irrestritos não precisam de lista de unidades**, pelo mesmo
   motivo que hoje: eles passam por cima dela.

### 3.4 A armadilha — e é séria

A rota de aceite é **pública**: quem a chama ainda não tem conta, logo não tem
token. E o guarda de unidade (`auth/guarda_unidade.py`) tem esta regra:

```python
if not autorizacao.lower().startswith("bearer "):
    return await self.app(scope, receber, send)   # sem token, a rota devolve 401
```

O comentário assume que toda rota que carrega `unidade_id` exige autenticação.
A rota de aceite quebra essa suposição: ela passa direto pelo guarda.

**Consequência:** se o aceite ler papel ou unidades do corpo do pedido,
qualquer um se concede o que quiser. O convite viraria uma porta lateral em
volta de todo o controle de acesso.

**Como fechar:** o corpo do aceite carrega **apenas** `codigo`, `nome`,
`login` e `senha`. Papel, unidades, empresa e regional saem exclusivamente do
registro do convite, que foi gravado por quem tinha autoridade. O cliente não
opina.

Vale um teste dedicado: mandar `papel: "ARQUITETO"` e `unidade_ids: [1,2,3]`
no corpo do aceite e provar que são ignorados.

### 3.5 Rota pública no frontend

Hoje o `app.js` faz: tem token? abre o sistema. Não tem? tela de login. Não
existe terceiro caminho.

Precisa de um: `#convite/SOLO-XXXX-XXXX` renderiza a tela de cadastro **antes**
da checagem de sessão. Mexe em `app.js` e `router.js`.

A tela mostra o que o convite concede — papel, unidades, quem convidou — para
a pessoa saber o que está aceitando, e pede nome, login e senha.

### 3.6 Regra de senha

O `hash_senha` já trata o limite de 72 bytes do bcrypt. Falta definir o
mínimo. Sugiro 10 caracteres, validado no backend (nunca só na tela), com a
mensagem dizendo a regra antes de a pessoa digitar.

### 3.7 Entrega do convite

Sem servidor de e-mail configurado, o caminho natural é **link**:

```
https://solocmv.duckdns.org/#convite/SOLO-K3M9-P7QR
```

Copiável, mandado por WhatsApp. O código aparece junto em texto, para quando
o link quebra no meio da mensagem — foi para isso que o alfabeto do Rotinas
tirou os caracteres ambíguos.

E-mail pode vir depois sem mudar nada do resto.

---

## 4. Três decisões que eu não tomo sozinho

**Expiração padrão.** O Rotinas usa 30 dias. Sugiro 7 para o CMV: convite de
trabalho ou é aceito na semana ou virou esquecimento. Continua podendo ser
sem prazo.

**Quem lista o quê.** No Rotinas, cada um vê só os convites que criou. Aqui o
Diretor provavelmente quer ver todos os da empresa dele — inclusive os que um
Admin criou. Sugiro: Diretor e Arquiteto veem todos do escopo deles; os demais
veem os próprios.

**Convidar quem já tem conta.** Hoje o login é único no sistema inteiro. Se a
pessoa já existe, o aceite deve falhar dizendo isso, ou o convite deve servir
para *acrescentar* unidades a quem já está lá? Sugiro falhar, e tratar
acréscimo de acesso pela tela de Usuários, que já existe. Misturar os dois
deixa o convite ambíguo.

---

## 5. Ordem de implementação

1. Modelo + migração + tabela de vínculo
2. `servicos/convites.py` — geração, validação e aceite num lugar só
3. Rotas protegidas: gerar, listar, revogar
4. Rotas públicas: validar e aceitar
5. Testes: as regras de autorização, a queima, e a armadilha do 3.4
6. Tela de convites (Diretor e Arquiteto) e tela pública de aceite
7. Teste de tela em jsdom, como as outras oito

Do 1 ao 5 o sistema já funciona por API. O 6 e o 7 são a parte visível.
