"""Render the current model-free InvoiceIQ architecture as a presentation PNG."""
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "docs" / "architecture" / "top-level-architecture.png"
W, H = 3200, 1800
BG, WHITE, INK, MUTED, BORDER = "#F4F8FC", "#FFFFFF", "#0B2239", "#526B82", "#CCD9E5"
NAVY, BLUE, CYAN, TEAL = "#0C2944", "#1976B9", "#1B9AAA", "#087F70"
GREEN, VIOLET, AMBER, RED = "#27855F", "#6852A3", "#B06D16", "#B63C48"
canvas = Image.new("RGB", (W, H), BG)
draw = ImageDraw.Draw(canvas)


def font(size, bold=False):
    name = "segoeuib.ttf" if bold else "segoeui.ttf"
    return ImageFont.truetype(str(Path("C:/Windows/Fonts") / name), size)


def label(x, y, value, size=30, color=INK, bold=False, anchor=None):
    draw.text((x, y), value, font=font(size, bold), fill=color, anchor=anchor)


def wrapped(value, max_width, face):
    words, lines, current = value.split(), [], ""
    for word in words:
        candidate = f"{current} {word}".strip()
        if current and draw.textlength(candidate, font=face) > max_width:
            lines.append(current)
            current = word
        else:
            current = candidate
    if current:
        lines.append(current)
    return lines


def rounded_box(x, y, w, h, fill=WHITE, outline=BORDER, radius=26, width=3):
    draw.rounded_rectangle((x, y, x + w, y + h), radius=radius, fill=fill, outline=outline, width=width)


def card(x, y, w, h, kicker, title, items, accent=BLUE, fill=WHITE):
    rounded_box(x, y, w, h, fill)
    draw.rounded_rectangle((x, y, x + 16, y + h), radius=8, fill=accent)
    label(x + 46, y + 28, kicker.upper(), 22, accent, True)
    label(x + 46, y + 66, title, 34, INK, True)
    yy, face = y + 118, font(22)
    for item in items:
        draw.ellipse((x + 48, yy + 10, x + 58, yy + 20), fill=accent)
        for line in wrapped(item, w - 105, face):
            draw.text((x + 75, yy), line, font=face, fill=MUTED)
            yy += 29
        yy += 6
    assert yy <= y + h + 8, (title, yy, y + h)


def arrow(x1, y1, x2, y2, color=BLUE, width=7):
    draw.line((x1, y1, x2, y2), fill=color, width=width)
    if abs(x2 - x1) >= abs(y2 - y1):
        direction = 1 if x2 > x1 else -1
        draw.polygon([(x2, y2), (x2 - 24 * direction, y2 - 14), (x2 - 24 * direction, y2 + 14)], fill=color)
    else:
        direction = 1 if y2 > y1 else -1
        draw.polygon([(x2, y2), (x2 - 14, y2 - 24 * direction), (x2 + 14, y2 - 24 * direction)], fill=color)


# Header
draw.rectangle((0, 0, W, 195), fill=NAVY)
label(105, 45, "INVOICEIQ", 28, "#75C8FF", True)
label(105, 84, "Intelligent Invoice Workflow Orchestration", 58, WHITE, True)
label(3090, 75, "LOCAL • TRACEABLE • MODEL-FREE", 25, "#B9D4E8", True, "ra")
label(3090, 123, "From invoice documents to validated, upload-ready data", 25, "#B9D4E8", False, "ra")

label(105, 235, "1  INPUT CHANNELS", 24, BLUE, True)
label(890, 235, "2  LOCAL PROCESSING PIPELINE", 24, TEAL, True)
label(2510, 235, "3  CONTROL DATA", 24, VIOLET, True)

card(100, 280, 620, 225, "Manual intake", "Upload workspace", [
    "PDF, scanned image, ZIP, MSG, EML, CSV and XLSX",
    "Drag-and-drop or configured input folder",
], BLUE, "#EAF4FC")
card(100, 535, 620, 225, "Automated intake", "Classic Outlook", [
    "Invoices folder through Windows COM",
    "Optional 30-minute Windows scheduled run",
], CYAN, "#EAF8FA")
card(100, 790, 620, 225, "Operator", "Finance processor", [
    "Runs extraction, MDM check and downloads",
    "Sees clear rejected or exception reasons",
], AMBER, "#FFF7E9")

