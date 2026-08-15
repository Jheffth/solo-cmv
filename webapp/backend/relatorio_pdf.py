"""
PDFs dos relatórios gerenciais — A4, para imprimir ou enviar.

Mesmo padrão visual do relatório de inventário (navy/dourado, cabeçalho com
a procedência dos inventários), para que os documentos do sistema pareçam
de uma família só.

Uma regra de conteúdo em todos: o número nunca aparece sem a memória de
como foi obtido. O rodapé de cada página traz de quais inventários o estoque
saiu e quando o documento foi gerado.
"""
from datetime import date, datetime
from io import BytesIO
from typing import List, Optional

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
)

NAVY = colors.HexColor("#1F3B57")
GOLD = colors.HexColor("#B08D3E")
CINZA = colors.HexColor("#6B7280")
LINHA = colors.HexColor("#E3E6EA")
FUNDO = colors.HexColor("#F2EFE8")
VERMELHO = colors.HexColor("#A6231F")
VERDE = colors.HexColor("#1C7A3C")
AZUL = colors.HexColor("#4A7CA6")

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho",
         "julho", "agosto", "setembro", "outubro", "novembro", "dezembro"]


# ---------------------------------------------------------------- formatação
def brl(valor) -> str:
    if valor is None:
        return "—"
    txt = f"{abs(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return ("-R$ " if valor < 0 else "R$ ") + txt


def pct(valor, casas: int = 1) -> str:
    if valor is None:
        return "—"
    return f"{valor * 100:.{casas}f}".replace(".", ",") + "%"


def pontos(valor) -> str:
    if valor is None:
        return "—"
    sinal = "+" if valor > 0 else ""
    return f"{sinal}{valor * 100:.1f}".replace(".", ",") + " pp"


def num(valor) -> str:
    if valor is None:
        return "—"
    return (f"{valor:,.3f}".rstrip("0").rstrip(".")
            .replace(",", "X").replace(".", ",").replace("X", "."))


def hexa(cor) -> str:
    """reportlab devolve '0xrrggbb'; a marcação inline quer '#rrggbb'."""
    return "#" + cor.hexval()[2:]


def data_br(iso: Optional[str]) -> str:
    if not iso:
        return "—"
    return "/".join(reversed(str(iso)[:10].split("-")))


# ---------------------------------------------------------------- estrutura
def _estilos():
    base = getSampleStyleSheet()
    return {
        "titulo": ParagraphStyle("titulo", parent=base["Title"], fontSize=16,
                                 textColor=NAVY, spaceAfter=2, alignment=0),
        "subtitulo": ParagraphStyle("subtitulo", parent=base["Normal"], fontSize=9.5,
                                    textColor=CINZA, spaceAfter=1),
        "secao": ParagraphStyle("secao", parent=base["Heading2"], fontSize=11.5,
                                textColor=NAVY, spaceBefore=10, spaceAfter=5),
        "texto": ParagraphStyle("texto", parent=base["Normal"], fontSize=9,
                                textColor=colors.HexColor("#20242B"), leading=13),
        "nota": ParagraphStyle("nota", parent=base["Normal"], fontSize=8,
                               textColor=CINZA, leading=11),
        # Fonte de 22pt não cabe em entrelinha de 13: o número subiria por
        # cima do rótulo. Cada cartão de destaque tem entrelinha própria.
        "destaque": ParagraphStyle("destaque", parent=base["Normal"], fontSize=9,
                                   textColor=colors.HexColor("#20242B"), leading=27),
        "destaque_menor": ParagraphStyle("destaque_menor", parent=base["Normal"],
                                         fontSize=9, textColor=colors.HexColor("#20242B"),
                                         leading=21),
    }


