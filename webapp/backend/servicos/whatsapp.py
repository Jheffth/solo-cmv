"""
Serviço de WhatsApp do Solo CMV — Pareamento, segurança e atendimento de comandos.

A arquitetura espelha a proteção do Telegram:
- Códigos de 6 dígitos válidos por 10 minutos para pareamento seguro.
- Proteção contra força bruta (5 tentativas erradas por JID = 15 min de bloqueio).
- Validação de capacidades e restrições por cargo na execução dos comandos.
- Idempotência de mensagens para evitar contagens ou comandos duplicados.
"""
import json
import logging
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, Any

from fastapi import HTTPException
from sqlalchemy.orm import Session

from models import (
    Usuario, CodigoPareamento, TentativaVinculoWhatsApp,
    SessaoWhatsApp, MensagemProcessadaWhatsApp, ModoTelegram
)
from servicos import permissoes
from servicos.evolution_cliente import cliente_evolution
from servicos import painel as servico_painel
from servicos import cmv as servico_cmv
from servicos import hierarquia

log = logging.getLogger("servicos.whatsapp")

MINUTOS_VALIDADE = 10
TENTATIVAS_ATE_BLOQUEAR = 5
MINUTOS_BLOQUEIO = 15
DIGITOS = 6


class ErroVinculoWhatsApp(Exception):
    def __init__(self, mensagem: str):
        self.mensagem = mensagem
        super().__init__(mensagem)


# QUANTO O QR PODE ENVELHECER ANTES DE SER INÚTIL
#
# O QR do WhatsApp vive cerca de 20 segundos: o Baileys gira um novo a cada
# ~20s e o servidor descarta o anterior. Escanear um vencido é o pior tipo de
# falha — o celular LÊ o código, aceita, tenta parear, e o servidor já jogou
# a vaga fora. Não aparece erro em lugar nenhum; simplesmente não conecta.
#
# O cache estava em 30 segundos e a tela buscava de 30 em 30. Somados, o QR
# exibido podia ter até 60 segundos — três vezes a validade dele. Não era um
# problema de leitura, de contraste ou de tamanho do QR, que foi onde se
# procurou primeiro: era um código morto na tela.
#
# 8 segundos deixa margem para a viagem até o servidor e a pintura na tela.
SEGUNDOS_CACHE_QRCODE = 8

CACHE_QRCODE = {
    "base64": None,
    "code": None,
    "pairing_code": None,
    "atualizado_em": None
}


def atualizar_cache_qrcode(dados: dict) -> None:
    data = dados.get("data") or {}
    qrcode = data.get("qrcode") or {}
    b64 = qrcode.get("base64") or data.get("base64")
    if b64:
        if not b64.startswith("data:"):
            b64 = f"data:image/png;base64,{b64}"
        CACHE_QRCODE["base64"] = b64
        CACHE_QRCODE["code"] = qrcode.get("code") or data.get("code")
        CACHE_QRCODE["pairing_code"] = qrcode.get("pairingCode") or data.get("pairingCode")
        CACHE_QRCODE["atualizado_em"] = datetime.utcnow()
        log.info("QR Code de WhatsApp atualizado em cache com sucesso.")


def obter_qrcode_cache_ou_api(numero_telefone: str = None) -> dict:
    if not numero_telefone and CACHE_QRCODE["base64"] and CACHE_QRCODE["atualizado_em"]:
        idade = (datetime.utcnow() - CACHE_QRCODE["atualizado_em"]).total_seconds()
        if idade < SEGUNDOS_CACHE_QRCODE:
            return {
                "sucesso": True,
                "base64": CACHE_QRCODE["base64"],
                "code": CACHE_QRCODE["code"],
                "pairing_code": CACHE_QRCODE["pairing_code"],
                "estado": "connecting",
                "idade_segundos": round(idade, 1),
            }
    res = cliente_evolution.obter_qrcode(numero_telefone=numero_telefone)
    res["idade_segundos"] = 0
    if res.get("base64"):
        CACHE_QRCODE["base64"] = res.get("base64")
        CACHE_QRCODE["code"] = res.get("code")
        CACHE_QRCODE["pairing_code"] = res.get("pairing_code")
        CACHE_QRCODE["atualizado_em"] = datetime.utcnow()
    return res


def _gerar_codigo() -> str:
    return "".join(str(secrets.randbelow(10)) for _ in range(DIGITOS))


def _limpar_expirados(db: Session) -> None:
    db.query(CodigoPareamento).filter(
        CodigoPareamento.canal == "WHATSAPP",
        CodigoPareamento.expira_em < datetime.utcnow(),
        CodigoPareamento.usado_em.is_(None),
    ).delete(synchronize_session=False)


