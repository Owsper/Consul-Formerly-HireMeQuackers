"""Job-specific ATS audit measured on the exported file, not on the model.

Why it works this way
---------------------
Commercial screening engines (Workday, SAP SuccessFactors, Oracle Taleo, iCIMS,
Greenhouse, Lever, SmartRecruiters) never expose their parser or their ranker.
There is no public API that returns "your Workday score". Anything that claims
that number is invented.

What *is* observable and reproducible is the pipeline every one of them runs:

1. extract a linear text stream from the uploaded file,
2. parse contact fields and section headings out of that stream,
3. match the posting's terms against the parsed text.

So this module does exactly that. It opens the same DOCX/PDF the employer would
receive, extracts its text with a real PDF/DOCX reader, re-parses the fields from
that extracted text, and scores the result against the target job's terms. Every
point is traceable to a measurement on the file. If the text layer loses a line,
the score drops here for the same reason it would drop in a real system.

The output is labelled as a simulation everywhere it is shown. It is a faithful
replica of published parser behaviour, never a vendor score.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from core.ats_rules import (
    ATS_RULES_VERSION,
    KNOCKOUT_NOTE,
    coverage_of,
    evidence_claim_text,
    job_terms,
    standard_heading_set,
)
from core.logging_config import get_logger
from core.schemas import CandidateProfileData, EvidenceItem, JobRecord, TailoredCV
from core.text import normalize_text

logger = get_logger("ats_audit")

ATS_AUDIT_VERSION = "1.0"
ENGINE = "consul-ats-sim"

VENDOR_MODEL = (
    "Measured on the exported file by re-running the pipeline commercial screening "
    "systems use: text extraction, contact and section parsing, then keyword matching "
    "against this posting's terms. Vendors such as Workday, SAP SuccessFactors, "
    "Oracle Taleo, iCIMS, Greenhouse and Lever do not publish or expose their scoring "
    "engine, so this is a replica of their documented parsing behaviour — not a score "
    "produced by their software."
)

# Criteria whose failure actually costs an application (an unreadable or unparseable
# document is not recoverable by keyword coverage).
HARD_GATES = ("text_layer", "contact_block", "section_recognition", "format_safety")

_EMAIL_RE = re.compile(r"[\w.+-]+@[\w-]+\.[\w.-]{2,}")
_PHONE_RE = re.compile(r"\+?\d[\d\s()./-]{7,}\d")
_URL_RE = re.compile(r"(?:https?://|www\.)\S+|\b(?:linkedin|github)\.com/\S+", re.IGNORECASE)
_TOKEN_RE = re.compile(r"[0-9A-Za-zÀ-ÖØ-öø-ÿ][0-9A-Za-zÀ-ÖØ-öø-ÿ+#./'-]{2,}")
_YEAR_RE = re.compile(r"(?:19|20)\d{2}")
_ICON_FONTS = ("wingdings", "webdings", "symbol", "fontawesome", "material icons",
               "glyphicons", "icomoon")
_PRESENT_RE = re.compile(
    r"\b(present|current|currently|today|now|ongoing|heute|aktuell|derzeit|"
    r"presente|actualidad|actuel|présent|nu|heden)\b", re.IGNORECASE,
)
_MONTHS = {
    "jan": 1, "january": 1, "feb": 2, "february": 2, "mar": 3, "march": 3,
    "apr": 4, "april": 4, "may": 5, "jun": 6, "june": 6, "jul": 7, "july": 7,
    "aug": 8, "august": 8, "sep": 9, "sept": 9, "september": 9, "oct": 10,
    "october": 10, "nov": 11, "november": 11, "dec": 12, "december": 12,
}


# ---------------------------------------------------------------------------
# Reading the document the way a parser reads it
# ---------------------------------------------------------------------------
@dataclass
class DocumentText:
    """The text and structure an ATS would actually receive."""

    text: str = ""
    source: str = ""
    page_count: int = 0
    images: int = 0
    tables: int = 0
    text_boxes: int = 0
    header_footer: str = ""
    fonts: list[str] = field(default_factory=list)
    file_size_kb: float = 0.0
    characters: int = 0

    @property
    def lines(self) -> list[str]:
        return [line.strip() for line in self.text.splitlines() if line.strip()]


def _read_pdf(path: Path) -> DocumentText:
    import pymupdf

    with pymupdf.open(str(path)) as document:
        pages = [page.get_text("text") for page in document]
        images = sum(len(page.get_images(full=True)) for page in document)
        fonts: set[str] = set()
        for page in document:
            for block in page.get_text("dict").get("blocks", []):
                for line in block.get("lines", []):
                    for span in line.get("spans", []):
                        name = (span.get("font") or "").split("+")[-1]
                        if name:
                            fonts.add(name)
        text = "\n".join(pages)
        return DocumentText(
            text=text, source="pdf", page_count=document.page_count, images=images,
            fonts=sorted(fonts), file_size_kb=round(path.stat().st_size / 1024, 1),
            characters=len(text),
        )


def _read_docx(path: Path) -> DocumentText:
    from docx import Document
    from docx.oxml.ns import qn

    document = Document(str(path))
    paragraphs = [p.text for p in document.paragraphs]
    body = document.element.body
    text_boxes = len(list(body.iter(qn("w:txbxContent"))))
    header_footer: list[str] = []
    for section in document.sections:
        for part in (section.header, section.footer):
            header_footer.extend(p.text for p in part.paragraphs if p.text.strip())
    text = "\n".join(paragraphs)
    return DocumentText(
        text=text, source="docx", tables=len(document.tables), text_boxes=text_boxes,
        header_footer="\n".join(header_footer), file_size_kb=round(path.stat().st_size / 1024, 1),
        characters=len(text),
    )


def read_document(*, pdf_path: str | Path | None, docx_path: str | Path | None) -> DocumentText:
    """Read the PDF when present (that is what most portals parse), else the DOCX.

    A PDF that opens but carries no text is returned as-is: that is the finding.
    Falling back to the DOCX would hide a scan or an image-only export.
    """
    for path, reader in ((pdf_path, _read_pdf), (docx_path, _read_docx)):
        if not path:
            continue
        candidate = Path(path)
        if not candidate.exists():
            continue
        try:
            return reader(candidate)
        except Exception as exc:  # a broken file must report, not crash the page
            logger.warning("Could not read %s: %s", candidate.name, exc)
            continue
    return DocumentText()


def _tokens(text: str) -> set[str]:
    return {normalize_text(token) for token in _TOKEN_RE.findall(text or "")}


def _recovery(expected: str, actual: str) -> float:
    """Share of the document's own vocabulary the parser managed to recover."""
    wanted = _tokens(expected)
    if not wanted:
        return 1.0
    return len(wanted & _tokens(actual)) / len(wanted)


