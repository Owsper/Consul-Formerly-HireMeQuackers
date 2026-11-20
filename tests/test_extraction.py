"""Document text extraction without any network access."""

from io import BytesIO

import pytest

from core.exceptions import DocumentExtractionError, LLMUnavailableError, UnsupportedFileTypeError
from services.cv_extraction import extract_document, heuristic_hints, structured_extraction

CV_TEXT = (
    "Ada Lovelace\nBackend Engineer\nada@example.com | +49 30 123456\n"
    "https://github.com/ada\n\nExperience\nSoftware Engineer at Shop GmbH 2021-2024\n"
    "Built Python APIs with FastAPI and PostgreSQL.\n"
)


def _docx_bytes() -> bytes:
    from docx import Document

    document = Document()
    for line in CV_TEXT.splitlines():
        document.add_paragraph(line)
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def _pdf_bytes() -> bytes:
    from reportlab.lib.pagesizes import A4
    from reportlab.pdfgen import canvas

    buffer = BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A4)
    text = pdf.beginText(40, 800)
    for line in CV_TEXT.splitlines():
        text.textLine(line)
    pdf.drawText(text)
    pdf.save()
    return buffer.getvalue()


def test_extracts_docx_text():
    result = extract_document("ada.docx", _docx_bytes())
    assert result.file_format == "docx"
    assert "Ada Lovelace" in result.text
    assert "Python APIs" in result.text


def test_extracts_pdf_text():
    result = extract_document("ada.pdf", _pdf_bytes())
    assert result.file_format == "pdf"
    assert result.pages == 1
    assert "PostgreSQL" in result.text


def test_rejects_unsupported_and_empty_documents():
    with pytest.raises(UnsupportedFileTypeError):
        extract_document("notes.txt", b"hello")
    with pytest.raises(DocumentExtractionError):
        extract_document("empty.docx", _docx_bytes_of_empty())


def _docx_bytes_of_empty() -> bytes:
    from docx import Document

    document = Document()
    document.add_paragraph(" ")
    buffer = BytesIO()
    document.save(buffer)
    return buffer.getvalue()


def test_structured_extraction_requires_an_llm():
    with pytest.raises(LLMUnavailableError):
        structured_extraction(CV_TEXT, "ada.docx")
    with pytest.raises(DocumentExtractionError):
        structured_extraction("   ", "ada.docx")


def test_extra_sections_are_coerced_from_loose_model_output():
    from core.schemas import CandidateProfileData

    assert CandidateProfileData.model_validate(
        {"extra_sections": "Applying for: Working Student"}
    ).extra_sections == {"notes": ["Applying for: Working Student"]}
    assert CandidateProfileData.model_validate(
        {"extra_sections": {"a": "one", "b": None, "c": ["x"]}}
    ).extra_sections == {"a": ["one"], "b": [], "c": ["x"]}


def test_heuristic_hints_only_return_source_facts():
    hints = heuristic_hints(CV_TEXT)
    assert hints["email"] == "ada@example.com"
    assert hints["github"] == "https://github.com/ada"
    assert "email" not in heuristic_hints("No contact details here.")