def _bloqueado(db: Session, whatsapp_jid: str) -> bool:
    """Verifica se este JID excedeu 5 erros nos últimos 15 minutos."""
    limite = datetime.utcnow() - timedelta(minutes=MINUTOS_BLOQUEIO)
    erros = db.query(TentativaVinculoWhatsApp).filter(
        TentativaVinculoWhatsApp.whatsapp_jid == whatsapp_jid,
        TentativaVinculoWhatsApp.quando >= limite
    ).count()
    return erros >= TENTATIVAS_ATE_BLOQUEAR


def _anotar_erro(db: Session, whatsapp_jid: str) -> None:
    db.add(TentativaVinculoWhatsApp(whatsapp_jid=whatsapp_jid))
    db.commit()


def _limpar_erros(db: Session, whatsapp_jid: str) -> None:
    db.query(TentativaVinculoWhatsApp).filter(
        TentativaVinculoWhatsApp.whatsapp_jid == whatsapp_jid
    ).delete(synchronize_session=False)


def gerar(db: Session, usuario: Usuario) -> dict:
    """Gera um código de 6 dígitos para o usuário vincular seu WhatsApp."""
    _limpar_expirados(db)

    # Invalida códigos anteriores não usados deste usuário para WhatsApp
    db.query(CodigoPareamento).filter(
        CodigoPareamento.usuario_id == usuario.id,
        CodigoPareamento.canal == "WHATSAPP",
        CodigoPareamento.usado_em.is_(None)
    ).delete(synchronize_session=False)

    codigo = _gerar_codigo()
    expira = datetime.utcnow() + timedelta(minutes=MINUTOS_VALIDADE)

    pareamento = CodigoPareamento(
        usuario_id=usuario.id,
        codigo=codigo,
        canal="WHATSAPP",
        expira_em=expira
    )
    db.add(pareamento)
    db.commit()

    return {
        "codigo": codigo,
        "expira_em": expira.isoformat(),
        "minutos": MINUTOS_VALIDADE
    }


def vincular(db: Session, codigo: str, whatsapp_jid: str, whatsapp_nome: str = None) -> dict:
    """Valida o código de pareamento e vincula o usuário ao WhatsApp."""
    jid = whatsapp_jid.strip()
    if _bloqueado(db, jid):
        raise ErroVinculoWhatsApp(
            f"Muitas tentativas incorretas. Aguarde {MINUTOS_BLOQUEIO} minutos e tente novamente."
        )

    codigo_limpo = str(codigo or "").strip()
    if not codigo_limpo.isdigit() or len(codigo_limpo) != DIGITOS:
        _anotar_erro(db, jid)
        raise ErroVinculoWhatsApp("Código inválido. Digite os 6 dígitos numéricos gerados na tela do sistema.")

    pareamento = db.query(CodigoPareamento).filter(
        CodigoPareamento.codigo == codigo_limpo,
        CodigoPareamento.canal == "WHATSAPP"
    ).order_by(CodigoPareamento.id.desc()).first()

    if not pareamento:
        _anotar_erro(db, jid)
        raise ErroVinculoWhatsApp("Código não encontrado ou já expirado. Gere um novo código no seu perfil.")

    if pareamento.usado_em:
        _anotar_erro(db, jid)
        raise ErroVinculoWhatsApp("Este código já foi utilizado. Gere um novo código.")

    if pareamento.expira_em < datetime.utcnow():
        _anotar_erro(db, jid)
        raise ErroVinculoWhatsApp("Este código expirou (validade de 10 min). Gere outro código no sistema.")

    usuario = db.query(Usuario).filter(Usuario.id == pareamento.usuario_id).first()
    if not usuario or usuario.excluido_em or not usuario.ativo:
        _anotar_erro(db, jid)
        raise ErroVinculoWhatsApp("Usuário inativo ou não autorizado.")

    # Desvincula se este JID já estava em outro usuário
    outro = db.query(Usuario).filter(Usuario.whatsapp_jid == jid).first()
    if outro and outro.id != usuario.id:
        outro.whatsapp_jid = None
        outro.whatsapp_vinculado_em = None

    # Extrai o número formatado a partir do JID (ex: 5511999999999@s.whatsapp.net)
    numero_limpo = jid.split("@")[0]

    # Atualiza o usuário
    usuario.whatsapp_jid = jid
    usuario.whatsapp_numero = numero_limpo
    usuario.whatsapp_nome = whatsapp_nome
    usuario.whatsapp_vinculado_em = datetime.utcnow()

    pareamento.usado_em = datetime.utcnow()
    pareamento.whatsapp_jid = jid

    _limpar_erros(db, jid)
    db.commit()

    return {
        "usuario_id": usuario.id,
        "nome": usuario.nome,
        "apelido": usuario.apelido,
        "papel": usuario.papel.value,
        "rotulo_papel": hierarquia.ROTULO.get(usuario.papel, usuario.papel.value)
    }