def _date_ordinal(value: str) -> int | None:
    """Year*12 + month; 'Present' ranks above every real date."""
    if not value:
        return None
    text = normalize_text(value)
    if _PRESENT_RE.search(text):
        return 10**6
    match = re.search(r"([a-z]{3,9})\.?\s*((?:19|20)\d{2})", text)
    if match and match.group(1) in _MONTHS:
        return int(match.group(2)) * 12 + _MONTHS[match.group(1)]
    match = re.search(r"\b((?:19|20)\d{2})\b", text)
    if match:
        return int(match.group(1)) * 12
    return None


def _first_tokens(value: str, count: int = 3) -> list[str]:
    tokens = [t for t in _TOKEN_RE.findall(value or "") if len(t) >= 3]
    return [normalize_text(t) for t in tokens[:count]]


# ---------------------------------------------------------------------------
# Criteria
# ---------------------------------------------------------------------------
def _criterion(key: str, label: str, weight: int, points: float,
               detail: str, fix: str = "") -> dict[str, Any]:
    points = max(0.0, min(float(weight), float(points)))
    if points >= weight - 1e-9:
        status = "pass"
    elif points > 0:
        status = "partial"
    else:
        status = "fail"
    return {
        "id": key, "label": label, "weight": weight, "points": round(points, 1),
        "status": status, "detail": detail, "fix": fix,
    }


def audit_document(*, cv: TailoredCV, job: JobRecord, profile: CandidateProfileData,
                   evidence: list[EvidenceItem], pdf_path: str | Path | None = None,
                   docx_path: str | Path | None = None) -> dict[str, Any]:
    """Score the exported document against the target job. Never raises.

    Every criterion is a measurement on the file, so the result is deterministic
    for a given document and posting.
    """
    try:
        return _audit(cv=cv, job=job, profile=profile, evidence=evidence,
                      pdf_path=pdf_path, docx_path=docx_path)
    except Exception as exc:  # pragma: no cover - defensive
        logger.warning("ATS audit failed: %s", exc)
        return {"engine": ENGINE, "version": ATS_AUDIT_VERSION, "score": 0,
                "status": "unavailable", "criteria": [], "blockers": [],
                "error": type(exc).__name__, "disclaimer": VENDOR_MODEL,
                "knockout_note": KNOCKOUT_NOTE}


