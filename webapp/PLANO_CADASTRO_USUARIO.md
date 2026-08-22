# Cadastro de usuário — o que falta para fechar o ciclo

O aceite por convite já funciona: link `/#convite/SOLO-XXXX-XXXX`, a pessoa vê
o que está recebendo e cria a conta com **nome, login e senha**.

Falta o que você apontou: **e-mail**. E, atrás dele, três coisas que hoje não
existem e que só fazem sentido juntas.

---

## 1. O estado de hoje, sem maquiagem

| | Solo Rotinas | Solo CMV |
|---|---|---|
| Cadastro fechado por convite | sim | **sim** (feito) |
| Campo `email` no usuário | sim | **não existe em models.py** |
| Recuperação de senha | via e-mail | **não existe** |
| Criar usuário sem convite | não | **sim — a tela de Usuários faz isso** |

As duas últimas linhas são o problema real.

### 1.1 A porta que ficou aberta

`routers/usuarios.py` continua criando conta direto: um ADMIN digita nome,
login, **senha** e papel, e o usuário nasce. Isso contradiz o cadastro
fechado, e de um jeito pior do que parece: **outra pessoa escolhe a senha**.
Quem entra pela primeira vez usando uma senha que o chefe digitou não tem
senha — tem um segredo compartilhado.

O convite existe justamente para que só o dono da conta conheça a própria
senha.

### 1.2 Sem e-mail, esquecer a senha é perder a conta

Não há "esqueci minha senha". Hoje a saída é alguém com acesso ao banco
trocar o hash à mão. Com duas lojas e cinco pessoas isso passa; num
restaurante com rotatividade de estoquista, vira chamado toda semana.

O e-mail não é um campo de ficha — é o que torna a recuperação possível.

---

## 2. O que implementar

### 2.1 Campo `email` no usuário

```
email = Column(String(200), nullable=True, index=True)
```

Nulo permitido, e com motivo: os usuários que já existem não têm e-mail, e
uma migração não pode inventar um. Quem entra por convite daqui em diante
informa o dele.

**Único?** Sim, mas com cuidado: unicidade em coluna que aceita nulo funciona
no PostgreSQL e no SQLite (vários nulos são permitidos), então dá para exigir
sem quebrar quem já está lá. Evita duas contas disputando a mesma caixa de
entrada na hora de recuperar a senha.

### 2.2 Campo `email` no convite

Quem convida já sabe para quem está convidando. Preencher o e-mail no convite
traz duas coisas:

- a tela de aceite abre com o campo preenchido, e a pessoa só confirma;
- fica registrado **para quem** o convite foi emitido, em vez de só um recado
  em texto livre.

Se ficar vazio no convite, a pessoa informa no aceite. O convite manda quando
está preenchido — pelo mesmo princípio de sempre: o que vem do convite é
decidido por quem tinha autoridade.

### 2.3 Fechar a criação direta em Usuários

`POST /api/usuarios` deixa de criar conta. A tela passa a ter dois blocos:

- **Convidar** — leva para a tela de Convites, que é onde a conta nasce;
- **Administrar quem já entrou** — ativar, desativar, trocar papel, ajustar
  unidades. Isso continua sendo trabalho do ADMIN.

Editar acesso é diferente de criar acesso. O primeiro é rotina; o segundo é
uma decisão que precisa deixar rastro — e o convite deixa: quem emitiu, para
quem, quando, com o quê.

### 2.4 Recuperação de senha

Três rotas, uma tela:

```
POST /api/auth/recuperar        { email }        → sempre 200
GET  /api/auth/recuperar/{token} → confere o token
POST /api/auth/redefinir        { token, senha }
```

Uma tabela `tokens_recuperacao`: token, usuario_id, expira_em (1 hora),
usado_em. Uso único, como o convite.

**Detalhe que não é detalhe:** a primeira rota devolve 200 mesmo quando o
e-mail não existe. Responder "e-mail não cadastrado" entrega ao curioso a
lista de quem tem conta no sistema. A mensagem na tela é sempre a mesma:
"se este e-mail estiver cadastrado, você receberá as instruções".

### 2.5 O envio — e o problema honesto

Nada disso envia e-mail sozinho. Não há SMTP configurado, e o servidor é uma
Contabo sem serviço de e-mail. Duas saídas:

**a) Serviço de envio** (Resend, Brevo, SendGrid — todos com faixa gratuita
suficiente para este volume). Meia hora de configuração, uma chave no `.env`,
e o convite passa a chegar por e-mail além do link.

**b) Continuar no link copiado.** O convite já funciona assim. Para a
recuperação de senha, porém, não serve: o link teria que passar pela pessoa
que esqueceu a senha, e quem entrega o link é justamente quem não deveria
poder redefinir a senha dos outros.

Ou seja: **recuperação de senha exige (a)**. O convite vive sem.

---

## 3. Ordem sugerida

1. `email` no `Usuario` e no `Convite` + migração
2. Aceite passa a pedir e-mail; validação de formato e de unicidade
3. Fechar `POST /api/usuarios`; tela de Usuários vira administração
4. Tela de Usuários reflete o escopo novo (hoje ela não oferece "todas as
   lojas", que o convite já concede — as duas telas discordam)
5. Envio por e-mail (item 2.5a)
6. Recuperação de senha, que depende do 5

Do 1 ao 4 não depende de nada externo e fecha a contradição do cadastro
aberto. O 5 e o 6 dependem de escolher o serviço de envio.

---

## 4. O que preciso que você decida

**E-mail obrigatório no aceite?** Sugiro **sim** para quem entra daqui em
diante. Opcional significa que metade das contas não poderá recuperar a
senha, e ninguém descobre isso até precisar.

**Serviço de envio.** Se topar o item 2.5a, digo qual configurar e faço.
Sem ele, o passo 6 não sai do papel — e prefiro dizer isso agora a entregar
uma tela de "esqueci minha senha" que não manda nada.

**A tela de Usuários deixa de criar conta?** É a mudança que mais mexe na
rotina de quem já usa o sistema. Se preferir manter a criação direta como
exceção para o Arquiteto, dá para fazer — mas aí ela precisa gerar senha
aleatória e forçar troca no primeiro acesso, senão volta o problema do
segredo compartilhado.