def desvincular(db: Session, usuario: Usuario) -> dict:
    """Remove o vínculo do WhatsApp do usuário."""
    usuario.whatsapp_jid = None
    usuario.whatsapp_numero = None
    usuario.whatsapp_nome = None
    usuario.whatsapp_vinculado_em = None

    # Limpa sessões ativas no WhatsApp
    db.query(SessaoWhatsApp).filter(SessaoWhatsApp.usuario_id == usuario.id).delete()
    db.commit()

    return {"desvinculado": True}


def status(db: Session, usuario: Usuario) -> dict:
    """Retorna o status da conexão WhatsApp para o usuário atual."""
    inst_status = cliente_evolution.obter_status_instancia()
    return {
        "instancia_conectada": inst_status.get("conectado", False),
        "instancia_estado": inst_status.get("estado", "close"),
        "vinculado": bool(usuario.whatsapp_jid),
        "numero": usuario.whatsapp_numero,
        "nome": usuario.whatsapp_nome,
        "desde": usuario.whatsapp_vinculado_em.isoformat() if usuario.whatsapp_vinculado_em else None
    }


# ==============================================================================
# MOTOR DE COMANDOS DO WHATSAPP
# ==============================================================================

def formatar_moeda(valor: float) -> str:
    if valor is None:
        return "R$ 0,00"
    return f"R$ {valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def formatar_ajuda(usuario: Usuario) -> str:
    papel = usuario.papel.value
    eh_diretoria = papel in ("ARQUITETO", "DIRETOR")
    eh_gestor = papel in ("ARQUITETO", "DIRETOR", "ADMIN", "GERENTE")

    linhas = [
        f"👋 Olá, *{usuario.apelido or usuario.nome}*!",
        f"Cargo: *{hierarquia.ROTULO.get(usuario.papel, papel)}*",
        "",
        "📋 *Comandos disponíveis no Solo CMV:*",
        "",
        "📊 *Consultas:*",
        "• `/painel` — Resumo do mês atual (CMV, metas e alertas)",
    ]

    if eh_diretoria:
        linhas.extend([
            "• `/cmv` — Consulta o CMV apurado da rede e por loja",
            "• `/faturamento` — Faturamento acumulado do mês",
        ])

    linhas.extend([
        "",
        "📦 *Operação e Estoque:*",
        "• `/contar` — Contar produtos do inventário congelado",
        "• `/perda` — Registrar perda de mercadoria",
        "• `/requisicao` — Registrar requisição entre lojas",
        "• `/compra` — Registrar compra de insumos",
    ])

    if eh_gestor:
        linhas.append("• `/congelar` — Congelar inventário por loja")

    linhas.extend([
        "",
        "⚙️ *Conta:*",
        "• `/status` — Informações do seu acesso",
        "• `/desvincular` — Desconectar este WhatsApp do sistema",
    ])

    return "\n".join(linhas)


