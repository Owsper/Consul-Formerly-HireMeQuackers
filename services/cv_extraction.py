"""CV text extraction for PDF and DOCX, with an optional OCR fallback."""

from __future__ import annotations

import io
import re
from dataclasses import dataclass, field

from pydantic import Field

from core.schemas import CandidateProfileData, EvidenceItem

from core.exceptions import DocumentExtractionError, UnsupportedFileTypeError
from core.logging_config import get_logger
from core.security import sanitize_plain_text, validate_upload

logger = get_logger("cv_extraction")

OCR_MIN_CHARS = 120  # below this a PDF is probably a scan


@dataclass
class ExtractionResult:
    text: str
    file_format: str
    pages: int = 0
    used_ocr: bool = False
    warnings: list[str] = field(default_factory=list)

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def is_empty(self) -> bool:
        return len(self.text.strip()) < 20


def _pdf_text(data: bytes) -> tuple[str, int]:
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        try:
            import fitz as pymupdf  # type: ignore
        except ImportError as exc:  # pragma: no cover
            raise DocumentExtractionError("PDF support is not installed (pip install PyMuPDF)") from exc
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception as exc:
        raise DocumentExtractionError(f"Could not read the PDF file: {exc}") from exc
    try:
        parts = [page.get_text("text") for page in doc]
        return "\n".join(parts), doc.page_count
    finally:
        doc.close()


def _ocr_pdf(data: bytes) -> tuple[str, int, bool]:
    """Render pages and OCR them. Returns (text, pages, worked)."""
    try:
        import pymupdf
    except ImportError:  # pragma: no cover
        import fitz as pymupdf  # type: ignore
    try:
        import pytesseract
        from PIL import Image
    except ImportError:
        logger.info("OCR requested but pytesseract/Pillow are not installed")
        return "", 0, False
    try:
        doc = pymupdf.open(stream=data, filetype="pdf")
    except Exception:
        return "", 0, False
    texts: list[str] = []
    try:
        for page in doc:
            pix = page.get_pixmap(dpi=200)
            image = Image.open(io.BytesIO(pix.tobytes("png")))
            texts.append(pytesseract.image_to_string(image))
        return "\n".join(texts), doc.page_count, True
    except Exception as exc:  # pragma: no cover - depends on tesseract install
        logger.warning("OCR failed: %s", exc)
        return "", doc.page_count, False
    finally:
        doc.close()


def _docx_text(data: bytes) -> tuple[str, int]:
    try:
        from docx import Document
    except ImportError as exc:  # pragma: no cover
        raise DocumentExtractionError("DOCX support is not installed (pip install python-docx)") from exc
    try:
        document = Document(io.BytesIO(data))
    except Exception as exc:
        raise DocumentExtractionError(f"Could not read the DOCX file: {exc}") from exc

    blocks: list[str] = []
    for paragraph in document.paragraphs:
        text = paragraph.text.strip()
        if text:
            style = (paragraph.style.name if paragraph.style is not None else "") or ""
            if style.lower().startswith("heading") and text.upper() != text:
                blocks.append(f"\n## {text}")
            else:
                blocks.append(text)
    for table in document.tables:
        for row in table.rows:
            cells = [c.text.strip() for c in row.cells if c.text.strip()]
            if cells:
                blocks.append(" | ".join(dict.fromkeys(cells)))
    return "\n".join(blocks), 1


