"""
Migrações leves de banco, executadas na inicialização.

O SQLAlchemy cria tabelas novas sozinho (create_all), mas não altera tabelas
que já existem. Quando um campo ou um valor de status muda, o ajuste vai aqui.

Todas as funções são idempotentes: rodar várias vezes não causa efeito algum
além da primeira. Se algo já está no formato novo, a migração é ignorada.
"""
from sqlalchemy import text, inspect

from database import engine

# As migrações usam SQL cru (o SQLAlchemy não altera tabela existente), e SQL
# cru tem dialeto. Só duas coisas divergem entre SQLite e PostgreSQL aqui —
# booleano e o tipo de texto livre — e ficam resolvidas nestes dois mapas.
EH_POSTGRES = engine.dialect.name == "postgresql"

FALSO = "FALSE" if EH_POSTGRES else "0"
TEXTO_LIVRE = "TEXT"          # os dois aceitam TEXT


def _colunas(conexao, tabela: str) -> set:
    inspetor = inspect(conexao)
    try:
        return {c["name"] for c in inspetor.get_columns(tabela)}
    except Exception:
        return set()


def _tabela_existe(conexao, tabela: str) -> bool:
    return tabela in inspect(conexao).get_table_names()


def _inventario_descricao(conexao):
    """Campo 'descricao' da sessão de inventário (preenchido na abertura)."""
    if not _tabela_existe(conexao, "sessoes_inventario"):
        return
    if "descricao" in _colunas(conexao, "sessoes_inventario"):
        return
    conexao.execute(text("ALTER TABLE sessoes_inventario ADD COLUMN descricao VARCHAR(255)"))
    print("[MIGRACAO] sessoes_inventario: coluna 'descricao' adicionada.")


def _inventario_status(conexao):
    """Status passou de ABERTA/FECHADA para ABERTO/EM_CONTAGEM/FECHADO/CANCELADO.
    Converte os valores antigos para não quebrar registros já gravados."""
    if not _tabela_existe(conexao, "sessoes_inventario"):
        return
    conversoes = {"ABERTA": "ABERTO", "FECHADA": "FECHADO"}
    for antigo, novo in conversoes.items():
        resultado = conexao.execute(
            text("UPDATE sessoes_inventario SET status = :novo WHERE status = :antigo"),
            {"novo": novo, "antigo": antigo},
        )
        if resultado.rowcount:
            print(f"[MIGRACAO] sessoes_inventario: {resultado.rowcount} registro(s) "
                  f"de status '{antigo}' convertido(s) para '{novo}'.")


def _inventario_escopo(conexao):
    """Campos de escopo/controle acrescentados ao inventário: geral,
    data_congelamento e observacao."""
    if not _tabela_existe(conexao, "sessoes_inventario"):
        return
    existentes = _colunas(conexao, "sessoes_inventario")
    novas = {
        # DATETIME não existe no PostgreSQL; TIMESTAMP existe nos dois
        "geral": f"BOOLEAN DEFAULT {FALSO} NOT NULL",
        "data_congelamento": "TIMESTAMP",
        "observacao": "TEXT",
    }
    for nome, tipo in novas.items():
        if nome not in existentes:
            conexao.execute(text(f"ALTER TABLE sessoes_inventario ADD COLUMN {nome} {tipo}"))
            print(f"[MIGRACAO] sessoes_inventario: coluna '{nome}' adicionada.")


def _inventario_status_finalizado(conexao):
    """O status FECHADO passou a se chamar FINALIZADO (o botão da tela é
    'Finalizar Inventário'). Converte os registros antigos."""
    if not _tabela_existe(conexao, "sessoes_inventario"):
        return
    resultado = conexao.execute(
        text("UPDATE sessoes_inventario SET status = 'FINALIZADO' WHERE status = 'FECHADO'")
    )
    if resultado.rowcount:
        print(f"[MIGRACAO] sessoes_inventario: {resultado.rowcount} registro(s) "
              f"de status 'FECHADO' convertido(s) para 'FINALIZADO'.")


def _inventario_item_origem(conexao):
    """Origem da contagem (WEB, TELEGRAM, API) — ver servicos/contagem.py."""
    if not _tabela_existe(conexao, "inventario_itens"):
        return
    if "origem" in _colunas(conexao, "inventario_itens"):
        return
    conexao.execute(text("ALTER TABLE inventario_itens ADD COLUMN origem VARCHAR(20)"))
    print("[MIGRACAO] inventario_itens: coluna 'origem' adicionada.")


def _movimento_requisicao(conexao):
    """Vínculo do movimento com a requisição que o originou."""
    if not _tabela_existe(conexao, "movimentos"):
        return
    if "requisicao_id" in _colunas(conexao, "movimentos"):
        return
    conexao.execute(text("ALTER TABLE movimentos ADD COLUMN requisicao_id INTEGER"))
    print("[MIGRACAO] movimentos: coluna 'requisicao_id' adicionada.")


def _movimento_perda(conexao):
    """Perdas: motivo (quebra, validade, furto…) e observação livre."""
    if not _tabela_existe(conexao, "movimentos"):
        return
    existentes = _colunas(conexao, "movimentos")
    novas = {"motivo": "VARCHAR(30)", "observacao": "TEXT"}
    for nome, tipo in novas.items():
        if nome not in existentes:
            conexao.execute(text(f"ALTER TABLE movimentos ADD COLUMN {nome} {tipo}"))
            print(f"[MIGRACAO] movimentos: coluna '{nome}' adicionada.")