def processar_comando(db: Session, usuario: Usuario, comando: str, texto_completo: str,
                      sessao_wpp: Optional[SessaoWhatsApp] = None) -> str:
    partes = (texto_completo or comando).strip().split()
    cmd = partes[0].lower() if partes else comando.lower().strip()
    eh_diretoria = usuario.papel.value in ("ARQUITETO", "DIRETOR")
    eh_gestor = usuario.papel.value in ("ARQUITETO", "DIRETOR", "ADMIN", "GERENTE")

    if cmd in ("/ajuda", "/start", "/menu", "ajuda", "menu"):
        return formatar_ajuda(usuario)

    elif cmd == "/status":
        lojas_str = "Todas as lojas" if usuario.escopo_unidades.value == "TODAS" else f"{len(usuario.unidades)} loja(s)"
        return (
            f"👤 *Seu Acesso — Solo CMV*\n\n"
            f"• Nome: *{usuario.nome}*\n"
            f"• Cargo: *{hierarquia.ROTULO.get(usuario.papel, usuario.papel.value)}*\n"
            f"• Lojas: *{lojas_str}*\n"
            f"• WhatsApp: *+{usuario.whatsapp_numero}*\n\n"
            f"Para ver os comandos disponíveis, envie `/ajuda`."
        )

    elif cmd == "/painel":
        hoje = datetime.utcnow()
        try:
            # Consulta o painel para a primeira unidade ou geral
            unidade_id = usuario.unidades[0].id if usuario.unidades else 1
            dados = servico_painel.obter_painel(db, ano=hoje.year, mes=hoje.month, unidade_id=unidade_id, usuario=usuario)
            
            resumo = dados.get("resumo") or {}
            cmv_pct = resumo.get("cmv_pct")
            cmv_str = f"{cmv_pct:.1f}%" if cmv_pct is not None else "Em apuração"
            cmv_reais = formatar_moeda(resumo.get("cmv_reais"))
            faturamento = formatar_moeda(resumo.get("faturamento"))
            perdas = formatar_moeda(resumo.get("perdas"))

            alerta_protecao = "✅ Backups protegidos e em dia."
            if dados.get("protecao", {}).get("precisa_atencao"):
                alerta_protecao = "⚠️ *Atenção:* Backup pendente há mais de 24h."

            return (
                f"📊 *Painel Solo CMV — {hoje.strftime('%m/%Y')}*\n\n"
                f"• *CMV Atual:* {cmv_str} ({cmv_reais})\n"
                f"• *Faturamento:* {faturamento}\n"
                f"• *Perdas:* {perdas}\n\n"
                f"{alerta_protecao}\n\n"
                f"_Acesse o sistema web para o detalhamento completo._"
            )
        except Exception as e:
            log.exception("Erro ao gerar painel no WhatsApp")
            return f"❌ Não foi possível carregar o painel: {e}"

    elif cmd == "/cmv":
        if not eh_diretoria:
            return "🚫 Acesso restrito à Diretoria."
        hoje = datetime.utcnow()
        try:
            unidade_id = usuario.unidades[0].id if usuario.unidades else 1
            dados = servico_cmv.calcular_cmv_periodo(db, hoje.year, hoje.month, unidade_id, usuario)
            cmv_pct = dados.get("cmv_percentual")
            cmv_str = f"{cmv_pct:.2f}%" if cmv_pct is not None else "Em apuração"
            return (
                f"📈 *Motor de CMV — {hoje.strftime('%m/%Y')}*\n\n"
                f"• CMV Calculado: *{cmv_str}*\n"
                f"• CMV em Reais: *{formatar_moeda(dados.get('cmv_reais'))}*\n"
                f"• Faturamento Base: *{formatar_moeda(dados.get('faturamento'))}*\n"
                f"• Compras do Período: *{formatar_moeda(dados.get('compras_reais'))}*\n"
            )
        except Exception as e:
            return f"❌ Erro ao apurar CMV: {e}"

    elif cmd == "/faturamento":
        if not eh_diretoria:
            return "🚫 Acesso restrito à Diretoria."
        hoje = datetime.utcnow()
        try:
            unidade_id = usuario.unidades[0].id if usuario.unidades else 1
            dados = servico_painel.obter_painel(db, ano=hoje.year, mes=hoje.month, unidade_id=unidade_id, usuario=usuario)
            fat = formatar_moeda(dados.get("resumo", {}).get("faturamento"))
            return f"💰 *Faturamento Acumulado ({hoje.strftime('%m/%Y')}):* {fat}"
        except Exception as e:
            return f"❌ Erro ao consultar faturamento: {e}"

    elif cmd == "/congelar":
        if not eh_gestor:
            return "🚫 Apenas Gerentes e Diretores podem congelar inventários."

        from calculo_estoque import saldos_por_produto, ultimos_custos
        from routers.inventario import _produtos_do_escopo
        from models import Unidade, SessaoInventario, StatusSessaoInventario, InventarioItem

        param = partes[1] if len(partes) > 1 else None
        unidade_ids = None if (usuario.acesso_regional or eh_diretoria) else ([u.id for u in usuario.unidades] if usuario.unidades else None)

        q = db.query(SessaoInventario).join(Unidade).filter(
            Unidade.empresa_id == usuario.empresa_id,
            SessaoInventario.status == StatusSessaoInventario.ABERTO
        )
        if unidade_ids:
            q = q.filter(SessaoInventario.unidade_id.in_(unidade_ids))

        abertos = q.all()

        # Se especificou ID ou número do documento
        if param and abertos:
            alvo = next((s for s in abertos if str(s.id) == param or s.numero_documento.lower() == param.lower() or str(s.unidade_id) == param), None)
            if alvo:
                abertos = [alvo]

        if not abertos:
            q_prontos = db.query(SessaoInventario).join(Unidade).filter(
                Unidade.empresa_id == usuario.empresa_id,
                SessaoInventario.status.in_([StatusSessaoInventario.CONGELADO, StatusSessaoInventario.EM_CONTAGEM])
            )
            if unidade_ids:
                q_prontos = q_prontos.filter(SessaoInventario.unidade_id.in_(unidade_ids))
            prontos = q_prontos.all()

            if prontos:
                doc_str = ", ".join(f"nº {s.numero_documento} ({s.unidade.nome})" for s in prontos)
                return (
                    f"❄️ *Inventário Já Congelado*\n\n"
                    f"O inventário {doc_str} já está congelado e pronto para contagens.\n\n"
                    f"Mande `/contar` para iniciar a contagem."
                )

            return (
                "📋 *Nenhum Inventário Aberto Encontrado*\n\n"
                "Para iniciar um inventário, primeiro clique em *Novo Inventário* na aba *Inventários* do painel web "
                "(onde você escolhe as famílias/categorias que entram no fechamento).\n\n"
                "Assim que criar na tela, envie `/congelar` aqui para tirar a fotografia do estoque e liberar a contagem para a equipe."
            )

        if len(abertos) == 1:
            sessao = abertos[0]
            produtos = _produtos_do_escopo(db, sessao, usuario.empresa_id)
            if not produtos:
                return f"❌ Nenhum produto ativo no escopo do inventário nº {sessao.numero_documento}."

            ids = [p.id for p in produtos]
            saldos = saldos_por_produto(db, sessao.unidade_id, ids)
            custos = ultimos_custos(db, sessao.unidade_id)
            for p in produtos:
                db.add(InventarioItem(
                    sessao_inventario_id=sessao.id,
                    produto_id=p.id,
                    quantidade_sistema=saldos.get(p.id, 0.0),
                    custo_unitario=custos.get(p.id),
                ))
            sessao.status = StatusSessaoInventario.CONGELADO
            sessao.data_congelamento = datetime.utcnow()
            db.commit()
            return (
                f"✅ *Inventário Nº {sessao.numero_documento} Congelado com Sucesso!*\n\n"
                f"• Loja: *{sessao.unidade.nome}*\n"
                f"• Itens no Escopo: *{len(produtos)} produtos*\n"
                f"• Data: *{sessao.data_congelamento.strftime('%d/%m/%Y %H:%M')}*\n\n"
                f"📸 A fotografia do estoque do sistema foi tirada.\n"
                f"A contagem está liberada! Quem for contar pode mandar `/contar` agora."
            )

        linhas_inv = "\n".join([f"• `/congelar {s.id}` — Nº {s.numero_documento} ({s.unidade.nome})" for s in abertos])
        return (
            f"❄️ *Mais de um inventário aberto encontrado:*\n\n"
            f"{linhas_inv}\n\n"
            f"Envie `/congelar <numero>` para escolher qual congelar."
        )

    elif cmd == "/contar":
        if sessao_wpp is None:
            sessao_wpp = _obter_sessao_conversa(db, usuario.whatsapp_jid, usuario)
        param = partes[1] if len(partes) > 1 else None
        return _iniciar_contagem(db, usuario, sessao_wpp, param)

    elif cmd in ("/perda", "/requisicao", "/compra"):
        operacoes = {
            "/perda": ("Perda de Estoque", "motivo e produto"),
            "/requisicao": ("Requisição de Mercadoria", "loja de destino e itens"),
            "/compra": ("Entrada de Compra", "fornecedor e valor"),
        }
        nome_op, desc = operacoes[cmd]
        return (
            f"📝 *Lançador Rápido — {nome_op}*\n\n"
            f"Você pode lançar diretamente informando o item e quantidade.\n"
            f"Exemplo: `Batata Doce 15kg`\n\n"
            f"Deseja iniciar o lançamento agora? Envie o nome do produto."
        )

    elif cmd == "/desvincular":
        desvincular(db, usuario)
        return "👋 Seu WhatsApp foi desvinculado do Solo CMV com sucesso. Para reconectar, gere um novo código no seu Perfil."

    return (
        f"🤔 Não reconheci o comando `{comando}`.\n\n"
        f"Envie `/ajuda` para ver todos os comandos disponíveis."
    )


