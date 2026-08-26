"""
Achar um produto pelo nome que a pessoa usa.

POR QUE ISTO É INFRAESTRUTURA, E NÃO ENFEITE
--------------------------------------------
O bot inteiro depende de transformar "bata doce" em `produto 111008`. Quem
faz a contagem é o auxiliar de cozinha, o estoquista, o ajudante — gente que
sabe "batata doce, cinco quilos" e que nunca vai decorar que batata doce é
111008. Exigir o código é reintroduzir o atrito que o bot veio eliminar.

O código existe para o SISTEMA, não para a pessoa.

`ilike` NÃO RESOLVE, EM NENHUM DOS DOIS BANCOS
----------------------------------------------
"mucarela" não acha "Muçarela" no SQLite nem no PostgreSQL sem ajuda. No
PostgreSQL a solução elegante são as extensões `unaccent` e `pg_trgm`; elas
exigem instalação no servidor, e vale migrar para lá quando houver — aí a
busca passa a tolerar erro de digitação de verdade ("gengibri" achando
"Gengibre").

Enquanto isso, normalizamos em Python. Com 244 produtos isso é instantâneo:
carrega, compara, devolve. A escolha é deliberada — esperar o PostgreSQL para
começar seria adiar o que resolve dor real por uma otimização que ninguém
sente neste tamanho.

ORDENAR IMPORTA TANTO QUANTO ACHAR
-----------------------------------
Quem digita "batata" contando o Hortifruti quase nunca quer "Batata palha
800g" da Mercearia. E item já contado neste inventário quase nunca é o que
se procura em seguida. Uma lista de candidatos na ordem errada obriga a ler
tudo — e ler tudo no celular, com a mão fria, é onde se toca no botão errado.
"""
import unicodedata
from dataclasses import dataclass
from typing import List, Optional, Sequence

from sqlalchemy.orm import Session

from models import InventarioItem, Produto, SessaoInventario, SinonimoProduto


def normalizar(texto: str) -> str:
    """Sem acento, sem caixa, sem espaço sobrando.

    NFD separa a letra do acento; descartar a categoria "Mn" (marca sem
    largura) deixa "muçarela" e "mucarela" idênticos — que é o caso real,
    porque ninguém digita cedilha no teclado do celular com pressa.
    """
    if not texto:
        return ""
    sem_acento = unicodedata.normalize("NFD", str(texto))
    sem_acento = "".join(c for c in sem_acento
                         if unicodedata.category(c) != "Mn")
    return " ".join(sem_acento.lower().split())


@dataclass
class Candidato:
    produto_id: int
    codigo: str
    nome: str
    unidade_medida: str
    categoria: Optional[str]
    pontos: float
    ja_contado: bool = False
    no_escopo: bool = True


def _pontuar(termo_norm: str, nome_norm: str) -> float:
    """Quanto este nome responde ao que foi digitado.

    A escala não é arbitrária: ela reflete o que a pessoa provavelmente quis.
    Nome exato ganha de prefixo, que ganha de "contém", que ganha de "todas as
    palavras aparecem soltas". O último caso é o que faz "bata doce" achar
    "Batata Doce" — cada palavra digitada precisa aparecer no começo de
    alguma palavra do nome.
    """
    if not termo_norm:
        return 0.0
    if nome_norm == termo_norm:
        return 100.0
    if nome_norm.startswith(termo_norm):
        return 80.0
    if termo_norm in nome_norm:
        return 60.0

    palavras_termo = termo_norm.split()
    palavras_nome = nome_norm.split()
    if not palavras_termo:
        return 0.0

    casadas = 0
    for pt in palavras_termo:
        # Prefixo de palavra, não substring solta: senão "ada" casaria com
        # "salada" e a lista encheria de coisa que a pessoa não pediu.
        if any(pn.startswith(pt) for pn in palavras_nome):
            casadas += 1
    if casadas == len(palavras_termo):
        return 40.0 + casadas
    if casadas:
        return 10.0 * casadas / len(palavras_termo)
    return 0.0