def extract_document(filename: str, data: bytes, *, max_mb: int | None = None,
                     allow_ocr: bool = True) -> ExtractionResult:
    """Extract text from an uploaded PDF/DOCX, validating type and size."""
    from config import get_settings

    settings = get_settings()
    ext = validate_upload(filename, len(data), max_mb or settings.max_upload_mb)
    warnings: list[str] = []
    used_ocr = False

    if ext == ".pdf":
        text, pages = _pdf_text(data)
        if allow_ocr and len(text.strip()) < OCR_MIN_CHARS and pages:
            ocr_text, ocr_pages, worked = _ocr_pdf(data)
            if worked and len(ocr_text.strip()) > len(text.strip()):
                text = ocr_text
                used_ocr = True
                pages = ocr_pages or pages
            elif not worked:
                warnings.append(
                    "The PDF appears to be a scan and OCR is not available. "
                    "Install Tesseract + pytesseract, or enter the profile manually."
                )
        if not text.strip():
            raise DocumentExtractionError(
                "No selectable text was found in the PDF. It may be an image-only scan. "
                "Install OCR support or create the profile manually.",
                details={"file": filename},
            )
    elif ext == ".docx":
        text, pages = _docx_text(data)
        if not text.strip():
            raise DocumentExtractionError(
                "The DOCX file contains no readable text. Try another file or create the profile manually."
            )
    else:  # pragma: no cover - validate_upload already guards this
        raise UnsupportedFileTypeError(f"Unsupported file type: {ext}")

    text = sanitize_plain_text(text)
    if len(text) < 20:
        warnings.append("Very little text was extracted — check the document before approving.")
    logger.info("Extracted %s chars from %s (%s pages)", len(text), filename, pages)
    return ExtractionResult(text=text, file_format=ext.lstrip("."), pages=pages,
                            used_ocr=used_ocr, warnings=warnings)


# ---------------------------------------------------------------------------
# Structured extraction (LLM) and offline heuristics
# ---------------------------------------------------------------------------
class ProfileExtractionResponse(CandidateProfileData):  # type: ignore[name-defined]
    evidence: list[dict] = Field(default_factory=list)


def _extraction_payload(text: str) -> ProfileExtractionResponse:
    from services.llm_service import get_llm_service

    service = get_llm_service()
    result = service.prompt_json("profile_extraction", ProfileExtractionResponse, cv_text=text[:60000])
    return result


def structured_extraction(text: str, source_document: str) -> tuple[CandidateProfileData, list[EvidenceItem]]:
    """Run Gemini extraction and normalise the evidence ledger.

    Raises ``LLMUnavailableError`` when no LLM is configured so the caller can
    offer manual entry instead of silently producing an empty profile.
    """
    from services.profile_service import normalise_llm_evidence

    if not text.strip():
        raise DocumentExtractionError("There is no text to extract a profile from.")

    response = _extraction_payload(text)
    evidence_raw = list(response.evidence)
    payload = response.model_dump(mode="json")
    payload.pop("evidence", None)
    data = CandidateProfileData.model_validate(payload)
    evidence = normalise_llm_evidence(evidence_raw, data, source_document)
    logger.info("Structured extraction produced %s evidence items", len(evidence))
    return data, evidence


_EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
_PHONE_RE = re.compile(r"(?:\+\d{1,3}[\s\-/]?)?(?:\(?\d{2,5}\)?[\s\-/]?)?\d{3,4}[\s\-]?\d{3,6}")
_URL_RE = re.compile(r"https?://[^\s)>\]\"']+")


def heuristic_hints(text: str) -> dict[str, str]:
    """Offline best-effort contact hints. Only returns text found verbatim."""
    hints: dict[str, str] = {}
    emails = _EMAIL_RE.findall(text or "")
    if emails:
        hints["email"] = emails[0]
    urls = _URL_RE.findall(text or "")
    for url in urls:
        low = url.lower()
        if "linkedin.com" in low and "linkedin" not in hints:
            hints["linkedin"] = url
        elif "github.com" in low and "github" not in hints:
            hints["github"] = url
        elif "portfolio" not in hints:
            hints["portfolio"] = url
    phones = [p for p in _PHONE_RE.findall(text or "") if len(re.sub(r"\D", "", p)) >= 7]
    if phones:
        hints["phone"] = phones[0].strip()
    for line in (text or "").splitlines():
        stripped = line.strip()
        if stripped and 2 <= len(stripped.split()) <= 4 and stripped[0].isupper() and "@" not in stripped:
            hints.setdefault("possible_name", stripped)
            break
    return hints