def _obter_sessao_conversa(db: Session, remote_jid: str, usuario: Usuario) -> SessaoWhatsApp:
    sessao = db.query(SessaoWhatsApp).filter(SessaoWhatsApp.whatsapp_jid == remote_jid).first()
    if not sessao:
        sessao = SessaoWhatsApp(
            whatsapp_jid=remote_jid,
            usuario_id=usuario.id,
            unidade_id=usuario.unidades[0].id if usuario.unidades else None,
            modo=ModoTelegram.LIVRE
        )
        db.add(sessao)
        db.commit()
        db.refresh(sessao)
    return sessao


def _iniciar_contagem(db: Session, usuario: Usuario, sessao_wpp: SessaoWhatsApp, param: Optional[str] = None) -> str:
    from models import Unidade, SessaoInventario, StatusSessaoInventario, InventarioItem
    eh_diretoria = usuario.papel.value in ("ARQUITETO", "DIRETOR")
    unidade_ids = None if (usuario.acesso_regional or eh_diretoria) else ([u.id for u in usuario.unidades] if usuario.unidades else None)

    q = db.query(SessaoInventario).join(Unidade).filter(
        Unidade.empresa_id == usuario.empresa_id,
        SessaoInventario.status.in_([StatusSessaoInventario.CONGELADO, StatusSessaoInventario.EM_CONTAGEM])
    )
    if unidade_ids:
        q = q.filter(SessaoInventario.unidade_id.in_(unidade_ids))

    prontos = q.all()

    if param and prontos:
        alvo = next((s for s in prontos if str(s.id) == param or s.numero_documento.lower() == param.lower() or str(s.unidade_id) == param), None)
        if alvo:
            prontos = [alvo]

    if not prontos:
        q_abertos = db.query(SessaoInventario).join(Unidade).filter(
            Unidade.empresa_id == usuario.empresa_id,
            SessaoInventario.status == StatusSessaoInventario.ABERTO
        )
        if unidade_ids:
            q_abertos = q_abertos.filter(SessaoInventario.unidade_id.in_(unidade_ids))
        abertos = q_abertos.all()

        if abertos:
            doc_str = ", ".join(f"nº {s.numero_documento} ({s.unidade.nome})" for s in abertos)
            return (
                f"⚠️ *Inventário Ainda Não Congelado*\n\n"
                f"O inventário {doc_str} está aberto, mas ainda não foi congelado.\n\n"
                f"Envie `/congelar` primeiro para tirar a fotografia do estoque e liberar a contagem."
            )

        return (
            "📋 *Nenhum Inventário Pronto para Contagem*\n\n"
            "Não há nenhum inventário congelado nesta loja no momento.\n\n"
            "Quem abre na tela e congela é o gerente. Assim que congelar, mande `/contar` novamente."
        )

    if len(prontos) > 1 and not param:
        linhas = "\n".join([f"• `/contar {s.id}` — Nº {s.numero_documento} ({s.unidade.nome})" for s in prontos])
        return (
            f"📦 *Mais de um inventário pronto para contagem:*\n\n"
            f"{linhas}\n\n"
            f"Envie `/contar <numero>` escolhendo um deles."
        )

    sessao_inv = prontos[0]
    itens_todos = db.query(InventarioItem).filter(InventarioItem.sessao_inventario_id == sessao_inv.id).all()
    itens_pendentes = [i for i in itens_todos if i.quantidade_contada is None]

    fila_ids = [i.produto_id for i in itens_pendentes]
    catalogo = {str(i.produto_id): [i.produto.nome, i.produto.unidade_medida or "UN"] for i in itens_todos}

    ctx = {
        "inventario_id": sessao_inv.id,
        "numero": sessao_inv.numero_documento,
        "unidade_nome": sessao_inv.unidade.nome,
        "fila": fila_ids,
        "total": len(itens_todos),
        "catalogo": catalogo,
        "aguardando_id": fila_ids[0] if fila_ids else None
    }

    sessao_wpp.modo = ModoTelegram.CONTAGEM
    sessao_wpp.contexto = json.dumps(ctx)
    db.commit()

    if not fila_ids:
        sessao_wpp.modo = ModoTelegram.LIVRE
        db.commit()
        return (
            f"🎉 *Inventário Nº {sessao_inv.numero_documento} Concluído!*\n\n"
            f"Todos os {len(itens_todos)} itens desta loja já foram contados.\n"
            f"O gerente/diretor já pode conferir e finalizar no painel web."
        )

    primeiro = catalogo.get(str(fila_ids[0]))
    nome_prod, un_prod = primeiro[0], primeiro[1]
    pos = len(itens_todos) - len(fila_ids) + 1

    return (
        f"📝 *Iniciando Contagem — Inventário Nº {sessao_inv.numero_documento}*\n"
        f"Loja: *{sessao_inv.unidade.nome}* ({len(itens_todos) - len(fila_ids)}/{len(itens_todos)} já contados)\n\n"
        f"Vou passar item por item. Responda apenas a quantidade.\n"
        f"━━━━━━━━━━━━━━━━━━━━\n"
        f"📦 *Item {pos}/{len(itens_todos)}:*\n"
        f"*{nome_prod}*\n"
        f"Unidade de medida: *{un_prod}*\n\n"
        f"👉 Envie a *quantidade contada* (ex: `15` ou `12,5`):\n"
        f"• Digite `0` ou `zero` se não houver estoque\n"
        f"• Digite `pular` para contar depois\n"
        f"• Digite `/sair` para pausar a contagem"
    )


