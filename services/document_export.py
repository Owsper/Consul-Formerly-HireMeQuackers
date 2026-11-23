"""DOCX / PDF / TXT export for tailored CVs.

Every document is populated into ``templates/master_cv.docx`` — the reusable
reconstruction of the reference CV (A4, 57.7 pt margins, Times/Liberation Serif,
111.6 pt date column, underlined section rules, hanging bullets, two-column skill
rows). No generic centred resume layout is created.

The PDF is rendered from the DOCX with LibreOffice when a converter is available.
When it is not (for example on a machine without LibreOffice), a measured renderer
draws the same geometry directly, so the exported PDF still matches the reference.
"""

from __future__ import annotations

import tempfile
from datetime import date
from pathlib import Path

from core.logging_config import get_logger
from core.schemas import CVEntry, CVRow, CVSection, CoverLetterDraft, TailoredCV
from services.cv_tailoring import filename_for
from services.master_template import (
    BODY_SIZE_PT, BULLET_GAP_PT, BULLET_INDENT_PT, BULLET_LINE_PT, COLUMN_START_PT,
    CONTACT_LINE_PT, ENTRY_GAP_PT, FONT_FAMILY, MARGIN_BOTTOM_PT, MARGIN_LEFT_PT,
    MARGIN_RIGHT_PT, MARGIN_TOP_PT, META_GAP_PT, META_SIZE_PT, NAME_SIZE_PT,
    PAGE_HEIGHT_PT, PAGE_WIDTH_PT, ROW_LINE_PT, SECTION_LINE_PT, SECTION_RULE_PT,
    SECTION_SIZE_PT, SECTION_SPACE_BEFORE_PT, STYLE_BODY, STYLE_BULLET, STYLE_CONTACT,
    STYLE_DETAIL, STYLE_ENTRY, STYLE_META, STYLE_NAME, STYLE_ROW, STYLE_SECTION,
    convert_docx_to_pdf, new_document_from_master,
)

logger = get_logger("export")

CONTENT_WIDTH_PT = PAGE_WIDTH_PT - MARGIN_LEFT_PT - MARGIN_RIGHT_PT
MAIN_WIDTH_PT = PAGE_WIDTH_PT - MARGIN_RIGHT_PT - (MARGIN_LEFT_PT + COLUMN_START_PT)
BULLET_TEXT_X_PT = MARGIN_LEFT_PT + COLUMN_START_PT + BULLET_INDENT_PT
AVAILABLE_HEIGHT_PT = PAGE_HEIGHT_PT - MARGIN_TOP_PT - MARGIN_BOTTOM_PT
PDF_SOURCES: dict[str, str] = {}


def pdf_render_source(path: str | Path) -> str:
    return PDF_SOURCES.get(str(Path(path)), "measured_renderer")

SECTION_ORDER = [
    "profile", "professional experience", "work experience", "experience",
    "project experience", "projects", "academic projects", "education",
    "technical skills", "skills", "languages", "certifications", "awards",
    "publications", "volunteering", "additional information",
]


