"""
Relatório PDF do inventário — análise item a item.

Mostra, para cada produto do escopo: o que o sistema dizia (estoque anterior,
fotografado no congelamento), o que foi contado, a divergência e o valor
financeiro dessa divergência (perda quando falta, sobra quando excede).
"""
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle, PageBreak,
)

NAVY = colors.HexColor("#1F3B57")
GOLD = colors.HexColor("#B08D3E")
CINZA = colors.HexColor("#6B7280")
LINHA = colors.HexColor("#E3E6EA")
FUNDO = colors.HexColor("#F2EFE8")
VERMELHO = colors.HexColor("#A6231F")
VERDE = colors.HexColor("#1C7A3C")

ROTULO_STATUS = {
    "ABERTO": "Aberto",
    "CONGELADO": "Congelado",
    "EM_CONTAGEM": "Em Contagem",
    "FINALIZADO": "Finalizado",
    "CANCELADO": "Cancelado",
}


def _brl(valor) -> str:
    if valor is None:
        return "—"
    txt = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if valor < 0 else "R$ ") + txt


def _num(valor) -> str:
    if valor is None:
        return "—"
    return f"{valor:,.3f}".rstrip("0").rstrip(".").replace(",", "X").replace(".", ",").replace("X", ".")


def _dt(valor) -> str:
    if not valor:
        return "—"
    if isinstance(valor, datetime):
        return valor.strftime("%d/%m/%Y %H:%M")
    return str(valor)


def gerar_pdf_inventario(sessao, itens, resumo) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=landscape(A4),
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=14 * mm, bottomMargin=14 * mm,
        title=f"Inventário {sessao.numero_documento}",
    )

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("titulo", parent=estilos["Title"], fontSize=17, textColor=NAVY,
                            alignment=0, spaceAfter=2)
    subtitulo = ParagraphStyle("subtitulo", parent=estilos["Normal"], fontSize=10, textColor=GOLD,
                               spaceAfter=10)
    secao = ParagraphStyle("secao", parent=estilos["Heading2"], fontSize=11.5, textColor=NAVY,
                           spaceBefore=12, spaceAfter=6)
    normal = ParagraphStyle("normal", parent=estilos["Normal"], fontSize=8.5)
    rodape = ParagraphStyle("rodape", parent=estilos["Normal"], fontSize=7.5, textColor=CINZA)

    hist = []

    # ---------- Cabeçalho ----------
    hist.append(Paragraph(f"Inventário nº {sessao.numero_documento}", titulo))
    hist.append(Paragraph(sessao.descricao or "(sem descrição)", subtitulo))

    escopo = "Geral — todas as famílias" if sessao.geral else \
        (", ".join(c.nome for c in sessao.categorias) or "—")

    ficha = [
        ["Status", ROTULO_STATUS.get(
            sessao.status.value if hasattr(sessao.status, "value") else str(sessao.status),
            str(sessao.status))],
        ["Escopo", escopo],
        ["Aberto em", _dt(sessao.data_abertura)],
        ["Congelado em", _dt(sessao.data_congelamento)],
        ["Encerrado em", _dt(sessao.data_fechamento)],
    ]
    t_ficha = Table([[Paragraph(f"<b>{a}</b>", normal), Paragraph(str(b), normal)] for a, b in ficha],
                    colWidths=[32 * mm, 200 * mm])
    t_ficha.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINHA),
    ]))
    hist.append(t_ficha)

    # ---------- Resumo ----------
    hist.append(Paragraph("Resumo", secao))
    cabecalho_resumo = ["Itens no escopo", "Contados", "Não contados", "Com divergência",
                        "Valor contado", "Perdas", "Sobras", "Resultado líquido"]
    valores_resumo = [
        str(resumo["total_itens"]), str(resumo["itens_contados"]), str(resumo["itens_nao_contados"]),
        str(resumo["itens_com_divergencia"]), _brl(resumo["valor_contado"]),
        _brl(resumo["valor_perdas"]), _brl(resumo["valor_sobras"]), _brl(resumo["valor_liquido"]),
    ]
    t_resumo = Table([cabecalho_resumo, valores_resumo], colWidths=[33 * mm] * 8)
    t_resumo.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTNAME", (0, 1), (-1, 1), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("ALIGN", (0, 0), (-1, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("BACKGROUND", (0, 1), (-1, 1), FUNDO),
        ("TEXTCOLOR", (5, 1), (5, 1), VERMELHO),
        ("TEXTCOLOR", (6, 1), (6, 1), VERDE),
        ("TEXTCOLOR", (7, 1), (7, 1), VERMELHO if resumo["valor_liquido"] < 0 else VERDE),
        ("GRID", (0, 0), (-1, -1), 0.4, LINHA),
    ]))
    hist.append(t_resumo)

    # ---------- Itens ----------
    hist.append(Paragraph("Análise item a item", secao))

    dados = [["Código", "Produto", "Família", "Un.", "Estoque\nanterior",
              "Contado", "Divergência", "Custo un.", "Valor da\ndivergência"]]
    estilo_linhas = []

    for i, item in enumerate(itens, start=1):
        nao_contado = item.quantidade_contada is None
        dados.append([
            item.codigo or "—",
            Paragraph((item.produto or "—")[:60], normal),
            Paragraph((item.categoria or "—").replace("Família - ", ""), normal),
            item.unidade_medida or "—",
            _num(item.quantidade_sistema),
            "não contado" if nao_contado else _num(item.quantidade_contada),
            "—" if nao_contado else _num(item.divergencia),
            _brl(item.custo_unitario) if item.custo_unitario is not None else "—",
            "—" if nao_contado else _brl(item.valor_divergencia),
        ])
        # Colore só Divergência (col. 6) e Valor da divergência (col. 8) —
        # o Custo unitário (col. 7) fica sempre neutro.
        if nao_contado:
            estilo_linhas.append(("TEXTCOLOR", (5, i), (6, i), CINZA))
            estilo_linhas.append(("TEXTCOLOR", (8, i), (8, i), CINZA))
        elif item.valor_divergencia < 0:
            estilo_linhas.append(("TEXTCOLOR", (6, i), (6, i), VERMELHO))
            estilo_linhas.append(("TEXTCOLOR", (8, i), (8, i), VERMELHO))
        elif item.valor_divergencia > 0:
            estilo_linhas.append(("TEXTCOLOR", (6, i), (6, i), VERDE))
            estilo_linhas.append(("TEXTCOLOR", (8, i), (8, i), VERDE))
        if i % 2 == 0:
            estilo_linhas.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FAFAFB")))

    t_itens = Table(
        dados,
        colWidths=[18 * mm, 74 * mm, 30 * mm, 12 * mm, 24 * mm, 24 * mm, 24 * mm, 24 * mm, 28 * mm],
        repeatRows=1,
    )
    t_itens.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 7.5),
        ("ALIGN", (3, 0), (-1, -1), "RIGHT"),
        ("ALIGN", (0, 0), (0, -1), "CENTER"),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.3, LINHA),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ] + estilo_linhas))
    hist.append(t_itens)

    hist.append(Spacer(1, 8))
    hist.append(Paragraph(
        "Divergência = quantidade contada − estoque anterior. Valor negativo indica perda; "
        "positivo, sobra. Itens sem contagem não foram aplicados ao estoque.", rodape))
    hist.append(Paragraph(
        f"Solo CMV — relatório gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')}.", rodape))

    doc.build(hist)
    buffer.seek(0)
    return buffer