def _processar_texto_contagem(db: Session, usuario: Usuario, sessao_wpp: SessaoWhatsApp, texto: str) -> str:
    from servicos.contagem import registrar_contagem

    txt = texto.strip()
    if txt.lower() in ("/sair", "sair", "/cancelar", "cancelar", "/parar", "parar"):
        sessao_wpp.modo = ModoTelegram.LIVRE
        sessao_wpp.contexto = None
        db.commit()
        return "⏸️ *Contagem pausada.* Você pode retomar a qualquer momento enviando `/contar`."

    try:
        ctx = json.loads(sessao_wpp.contexto or "{}")
    except Exception:
        sessao_wpp.modo = ModoTelegram.LIVRE
        db.commit()
        return "⚠️ Sessão de contagem expirada. Envie `/contar` para recomeçar."

    inv_id = ctx.get("inventario_id")
    fila = ctx.get("fila") or []
    catalogo = ctx.get("catalogo") or {}
    total = ctx.get("total") or len(fila)
    aguardando_id = ctx.get("aguardando_id")

    if not inv_id or not fila or not aguardando_id:
        sessao_wpp.modo = ModoTelegram.LIVRE
        db.commit()
        return "Todos os itens deste inventário já foram contados! Envie `/ajuda` para outros comandos."

    # 1. Comando Pular
    if txt.lower() in ("pular", "pula", "skip", "proximo", "próximo"):
        pulado = fila.pop(0)
        fila.append(pulado)
        ctx["fila"] = fila
        ctx["aguardando_id"] = fila[0]
        sessao_wpp.contexto = json.dumps(ctx)
        db.commit()

        prox = catalogo.get(str(fila[0]))
        pos = total - len(fila) + 1
        return (
            f"⏭️ *Item pulado.*\n\n"
            f"📦 *Item {pos}/{total}:*\n"
            f"*{prox[0]}* (em {prox[1]})\n\n"
            f"👉 Envie a quantidade (ou `pular` / `0`):"
        )

    # 2. Número ou Zero digitado
    num_str = txt.replace(",", ".").lower()
    if num_str in ("zero", "nenhum", "nao tem", "não tem", "sem estoque", "zerado"):
        num_str = "0"

    try:
        qtd = float(num_str)
        if qtd < 0:
            return "❌ A quantidade contada não pode ser negativa. Digite novamente:"
    except ValueError:
        # Se digitou Nome + Quantidade, ex: "Gengibre 8"
        partes = txt.rsplit(maxsplit=1)
        if len(partes) == 2:
            nome_busca, val_str = partes[0].lower(), partes[1].replace(",", ".")
            try:
                qtd_busca = float(val_str)
                prod_encontrado_id = None
                for pid_s, dados in catalogo.items():
                    if nome_busca in dados[0].lower():
                        prod_encontrado_id = int(pid_s)
                        break
                if prod_encontrado_id:
                    registrar_contagem(
                        db,
                        sessao_id=inv_id,
                        produto_id=prod_encontrado_id,
                        quantidade=qtd_busca,
                        usuario_id=usuario.id,
                        empresa_id=usuario.empresa_id,
                        origem="WHATSAPP"
                    )
                    if prod_encontrado_id in fila:
                        fila.remove(prod_encontrado_id)
                    ctx["fila"] = fila
                    ctx["aguardando_id"] = fila[0] if fila else None
                    sessao_wpp.contexto = json.dumps(ctx)
                    db.commit()

                    prod_info = catalogo[str(prod_encontrado_id)]
                    resp = f"✓ *{prod_info[0]}:* {qtd_busca:g} {prod_info[1]} lançado com sucesso!\n\n"
                    if not fila:
                        sessao_wpp.modo = ModoTelegram.LIVRE
                        db.commit()
                        return resp + f"🎉 *Todos os {total} itens foram contados!*\nO gerente já pode conferir e finalizar no painel web."

                    prox = catalogo.get(str(fila[0]))
                    pos = total - len(fila) + 1
                    return resp + (
                        f"📦 *Item {pos}/{total}:*\n"
                        f"*{prox[0]}* (em {prox[1]})\n\n"
                        f"👉 Envie a quantidade:"
                    )
            except ValueError:
                pass
        return "🤔 Não entendi a quantidade. Digite apenas o número (ex: `10` ou `12,5`), `0` para zerado, ou `pular`."

    # Registra o item da vez
    prod_id = aguardando_id
    prod_info = catalogo.get(str(prod_id))

    registrar_contagem(
        db,
        sessao_id=inv_id,
        produto_id=prod_id,
        quantidade=qtd,
        usuario_id=usuario.id,
        empresa_id=usuario.empresa_id,
        origem="WHATSAPP"
    )

    fila.pop(0)
    ctx["fila"] = fila
    ctx["aguardando_id"] = fila[0] if fila else None
    sessao_wpp.contexto = json.dumps(ctx)
    db.commit()

    resp_item = f"✓ *{prod_info[0]}:* {qtd:g} {prod_info[1]} gravado.\n\n"
    if not fila:
        sessao_wpp.modo = ModoTelegram.LIVRE
        db.commit()
        return resp_item + f"🎉 *Parabéns! Todos os {total} itens foram contados com sucesso!*\n\nO inventário está pronto para ser conferido e finalizado no painel web."

    prox = catalogo.get(str(fila[0]))
    pos = total - len(fila) + 1
    return resp_item + (
        f"📦 *Item {pos}/{total}:*\n"
        f"*{prox[0]}* (em {prox[1]})\n\n"
        f"👉 Envie a quantidade:"
    )