def _rodape_factory(cabecalho: dict):
    origem = ""
    if cabecalho.get("inventario_abertura") or cabecalho.get("inventario_fechamento"):
        origem = (f"Estoque apurado de INV-{cabecalho.get('inventario_abertura') or '—'} "
                  f"({data_br(cabecalho.get('data_inicio'))}) a "
                  f"INV-{cabecalho.get('inventario_fechamento') or '—'} "
                  f"({data_br(cabecalho.get('data_fim'))})")

    def rodape(canvas, doc):
        canvas.saveState()
        largura = doc.pagesize[0]
        canvas.setStrokeColor(LINHA)
        canvas.setLineWidth(0.5)
        canvas.line(15 * mm, 12 * mm, largura - 15 * mm, 12 * mm)
        canvas.setFont("Helvetica", 7)
        canvas.setFillColor(CINZA)
        if origem:
            canvas.drawString(15 * mm, 8 * mm, origem)
        canvas.drawRightString(
            largura - 15 * mm, 8 * mm,
            f"Solo CMV · gerado em {datetime.now().strftime('%d/%m/%Y %H:%M')} "
            f"· pág. {doc.page}")
        canvas.restoreState()

    return rodape


def _cabecalho_flow(titulo: str, cabecalho: dict, estilos) -> list:
    partes = [Paragraph(titulo, estilos["titulo"])]
    linha = cabecalho.get("rotulo", "")
    if cabecalho.get("unidade"):
        linha += f" · {cabecalho['unidade']}"
    partes.append(Paragraph(linha, estilos["subtitulo"]))
    if cabecalho.get("encaixado_no_ciclo"):
        partes.append(Paragraph(
            "Período ajustado aos inventários que o delimitam — o CMV nasce de "
            "contagem, não de calendário.", estilos["nota"]))
    partes.append(Spacer(1, 7))
    return partes


def _documento(buffer, paisagem: bool, cabecalho: dict):
    tamanho = landscape(A4) if paisagem else A4
    return SimpleDocTemplate(
        buffer, pagesize=tamanho,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=14 * mm, bottomMargin=18 * mm,
        title="Solo CMV", author="Solo CMV",
    )


ESTILO_TABELA = TableStyle([
    ("BACKGROUND", (0, 0), (-1, 0), NAVY),
    ("TEXTCOLOR", (0, 0), (-1, 0), colors.white),
    ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
    ("FONTSIZE", (0, 0), (-1, -1), 8),
    ("BOTTOMPADDING", (0, 0), (-1, 0), 6),
    ("TOPPADDING", (0, 0), (-1, 0), 6),
    ("GRID", (0, 0), (-1, -1), 0.4, LINHA),
    ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
    ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, colors.HexColor("#FAFAFB")]),
])


def _indisponivel(titulo: str, dados: dict) -> BytesIO:
    buffer = BytesIO()
    estilos = _estilos()
    doc = _documento(buffer, False, dados["cabecalho"])
    partes = _cabecalho_flow(titulo, dados["cabecalho"], estilos)
    partes.append(Paragraph(
        f"<b>Relatório não disponível.</b> {dados.get('motivo', '')}", estilos["texto"]))
    partes.append(Spacer(1, 6))
    partes.append(Paragraph(
        "Um número inventado seria pior que a ausência dele: feche um inventário "
        "no período e o relatório passa a existir.", estilos["nota"]))
    doc.build(partes, onFirstPage=_rodape_factory(dados["cabecalho"]),
              onLaterPages=_rodape_factory(dados["cabecalho"]))
    buffer.seek(0)
    return buffer


