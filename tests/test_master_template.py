"""The reference CV is the mandatory design; these tests guard its geometry."""

from pathlib import Path

import pytest

from core.schemas import JobRecord
from services.application_service import create_application
from services.cv_service import (
    approve_cv, generate_cv_for_job, is_cv_approved, load_cv, revoke_cv_approval,
)
from services.cv_tailoring import tailor_cv
from services.deduplication import persist_job
from services.document_export import export_cv, export_docx, pdf_render_source
from services.layout_verification import compare_layout, extract_metrics
from services.master_template import (
    BULLET_INDENT_PT, COLUMN_START_PT, MARGIN_LEFT_PT, MARGIN_RIGHT_PT,
    PAGE_HEIGHT_PT, PAGE_WIDTH_PT, STYLE_BULLET, STYLE_ENTRY, STYLE_NAME,
    STYLE_ROW, STYLE_SECTION, ensure_master_template, find_office_converter,
)


def test_master_template_is_a4_with_reference_margins_and_styles():
    from docx import Document

    path = ensure_master_template()
    document = Document(str(path))
    section = document.sections[0]
    assert section.page_width.pt == pytest.approx(PAGE_WIDTH_PT, abs=0.2)
    assert section.page_height.pt == pytest.approx(PAGE_HEIGHT_PT, abs=0.2)
    assert section.left_margin.pt == pytest.approx(MARGIN_LEFT_PT, abs=0.1)
    assert section.right_margin.pt == pytest.approx(MARGIN_RIGHT_PT, abs=0.1)

    styles = {style.name: style for style in document.styles}
    for name in (STYLE_NAME, STYLE_SECTION, STYLE_ENTRY, STYLE_BULLET, STYLE_ROW):
        assert name in styles
    assert styles[STYLE_NAME].font.size.pt == 16
    assert styles[STYLE_NAME].font.bold is True
    assert styles[STYLE_SECTION].font.size.pt == 10.5
    assert styles[STYLE_SECTION].font.underline is True
    entry_tabs = [t.position.pt for t in styles[STYLE_ENTRY].paragraph_format.tab_stops]
    assert COLUMN_START_PT in entry_tabs
    bullet = styles[STYLE_BULLET].paragraph_format
    assert bullet.left_indent.pt == pytest.approx(COLUMN_START_PT + BULLET_INDENT_PT)
    assert bullet.first_line_indent.pt == pytest.approx(-BULLET_INDENT_PT)
    row = styles[STYLE_ROW].paragraph_format
    assert row.left_indent.pt == pytest.approx(COLUMN_START_PT)
    assert row.first_line_indent.pt == pytest.approx(-COLUMN_START_PT)


def test_docx_is_populated_into_the_master_not_built_from_scratch(profile_data, evidence,
                                                                  job_record, tmp_path):
    from docx import Document

    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    path = export_docx(cv, tmp_path / "master.docx")
    document = Document(path)
    assert document.sections[0].left_margin.pt == pytest.approx(MARGIN_LEFT_PT, abs=0.1)
    assert document.paragraphs[0].style.name == STYLE_NAME
    assert document.paragraphs[0].text == "ADA LOVELACE"
    styles_used = {p.style.name for p in document.paragraphs}
    assert {STYLE_SECTION, STYLE_ENTRY, STYLE_BULLET}.issubset(styles_used)
    assert not document.tables
    assert not document.inline_shapes
    assert "TECHNICAL SKILLS" in [p.text for p in document.paragraphs]


def test_pdf_matches_reference_geometry(profile_data, evidence, job_record, tmp_path):
    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    files = export_cv(cv, out_dir=tmp_path, version=1, formats=("pdf",))
    pdf = files["pdf"]
    metrics = extract_metrics(pdf)
    assert metrics["pages"] <= 2
    assert metrics["page_width"] == pytest.approx(595.28, abs=0.5)
    assert metrics["left_edge"] == pytest.approx(MARGIN_LEFT_PT, abs=1.0)
    assert metrics["column_x"] == pytest.approx(169.3, abs=1.5)
    assert metrics["name_size"] == pytest.approx(16.0, abs=0.2)
    assert metrics["body_size"] == pytest.approx(10.0, abs=0.2)
    assert metrics["rules"] >= 3
    report = compare_layout(pdf)
    assert report["passed"] is True, [c for c in report["checks"] if not c["passed"]]
    assert report["reference"]["column_x"] == pytest.approx(169.3, abs=1.0)
    source = pdf_render_source(pdf)
    assert source in {"docx_conversion", "measured_renderer"}
    if find_office_converter():
        assert source == "docx_conversion", "install detected but DOCX was not converted"


def test_pdf_conversion_is_used_when_available(profile_data, evidence, job_record,
                                               tmp_path, monkeypatch):
    import services.master_template as master

    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    docx_path = export_docx(cv, tmp_path / "source.docx")
    called = {}

    def fake_find():
        return "fake-soffice"

    def fake_convert(docx, pdf, timeout=120):
        assert Path(docx).exists()
        Path(pdf).write_bytes(Path(docx).read_bytes())
        called["yes"] = True
        return Path(pdf)

    monkeypatch.setattr(master, "find_office_converter", fake_find)
    monkeypatch.setattr(master, "convert_docx_to_pdf", fake_convert)
    import services.document_export as exporter

    monkeypatch.setattr(exporter, "convert_docx_to_pdf", fake_convert)
    files = exporter.export_cv(cv, out_dir=tmp_path, version=2, formats=("docx", "pdf"))
    assert called.get("yes") is True
    assert pdf_render_source(files["pdf"]) == "docx_conversion"


def test_approval_gate_on_a_generated_version(session, approved_profile, profile_data,
                                              evidence, job_record):
    row, _ = persist_job(session, job_record)
    cv_row, _cv, report = generate_cv_for_job(session, row.id, use_llm=False,
                                              formats=("docx", "pdf"))
    assert report.layout.get("passed") is True
    assert is_cv_approved(session, cv_row.id) is False
    approve_cv(session, cv_row.id)
    assert is_cv_approved(session, cv_row.id) is True
    revoke_cv_approval(session, cv_row.id)
    assert is_cv_approved(session, cv_row.id) is False


def test_cv_generation_does_not_touch_ground_truth(session, approved_profile,
                                                   profile_data, evidence, job_record):
    row, _ = persist_job(session, job_record)
    before = profile_data.model_dump_json()
    cv_row, _cv, _report = generate_cv_for_job(session, row.id, use_llm=False,
                                               formats=("docx",))
    assert cv_row.template_name == "master_cv.docx"
    assert profile_data.model_dump_json() == before
    _loaded, report = load_cv(cv_row)
    assert report.passed is True
