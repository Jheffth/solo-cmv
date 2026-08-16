"""
Seed inicial do Solo CMV.

Cria a empresa e as unidades a partir das planilhas de origem (Josefina e
Casa Josefina), o usuário Arquiteto com acesso irrestrito, e importa o
catálogo mestre (categorias, fornecedores e produtos) extraído das planilhas
"INVENTÁRIO E CMV JUNHO" para que o sistema já nasça com dados reais de
cadastro — sem precisar digitar tudo de novo.
"""
import json
import os
import secrets

from sqlalchemy.orm import Session

from database import SessionLocal
from models import Empresa, Unidade, Usuario, PapelUsuario, Categoria, Fornecedor, Produto
from auth.security import hash_senha
from codigos import gerar_codigo

SEED_DATA_PATH = os.path.join(os.path.dirname(__file__), "seed_data.json")

NOME_EMPRESA = "Josefina Gastronomia"
UNIDADES_INICIAIS = ["Josefina", "Casa Josefina"]

ARQUITETO_LOGIN = os.getenv("ARQUITETO_LOGIN", "Jh3ffth")
ARQUITETO_NOME = "Arquiteto"


def _senha_inicial() -> str:
    """A senha do primeiro usuário — nunca escrita no código.

    Senha em arquivo versionado é senha pública: qualquer pessoa com acesso
    ao repositório, hoje ou daqui a cinco anos, entra como Arquiteto. E como
    este sistema vai ser vendido a outros restaurantes, uma senha fixa no
    código seria a MESMA senha em toda instalação.

    Duas formas de definir, nesta ordem:

      1. Variável de ambiente `ARQUITETO_SENHA` — é o caminho de produção,
         e é o que o `.env` deve trazer.
      2. Nenhuma: geramos uma aleatória e imprimimos UMA vez, no momento em
         que o usuário é criado. Anote — não há como recuperá-la depois, só
         redefinir.

    Isto só roda quando o usuário ainda não existe. Instalação que já tem
    Arquiteto não é afetada: a senha atual continua valendo.
    """
    do_ambiente = os.getenv("ARQUITETO_SENHA")
    if do_ambiente:
        return do_ambiente

    senha = secrets.token_urlsafe(12)
    print("\n" + "=" * 68)
    print("  USUÁRIO ARQUITETO CRIADO")
    print(f"  login: {ARQUITETO_LOGIN}")
    print(f"  senha: {senha}")
    print("  Anote agora. Esta senha não será mostrada de novo.")
    print("  Para definir você mesmo, use ARQUITETO_SENHA no .env.")
    print("=" * 68 + "\n")
    return senha


def _get_or_create_empresa(db: Session) -> Empresa:
    empresa = db.query(Empresa).filter(Empresa.nome == NOME_EMPRESA).first()
    if empresa is None:
        empresa = Empresa(nome=NOME_EMPRESA)
        db.add(empresa)
        db.commit()
        db.refresh(empresa)
        print(f"[SEED] Empresa criada: {empresa.nome}")
    return empresa


def _get_or_create_unidades(db: Session, empresa: Empresa) -> list[Unidade]:
    unidades = []
    for nome in UNIDADES_INICIAIS:
        unidade = db.query(Unidade).filter(Unidade.empresa_id == empresa.id, Unidade.nome == nome).first()
        if unidade is None:
            unidade = Unidade(empresa_id=empresa.id, nome=nome)
            db.add(unidade)
            db.commit()
            db.refresh(unidade)
            print(f"[SEED] Unidade criada: {unidade.nome}")
        unidades.append(unidade)
    return unidades


def _get_or_create_arquiteto(db: Session, empresa: Empresa, unidades: list[Unidade]) -> Usuario:
    usuario = db.query(Usuario).filter(Usuario.login == ARQUITETO_LOGIN).first()
    if usuario is None:
        usuario = Usuario(
            empresa_id=empresa.id,
            nome=ARQUITETO_NOME,
            login=ARQUITETO_LOGIN,
            senha_hash=hash_senha(_senha_inicial()),
            papel=PapelUsuario.ARQUITETO,
            ativo=True,
        )
        usuario.unidades = unidades
        db.add(usuario)
        db.commit()
        db.refresh(usuario)
        print(f"[SEED] Usuário Arquiteto criado: login='{usuario.login}' (todas as permissões)")
    return usuario


