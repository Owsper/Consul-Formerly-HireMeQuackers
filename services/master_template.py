"""The reusable master CV template and DOCX→PDF conversion.

The reference document ``Rohan_Thomas_Vinu_CV.pdf`` defines the visual identity of
every generated CV. Its measured geometry (A4, 57.7 pt side margins, Times/Liberation
Serif at 10 pt, 111.6 pt date column, 480 pt rules) is reconstructed here as a real
DOCX template with named styles, tab stops and spacing.

Generated documents load this template, clear its sample body and populate it. They
never build a fresh generic layout, so page size, margins, typography and section
architecture stay identical across applications while the content changes.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

from core.logging_config import get_logger

logger = get_logger("master_template")

# ---------------------------------------------------------------------------
# Measured geometry of the reference PDF (points).
# ---------------------------------------------------------------------------
PAGE_WIDTH_PT = 595.28
PAGE_HEIGHT_PT = 841.89
MARGIN_LEFT_PT = 57.7
MARGIN_RIGHT_PT = 57.65
MARGIN_TOP_PT = 44.5
MARGIN_BOTTOM_PT = 57.7
CONTENT_WIDTH_PT = PAGE_WIDTH_PT - MARGIN_LEFT_PT - MARGIN_RIGHT_PT  # 480.0
COLUMN_START_PT = 111.6          # date/label column width
BULLET_INDENT_PT = 12.9          # hanging indent inside the main column

FONT_FAMILY = "Times New Roman"  # LibreOffice substitutes metric-identical Liberation Serif
NAME_SIZE_PT = 16.0
BODY_SIZE_PT = 10.0
META_SIZE_PT = 9.5
SECTION_SIZE_PT = 10.5
NAME_LINE_PT = 18.4
CONTACT_LINE_PT = 12.4
BODY_LINE_PT = 11.5
BULLET_LINE_PT = 11.45
ROW_LINE_PT = 13.0
SECTION_SPACE_BEFORE_PT = 10.4
SECTION_LINE_PT = 13.9
SECTION_RULE_PT = 0.5
ENTRY_GAP_PT = 3.2
META_GAP_PT = 1.5
BULLET_GAP_PT = 0.9

STYLE_NAME = "Consul Name"
STYLE_CONTACT = "Consul Contact"
STYLE_DETAIL = "Consul Detail"
STYLE_SECTION = "Consul Section"
STYLE_ENTRY = "Consul Entry"
STYLE_META = "Consul Meta"
STYLE_BULLET = "Consul Bullet"
STYLE_ROW = "Consul Row"
STYLE_BODY = "Consul Body"

MASTER_FILENAME = "master_cv.docx"
REFERENCE_FILENAME = "master_reference.pdf"

MASTER_TEMPLATE_PROPS = {
    "title": "consul Master CV Template",
    "subject": "Reusable CV layout reconstructed from the reference document",
    "author": "consul",
    "comments": (
        "Named styles reproduce the reference CV. Generated CVs populate this file; "
        "they do not replace its layout."
    ),
}


def templates_dir() -> Path:
    from config import get_settings

    return get_settings().templates_dir


def master_template_path() -> Path:
    return templates_dir() / MASTER_FILENAME


def reference_pdf_path() -> Path:
    """Prefer the bundled reference, fall back to the project-root upload."""
    bundled = templates_dir() / REFERENCE_FILENAME
    if bundled.exists():
        return bundled
    from config import PROJECT_ROOT

    return PROJECT_ROOT / "Rohan_Thomas_Vinu_CV.pdf"


def _set_run_fonts(run, name: str) -> None:
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    run.font.name = name
    r_pr = run._element.get_or_add_rPr()
    r_fonts = r_pr.find(qn("w:rFonts"))
    if r_fonts is None:
        r_fonts = OxmlElement("w:rFonts")
        r_pr.append(r_fonts)
    for attr in ("w:ascii", "w:hAnsi", "w:eastAsia", "w:cs"):
        r_fonts.set(qn(attr), name)


def _style_border(style, color: str = "000000", size: int = 4, space: int = 0) -> None:
    """Attach a paragraph bottom border to a style in schema-correct order."""
    from docx.oxml import OxmlElement
    from docx.oxml.ns import qn

    p_pr = style.element.get_or_add_pPr()
    existing = p_pr.find(qn("w:pBdr"))
    if existing is not None:
        p_pr.remove(existing)
    borders = OxmlElement("w:pBdr")
    bottom = OxmlElement("w:bottom")
    bottom.set(qn("w:val"), "single")
    bottom.set(qn("w:sz"), str(size))
    bottom.set(qn("w:space"), str(space))
    bottom.set(qn("w:color"), color)
    borders.append(bottom)
    p_pr.insert_element_before(
        borders, "w:shd", "w:tabs", "w:suppressAutoHyphens", "w:kinsoku", "w:wordWrap",
        "w:overflowPunct", "w:topLinePunct", "w:autoSpaceDE", "w:autoSpaceDN",
        "w:bidi", "w:adjustRightInd", "w:snapToGrid", "w:spacing", "w:ind",
        "w:contextualSpacing", "w:mirrorIndents", "w:suppressOverlap", "w:jc",
        "w:textDirection", "w:textAlignment", "w:textboxTightWrap", "w:outlineLvl",
        "w:divId", "w:cnfStyle", "w:rPr", "w:sectPr", "w:pPrChange",
    )


def _define_style(styles, name: str, *, size: float, bold: bool = False,
                  italic: bool = False, underline: bool = False,
                  line_pt: float, before: float = 0.0, after: float = 0.0,
                  left: float = 0.0, first: float = 0.0,
                  tab_stops: tuple[float, ...] = (), keep_next: bool = False,
                  border: bool = False):
    from docx.enum.style import WD_STYLE_TYPE
    from docx.shared import Pt

    try:
        style = styles[name]
    except KeyError:
        style = styles.add_style(name, WD_STYLE_TYPE.PARAGRAPH)
    style.base_style = styles["Normal"]
    style.quick_style = True
    style.font.name = FONT_FAMILY
    style.font.size = Pt(size)
    style.font.bold = bold
    style.font.italic = italic
    style.font.underline = underline
    style.font.color.rgb = None
    fmt = style.paragraph_format
    fmt.space_before = Pt(before)
    fmt.space_after = Pt(after)
    fmt.line_spacing = Pt(line_pt)
    fmt.left_indent = Pt(left)
    fmt.first_line_indent = Pt(first)
    fmt.keep_with_next = keep_next
    fmt.widow_control = True
    for stop in tab_stops:
        fmt.tab_stops.add_tab_stop(Pt(stop))
    if border:
        _style_border(style)
    return style


def build_master_template(path: Path | None = None, *, force: bool = False) -> Path:
    """Create the reusable DOCX template from the reference measurements."""
    from docx import Document
    from docx.shared import Mm, Pt

    target = Path(path) if path else master_template_path()
    if target.exists() and not force:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)

    document = Document()
    section = document.sections[0]
    section.page_width = Mm(210)
    section.page_height = Mm(297)
    section.left_margin = Pt(MARGIN_LEFT_PT)
    section.right_margin = Pt(MARGIN_RIGHT_PT)
    section.top_margin = Pt(MARGIN_TOP_PT)
    section.bottom_margin = Pt(MARGIN_BOTTOM_PT)
    section.header_distance = Pt(18)
    section.footer_distance = Pt(18)

    normal = document.styles["Normal"]
    normal.font.name = FONT_FAMILY
    normal.font.size = Pt(BODY_SIZE_PT)
    normal.paragraph_format.space_before = Pt(0)
    normal.paragraph_format.space_after = Pt(0)
    normal.paragraph_format.line_spacing = Pt(BODY_LINE_PT)

    styles = document.styles
    _define_style(styles, STYLE_NAME, size=NAME_SIZE_PT, bold=True,
                  line_pt=NAME_LINE_PT, keep_next=True)
    _define_style(styles, STYLE_CONTACT, size=BODY_SIZE_PT, line_pt=CONTACT_LINE_PT,
                  before=1.3)
    _define_style(styles, STYLE_DETAIL, size=BODY_SIZE_PT, line_pt=CONTACT_LINE_PT,
                  before=1.3)
    _define_style(styles, STYLE_SECTION, size=SECTION_SIZE_PT, bold=True, underline=True,
                  line_pt=SECTION_LINE_PT, before=SECTION_SPACE_BEFORE_PT, after=3.7,
                  keep_next=True, border=True)
    _define_style(styles, STYLE_ENTRY, size=BODY_SIZE_PT, line_pt=BODY_LINE_PT,
                  before=ENTRY_GAP_PT, keep_next=True,
                  left=COLUMN_START_PT, first=-COLUMN_START_PT,
                  tab_stops=(COLUMN_START_PT,))
    _define_style(styles, STYLE_META, size=META_SIZE_PT, italic=True, line_pt=11.0,
                  before=META_GAP_PT, left=COLUMN_START_PT, keep_next=True)
    _define_style(styles, STYLE_BULLET, size=BODY_SIZE_PT, line_pt=BULLET_LINE_PT,
                  left=COLUMN_START_PT + BULLET_INDENT_PT, first=-BULLET_INDENT_PT,
                  tab_stops=(COLUMN_START_PT + BULLET_INDENT_PT,))
    _define_style(styles, STYLE_ROW, size=BODY_SIZE_PT, line_pt=ROW_LINE_PT,
                  left=COLUMN_START_PT, first=-COLUMN_START_PT,
                  tab_stops=(COLUMN_START_PT,))
    _define_style(styles, STYLE_BODY, size=BODY_SIZE_PT, line_pt=CONTACT_LINE_PT,
                  before=7.0)

    props = document.core_properties
    props.title = MASTER_TEMPLATE_PROPS["title"]
    props.subject = MASTER_TEMPLATE_PROPS["subject"]
    props.author = MASTER_TEMPLATE_PROPS["author"]
    props.comments = MASTER_TEMPLATE_PROPS["comments"]

    marker = document.add_paragraph(style=STYLE_BODY)
    marker.add_run("[consul master CV template — content is populated per application]")

    document.save(str(target))
    logger.info("Master CV template written to %s", target)
    return target


def ensure_master_template() -> Path:
    """Create the template and bundle the reference PDF when they are missing."""
    target = build_master_template()
    bundled = templates_dir() / REFERENCE_FILENAME
    if not bundled.exists():
        source = reference_pdf_path()
        if source.exists() and source != bundled:
            bundled.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, bundled)
            logger.info("Bundled reference PDF at %s", bundled)
    return target


def new_document_from_master():
    """Load the template and remove the sample body while keeping its styles."""
    from docx import Document

    document = Document(str(ensure_master_template()))
    body = document.element.body
    for child in list(body):
        if child.tag.endswith("}sectPr"):
            continue
        body.remove(child)
    for section in document.sections:
        for part in (section.header, section.footer):
            try:
                for paragraph in part.paragraphs:
                    for run in paragraph.runs:
                        run.text = ""
                for table in part.tables:
                    for row in table.rows:
                        for cell in row.cells:
                            cell.text = ""
            except Exception:  # pragma: no cover - header weirdness must not break export
                continue
    return document


# ---------------------------------------------------------------------------
# DOCX → PDF conversion
# ---------------------------------------------------------------------------
def find_office_converter() -> str | None:
    """Return a LibreOffice/soffice executable if one is installed."""
    import os

    for env in ("CONSUL_SOFFICE", "SOFFICE_PATH", "LIBREOFFICE_PATH"):
        candidate = os.environ.get(env, "").strip()
        if candidate and Path(candidate).exists():
            return candidate
    found = shutil.which("soffice") or shutil.which("libreoffice")
    if found:
        return found
    candidates = [
        Path("C:/Program Files/LibreOffice/program/soffice.exe"),
        Path("C:/Program Files (x86)/LibreOffice/program/soffice.exe"),
        Path("/usr/bin/soffice"),
        Path("/usr/local/bin/soffice"),
        Path("/Applications/LibreOffice.app/Contents/MacOS/soffice"),
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return None


def convert_docx_to_pdf(docx_path: str | Path, pdf_path: str | Path,
                        timeout: int = 120) -> Path | None:
    """Render the DOCX with LibreOffice. Returns None when no converter exists."""
    converter = find_office_converter()
    if converter is None:
        logger.info("No DOCX→PDF converter found; using the measured PDF renderer")
        return None
    docx_path = Path(docx_path)
    pdf_path = Path(pdf_path)
    pdf_path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="consul-pdf-") as tmp:
        try:
            result = subprocess.run(
                [converter, "--headless", "--convert-to", "pdf", "--outdir", tmp,
                 str(docx_path)],
                capture_output=True, text=True, timeout=timeout, check=False,
            )
        except (OSError, subprocess.SubprocessError) as exc:
            logger.warning("DOCX→PDF conversion failed to start: %s", exc)
            return None
        produced = Path(tmp) / f"{docx_path.stem}.pdf"
        if result.returncode != 0 or not produced.exists():
            logger.warning("DOCX→PDF conversion failed: %s", (result.stderr or "")[:500])
            return None
        shutil.copyfile(produced, pdf_path)
    return pdf_path