# ---------------------------------------------------------------------------
# Shared content helpers
# ---------------------------------------------------------------------------
def _safe_path(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def ordered_sections(cv: TailoredCV) -> list[CVSection]:
    """Apply the master's section order (education leads for early-career CVs)."""
    ranked: list[tuple[int, int, CVSection]] = []
    for index, section in enumerate(cv.sections):
        key = (section.heading or "").strip().lower()
        try:
            rank = SECTION_ORDER.index(key)
        except ValueError:
            rank = len(SECTION_ORDER)
        ranked.append((rank, index, section))
    ranked.sort(key=lambda item: (item[0], item[1]))
    sections = [item[2] for item in ranked]

    has_experience = any(
        s.heading.strip().lower() in {"professional experience", "work experience", "experience"}
        and s.entries for s in sections
    )
    if not has_experience:
        education = next((s for s in sections if s.heading.strip().lower() == "education"), None)
        if education is not None:
            sections.remove(education)
            project_index = next(
                (i for i, s in enumerate(sections)
                 if s.heading.strip().lower() in {"project experience", "projects"}),
                None,
            )
            sections.insert(project_index if project_index is not None else 0, education)
    return sections


def _entry_heading(entry: CVEntry) -> list[tuple[str, bool, bool]]:
    """Bold title, en-dash separator, normal organisation."""
    parts: list[tuple[str, bool, bool]] = []
    if entry.title:
        parts.append((entry.title, True, False))
    if entry.organization:
        prefix = "  –  " if parts else ""
        parts.append((prefix + entry.organization, False, False))
    return parts


def _rows_for(section: CVSection) -> list[CVRow]:
    if section.rows:
        return section.rows
    if section.kind == "skills" and section.skills:
        return [CVRow(label="Technical", text=", ".join(section.skills))]
    return []


def _summary_text(cv: TailoredCV) -> str:
    return (cv.summary or "").strip()


def _line_count(text: str, font: str, size: float, width: float) -> int:
    from reportlab.lib.utils import simpleSplit
    from reportlab.pdfbase.pdfmetrics import stringWidth

    if not text:
        return 1
    lines = simpleSplit(text, font, size, width)
    count = 0
    for line in lines or [text]:
        if stringWidth(line, font, size) <= width:
            count += 1
        else:  # unbroken token longer than the column
            count += max(1, int(stringWidth(line, font, size) / width) + 1)
    return max(1, count)


def _estimate_height(cv: TailoredCV, factor: float = 1.0) -> float:
    height = NAME_SIZE_PT * 1.15
    if cv.header.contact_lines:
        height += _line_count("  |  ".join(cv.header.contact_lines), "Times-Roman",
                              BODY_SIZE_PT, CONTENT_WIDTH_PT) * CONTACT_LINE_PT
    for labelled in (cv.header.visa_status, cv.header.applying_for):
        if labelled:
            height += _line_count(labelled, "Times-Roman", BODY_SIZE_PT,
                                  CONTENT_WIDTH_PT - 70) * CONTACT_LINE_PT + 1.3
    if _summary_text(cv):
        height += 7 + _line_count(_summary_text(cv), "Times-Roman", BODY_SIZE_PT,
                                  CONTENT_WIDTH_PT) * CONTACT_LINE_PT
    for section in ordered_sections(cv):
        height += SECTION_SPACE_BEFORE_PT * factor + SECTION_LINE_PT + 3.7
        rows = _rows_for(section)
        for row in rows:
            height += max(
                _line_count(row.text, "Times-Roman", BODY_SIZE_PT, MAIN_WIDTH_PT),
                _line_count(row.label, "Times-Roman", BODY_SIZE_PT, COLUMN_START_PT),
            ) * ROW_LINE_PT * factor
        for line in section.lines:
            height += _line_count(line, "Times-Roman", BODY_SIZE_PT, CONTENT_WIDTH_PT) \
                * CONTACT_LINE_PT
        for entry in section.entries:
            height += ENTRY_GAP_PT * factor + BODY_SIZE_PT * 1.15
            if entry.technologies:
                height += META_GAP_PT * factor + META_SIZE_PT * 1.2
            for bullet in entry.bullets:
                height += (
                    _line_count(bullet.text, "Times-Roman", BODY_SIZE_PT,
                                PAGE_WIDTH_PT - MARGIN_RIGHT_PT - BULLET_TEXT_X_PT)
                    * BULLET_LINE_PT * factor
                ) + BULLET_GAP_PT
    return height


def _spacing_factor(cv: TailoredCV) -> float:
    """Squeeze spacing slightly to keep a near-one-page CV on one page."""
    estimate = _estimate_height(cv, factor=1.0)
    if estimate <= AVAILABLE_HEIGHT_PT:
        return 1.0
    factor = AVAILABLE_HEIGHT_PT / estimate
    return max(0.88, factor) if factor >= 0.88 else 1.0


# ---------------------------------------------------------------------------
# DOCX: populate the master template
# ---------------------------------------------------------------------------
def export_docx(cv: TailoredCV, path: str | Path, *, template_path: str | None = None) -> str:
    from docx.shared import Pt

    if template_path:
        logger.info("Reference override ignored: the master CV template is authoritative")

    document = new_document_from_master()
    factor = _spacing_factor(cv)

    def paragraph(style: str):
        return document.add_paragraph(style=style)

    def set_spacing(par, *, before: float | None = None, line: float | None = None,
                    after: float | None = None) -> None:
        if before is not None:
            par.paragraph_format.space_before = Pt(before * factor)
        if after is not None:
            par.paragraph_format.space_after = Pt(after)
        if line is not None and factor < 1.0:
            par.paragraph_format.line_spacing = Pt(line * factor)

    # Header
    name = paragraph(STYLE_NAME)
    name.add_run((cv.header.name or "").upper())

    if cv.header.contact_lines:
        contact = paragraph(STYLE_CONTACT)
        contact.add_run("  |  ".join(cv.header.contact_lines))

    if cv.header.visa_status:
        detail = paragraph(STYLE_DETAIL)
        label = detail.add_run("Visa status: ")
        label.bold = True
        detail.add_run(cv.header.visa_status)

    if cv.header.applying_for:
        applying = paragraph(STYLE_DETAIL)
        label = applying.add_run("Applying for: ")
        label.bold = True
        applying.add_run(cv.header.applying_for)

    if _summary_text(cv):
        summary = paragraph(STYLE_BODY)
        summary.add_run(_summary_text(cv))

    for section in ordered_sections(cv):
        heading = paragraph(STYLE_SECTION)
        heading.add_run((section.heading or "").upper())
        set_spacing(heading, before=SECTION_SPACE_BEFORE_PT)

        for row in _rows_for(section):
            par = paragraph(STYLE_ROW)
            if row.label:
                par.add_run(row.label)
                par.add_run("\t")
            par.add_run(row.text)
            set_spacing(par, line=ROW_LINE_PT)

        for line in section.lines:
            par = paragraph(STYLE_BODY)
            par.add_run(line)
            set_spacing(par, before=0, line=CONTACT_LINE_PT)

        for entry in section.entries:
            title = paragraph(STYLE_ENTRY)
            if entry.dates:
                title.add_run(entry.dates)
            title.add_run("\t")
            for text, bold, italic in _entry_heading(entry):
                run = title.add_run(text)
                run.bold = bold
                run.italic = italic
            if entry.location:
                title.add_run(f"  |  {entry.location}")
            set_spacing(title, before=ENTRY_GAP_PT, line=CONTACT_LINE_PT)

            if entry.technologies:
                meta = paragraph(STYLE_META)
                meta.add_run(", ".join(entry.technologies))
                set_spacing(meta, before=META_GAP_PT, line=11.0)

            for bullet in entry.bullets:
                par = paragraph(STYLE_BULLET)
                # A standard round bullet parses more reliably than a decorative
                # glyph; the master's spacing and indentation are unchanged.
                par.add_run("•\t")
                par.add_run(bullet.text)
                set_spacing(par, line=BULLET_LINE_PT)

    path = _safe_path(Path(path))
    document.save(str(path))
    return str(path)


# ---------------------------------------------------------------------------
# PDF: measured renderer (used when LibreOffice is unavailable)
# ---------------------------------------------------------------------------
class _MeasuredPDF:
    def __init__(self, path: Path, cv: TailoredCV, factor: float = 1.0):
        from reportlab.pdfgen import canvas

        self.cv = cv
        self.factor = factor
        self.canvas = canvas.Canvas(
            str(path), pagesize=(PAGE_WIDTH_PT, PAGE_HEIGHT_PT),
            pageCompression=1,
        )
        self.canvas.setTitle(f"{cv.header.name} — {cv.target_job_title}".strip(" —"))
        self.canvas.setAuthor(cv.header.name or "Candidate")
        self.canvas.setSubject("Tailored CV")
        self.canvas.setCreator("consul")
        self.page = 1
        # The reference's first glyph starts at 47.5 pt on the page.
        self.top = 47.5

    # ---- primitives -------------------------------------------------------
    @property
    def bottom(self) -> float:
        return PAGE_HEIGHT_PT - MARGIN_BOTTOM_PT

    def _baseline(self, top: float, size: float) -> float:
        return PAGE_HEIGHT_PT - top - size * 0.891

    def new_page(self) -> None:
        self.canvas.showPage()
        self.page += 1
        self.top = MARGIN_TOP_PT

    def ensure(self, needed: float) -> None:
        if self.top + needed > self.bottom and self.top > MARGIN_TOP_PT + 1:
            self.new_page()

    def text(self, x: float, top: float, value: str, *, font: str = "Times-Roman",
             size: float = BODY_SIZE_PT) -> float:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        self.canvas.setFont(font, size)
        self.canvas.drawString(x, self._baseline(top, size), value)
        return stringWidth(value, font, size)

    def wrap(self, value: str, *, font: str = "Times-Roman", size: float = BODY_SIZE_PT,
             width: float = CONTENT_WIDTH_PT) -> list[str]:
        from reportlab.lib.utils import simpleSplit
        from reportlab.pdfbase.pdfmetrics import stringWidth

        if not value:
            return [""]
        lines: list[str] = []
        for raw in simpleSplit(value, font, size, width):
            if stringWidth(raw, font, size) <= width:
                lines.append(raw)
                continue
            chunk = ""
            for char in raw:
                if stringWidth(chunk + char, font, size) > width and chunk:
                    lines.append(chunk)
                    chunk = char
                else:
                    chunk += char
            if chunk:
                lines.append(chunk)
        return lines or [value]

    def rich_line(self, x: float, top: float,
                  segments: list[tuple[str, bool, bool]], *,
                  size: float = BODY_SIZE_PT, width: float = MAIN_WIDTH_PT,
                  leading: float = BODY_SIZE_PT * 1.15) -> float:
        """Draw mixed bold/regular text with wrapping. Returns used height."""
        from reportlab.pdfbase.pdfmetrics import stringWidth

        tokens: list[tuple[str, str]] = []
        for text, bold, italic in segments:
            font = ("Times-Bold" if bold else "Times-Italic" if italic else "Times-Roman")
            for token in text.split(" "):
                tokens.append((token, font))
        line = ""
        line_font = "Times-Roman"
        max_lines = 20
        used = 0
        cx = x
        first_font = tokens[0][1] if tokens else "Times-Roman"
        for index, (token, font) in enumerate(tokens):
            addition = ("" if not line else " ") + token
            if stringWidth(line + addition, line_font, size) > width and line:
                self.canvas.setFont(line_font, size)
                self.canvas.drawString(cx if used == 0 else x,
                                       self._baseline(top + used, size), line)
                used += leading
                line = token
                line_font = font
            else:
                if not line:
                    line_font = font
                elif font != line_font:
                    # Keep the previous run's font for mixed tokens; flush instead.
                    if stringWidth(line + addition, line_font, size) > width:
                        self.canvas.setFont(line_font, size)
                        self.canvas.drawString(x, self._baseline(top + used, size), line)
                        used += leading
                        line = token
                        line_font = font
                        continue
                line += addition
            if used > max_lines * leading:
                break
        if line:
            self.canvas.setFont(line_font or first_font, size)
            self.canvas.drawString(x, self._baseline(top + used, size), line)
            used += leading
        return max(used, leading)

    # ---- blocks -----------------------------------------------------------
    def header(self) -> None:
        self.text(MARGIN_LEFT_PT, self.top, (self.cv.header.name or "").upper(),
                  font="Times-Bold", size=NAME_SIZE_PT)
        self.top += NAME_SIZE_PT * 1.15 + 1.3

        if self.cv.header.contact_lines:
            lines = self.wrap("  |  ".join(self.cv.header.contact_lines),
                              size=BODY_SIZE_PT, width=CONTENT_WIDTH_PT)
            for line in lines:
                self.text(MARGIN_LEFT_PT, self.top, line, size=BODY_SIZE_PT)
                self.top += CONTACT_LINE_PT

        for label, value in (("Visa status: ", self.cv.header.visa_status),
                            ("Applying for: ", self.cv.header.applying_for)):
            if not value:
                continue
            from reportlab.pdfbase.pdfmetrics import stringWidth

            label_width = stringWidth(label, "Times-Bold", BODY_SIZE_PT)
            self.text(MARGIN_LEFT_PT, self.top, label, font="Times-Bold")
            # Wrap the value in the remaining width; continuation lines start left.
            lines = self.wrap(value, size=BODY_SIZE_PT,
                              width=CONTENT_WIDTH_PT - label_width)
            self.text(MARGIN_LEFT_PT + label_width, self.top, lines[0])
            self.top += CONTACT_LINE_PT
            for line in lines[1:]:
                self.text(MARGIN_LEFT_PT, self.top, line)
                self.top += CONTACT_LINE_PT
            self.top += 1.3

        if _summary_text(self.cv):
            self.top += 7
            for line in self.wrap(_summary_text(self.cv), size=BODY_SIZE_PT,
                                  width=CONTENT_WIDTH_PT):
                self.text(MARGIN_LEFT_PT, self.top, line)
                self.top += CONTACT_LINE_PT

    def section(self, heading: str) -> None:
        needed = SECTION_SPACE_BEFORE_PT * self.factor + SECTION_LINE_PT + 3.7
        self.ensure(needed + 24)
        self.top += SECTION_SPACE_BEFORE_PT * self.factor
        width = self.text(MARGIN_LEFT_PT, self.top, (heading or "").upper(),
                          font="Times-Bold", size=SECTION_SIZE_PT)
        baseline = self._baseline(self.top, SECTION_SIZE_PT)
        self.canvas.setLineWidth(0.6)
        self.canvas.line(MARGIN_LEFT_PT, baseline - 1.1,
                         MARGIN_LEFT_PT + width, baseline - 1.1)
        self.canvas.setLineWidth(SECTION_RULE_PT)
        rule_y = PAGE_HEIGHT_PT - (self.top + SECTION_LINE_PT)
        self.canvas.line(MARGIN_LEFT_PT, rule_y, PAGE_WIDTH_PT - MARGIN_RIGHT_PT, rule_y)
        self.top += SECTION_LINE_PT + 3.7

    def row(self, row: CVRow) -> None:
        text_lines = self.wrap(row.text, size=BODY_SIZE_PT, width=MAIN_WIDTH_PT)
        label_lines = self.wrap(row.label, size=BODY_SIZE_PT, width=COLUMN_START_PT)
        line_count = max(len(text_lines), len(label_lines))
        self.ensure(line_count * ROW_LINE_PT * self.factor)
        for index, line in enumerate(label_lines):
            self.text(MARGIN_LEFT_PT, self.top + index * ROW_LINE_PT * self.factor, line)
        for index, line in enumerate(text_lines):
            self.text(MARGIN_LEFT_PT + COLUMN_START_PT,
                      self.top + index * ROW_LINE_PT * self.factor, line)
        self.top += line_count * ROW_LINE_PT * self.factor

    def line(self, value: str) -> None:
        for line in self.wrap(value, size=BODY_SIZE_PT, width=CONTENT_WIDTH_PT):
            self.ensure(CONTACT_LINE_PT)
            self.text(MARGIN_LEFT_PT, self.top, line)
            self.top += CONTACT_LINE_PT

    def entry(self, entry: CVEntry) -> None:
        from reportlab.pdfbase.pdfmetrics import stringWidth

        x = MARGIN_LEFT_PT + COLUMN_START_PT
        self.ensure(ENTRY_GAP_PT + BODY_SIZE_PT * 1.15)
        self.top += ENTRY_GAP_PT * self.factor
        if entry.dates:
            self.text(MARGIN_LEFT_PT, self.top, entry.dates, size=BODY_SIZE_PT)

        title_lines = self.wrap(entry.title, font="Times-Bold", size=BODY_SIZE_PT,
                                width=MAIN_WIDTH_PT)
        for index, line in enumerate(title_lines):
            self.text(x, self.top + index * CONTACT_LINE_PT, line,
                      font="Times-Bold", size=BODY_SIZE_PT)
        used = len(title_lines) * CONTACT_LINE_PT
        if entry.organization:
            last = title_lines[-1] if title_lines else ""
            title_width = stringWidth(last, "Times-Bold", BODY_SIZE_PT)
            gap = 7.0 if last else 0.0
            org_text = ("–  " + entry.organization) if last else entry.organization
            first_width = max(40.0, MAIN_WIDTH_PT - title_width - gap)
            org_lines = self.wrap(org_text, size=BODY_SIZE_PT, width=first_width)
            self.text(x + title_width + gap, self.top + used - CONTACT_LINE_PT,
                      org_lines[0], size=BODY_SIZE_PT)
            for line in org_lines[1:]:
                self.text(x, self.top + used, line, size=BODY_SIZE_PT)
                used += CONTACT_LINE_PT
        self.top += used
        if entry.technologies:
            self.top += META_GAP_PT * self.factor
            for line in self.wrap(", ".join(entry.technologies), font="Times-Italic",
                                  size=META_SIZE_PT, width=MAIN_WIDTH_PT):
                self.text(MARGIN_LEFT_PT + COLUMN_START_PT, self.top, line,
                          font="Times-Italic", size=META_SIZE_PT)
                self.top += 11.0
        for bullet in entry.bullets:
            leading = BULLET_LINE_PT * self.factor
            lines = self.wrap(bullet.text, size=BODY_SIZE_PT,
                              width=PAGE_WIDTH_PT - MARGIN_RIGHT_PT - BULLET_TEXT_X_PT)
            self.ensure(len(lines) * leading)
            # A real, extractable bullet character (ATS-safe) plus a filled circle
            # matching the reference's ● weight.
            bullet_x = MARGIN_LEFT_PT + COLUMN_START_PT
            bullet_baseline = self._baseline(self.top, BODY_SIZE_PT)
            self.canvas.setFont("Times-Roman", BODY_SIZE_PT)
            self.canvas.drawString(bullet_x, bullet_baseline, "•")
            self.canvas.setFillColorRGB(0, 0, 0)
            self.canvas.circle(bullet_x + 2.4, bullet_baseline + 3.1, 2.1, stroke=0, fill=1)
            for line in lines:
                self.text(BULLET_TEXT_X_PT, self.top, line)
                self.top += leading
            self.top += BULLET_GAP_PT
        if entry.bullets:
            self.top -= BULLET_GAP_PT  # spacing belongs between blocks, not after

    def build(self) -> None:
        self.header()
        for section in ordered_sections(self.cv):
            self.section(section.heading)
            for row in _rows_for(section):
                self.row(row)
            for line in section.lines:
                self.line(line)
            for entry in section.entries:
                self.entry(entry)
        self.canvas.save()


def _render_measured_pdf(cv: TailoredCV, path: Path, factor: float | None = None) -> str:
    layout = _MeasuredPDF(path, cv, factor=factor if factor is not None else _spacing_factor(cv))
    layout.build()
    PDF_SOURCES[str(path)] = "measured_renderer"
    return str(path)


def _has_text_layer(path: Path) -> bool | None:
    """True/False for a readable PDF; None when the file cannot be opened."""
    try:
        import pymupdf

        with pymupdf.open(str(path)) as document:
            characters = sum(len(page.get_text("text")) for page in document)
        return characters >= 20
    except Exception:  # unreadable output is handled by the layout report
        return None


def export_pdf(cv: TailoredCV, path: str | Path, *, template_path: str | None = None,
               docx_path: str | Path | None = None) -> str:
    """Convert the DOCX when possible, otherwise draw the same measured layout."""
    target = _safe_path(Path(path))
    if template_path:
        logger.info("Reference override ignored: the master CV template is authoritative")

    source = Path(docx_path) if docx_path else None
    if source is None or not source.exists():
        # The conversion path needs a DOCX source even when only PDF was requested.
        with tempfile.TemporaryDirectory(prefix="consul-docx-") as tmp:
            source = Path(tmp) / f"{target.stem}.docx"
            export_docx(cv, source)
            converted = convert_docx_to_pdf(source, target)
    else:
        converted = convert_docx_to_pdf(source, target)
    if converted is not None and converted.exists():
        # Some conversion setups can emit an image-only or blank page. A CV must
        # always carry a real text layer, so fall back to the measured renderer.
        if _has_text_layer(Path(converted)) is False:
            logger.warning("Converted PDF has no text layer; using the measured renderer")
            return _render_measured_pdf(cv, target)
        PDF_SOURCES[str(target)] = "docx_conversion"
        return str(converted)

    return _render_measured_pdf(cv, target)


# ---------------------------------------------------------------------------
# Plain text and orchestration
# ---------------------------------------------------------------------------
def _escape(text: str) -> str:
    return (text or "").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def cv_to_text(cv: TailoredCV) -> str:
    lines: list[str] = [(cv.header.name or "").upper()]
    if cv.header.contact_lines:
        lines.append("  |  ".join(cv.header.contact_lines))
    if cv.header.visa_status:
        lines.append(f"Visa status: {cv.header.visa_status}")
    if cv.header.applying_for:
        lines.append(f"Applying for: {cv.header.applying_for}")
    lines.append("")
    if _summary_text(cv):
        lines.extend([_summary_text(cv), ""])
    for section in ordered_sections(cv):
        lines.append(section.heading.upper())
        for row in _rows_for(section):
            lines.append(f"{row.label}\t{row.text}" if row.label else row.text)
        lines.extend(section.lines)
        for entry in section.entries:
            title = " – ".join(x for x in (entry.title, entry.organization) if x)
            # Dates already lead the line; repeating them in the details would
            # print the same range twice in the exported text.
            details = entry.location.strip()
            prefix = f"{entry.dates}\t" if entry.dates else ""
            lines.append(f"{prefix}{title}" + (f"  ({details})" if details else ""))
            if entry.technologies:
                lines.append(", ".join(entry.technologies))
            lines.extend(f"- {bullet.text}" for bullet in entry.bullets)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def export_txt(cv: TailoredCV, path: str | Path) -> str:
    path = _safe_path(Path(path))
    path.write_text(cv_to_text(cv), encoding="utf-8")
    return str(path)


def export_cover_letter_docx(draft: CoverLetterDraft, path: str | Path, *,
                             generated_on: date | None = None) -> str:
    """One-page business-letter DOCX.

    Unlike a CV, a cover letter is not populated into the master CV template: it
    uses a plain single-column letter layout with the same readable serif family.
    """
    from docx import Document
    from docx.shared import Inches, Pt

    document = Document()
    for section in document.sections:
        section.top_margin = Inches(1)
        section.bottom_margin = Inches(1)
        section.left_margin = Inches(1)
        section.right_margin = Inches(1)
    normal = document.styles["Normal"]
    normal.font.name = "Times New Roman"
    normal.font.size = Pt(11)
    normal.paragraph_format.line_spacing = 1.15
    normal.paragraph_format.space_after = Pt(6)

    def paragraph(text: str = "", *, bold: bool = False, after: float = 6) -> None:
        par = document.add_paragraph()
        run = par.add_run(text)
        run.bold = bold
        par.paragraph_format.space_after = Pt(after)

    paragraph(draft.signature, bold=True, after=0)
    for line in draft.contact_lines:
        paragraph(line, after=0)
    paragraph("")
    paragraph((generated_on or date.today()).strftime("%d %B %Y"), after=12)
    paragraph(draft.greeting, after=8)
    for body in draft.paragraphs:
        paragraph(body.text, after=8)
    paragraph(draft.closing, after=18)
    paragraph(draft.signature, after=0)

    path = _safe_path(Path(path))
    document.save(str(path))
    return str(path)


def export_cv(cv: TailoredCV, *, out_dir: str | Path, version: int = 1,
              formats: tuple[str, ...] = ("docx", "pdf"),
              template_path: str | None = None) -> dict[str, str]:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    results: dict[str, str] = {}
    requested = [fmt for fmt in formats if fmt in {"docx", "pdf", "txt"}]
    docx_path: str | None = None

    if "docx" in requested or "pdf" in requested:
        docx_target = out_dir / filename_for(cv, "docx", version)
        docx_path = export_docx(cv, docx_target, template_path=template_path)
        if "docx" in requested:
            results["docx"] = docx_path

    for fmt in requested:
        filename = filename_for(cv, fmt, version)
        target = out_dir / filename
        if fmt == "pdf":
            results["pdf"] = export_pdf(cv, target, template_path=template_path,
                                        docx_path=docx_path)
        elif fmt == "txt":
            results["txt"] = export_txt(cv, target)
    return results
