"""Build the shareable Word copy of SUBMISSION.md with the bundled runtime."""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from docx.enum.table import WD_CELL_VERTICAL_ALIGNMENT
from docx.enum.text import WD_ALIGN_PARAGRAPH
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.shared import Inches, Pt, RGBColor


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "SUBMISSION.md"
OUTPUT = ROOT / "SUBMISSION.docx"


def set_cell_shading(cell, fill: str) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    shd = OxmlElement("w:shd")
    shd.set(qn("w:fill"), fill)
    tc_pr.append(shd)


def set_cell_border(cell) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    borders = tc_pr.first_child_found_in("w:tcBorders")
    if borders is None:
        borders = OxmlElement("w:tcBorders")
        tc_pr.append(borders)
    for edge in ("top", "left", "bottom", "right"):
        element = OxmlElement(f"w:{edge}")
        element.set(qn("w:val"), "single")
        element.set(qn("w:sz"), "4")
        element.set(qn("w:color"), "D9D9D9")
        borders.append(element)


def set_cell_padding(cell, compact: bool = False) -> None:
    tc_pr = cell._tc.get_or_add_tcPr()
    mar = OxmlElement("w:tcMar")
    for side in ("top", "bottom", "left", "right"):
        item = OxmlElement(f"w:{side}")
        item.set(qn("w:w"), "55" if compact else "70")
        item.set(qn("w:type"), "dxa")
        mar.append(item)
    tc_pr.append(mar)


def add_inline(paragraph, value: str) -> None:
    for token in re.split(r"(\*\*[^*]+\*\*|`[^`]+`)", value):
        if not token:
            continue
        if token.startswith("**") and token.endswith("**"):
            run = paragraph.add_run(token[2:-2])
            run.bold = True
        elif token.startswith("`") and token.endswith("`"):
            run = paragraph.add_run(token[1:-1])
            run.font.name = "Consolas"
            run.font.size = Pt(9)
        else:
            paragraph.add_run(token)


def parse_table(lines: list[str], doc: Document) -> None:
    rows = []
    for line in lines:
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if all(re.fullmatch(r":?-{3,}:?", cell) for cell in cells):
            continue
        rows.append(cells)
    if not rows:
        return
    table = doc.add_table(rows=len(rows), cols=len(rows[0]))
    table.autofit = False
    table.style = "Table Grid"
    widths = ([1.5, 4.9] if len(rows[0]) == 2 else [1.35, 1.0, 1.35, 1.25, 2.45])
    if len(widths) != len(rows[0]):
        widths = [6.4 / len(rows[0])] * len(rows[0])
    for row_index, values in enumerate(rows):
        row = table.rows[row_index]
        for index, value in enumerate(values):
            cell = row.cells[index]
            cell.width = Inches(widths[index])
            cell.vertical_alignment = WD_CELL_VERTICAL_ALIGNMENT.CENTER
            cell.text = ""
            paragraph = cell.paragraphs[0]
            paragraph.paragraph_format.space_after = Pt(0)
            paragraph.paragraph_format.line_spacing = 1.05
            add_inline(paragraph, value)
            for run in paragraph.runs:
                run.font.size = Pt(7.7 if len(rows[0]) == 5 else 9)
                if row_index == 0:
                    run.font.bold = True
                    run.font.color.rgb = RGBColor(255, 255, 255)
            set_cell_border(cell)
            set_cell_padding(cell, compact=len(rows[0]) == 5)
            if row_index == 0:
                set_cell_shading(cell, "253A52")
            elif row_index % 2 == 0:
                set_cell_shading(cell, "F3F6F9")
    header_pr = table.rows[0]._tr.get_or_add_trPr()
    header = OxmlElement("w:tblHeader")
    header.set(qn("w:val"), "true")
    header_pr.append(header)
    doc.add_paragraph().paragraph_format.space_after = Pt(1)


def main() -> None:
    lines = SOURCE.read_text(encoding="utf-8").splitlines()
    doc = Document()
    section = doc.sections[0]
    section.page_width = Inches(8.5)
    section.page_height = Inches(11)
    section.top_margin = Inches(0.8)
    section.bottom_margin = Inches(0.75)
    section.left_margin = Inches(0.85)
    section.right_margin = Inches(0.85)

    normal = doc.styles["Normal"]
    normal.font.name = "Aptos"
    normal.font.size = Pt(10.2)
    normal.font.color.rgb = RGBColor(0, 0, 0)
    normal.paragraph_format.space_after = Pt(6)
    normal.paragraph_format.line_spacing = 1.1
    for name, size, before, after in (
        ("Title", 19, 0, 13),
        ("Heading 1", 13, 14, 7),
        ("Heading 2", 11, 12, 5),
    ):
        style = doc.styles[name]
        style.font.name = "Aptos Display" if name == "Title" else "Aptos"
        style.font.size = Pt(size)
        style.font.bold = name != "Title"
        style.font.color.rgb = RGBColor(0, 0, 0)
        style.paragraph_format.space_before = Pt(before)
        style.paragraph_format.space_after = Pt(after)
        style.paragraph_format.keep_with_next = True
    title_pr = doc.styles["Title"]._element.get_or_add_pPr()
    title_border = title_pr.find(qn("w:pBdr"))
    if title_border is not None:
        title_pr.remove(title_border)

    index = 0
    in_code = False
    while index < len(lines):
        line = lines[index]
        if line.startswith("```"):
            in_code = not in_code
            if not in_code:
                spacer = doc.add_paragraph()
                spacer.paragraph_format.space_after = Pt(2)
            index += 1
            continue
        if in_code:
            p = doc.add_paragraph(style="Normal")
            p.paragraph_format.left_indent = Inches(0.2)
            p.paragraph_format.space_after = Pt(1)
            run = p.add_run(line or " ")
            run.font.name = "Consolas"
            run.font.size = Pt(8.4)
            index += 1
            continue
        if line.startswith("| "):
            table_lines = []
            while index < len(lines) and lines[index].startswith("| "):
                table_lines.append(lines[index])
                index += 1
            parse_table(table_lines, doc)
            continue
        if line.startswith("# "):
            doc.add_paragraph(line[2:], style="Title")
        elif line.startswith("## "):
            heading = line[3:]
            paragraph = doc.add_paragraph(heading, style="Heading 1")
            if heading in {"Key Features", "Open Source and Third Party Inventory"}:
                paragraph.paragraph_format.page_break_before = True
        elif line.startswith("### "):
            doc.add_paragraph(line[4:], style="Heading 2")
        elif re.match(r"^\d+\. ", line):
            p = doc.add_paragraph(style="List Number")
            add_inline(p, re.sub(r"^\d+\. ", "", line))
        elif line.startswith("- [ ] "):
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, "[ ] " + line[6:])
        elif line.startswith("- "):
            p = doc.add_paragraph(style="List Bullet")
            add_inline(p, line[2:])
        elif line.strip():
            p = doc.add_paragraph()
            add_inline(p, line)
        index += 1

    doc.core_properties.title = "Intelligent Invoice Workflow Orchestration"
    doc.core_properties.subject = "Business problem and solution submission"
    doc.save(OUTPUT)
    print(OUTPUT)


if __name__ == "__main__":
    main()