rounded_box(835, 280, 1570, 735, WHITE, "#BFD2E2", 32, 4)
label(895, 315, "LOCAL APPLICATION PIPELINE", 25, NAVY, True)
label(895, 353, "Runs on the Windows computer; no OpenAI, Gemini, LLM or custom inference model.", 23, MUTED)
pipeline = [
    (895, 420, 445, 235, "01", "Document decoding", ["PyMuPDF native PDF text", "Tesseract OCR + Pillow", "extract-msg / EML parser"], BLUE),
    (1430, 420, 445, 235, "02", "Field extraction", ["Spatial word coordinates", "Label and table rules", "Printed dates preserved"], TEAL),
    (1965, 420, 380, 235, "03", "Invoice validation", ["Required fields", "Amount arithmetic", "Service dates + duplicates"], AMBER),
    (895, 735, 445, 230, "04", "MDM reconciliation", ["Vendor normalization", "Supplier-region restriction", "Unambiguous account only"], VIOLET),
    (1430, 735, 445, 230, "05", "Contract control", ["Account ↔ Contract ID", "Start/end presence", "Expired/future rejection"], RED),
    (1965, 735, 380, 230, "06", "Result decision", ["Success", "Rejected", "Needs review / reason"], GREEN),
]
for args in pipeline:
    x, y, w, h, number, title, items, accent = args
    card(x, y, w, h, number, title, items, accent, "#F9FBFD")
arrow(1345, 537, 1415, 537, TEAL)
arrow(1880, 537, 1950, 537, AMBER)
arrow(2155, 665, 1117, 720, VIOLET, 6)
arrow(1345, 850, 1415, 850, RED)
arrow(1880, 850, 1950, 850, GREEN)

card(2510, 280, 590, 225, "Read-only master", "Vendor Accounts", [
    "Vendor + Account Number", "Restricted To selects supplier region", "Today's InvoiceMDM export",
], VIOLET, "#F4F0FA")
card(2510, 535, 590, 225, "Read-only master", "Contracts", [
    "Contract ID / account mapping", "Contract Start Date + End Date", "Today's contracts export",
], RED, "#FBEFF1")
card(2510, 790, 590, 225, "Governance", "Deterministic controls", [
    "No arbitrary account assignment", "Ambiguous or invalid results stay visible",
], GREEN, "#EDF8F3")
arrow(2510, 395, 2405, 830, VIOLET, 6)
arrow(2510, 650, 2405, 865, RED, 6)

label(105, 1065, "4  PERSISTENCE, OUTPUTS & USER EXPERIENCE", 24, GREEN, True)
card(100, 1110, 620, 255, "Experience layer", "React operator workspace", [
    "React 19 + FLOWSTACK UI Brick", "Vite build served by FastAPI", "Upload, search, Run MDM, Check and export",
], BLUE, "#EAF4FC")
card(835, 1110, 620, 255, "Local persistence", "Audit-ready history", [
    "SQLite processing database", "Archived sources and fingerprints", "Saved corrections and traceable reasons",
], TEAL, "#EAF8FA")
card(1570, 1110, 620, 255, "Reporting", "Structured business outputs", [
    "Successful invoice data CSV", "Contract-verified cumulative feed", "Excel workbook via openpyxl",
], GREEN, "#EDF8F3")
card(2305, 1110, 795, 255, "Operating model", "Local Windows deployment", [
    "FastAPI + Uvicorn on 127.0.0.1:8505", "Configurable input, output and MDM folders", "Data remains on the application computer",
], NAVY, "#EDF2F6")
arrow(2160, 965, 1880, 1095, GREEN, 7)

label(105, 1420, "TECHNOLOGY STACK", 24, NAVY, True)
rounded_box(100, 1460, 3000, 245, NAVY, NAVY, 30, 0)
groups = [
    ("FRONTEND", "React 19  •  FLOWSTACK UI Brick  •  Vite 7", "#63B3ED"),
    ("API & SCHEMA", "Python  •  FastAPI  •  Uvicorn  •  Pydantic", "#61D6C4"),
    ("DOCUMENTS", "PyMuPDF  •  Tesseract  •  pytesseract  •  Pillow  •  extract-msg", "#F6C35B"),
    ("DATA & REPORTS", "SQLite  •  CSV  •  openpyxl  •  Local filesystem", "#73D39B"),
    ("WINDOWS INTEGRATION", "pywin32  •  Outlook COM  •  Task Scheduler", "#BEA4F4"),
    ("QUALITY", "pytest  •  FastAPI TestClient  •  Vite production build", "#F29BA5"),
]
positions = [(145, 1495), (1110, 1495), (2060, 1495), (145, 1595), (1110, 1595), (2060, 1595)]
for (heading, values, accent), (x, y) in zip(groups, positions):
    label(x, y, heading, 20, accent, True)
    label(x, y + 36, values, 22, WHITE)

label(100, 1742, "DESIGN PRINCIPLE", 20, BLUE, True)
label(345, 1742, "AI-free runtime: native PDF text + OCR + deterministic rules + authoritative master-data validation.", 23, MUTED)
label(3100, 1742, "InvoiceIQ • Architecture v2", 21, MUTED, False, "ra")

OUTPUT.parent.mkdir(parents=True, exist_ok=True)
canvas.save(OUTPUT, optimize=True, dpi=(200, 200))
print(f"{OUTPUT} ({W} x {H})")