def _meta_origem(conexao):
    """Origem da meta: digitada à mão ou vinda da distribuição automática."""
    if not _tabela_existe(conexao, "metas"):
        return
    if "origem" in _colunas(conexao, "metas"):
        return
    conexao.execute(text(
        "ALTER TABLE metas ADD COLUMN origem VARCHAR(20) DEFAULT 'MANUAL' NOT NULL"))
    print("[MIGRACAO] metas: coluna 'origem' adicionada.")


def _metas_iniciais(conexao):
    """Traz a meta que vivia em ConfiguracaoCMV para a tabela de metas.

    A meta antiga era um campo solto, sem data. Ao virar registro com
    vigência, ela precisa valer *desde sempre* — senão todo o histórico
    anterior ficaria sem meta e o acompanhamento começaria com um buraco.
    Por isso a vigência inicial é a data do primeiro movimento da unidade.
    """
    if not _tabela_existe(conexao, "metas") or not _tabela_existe(conexao, "configuracoes_cmv"):
        return
    ja_tem = conexao.execute(text("SELECT COUNT(*) FROM metas")).scalar()
    if ja_tem:
        return

    configs = conexao.execute(text(
        "SELECT unidade_id, meta_percentual FROM configuracoes_cmv"
    )).fetchall()
    if not configs:
        return

    for unidade_id, meta in configs:
        if not meta:
            continue
        inicio = conexao.execute(text(
            "SELECT MIN(data) FROM movimentos WHERE unidade_id = :u"
        ), {"u": unidade_id}).scalar() or "2020-01-01"
        conexao.execute(text(
            "INSERT INTO metas (unidade_id, tipo, valor, formato, vigencia_inicio, "
            "observacao, origem, criado_em) "
            "VALUES (:u, 'CMV_GERAL', :v, 'PERCENTUAL', :d, "
            "'Meta herdada da configuração anterior, sem data de vigência.', "
            "'MANUAL', CURRENT_TIMESTAMP)"
        ), {"u": unidade_id, "v": meta, "d": str(inicio)[:10]})
        print(f"[MIGRACAO] metas: CMV geral {meta:.0%} da unidade {unidade_id} "
              f"com vigência desde {str(inicio)[:10]}.")


def _usuario_escopo(conexao):
    """Acesso regional e vínculo com unidades.

    Quem já usava o sistema não tem vínculo registrado. Zerar o acesso
    dessas pessoas trocaria um furo de segurança por uma parada de
    operação — então a migração vincula cada usuário às unidades da
    empresa dele. Daqui em diante o cadastro exige a escolha explícita.
    """
    if not _tabela_existe(conexao, "usuarios"):
        return

    if "acesso_regional" not in _colunas(conexao, "usuarios"):
        conexao.execute(text(
            f"ALTER TABLE usuarios ADD COLUMN acesso_regional "
            f"BOOLEAN DEFAULT {FALSO} NOT NULL"))
        print("[MIGRACAO] usuarios: coluna 'acesso_regional' adicionada.")

    if not _tabela_existe(conexao, "usuario_unidade"):
        return

    sem_vinculo = conexao.execute(text(
        "SELECT u.id, u.empresa_id, u.papel FROM usuarios u "
        "WHERE NOT EXISTS (SELECT 1 FROM usuario_unidade v WHERE v.usuario_id = u.id)"
    )).fetchall()

    for usuario_id, empresa_id, papel in sem_vinculo:
        if empresa_id:
            unidades = conexao.execute(text(
                "SELECT id FROM unidades WHERE empresa_id = :e"), {"e": empresa_id}).fetchall()
        else:
            unidades = conexao.execute(text("SELECT id FROM unidades")).fetchall()
        for (unidade_id,) in unidades:
            conexao.execute(text(
                "INSERT INTO usuario_unidade (usuario_id, unidade_id) VALUES (:u, :n)"),
                {"u": usuario_id, "n": unidade_id})
        # Quem administrava a empresa continua enxergando o consolidado
        if papel in ("ARQUITETO", "DIRETOR", "ADMIN"):
            conexao.execute(text(
                f"UPDATE usuarios SET acesso_regional = "
                f"{'TRUE' if EH_POSTGRES else '1'} WHERE id = :u"), {"u": usuario_id})

    if sem_vinculo:
        print(f"[MIGRACAO] usuario_unidade: {len(sem_vinculo)} usuário(s) sem vínculo "
              f"receberam as unidades da própria empresa.")


def _usuario_escopo_unidades(conexao):
    """A coluna que separa "estas lojas" de "todas as lojas".

    Quem já existe fica em LISTA — exatamente as unidades que hoje enxerga.
    Isso é de propósito: promover alguém a "todas as unidades" sem que ninguém
    tenha decidido seria ampliar acesso numa migração, que é o último lugar
    onde alguém procuraria depois.

    ARQUITETO e DIRETOR não precisam da marca: eles já enxergam tudo por serem
    irrestritos, e essa regra não muda.
    """
    if not _tabela_existe(conexao, "usuarios"):
        return
    if "escopo_unidades" in _colunas(conexao, "usuarios"):
        return

    conexao.execute(text(
        "ALTER TABLE usuarios ADD COLUMN escopo_unidades "
        "VARCHAR(40) DEFAULT 'LISTA' NOT NULL"))
    print("[MIGRACAO] usuarios: coluna 'escopo_unidades' adicionada (todos em LISTA).")


def aplicar_migracoes():
    with engine.begin() as conexao:
        _usuario_escopo_unidades(conexao)
        _inventario_descricao(conexao)
        _inventario_status(conexao)
        _inventario_escopo(conexao)
        _inventario_status_finalizado(conexao)
        _inventario_item_origem(conexao)
        _movimento_requisicao(conexao)
        _movimento_perda(conexao)
        _meta_origem(conexao)
        _usuario_escopo(conexao)
        _metas_iniciais(conexao)