def atender_webhook(db: Session, evento: Dict[str, Any]) -> None:
    """
    Recebe eventos da Evolution API (messages.upsert) e despacha a resposta.
    """
    data = evento.get("data") or {}
    message_data = data.get("message") or {}

    # Extrai o texto da mensagem
    texto = (
        message_data.get("conversation")
        or (message_data.get("extendedTextMessage") or {}).get("text")
        or ""
    ).strip()

    if not texto:
        return

    # Tratamento de fromMe:
    # Se a mensagem foi enviada pelo próprio aparelho (fromMe),
    # só processamos se for um comando explícito (inicia com '/') ou resposta no modo contagem ou código de 6 dígitos.
    key = data.get("key") or {}
    from_me = bool(key.get("fromMe"))
    eh_comando_ou_codigo = texto.startswith("/") or (len(texto) == 6 and texto.isdigit())

    remote_jid = key.get("remoteJid") or ""
    if not remote_jid or "@s.whatsapp.net" not in remote_jid:
        # Ignora grupos por enquanto para privacidade e segurança
        return

    # Verifica se já está em contagem ativa antes de descartar fromMe
    usuario_previo = db.query(Usuario).filter(
        Usuario.whatsapp_jid == remote_jid,
        Usuario.excluido_em.is_(None),
        Usuario.ativo.is_(True)
    ).first()

    sessao_wpp_previa = _obter_sessao_conversa(db, remote_jid, usuario_previo) if usuario_previo else None
    em_contagem = sessao_wpp_previa and sessao_wpp_previa.modo == ModoTelegram.CONTAGEM

    if from_me and not (eh_comando_ou_codigo or em_contagem):
        return

    mensagem_id = key.get("id")
    if not mensagem_id:
        return

    # Idempotência: não processa a mesma mensagem duas vezes
    ja_processado = db.query(MensagemProcessadaWhatsApp).filter(
        MensagemProcessadaWhatsApp.mensagem_id == mensagem_id
    ).first()
    if ja_processado:
        log.info("Mensagem WhatsApp %s já processada — ignorando.", mensagem_id)
        return

    db.add(MensagemProcessadaWhatsApp(mensagem_id=mensagem_id))
    db.commit()

    push_name = data.get("pushName") or ""
    log.info("Mensagem WhatsApp recebida de %s (fromMe=%s): %s", remote_jid, from_me, texto)

    # 1. Tratamento de Vínculo: /vincular 123456 ou 123456
    partes = texto.split()
    if partes and partes[0].lower() in ("/vincular", "vincular"):
        codigo = partes[1] if len(partes) > 1 else ""
        try:
            res = vincular(db, codigo=codigo, whatsapp_jid=remote_jid, whatsapp_nome=push_name)
            resposta = (
                f"🎉 *WhatsApp Conectado com Sucesso!*\n\n"
                f"Olá, *{res['nome']}*! Sua conta foi vinculada com o cargo *{res['rotulo_papel']}*.\n\n"
                f"Envie `/ajuda` para ver o que você pode fazer pelo WhatsApp."
            )
        except ErroVinculoWhatsApp as e:
            resposta = f"❌ {e.mensagem}"
        cliente_evolution.enviar_texto(remote_jid, resposta)
        return

    # 2. Localiza o usuário vinculado
    usuario = usuario_previo

    if not usuario:
        # Se mandou apenas 6 dígitos, tenta vincular automaticamente
        if len(texto) == DIGITOS and texto.isdigit():
            try:
                res = vincular(db, codigo=texto, whatsapp_jid=remote_jid, whatsapp_nome=push_name)
                resposta = (
                    f"🎉 *WhatsApp Conectado com Sucesso!*\n\n"
                    f"Olá, *{res['nome']}*! Sua conta foi vinculada com o cargo *{res['rotulo_papel']}*.\n\n"
                    f"Envie `/ajuda` para ver os comandos disponíveis."
                )
            except ErroVinculoWhatsApp as e:
                resposta = f"❌ {e.mensagem}"
            cliente_evolution.enviar_texto(remote_jid, resposta)
            return

        resposta = (
            "🔒 *Solo CMV — Acesso Não Vinculado*\n\n"
            "Este número de WhatsApp ainda não está conectado a um usuário do sistema.\n\n"
            "📱 *Como conectar:*\n"
            "1. Acesse o sistema pelo navegador.\n"
            "2. Vá em *Meu Perfil › WhatsApp › Vincular WhatsApp*.\n"
            "3. Copie o código de 6 dígitos e envie aqui:\n"
            "   `/vincular SEU_CODIGO`"
        )
        cliente_evolution.enviar_texto(remote_jid, resposta)
        return

    # 3. Usuário autenticado: verifica se está no modo de contagem
    sessao_wpp = sessao_wpp_previa or _obter_sessao_conversa(db, remote_jid, usuario)
    primeira_palavra = partes[0].lower() if partes else ""

    if sessao_wpp.modo == ModoTelegram.CONTAGEM and not (texto.startswith("/") and primeira_palavra not in ("/sair", "/cancelar", "/contar")):
        resposta = _processar_texto_contagem(db, usuario, sessao_wpp, texto)
        cliente_evolution.enviar_texto(remote_jid, resposta)
        return

    try:
        resposta = processar_comando(db, usuario, primeira_palavra, texto, sessao_wpp)
    except Exception as e:
        log.exception("Erro ao processar comando WhatsApp: %s", e)
        resposta = f"❌ Erro ao executar `{primeira_palavra}`: {e}"
    cliente_evolution.enviar_texto(remote_jid, resposta)