# ==============================================================================
# 1 · FECHAMENTO
# ==============================================================================
def pdf_fechamento(dados: dict) -> BytesIO:
    if not dados.get("disponivel"):
        return _indisponivel("Fechamento do período", dados)

    buffer = BytesIO()
    estilos = _estilos()
    doc = _documento(buffer, False, dados["cabecalho"])
    partes = _cabecalho_flow("Fechamento do período", dados["cabecalho"], estilos)

    # Destaque do número que interessa
    dentro = dados.get("dentro_da_meta")
    cor = VERDE if dentro else VERMELHO
    destaque = Table([[
        Paragraph(f"<font size=9 color='#6B7280'>CMV do período</font><br/>"
                  f"<font size=22 color='{hexa(cor)}'><b>"
                  f"{pct(dados['geral']['cmv_percentual'])}</b></font>", estilos["destaque"]),
        Paragraph(f"<font size=9 color='#6B7280'>Em reais</font><br/>"
                  f"<font size=15 color='#1F3B57'><b>{brl(dados['geral']['cmv'])}</b></font>",
                  estilos["destaque_menor"]),
        Paragraph(f"<font size=9 color='#6B7280'>Meta</font><br/>"
                  f"<font size=15 color='#1F3B57'><b>{pct(dados['meta'])}</b></font>",
                  estilos["destaque_menor"]),
        Paragraph(f"<font size=9 color='#6B7280'>Desvio</font><br/>"
                  f"<font size=15 color='{hexa(cor)}'><b>"
                  f"{pontos(dados['desvio'])}</b></font>", estilos["destaque_menor"]),
    ]], colWidths=[45 * mm, 45 * mm, 45 * mm, 45 * mm])
    destaque.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FUNDO),
        ("BOX", (0, 0), (-1, -1), 0.5, LINHA),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    partes.append(destaque)

    partes.append(Paragraph("Composição", estilos["secao"]))
    linhas = [["", "Estoque inicial", "Compras", "Estoque final", "CMV",
               "Faturamento", "CMV %"]]
    for rotulo, chave in (("Geral", "geral"), ("Comida", "comida"), ("Bebida", "bebida")):
        b = dados[chave]
        linhas.append([rotulo, brl(b["estoque_inicial"]), brl(b["compras"]),
                       brl(b["estoque_final"]), brl(b["cmv"]),
                       brl(b["faturamento"]), pct(b["cmv_percentual"])])
    tabela = Table(linhas, colWidths=[26 * mm, 30 * mm, 28 * mm, 30 * mm, 30 * mm,
                                      30 * mm, 20 * mm])
    estilo = TableStyle(ESTILO_TABELA.getCommands())
    estilo.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
    estilo.add("FONTNAME", (0, 1), (0, -1), "Helvetica-Bold")
    estilo.add("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold")
    estilo.add("TEXTCOLOR", (0, 1), (0, 1), NAVY)
    tabela.setStyle(estilo)
    partes.append(tabela)
    partes.append(Spacer(1, 4))
    partes.append(Paragraph(dados["formula"] + " · Comida é tudo que não é bebida.",
                            estilos["nota"]))

    conf = dados["confiabilidade"]
    partes.append(Paragraph("Confiabilidade", estilos["secao"]))
    texto = (f"{conf['itens_apurados']} itens apurados no período. ")
    if conf["itens_estimados"]:
        texto += (f"<b>{conf['itens_estimados']} deles ({brl(conf['valor_estimado'])}) "
                  f"não tiveram contagem de fechamento</b> e entraram com estoque final "
                  f"estimado pelo saldo teórico. Quanto maior esse número, mais o CMV "
                  f"depende de estimativa.")
    else:
        texto += "Todos com contagem de fechamento — nenhum valor estimado."
    partes.append(Paragraph(texto, estilos["texto"]))

    if dados.get("avisos"):
        partes.append(Paragraph("Observações", estilos["secao"]))
        for aviso in dados["avisos"]:
            partes.append(Paragraph("• " + aviso, estilos["nota"]))

    doc.build(partes, onFirstPage=_rodape_factory(dados["cabecalho"]),
              onLaterPages=_rodape_factory(dados["cabecalho"]))
    buffer.seek(0)
    return buffer