def _audit(*, cv: TailoredCV, job: JobRecord, profile: CandidateProfileData,
           evidence: list[EvidenceItem], pdf_path, docx_path) -> dict[str, Any]:
    document = read_document(pdf_path=pdf_path, docx_path=docx_path)
    text = document.text
    lines = document.lines
    upper_lines = {line.upper().strip() for line in lines}
    criteria: list[dict[str, Any]] = []

    if not text.strip():
        return _no_document(cv, document, pdf_path, docx_path)

    # -- 1. Text layer and extraction (12) ---------------------------------
    model_text = _model_text(cv)
    recovery = _recovery(model_text, text)
    if document.characters >= 200 and recovery >= 0.95:
        points, note = 12.0, f"{document.characters} characters, {recovery:.0%} of the document recovered"
    elif document.characters >= 200 and recovery >= 0.85:
        points = 8.0
        note = f"{document.characters} characters, only {recovery:.0%} recovered"
    elif document.characters >= 60:
        points = 4.0
        note = f"only {document.characters} characters extracted ({recovery:.0%} recovered)"
    else:
        points = 0.0
        note = "no usable text layer was found"
    criteria.append(_criterion(
        "text_layer", "Text layer and extraction", 12, points, note,
        "" if points == 12 else "Export a PDF with a real text layer (no scan, no image).",
    ))

    # -- 2. Contact fields (12) -------------------------------------------
    email_present = bool(_EMAIL_RE.search(text))
    phone_present = bool(_PHONE_RE.search(text))
    name_present = _name_found(cv.header.name, lines)
    wanted = [("name", name_present)]
    if profile.personal.email:
        wanted.append(("email", email_present or _email_in(text, profile.personal.email)))
    if profile.personal.phone:
        wanted.append(("phone", phone_present))
    found = [field for field, ok in wanted if ok]
    missing = [field for field, ok in wanted if not ok]
    criteria.append(_criterion(
        "contact_block", "Contact fields", 10, 10.0 * len(found) / len(wanted),
        ("parsed: " + ", ".join(found)) + ("; missing: " + ", ".join(missing) if missing else ""),
        "" if not missing else "Put " + " and ".join(missing)
        + " as plain text in the document body, not in a header, footer or text box.",
    ))

    # -- 3. Section recognition (12) --------------------------------------
    headings = [section.heading.strip() for section in cv.sections if section.heading.strip()]
    accepted = standard_heading_set()
    standard = [heading for heading in headings if heading.lower() in accepted]
    detected = [heading for heading in standard if heading.upper() in upper_lines]
    ratio = len(detected) / len(standard) if standard else 0.0
    core = {"professional experience", "work experience", "experience", "employment",
            "education", "skills", "technical skills"}
    has_core = any(heading.lower() in core for heading in headings)
    points = 12.0 * ratio
    if not has_core:
        points = min(points, 6.0)
    unknown = [heading for heading in headings if heading.lower() not in accepted]
    criteria.append(_criterion(
        "section_recognition", "Section recognition", 12, points,
        f"{len(detected)}/{len(standard)} standard headings found in the parsed text"
        + (f"; non-standard: {', '.join(unknown[:3])}" if unknown else ""),
        "" if points >= 12 else "Use standard headings (Experience, Education, Skills).",
    ))

    # -- 4. Reading order (8) ---------------------------------------------
    entries = [entry for section in cv.sections for entry in section.entries]
    dated_entries = [entry for entry in entries if entry.dates.strip()]
    paired = [entry for entry in dated_entries if _pairing_ok(entry, text)]
    pairing_ratio = len(paired) / len(dated_entries) if dated_entries else 1.0
    criteria.append(_criterion(
        "reading_order", "Reading order", 8, 8.0 * pairing_ratio,
        f"{len(paired)}/{len(dated_entries)} dated entries keep their title on the same "
        "parsed line",
        "" if pairing_ratio >= 1 else
        "Avoid multi-column or table layouts for dates and titles; keep one linear flow.",
    ))

    # -- 5. Job keywords (20) ---------------------------------------------
    terms = job_terms(job)
    claimable = evidence_claim_text(evidence)
    must = coverage_of(text, terms.must_have, claimable)
    nice = coverage_of(text, terms.nice_to_have, claimable)
    keyword_points = 24.0 * must["ratio"] + 6.0 * nice["ratio"]
    nice_detail = (f"nice-to-have {len(nice['covered'])}/{nice['available']}"
                   if nice["available"] else "no evidenced nice-to-have terms to rank")
    criteria.append(_criterion(
        "role_keywords", "Job-specific keywords", 30, keyword_points,
        f"must-have {len(must['covered'])}/{must['available']} in the parsed text; "
        + nice_detail,
        "" if keyword_points >= 29.5 else
        ("Use these already-evidenced terms in Skills or a recent bullet: "
         + ", ".join(must["missing_evidenced"][:6])
         if must["missing_evidenced"] else
         "The posting's remaining terms are not evidenced in Ground Truth, so they must not be claimed."),
    ))

    # -- 6. Title alignment (5) -------------------------------------------
    title_tokens = _first_tokens(terms.target_title, 3)
    title_hits = [token for token in title_tokens if token in normalize_text(text)]
    title_ratio = len(title_hits) / len(title_tokens) if title_tokens else 1.0
    criteria.append(_criterion(
        "title_alignment", "Title alignment", 8, 8.0 * title_ratio,
        f"{len(title_hits)}/{len(title_tokens)} posting title terms appear in the document",
        "" if title_ratio >= 1 else
        "Mirror the posting's job title in the 'Applying for' line when it matches your real target.",
    ))

    # -- 7. Format safety (10) --------------------------------------------
    format_points = 0.0
    format_notes: list[str] = []
    if document.tables == 0:
        format_points += 4
    else:
        format_notes.append(f"{document.tables} table(s)")
    if document.text_boxes == 0:
        format_points += 2
    else:
        format_notes.append(f"{document.text_boxes} text box(es)")
    if document.images == 0:
        format_points += 3
    else:
        format_notes.append(f"{document.images} embedded image(s)")
    icon_fonts = [font for font in document.fonts if any(
        bad in font.lower() for bad in _ICON_FONTS)]
    if not icon_fonts:
        format_points += 3
    else:
        format_notes.append("icon fonts: " + ", ".join(icon_fonts[:3]))
    if document.header_footer.strip():
        format_notes.append("content in header or footer")
    criteria.append(_criterion(
        "format_safety", "Format safety", 12, format_points,
        "no tables, text boxes, images or icon fonts" if not format_notes
        else "; ".join(format_notes),
        "" if format_points >= 12 else
        "Keep the document single-flow: no tables, images, text boxes or header/footer content.",
    ))

    # -- 8. Dates and recency (8) -----------------------------------------
    dated = [entry for entry in entries if entry.dates.strip()]
    parsed = [entry for entry in dated if _date_ordinal(entry.dates) is not None]
    date_ratio = len(parsed) / len(dated) if dated else 0.0
    ordering_ok, ordering_note = _reverse_chronological(cv)
    criteria.append(_criterion(
        "dates", "Dates and recency", 8,
        4.0 * date_ratio + (4.0 if ordering_ok and dated else 0.0),
        f"{len(parsed)}/{len(dated)} dates parse; {ordering_note}",
        "" if date_ratio >= 1 and ordering_ok else
        "Write dates as 'Mon YYYY – Mon YYYY' and list the newest entry first.",
    ))

    total = int(round(sum(item["points"] for item in criteria)))
    blockers = [item for item in criteria
                if item["id"] in HARD_GATES and item["status"] == "fail"]
    if blockers:
        status = "blocked"
    elif total >= 85:
        status = "pass"
    else:
        status = "attention"

    notes: list[str] = []
    repeats = [(term, _count_term(text, term)) for term in must["covered"]]
    heavy = [(term, count) for term, count in repeats if count >= 8]
    if heavy:
        notes.append(
            "Repeated term(s) that some engines treat as stuffing: "
            + ", ".join(f"{term} ×{count}" for term, count in heavy[:4]) + "."
        )
    notes.append(
        "Knockout questions (work authorisation, licences, minimum years, availability) "
        "are answered on the employer's form and are not part of this score."
    )

    return {
        "engine": ENGINE,
        "version": ATS_AUDIT_VERSION,
        "rules_version": ATS_RULES_VERSION,
        "score": max(0, min(100, total)),
        "status": status,
        "criteria": criteria,
        "blockers": [item["label"] for item in blockers],
        "fixes": [item["fix"] for item in criteria if item["fix"]][:6],
        "keyword_coverage": {
            "must_have": must, "nice_to_have": nice,
            "target_title": terms.target_title,
        },
        "parsed": {
            "source": document.source,
            "characters": document.characters,
            "recovery": round(recovery, 3),
            "pages": document.page_count,
            "file_kb": document.file_size_kb,
            "tables": document.tables,
            "text_boxes": document.text_boxes,
            "images": document.images,
            "fonts": document.fonts[:8],
            "email": email_present,
            "phone": phone_present,
            "name": name_present,
            "headings": detected,
        },
        "extracted_text": text[:12000],
        "notes": notes,
        "disclaimer": VENDOR_MODEL,
        "knockout_note": KNOCKOUT_NOTE,
    }


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------
def _no_document(cv: TailoredCV, document: DocumentText, pdf_path, docx_path) -> dict[str, Any]:
    """No readable document means no score. Inventing one would be the whole bug."""
    source = document.source
    if not source:
        detail = "no exported file exists or could be opened"
        problem = "the exported files are missing or unreadable"
    else:
        detail = (f"the {source.upper()} carries no extractable text "
                  f"({document.characters} character(s))")
        problem = "the document has no text layer"
    criterion = _criterion(
        "text_layer", "Text layer and extraction", 12, 0, detail,
        "Re-export as a DOCX or a text PDF; never upload a scan or a flattened image.",
    )
    return {
        "engine": ENGINE, "version": ATS_AUDIT_VERSION, "rules_version": ATS_RULES_VERSION,
        "score": 0, "status": "blocked", "criteria": [criterion],
        "blockers": ["Text layer and extraction"], "fixes": [criterion["fix"]],
        "keyword_coverage": {},
        "parsed": {
            "source": source, "characters": document.characters,
            "pages": document.page_count, "file_kb": document.file_size_kb,
            "tables": document.tables, "text_boxes": document.text_boxes,
            "images": document.images, "fonts": document.fonts[:8],
            "email": False, "phone": False, "name": False,
            "recovery": 0.0, "headings": [],
        },
        "extracted_text": "",
        "notes": [f"No score is reported: {problem}."],
        "disclaimer": VENDOR_MODEL, "knockout_note": KNOCKOUT_NOTE,
    }


