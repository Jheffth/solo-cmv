"""
Folha de contagem cega — PDF A4 para impressão.

CONTAGEM CEGA
-------------
A folha traz apenas o código, a descrição e a unidade do item, com espaço em
branco para anotar à mão. A quantidade que o sistema tem é deliberadamente
omitida: quando o contador enxerga o número esperado, ele tende a confirmá-lo
em vez de contar de verdade, e a divergência real nunca aparece.

Layout pensado para o uso no chão da loja:
  * A4 retrato, itens agrupados por família (o contador percorre setor a setor)
  * linhas altas o bastante para escrever à caneta
  * duas colunas: Contagem e Recontagem (a segunda serve para conferir
    divergências grandes sem precisar de outra folha)
  * cabeçalho com campos para quem contou, quem conferiu e a data
"""
from io import BytesIO
from datetime import datetime

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#1F3B57")
GOLD = colors.HexColor("#B08D3E")
CINZA = colors.HexColor("#6B7280")
LINHA = colors.HexColor("#C9CDD3")
LINHA_LEVE = colors.HexColor("#E3E6EA")
FAIXA = colors.HexColor("#EEF3F8")

# Larguras em mm — somam a área útil do A4 retrato (210 − 2×14 = 182)
COL_CODIGO, COL_PRODUTO, COL_UNIDADE, COL_CONTAGEM, COL_RECONTAGEM = 20, 82, 12, 34, 34

ALTURA_LINHA = 7.6 * mm     # espaço confortável para escrever à mão


def _familia(item) -> str:
    return (item.categoria or "Sem família").replace("Família - ", "")


def _rodape(canvas, doc):
    """Numeração e identificação em todas as páginas."""
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(CINZA)
    canvas.drawString(14 * mm, 10 * mm, doc._rodape_texto)
    canvas.drawRightString(A4[0] - 14 * mm, 10 * mm, f"Página {canvas.getPageNumber()}")
    canvas.restoreState()


def gerar_pdf_contagem_cega(sessao, itens) -> BytesIO:
    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm, topMargin=13 * mm, bottomMargin=16 * mm,
        title=f"Folha de contagem — Inventário {sessao.numero_documento}",
    )
    doc._rodape_texto = (
        f"Inventário nº {sessao.numero_documento}"
        + (f" — {sessao.descricao}" if sessao.descricao else "")
        + "  ·  contagem cega"
    )

    estilos = getSampleStyleSheet()
    titulo = ParagraphStyle("t", parent=estilos["Title"], fontSize=15, textColor=NAVY,
                            alignment=0, spaceAfter=1)
    subtitulo = ParagraphStyle("s", parent=estilos["Normal"], fontSize=9.5, textColor=GOLD,
                               spaceAfter=8)
    normal = ParagraphStyle("n", parent=estilos["Normal"], fontSize=8.5)
    produto = ParagraphStyle("p", parent=estilos["Normal"], fontSize=8.5, leading=10)
    nota = ParagraphStyle("nota", parent=estilos["Normal"], fontSize=7.8, textColor=CINZA)

    hist = []

    # ---------- Cabeçalho ----------
    hist.append(Paragraph(f"Folha de contagem — Inventário nº {sessao.numero_documento}", titulo))
    hist.append(Paragraph(sessao.descricao or "(sem descrição)", subtitulo))

    escopo = "Geral — todas as famílias" if sessao.geral else \
        (", ".join(c.nome.replace("Família - ", "") for c in sessao.categorias) or "—")

    # A folha é emitida antes do congelamento, então o que identifica o
    # documento é a abertura do inventário.
    aberto = sessao.data_abertura.strftime("%d/%m/%Y %H:%M") if sessao.data_abertura else "—"
    ficha = [
        [Paragraph("<b>Escopo</b>", normal), Paragraph(escopo, normal),
         Paragraph("<b>Aberto em</b>", normal), Paragraph(aberto, normal)],
        [Paragraph("<b>Contado por</b>", normal), Paragraph("_" * 34, normal),
         Paragraph("<b>Data</b>", normal), Paragraph("_" * 22, normal)],
        [Paragraph("<b>Conferido por</b>", normal), Paragraph("_" * 34, normal),
         Paragraph("<b>Hora</b>", normal), Paragraph("_" * 22, normal)],
    ]
    t_ficha = Table(ficha, colWidths=[26 * mm, 72 * mm, 26 * mm, 58 * mm])
    t_ficha.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LINEBELOW", (0, 0), (-1, -2), 0.4, LINHA_LEVE),
    ]))
    hist.append(t_ficha)
    hist.append(Spacer(1, 5))
    hist.append(Paragraph(
        "Anote a quantidade encontrada na prateleira. Esta folha não traz a quantidade do sistema — "
        "a contagem é cega, para que o resultado reflita o estoque real.", nota))
    hist.append(Spacer(1, 8))

    # ---------- Tabela ----------
    larguras = [COL_CODIGO * mm, COL_PRODUTO * mm, COL_UNIDADE * mm,
                COL_CONTAGEM * mm, COL_RECONTAGEM * mm]

    dados = [["Código", "Produto", "Un.", "Contagem", "Recontagem"]]
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8.5),
        ("ALIGN", (0, 0), (-1, 0), "CENTER"),
        ("ALIGN", (0, 1), (0, -1), "CENTER"),
        ("ALIGN", (2, 1), (2, -1), "CENTER"),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINHA),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    alturas = [7 * mm]

    familia_atual = None
    linha = 1
    for item in sorted(itens, key=lambda i: (_familia(i), i.produto or "")):
        fam = _familia(item)
        if fam != familia_atual:
            familia_atual = fam
            dados.append([Paragraph(f"<b>{fam}</b>", normal), "", "", "", ""])
            estilo += [
                ("SPAN", (0, linha), (-1, linha)),
                ("BACKGROUND", (0, linha), (-1, linha), FAIXA),
                ("TEXTCOLOR", (0, linha), (-1, linha), NAVY),
            ]
            alturas.append(6 * mm)
            linha += 1

        dados.append([
            item.codigo or "—",
            Paragraph((item.produto or "—")[:70], produto),
            item.unidade_medida or "—",
            "", "",     # espaço em branco para escrever
        ])
        alturas.append(ALTURA_LINHA)
        linha += 1

    if len(dados) == 1:
        dados.append(["", Paragraph("Nenhum item no escopo deste inventário.", normal), "", "", ""])
        alturas.append(ALTURA_LINHA)

    tabela = Table(dados, colWidths=larguras, rowHeights=alturas, repeatRows=1)
    tabela.setStyle(TableStyle(estilo))
    hist.append(tabela)

    hist.append(Spacer(1, 10))
    hist.append(Paragraph(
        f"Solo CMV — folha gerada em {datetime.now().strftime('%d/%m/%Y %H:%M')}. "
        f"Após contar, lance as quantidades no sistema pelo Lançador.", nota))

    doc.build(hist, onFirstPage=_rodape, onLaterPages=_rodape)
    buffer.seek(0)
    return buffer