# ==============================================================================
# 2 · COMPARATIVO
# ==============================================================================
def pdf_comparativo(dados: dict) -> BytesIO:
    if not dados.get("disponivel"):
        return _indisponivel("Comparativo entre períodos", dados)

    buffer = BytesIO()
    estilos = _estilos()
    doc = _documento(buffer, False, dados["cabecalho"])
    partes = _cabecalho_flow("Comparativo entre períodos", dados["cabecalho"], estilos)
    partes.append(Paragraph(
        f"{dados['cabecalho']['rotulo']} comparado com {dados['periodo_anterior']['rotulo']}",
        estilos["texto"]))
    partes.append(Spacer(1, 6))

    linhas = [["Indicador", dados["cabecalho"]["rotulo"],
               dados["periodo_anterior"]["rotulo"], "Variação"]]
    cores_linha = []
    for i, ind in enumerate(dados["indicadores"], start=1):
        formatar = pct if ind["formato"] == "PERCENTUAL" else brl
        variacao = (pontos(ind["variacao"]) if ind["formato"] == "PERCENTUAL"
                    else (f"{'+' if (ind['variacao'] or 0) > 0 else ''}"
                          f"{ind['variacao'] * 100:.1f}%".replace(".", ",")
                          if ind["variacao"] is not None else "—"))
        linhas.append([ind["rotulo"], formatar(ind["atual"]),
                       formatar(ind["anterior"]), variacao])
        if ind["direcao"] == "boa":
            cores_linha.append((i, VERDE))
        elif ind["direcao"] == "ruim":
            cores_linha.append((i, VERMELHO))

    tabela = Table(linhas, colWidths=[45 * mm, 38 * mm, 38 * mm, 33 * mm])
    estilo = TableStyle(ESTILO_TABELA.getCommands())
    estilo.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
    estilo.add("FONTNAME", (3, 1), (3, -1), "Helvetica-Bold")
    for indice, cor in cores_linha:
        estilo.add("TEXTCOLOR", (3, indice), (3, indice), cor)
    tabela.setStyle(estilo)
    partes.append(tabela)
    partes.append(Spacer(1, 4))
    partes.append(Paragraph(
        f"Meta do período: {pct(dados['meta'])}"
        + (f" (era {pct(dados['meta_anterior'])} no período anterior)"
           if abs((dados['meta'] or 0) - (dados['meta_anterior'] or 0)) > 1e-9 else ""),
        estilos["nota"]))

    def bloco_itens(titulo, itens, cor):
        if not itens:
            return []
        saida = [Paragraph(titulo, estilos["secao"])]
        linhas = [["Código", "Produto", "Atual", "Anterior", "Diferença"]]
        for i in itens:
            linhas.append([i["codigo"] or "—", i["produto"][:38],
                           brl(i["atual"]), brl(i["anterior"]),
                           ("+" if i["delta"] > 0 else "") + brl(i["delta"])[3:]
                           if i["delta"] > 0 else brl(i["delta"])])
        t = Table(linhas, colWidths=[20 * mm, 62 * mm, 28 * mm, 28 * mm, 28 * mm])
        e = TableStyle(ESTILO_TABELA.getCommands())
        e.add("ALIGN", (2, 0), (-1, -1), "RIGHT")
        e.add("TEXTCOLOR", (4, 1), (4, -1), cor)
        e.add("FONTNAME", (4, 1), (4, -1), "Helvetica-Bold")
        t.setStyle(e)
        saida.append(t)
        return saida

    partes += bloco_itens("Itens que mais subiram", dados["pioraram"], VERMELHO)
    partes += bloco_itens("Itens que mais caíram", dados["melhoraram"], VERDE)

    doc.build(partes, onFirstPage=_rodape_factory(dados["cabecalho"]),
              onLaterPages=_rodape_factory(dados["cabecalho"]))
    buffer.seek(0)
    return buffer