def _model_text(cv: TailoredCV) -> str:
    from services.document_export import cv_to_text

    return cv_to_text(cv)


def _email_in(text: str, email: str) -> bool:
    return normalize_text(email) in normalize_text(text)


def _name_found(name: str, lines: list[str]) -> bool:
    tokens = _first_tokens(name, 4)
    if not tokens or not lines:
        return False
    head = normalize_text(" ".join(lines[:3]))
    return all(token in head for token in tokens)


def _count_term(text: str, term: str) -> int:
    needle = normalize_text(term)
    if not needle:
        return 0
    return normalize_text(text).count(needle)


def _pairing_ok(entry, text: str) -> bool:
    """Does the parsed text keep this entry's date and title together?"""
    if not entry.dates:
        return True
    lowered = normalize_text(text)
    position = lowered.find(normalize_text(entry.dates))
    if position < 0:
        return False
    window = lowered[position: position + 200]
    tokens = _first_tokens(entry.title, 3)
    if not tokens:
        return True
    hits = sum(1 for token in tokens if token in window)
    return hits >= min(2, len(tokens))


def _reverse_chronological(cv: TailoredCV) -> tuple[bool, str]:
    experience = {"professional experience", "work experience", "experience", "employment"}
    checked = 0
    for section in cv.sections:
        if section.heading.strip().lower() not in experience:
            continue
        ordinals = [value for value in
                    (_date_ordinal(entry.dates) for entry in section.entries)
                    if value is not None]
        for earlier, later in zip(ordinals, ordinals[1:]):
            checked += 1
            if later > earlier:
                return False, "entries are not newest-first"
    if not checked:
        return True, "a single dated entry, so order is not tested"
    return True, "entries run newest-first"
