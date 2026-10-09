"""Generate a realistic untagged sample: headings, two-column body, bulleted list,
a data table with header row, a figure, and running header/footer on 2 pages."""
import sys

from PIL import Image
from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import inch
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import (BaseDocTemplate, Frame, Image as RLImage, ListFlowable, ListItem,
                                PageTemplate, Paragraph, Spacer, Table, TableStyle)

F = "/usr/share/fonts/truetype/dejavu/"
pdfmetrics.registerFont(TTFont("DV", F + "DejaVuSans.ttf"))
pdfmetrics.registerFont(TTFont("DVB", F + "DejaVuSans-Bold.ttf"))
body = ParagraphStyle("b", fontName="DV", fontSize=10, leading=13)
h1 = ParagraphStyle("h1", fontName="DVB", fontSize=20, leading=24, spaceAfter=8)
h2 = ParagraphStyle("h2", fontName="DVB", fontSize=14, leading=18, spaceBefore=8, spaceAfter=4)

def deco(c, d):
    c.setFont("DV", 8)
    c.drawString(inch, 10.5 * inch, "State Department of Education | Budget Summary FY2026")
    c.drawRightString(7.5 * inch, 0.5 * inch, f"Page {d.page}")

doc = BaseDocTemplate(sys.argv[1], pagesize=letter)
w = (doc.width - 12) / 2
frames = [Frame(doc.leftMargin, doc.bottomMargin, w, doc.height, id="c1"),
          Frame(doc.leftMargin + w + 12, doc.bottomMargin, w, doc.height, id="c2")]
doc.addPageTemplates([PageTemplate(id="two", frames=frames, onPage=deco)])
img_path = sys.argv[1] + ".png"
Image.new("RGB", (300, 180), (40, 110, 70)).save(img_path)
lorem = ("Funding for accessible instructional materials increased this year. Districts must "
         "remediate legacy documents that remain in active use. ") * 3
story = [Paragraph("Budget Summary for Fiscal Year 2026", h1),
         Paragraph("Overview", h2), Paragraph(lorem, body),
         Paragraph("Priorities", h2),
         ListFlowable([ListItem(Paragraph(t, body)) for t in
                       ["Remediate high-traffic PDFs first", "Train content authors", "Audit vendors quarterly"]],
                      bulletType="bullet"),
         Paragraph("Allocations", h2),
         Table([["Program", "FY2025", "FY2026"], ["Remediation", "$1.2M", "$2.0M"],
                ["Training", "$0.4M", "$0.6M"], ["Audits", "$0.2M", "$0.3M"]],
               style=TableStyle([("FONT", (0, 0), (-1, -1), "DV", 9), ("FONT", (0, 0), (-1, 0), "DVB", 9),
                                 ("GRID", (0, 0), (-1, -1), 0.5, colors.grey)])),
         Spacer(1, 8), RLImage(img_path, width=2.4 * inch, height=1.4 * inch),
         Paragraph("Figure 1. Allocation trend, FY2022 to FY2026.", body),
         Paragraph("Outlook", h2)] + [Paragraph(lorem, body) for _ in range(6)]
doc.build(story)