# ==============================================================================
# 3 · CURVA ABC
# ==============================================================================
def pdf_curva_abc(dados: dict) -> BytesIO:
    if not dados.get("disponivel"):
        return _indisponivel("Curva ABC de itens", dados)

    buffer = BytesIO()
    estilos = _estilos()
    doc = _documento(buffer, True, dados["cabecalho"])
    partes = _cabecalho_flow("Curva ABC de itens", dados["cabecalho"], estilos)

    resumo = dados["resumo"]
    faixas = Table([[
        Paragraph(f"<font size=9 color='#6B7280'>Faixa A · 80% do custo</font><br/>"
                  f"<font size=16 color='#A6231F'><b>{resumo['A']['itens']} itens</b></font>"
                  f"<br/><font size=9>{brl(resumo['A']['valor'])}</font>", estilos["destaque_menor"]),
        Paragraph(f"<font size=9 color='#6B7280'>Faixa B · 15%</font><br/>"
                  f"<font size=16 color='#B08D3E'><b>{resumo['B']['itens']} itens</b></font>"
                  f"<br/><font size=9>{brl(resumo['B']['valor'])}</font>", estilos["destaque_menor"]),
        Paragraph(f"<font size=9 color='#6B7280'>Faixa C · 5%</font><br/>"
                  f"<font size=16 color='#6B7280'><b>{resumo['C']['itens']} itens</b></font>"
                  f"<br/><font size=9>{brl(resumo['C']['valor'])}</font>", estilos["destaque_menor"]),
        Paragraph(f"<font size=9 color='#6B7280'>Total apurado</font><br/>"
                  f"<font size=16 color='#1F3B57'><b>{brl(dados['total_cmv'])}</b></font>"
                  f"<br/><font size=9>{dados['total_itens']} itens</font>", estilos["destaque_menor"]),
    ]], colWidths=[62 * mm, 62 * mm, 62 * mm, 62 * mm])
    faixas.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), FUNDO),
        ("BOX", (0, 0), (-1, -1), 0.5, LINHA),
        ("INNERGRID", (0, 0), (-1, -1), 0.5, colors.white),
        ("LEFTPADDING", (0, 0), (-1, -1), 9),
        ("TOPPADDING", (0, 0), (-1, -1), 7),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    partes.append(faixas)
    partes.append(Spacer(1, 3))
    partes.append(Paragraph(
        f"Os {resumo['A']['itens']} itens da faixa A concentram "
        f"{pct(resumo['A']['participacao'])} do custo. É neles que negociação de preço "
        f"e controle de porção viram dinheiro perceptível.", estilos["nota"]))

    partes.append(Paragraph("Itens ordenados por custo", estilos["secao"]))
    linhas = [["#", "Faixa", "Código", "Produto", "Família", "Qtd.", "Custo un.",
               "CMV", "% do total", "Acumulado"]]
    for l in dados["linhas"]:
        linhas.append([
            str(l["posicao"]), l["faixa"], l["codigo"] or "—", l["produto"][:34],
            l["categoria"][:18], num(l["quantidade"]) + " " + (l["unidade_medida"] or ""),
            brl(l["custo_unitario"]), brl(l["cmv"]),
            pct(l["participacao"], 2), pct(l["acumulado"], 1),
        ])

    tabela = Table(linhas, repeatRows=1,
                   colWidths=[10 * mm, 13 * mm, 19 * mm, 62 * mm, 32 * mm, 26 * mm,
                              24 * mm, 26 * mm, 22 * mm, 22 * mm])
    estilo = TableStyle(ESTILO_TABELA.getCommands())
    estilo.add("ALIGN", (0, 0), (2, -1), "CENTER")
    estilo.add("ALIGN", (5, 0), (-1, -1), "RIGHT")
    estilo.add("FONTNAME", (7, 1), (7, -1), "Helvetica-Bold")
    for i, l in enumerate(dados["linhas"], start=1):
        cor = {"A": VERMELHO, "B": GOLD, "C": CINZA}[l["faixa"]]
        estilo.add("TEXTCOLOR", (1, i), (1, i), cor)
        estilo.add("FONTNAME", (1, i), (1, i), "Helvetica-Bold")
    tabela.setStyle(estilo)
    partes.append(tabela)

    doc.build(partes, onFirstPage=_rodape_factory(dados["cabecalho"]),
              onLaterPages=_rodape_factory(dados["cabecalho"]))
    buffer.seek(0)
    return buffer


