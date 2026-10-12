"""theme.py - shared dark theme for the aero_auto PDF documentation (reportlab).

Dark pages (#0f172a), amber/sky accents, panel-style code blocks. Both the
technical report and the user manual use these helpers so the two documents
always match.
"""
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib import colors
from reportlab.lib.units import mm

# ---- palette (matches the brand icon) -------------------------------------
BG = colors.HexColor("#0f172a")        # page background
PANEL = colors.HexColor("#1e293b")     # code panel / table bands
PANEL2 = colors.HexColor("#101d36")    # card
BAND = colors.HexColor("#12234a")      # table header
TEXT = colors.HexColor("#e2e8f0")      # body
MUTED = colors.HexColor("#94a3b8")     # secondary
CODE_TEXT = colors.HexColor("#f1f5f9") # code text
ACCENT = colors.HexColor("#f79e0b")    # amber
ACCENT2 = colors.HexColor("#7dd3fc")   # sky
RULE = colors.HexColor("#33415c")      # hairline
WHITE = colors.HexColor("#ffffff")


def register_styles():
    return {
        "title": ParagraphStyle("title", fontName="Helvetica-Bold", fontSize=27,
                                leading=33, textColor=WHITE, spaceAfter=6),
        "subtitle": ParagraphStyle("subtitle", fontName="Helvetica", fontSize=12,
                                   leading=16, textColor=ACCENT2),
        "intro": ParagraphStyle("intro", fontName="Helvetica", fontSize=10.5,
                                leading=16, textColor=TEXT, spaceAfter=8),
        "h1": ParagraphStyle("h1", fontName="Helvetica-Bold", fontSize=16,
                             leading=21, textColor=ACCENT, spaceBefore=16, spaceAfter=6),
        "h2": ParagraphStyle("h2", fontName="Helvetica-Bold", fontSize=12.5,
                             leading=17, textColor=ACCENT2, spaceBefore=12, spaceAfter=4),
        "h3": ParagraphStyle("h3", fontName="Helvetica-Bold", fontSize=10.5,
                             leading=14, textColor=WHITE, spaceBefore=6, spaceAfter=3),
        "body": ParagraphStyle("body", fontName="Helvetica", fontSize=9.8,
                               leading=14.2, textColor=TEXT, spaceAfter=5),
        "bullet": ParagraphStyle("bullet", fontName="Helvetica", fontSize=9.8,
                                 leading=14.2, textColor=TEXT, leftIndent=12,
                                 bulletIndent=2, spaceAfter=3),
        "tag": ParagraphStyle("tag", fontName="Helvetica-Bold", fontSize=8.5,
                              leading=11, textColor=ACCENT, spaceBefore=2, spaceAfter=1),
        "why": ParagraphStyle("why", fontName="Helvetica-Bold", fontSize=9.2,
                              leading=13, textColor=ACCENT2, spaceBefore=3, spaceAfter=1),
        "how": ParagraphStyle("how", fontName="Helvetica-Bold", fontSize=9.2,
                              leading=13, textColor=colors.HexColor("#86efac"),
                              spaceBefore=3, spaceAfter=1),
        "small": ParagraphStyle("small", fontName="Helvetica-Oblique", fontSize=8.6,
                                leading=11.5, textColor=MUTED, spaceAfter=3),
        "codecap": ParagraphStyle("codecap", fontName="Courier-Bold", fontSize=8,
                                  leading=10, textColor=ACCENT, spaceBefore=4, spaceAfter=1),
        "code": ParagraphStyle("code", fontName="Courier", fontSize=7.6, leading=10,
                               textColor=CODE_TEXT, backColor=PANEL,
                               borderColor=colors.HexColor("#2c3a55"),
                               borderWidth=0.6, borderPadding=7),
        "note": ParagraphStyle("note", fontName="Helvetica", fontSize=9.2, leading=13.4,
                               textColor=colors.HexColor("#cbd5e1"), backColor=PANEL2,
                               borderColor=colors.HexColor("#2c3a55"), borderWidth=0.6,
                               borderPadding=7, spaceBefore=4, spaceAfter=6),
        "cell": ParagraphStyle("cell", fontName="Helvetica", fontSize=8.6, leading=11.5,
                               textColor=TEXT),
        "cellb": ParagraphStyle("cellb", parent=None, fontName="Helvetica-Bold",
                                fontSize=8.6, leading=11.5, textColor=ACCENT),
    }


def draw_bg(canv, doc):
    """Full-page dark background + footer. Registered for every page."""
    w, h = A4
    canv.setPageCompression(0)          # keep text streams greppable for QA
    canv.saveState()
    canv.setFillColor(BG)
    canv.rect(0, 0, w, h, fill=1, stroke=0)
    # hairline + footer
    canv.setStrokeColor(RULE)
    canv.setLineWidth(0.4)
    canv.line(20 * mm, 13 * mm, w - 20 * mm, 13 * mm)
    canv.setFillColor(MUTED)
    canv.setFont("Helvetica", 7.5)
    canv.drawString(20 * mm, 9 * mm, "aero_auto 1.1 - dark edition")
    canv.drawRightString(w - 20 * mm, 9 * mm, f"- {doc.page} -")
    canv.restoreState()


def cover_bg(canv, doc):
    """Like draw_bg but without the -page- footer, for the cover page."""
    w, h = A4
    canv.setPageCompression(0)
    canv.saveState()
    canv.setFillColor(BG)
    canv.rect(0, 0, w, h, fill=1, stroke=0)
    # subtle band
    canv.setFillColor(PANEL)
    canv.rect(0, h - 22 * mm, w, 22 * mm, fill=1, stroke=0)
    canv.setFillColor(ACCENT)
    canv.rect(0, h - 22.6 * mm, w, 0.6 * mm, fill=1, stroke=0)
    canv.restoreState()


def dark_table(data, widths):
    """data: list of rows of Paragraphs; first row becomes the header band."""
    from reportlab.platypus import Table, TableStyle
    t = Table(data, colWidths=widths, repeatRows=1)
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, 0), BAND),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [BG, PANEL2]),
        ("GRID", (0, 0), (-1, -1), 0.5, RULE),
        ("BOX", (0, 0), (-1, -1), 0.8, colors.HexColor("#33415c")),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]))
    return t