def _importar_catalogo(db: Session, empresa: Empresa):
    if not os.path.exists(SEED_DATA_PATH):
        print("[SEED] seed_data.json não encontrado — catálogo mestre não importado.")
        return

    with open(SEED_DATA_PATH, "r", encoding="utf-8") as f:
        dados = json.load(f)

    # Categorias (Famílias)
    categorias_por_nome = {}
    for nome in dados.get("familias", []):
        cat = db.query(Categoria).filter(Categoria.empresa_id == empresa.id, Categoria.nome == nome).first()
        if cat is None:
            cat = Categoria(empresa_id=empresa.id, nome=nome)
            db.add(cat)
        categorias_por_nome[nome] = cat
    db.commit()
    for cat in categorias_por_nome.values():
        db.refresh(cat)
    if categorias_por_nome:
        print(f"[SEED] Categorias importadas/confirmadas: {len(categorias_por_nome)}")

    # Fornecedores
    total_fornecedores = 0
    for nome in dados.get("fornecedores", []):
        existe = db.query(Fornecedor).filter(Fornecedor.empresa_id == empresa.id, Fornecedor.nome == nome).first()
        if existe is None:
            db.add(Fornecedor(empresa_id=empresa.id, nome=nome))
            total_fornecedores += 1
    db.commit()
    if total_fornecedores:
        print(f"[SEED] Fornecedores importados: {total_fornecedores}")

    # Produtos — cada um recebe o código único de 6 dígitos do bloco da sua
    # família (ver codigos.py), no mesmo padrão da coluna "Cod." das planilhas.
    total_produtos = 0
    for item in dados.get("produtos", []):
        nome = item.get("nome")
        if not nome:
            continue
        existe = db.query(Produto).filter(Produto.empresa_id == empresa.id, Produto.nome == nome).first()
        if existe is not None:
            continue
        familia = item.get("familia")
        categoria = categorias_por_nome.get(familia)
        produto = Produto(
            empresa_id=empresa.id,
            categoria_id=categoria.id if categoria else None,
            nome=nome,
            unidade_medida=item.get("unidade_medida"),
            codigo=gerar_codigo(db, empresa.id, familia),
        )
        db.add(produto)
        db.flush()          # torna o código visível para o próximo gerar_codigo
        total_produtos += 1
    db.commit()
    if total_produtos:
        print(f"[SEED] Produtos importados do catálogo das planilhas: {total_produtos}")


def _preencher_codigos_faltantes(db: Session, empresa: Empresa):
    """Atribui código aos produtos que ainda não têm (bancos criados antes
    da numeração existir). Roda em toda inicialização; não mexe em quem já tem."""
    sem_codigo = db.query(Produto).filter(
        Produto.empresa_id == empresa.id,
        (Produto.codigo.is_(None)) | (Produto.codigo == ""),
    ).all()
    if not sem_codigo:
        return

    categorias = {c.id: c.nome for c in db.query(Categoria).filter(Categoria.empresa_id == empresa.id).all()}
    for produto in sem_codigo:
        produto.codigo = gerar_codigo(db, empresa.id, categorias.get(produto.categoria_id))
        db.flush()
    db.commit()
    print(f"[SEED] Códigos atribuídos a produtos que estavam sem: {len(sem_codigo)}")


def popular_banco():
    db = SessionLocal()
    try:
        empresa = _get_or_create_empresa(db)
        unidades = _get_or_create_unidades(db, empresa)
        _get_or_create_arquiteto(db, empresa, unidades)
        _importar_catalogo(db, empresa)
        _preencher_codigos_faltantes(db, empresa)
    finally:
        db.close()


if __name__ == "__main__":
    # Permite rodar "python seed.py" isoladamente (padrão usado pelo
    # INICIAR.bat, igual ao Solo Rotinas). O main.py também chama
    # popular_banco() automaticamente no startup — rodar os dois não causa
    # duplicidade, todas as funções acima são "get or create".
    from database import criar_tabelas
    criar_tabelas()
    popular_banco()
    print("[SEED] Concluído.")