# ==============================================================================
# 4 · CONSUMO POR FAMÍLIA
# ==============================================================================
def pdf_familias(dados: dict) -> BytesIO:
    if not dados.get("disponivel"):
        return _indisponivel("Consumo por família", dados)

    buffer = BytesIO()
    estilos = _estilos()
    doc = _documento(buffer, False, dados["cabecalho"])
    partes = _cabecalho_flow("Consumo por família", dados["cabecalho"], estilos)
    partes.append(Paragraph(
        f"CMV total de {brl(dados['total_cmv'])} sobre faturamento de "
        f"{brl(dados['faturamento'])}. Meta geral: {pct(dados['meta_geral'])}.",
        estilos["texto"]))
    partes.append(Spacer(1, 6))

    linhas = [["Família", "Itens", "CMV", "% do faturamento", "Meta", "Situação"]]
    situacoes = []
    for i, l in enumerate(dados["linhas"], start=1):
        if l["dentro_da_meta"] is None:
            situacao, cor = "—", CINZA
        elif l["dentro_da_meta"]:
            situacao, cor = "dentro", VERDE
        else:
            situacao, cor = "acima", VERMELHO
        meta_txt = pct(l["meta"])
        if not l["meta_definida"] and l["meta_herdada_de"]:
            meta_txt += " *"
        linhas.append([l["familia"][:28], str(l["itens"]), brl(l["cmv"]),
                       pct(l["percentual"], 2), meta_txt, situacao])
        situacoes.append((i, cor))

    tabela = Table(linhas, colWidths=[45 * mm, 16 * mm, 32 * mm, 34 * mm, 26 * mm, 24 * mm])
    estilo = TableStyle(ESTILO_TABELA.getCommands())
    estilo.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
    estilo.add("ALIGN", (5, 0), (5, -1), "CENTER")
    estilo.add("FONTNAME", (2, 1), (2, -1), "Helvetica-Bold")
    for indice, cor in situacoes:
        estilo.add("TEXTCOLOR", (5, indice), (5, indice), cor)
    tabela.setStyle(estilo)
    partes.append(tabela)
    partes.append(Spacer(1, 4))
    partes.append(Paragraph(
        "* meta herdada do bloco (comida/bebida) — a família ainda não tem meta própria. "
        "O percentual de cada família é sobre o faturamento total, de forma que a soma "
        "delas dá exatamente o CMV geral.", estilos["nota"]))

    if dados.get("evolucao"):
        partes.append(Paragraph("Evolução", estilos["secao"]))
        rotulos = [e["rotulo"].split("/")[0][:3] for e in dados["evolucao"]]
        cabeca = ["Família"] + rotulos + [dados["cabecalho"]["rotulo"].split("/")[0][:3]]
        linhas = [cabeca]
        for l in dados["linhas"]:
            linha = [l["familia"][:26]]
            for e in dados["evolucao"]:
                linha.append(pct(e["por_familia"].get(l["categoria_id"]), 2))
            linha.append(pct(l["percentual"], 2))
            linhas.append(linha)
        largura = (180 - 45) / max(len(cabeca) - 1, 1)
        tabela = Table(linhas, colWidths=[45 * mm] + [largura * mm] * (len(cabeca) - 1))
        estilo = TableStyle(ESTILO_TABELA.getCommands())
        estilo.add("ALIGN", (1, 0), (-1, -1), "RIGHT")
        estilo.add("FONTNAME", (-1, 1), (-1, -1), "Helvetica-Bold")
        tabela.setStyle(estilo)
        partes.append(tabela)

    doc.build(partes, onFirstPage=_rodape_factory(dados["cabecalho"]),
              onLaterPages=_rodape_factory(dados["cabecalho"]))
    buffer.seek(0)
    return buffer


GERADORES = {
    "fechamento": pdf_fechamento,
    "comparativo": pdf_comparativo,
    "curva-abc": pdf_curva_abc,
    "familias": pdf_familias,
}