def buscar(db: Session, termo: str, empresa_id: Optional[int] = None,
           sessao_inventario: Optional[SessaoInventario] = None,
           limite: int = 8) -> List[Candidato]:
    """Candidatos para o que foi digitado, do mais provável ao menos.

    `sessao_inventario` muda a ordem e, quando o inventário não é geral,
    esconde o que está fora do escopo: contando Hortifruti, "cerveja" não
    deve nem aparecer — seria recusado depois, e oferecer para então recusar
    é o pior dos dois mundos.
    """
    termo_norm = normalizar(termo)
    if len(termo_norm) < 2:
        return []

    query = db.query(Produto).filter(Produto.ativo.is_(True))
    if empresa_id:
        query = query.filter(Produto.empresa_id == empresa_id)
    produtos = query.all()

    ids_escopo = None
    ja_contados = set()
    if sessao_inventario is not None:
        itens = sessao_inventario.itens
        ids_escopo = {i.produto_id for i in itens}
        ja_contados = {i.produto_id for i in itens
                       if i.quantidade_contada is not None}

    # Apelidos aprendidos ("bata doce" → 111008). Entram como um nome a mais
    # do produto, com bônus por uso: apelido confirmado 40 vezes vale mais
    # que um digitado uma vez por engano.
    apelidos = {}
    for s in db.query(SinonimoProduto).filter(
            SinonimoProduto.fornecedor_id.is_(None)).all():
        apelidos.setdefault(s.produto_id, []).append(s)

    saida = []
    for p in produtos:
        pontos = _pontuar(termo_norm, normalizar(p.nome))

        # O código digitado inteiro é resposta exata — quem tem a folha de
        # contagem impressa na mão manda "111008 12,5" e não deveria passar
        # por desambiguação nenhuma.
        if p.codigo and normalizar(p.codigo) == termo_norm:
            pontos = 120.0

        for s in apelidos.get(p.id, []):
            p_apelido = _pontuar(termo_norm, normalizar(s.termo))
            if p_apelido:
                pontos = max(pontos, p_apelido + min(s.usos, 10))

        if pontos <= 0:
            continue

        no_escopo = ids_escopo is None or p.id in ids_escopo
        if ids_escopo is not None and not no_escopo:
            continue      # fora do escopo do inventário: nem oferece

        saida.append(Candidato(
            produto_id=p.id, codigo=p.codigo, nome=p.nome,
            unidade_medida=p.unidade_medida,
            categoria=p.categoria.nome if p.categoria else None,
            pontos=pontos,
            ja_contado=p.id in ja_contados,
            no_escopo=no_escopo,
        ))

    # Já contado vai para o fim: recontar existe, mas é a exceção. Empate
    # resolve por nome, para a lista não dançar entre duas chamadas iguais —
    # ordem instável no celular é o que faz tocar no botão errado.
    saida.sort(key=lambda c: (c.ja_contado, not c.no_escopo, -c.pontos, c.nome))
    return saida[:limite]


def aprender(db: Session, produto_id: int, termo: str,
             fornecedor_id: Optional[int] = None,
             fator: float = 1.0) -> None:
    """Guarda que ESTE texto significa ESTE produto.

    Chamado quando a pessoa escolhe um candidato depois de digitar algo que
    não casou direto. Na segunda vez, a mesma digitação acerta sozinha.
    """
    termo_norm = normalizar(termo)
    if len(termo_norm) < 2:
        return
    existente = db.query(SinonimoProduto).filter(
        SinonimoProduto.produto_id == produto_id,
        SinonimoProduto.termo == termo_norm,
        SinonimoProduto.fornecedor_id.is_(fornecedor_id) if fornecedor_id is None
        else SinonimoProduto.fornecedor_id == fornecedor_id,
    ).first()
    if existente:
        existente.usos += 1
    else:
        db.add(SinonimoProduto(produto_id=produto_id, termo=termo_norm,
                               fornecedor_id=fornecedor_id,
                               fator_conversao=fator, usos=1))
    db.commit()


PONTOS_EXATO = 100.0


def como_dicionario(candidatos: Sequence[Candidato]) -> List[dict]:
    """A lista para quem for oferecer as opções — com `exato` calculado aqui.

    A pontuação existia e não saía da API, e o efeito aparecia no bot: quem
    escrevia "batata doce" INTEIRO recebia um menu com Batata Doce, Batata
    Baroa e Batata Inglesa. A resposta certa estava em primeiro lugar, com
    100 pontos contra 42 das outras — e o cliente não tinha como saber disso,
    porque só recebia a ordem.

    `exato` é essa informação: houve um nome idêntico ao que foi digitado, e
    só um. Quem oferece opções pode então pular a pergunta — que é a mesma
    regra de "uma opção só não vira pergunta", aplicada à relevância em vez
    de à contagem.
    """
    perfeitos = [c for c in candidatos if c.pontos >= PONTOS_EXATO]
    unico_perfeito = perfeitos[0].produto_id if len(perfeitos) == 1 else None
    return [
        {"produto_id": c.produto_id, "codigo": c.codigo, "nome": c.nome,
         "unidade_medida": c.unidade_medida, "categoria": c.categoria,
         "ja_contado": c.ja_contado, "no_escopo": c.no_escopo,
         "exato": c.produto_id == unico_perfeito}
        for c in candidatos
    ]


def extrair_intencao_contagem(texto: str) -> tuple[Optional[str], Optional[float], str]:
    """
    Analisa a mensagem do usuário no fluxo de contagem.
    Retorna: (termo_busca, quantidade, modo)
    onde modo pode ser:
      - "SOMAR": acumula quantidade (padrão)
      - "SUBSTITUIR": sobrescreve a contagem (usando '=', 'corrigir', 'zero', 'zerar', '0')
      - "CONSULTAR": apenas digitou o nome do produto sem quantidade
    """
    txt = (texto or "").strip()
    if not txt:
        return None, None, "CONSULTAR"

    # Se começa com '='
    if txt.startswith("="):
        val_str = txt[1:].strip().replace(",", ".")
        try:
            return None, float(val_str), "SUBSTITUIR"
        except ValueError:
            pass

    # Termos de zero / zerado
    if txt.lower() in ("0", "zero", "zerar", "zerado", "nenhum", "nao tem", "não tem", "sem estoque"):
        return None, 0.0, "SUBSTITUIR"

    # Apenas número: "15", "+5", "12.5", "12,5"
    num_puro = txt.replace(",", ".").strip()
    if num_puro.startswith("+"):
        num_puro = num_puro[1:].strip()
    try:
        val = float(num_puro)
        return None, val, "SOMAR"
    except ValueError:
        pass

    # Nome com '=' (ex: "tomate = 12" ou "tomate=12" ou "tomate 12 =")
    if "=" in txt:
        partes = txt.split("=", 1)
        termo = partes[0].strip()
        val_str = partes[1].strip().replace(",", ".")
        try:
            val = float(val_str)
            return termo or None, val, "SUBSTITUIR"
        except ValueError:
            try:
                val = float(partes[0].strip().replace(",", "."))
                return partes[1].strip() or None, val, "SUBSTITUIR"
            except ValueError:
                pass

    # Nome com prefixo 'corrigir' (ex: "corrigir tomate 12")
    if txt.lower().startswith("corrigir ") or txt.lower().startswith("correcao ") or txt.lower().startswith("correção "):
        resto = txt.split(maxsplit=1)[1].strip()
        partes = resto.rsplit(maxsplit=1)
        if len(partes) == 2:
            termo = partes[0].strip()
            val_str = partes[1].replace(",", ".").strip()
            try:
                val = float(val_str)
                return termo, val, "SUBSTITUIR"
            except ValueError:
                pass

    # Nome com sufixo zero (ex: "tomate zero", "tomate 0")
    for z in (" zero", " 0", " zerar", " nao tem", " não tem"):
        if txt.lower().endswith(z):
            termo = txt[: -len(z)].strip()
            return termo, 0.0, "SUBSTITUIR"

    # Nome + Quantidade no final: "tomate 10", "batata doce +5", "cerveja 24"
    partes = txt.rsplit(maxsplit=1)
    if len(partes) == 2:
        val_str = partes[1].replace(",", ".").strip()
        eh_soma_explicita = val_str.startswith("+")
        if eh_soma_explicita:
            val_str = val_str[1:].strip()
        try:
            val = float(val_str)
            return partes[0].strip(), val, "SOMAR"
        except ValueError:
            pass

    # Se não identificou número, trata como consulta de produto
    return txt, None, "CONSULTAR"
