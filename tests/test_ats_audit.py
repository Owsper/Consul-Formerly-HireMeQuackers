"""The job-specific ATS audit must measure the exported file, not the model."""

from __future__ import annotations

from pathlib import Path

from core.schemas import TailoredCV
from services.ats_audit import audit_document, read_document
from services.cv_service import generate_cv_for_job
from services.deduplication import persist_job


def _generate(session, job_record):
    row, _ = persist_job(session, job_record)
    cv_row, cv, report = generate_cv_for_job(session, row.id, use_llm=False,
                                             formats=("docx", "pdf"))
    session.commit()
    return cv_row, cv, report, row


def test_audit_scores_the_exported_pdf(session, approved_profile, profile_data,
                                       evidence, job_record):
    cv_row, cv, report, _ = _generate(session, job_record)
    audit = report.ats_report["document_audit"]

    assert audit["engine"] == "consul-ats-sim"
    assert audit["parsed"]["source"] == "pdf"
    assert 0 <= audit["score"] <= 100
    assert audit["parsed"]["email"] is True
    assert audit["parsed"]["name"] is True
    assert abs(sum(item["weight"] for item in audit["criteria"]) - 100) < 1e-9
    assert all(item["points"] <= item["weight"] for item in audit["criteria"])

    ids = {item["id"]: item for item in audit["criteria"]}
    assert ids["text_layer"]["status"] == "pass"
    assert ids["format_safety"]["status"] == "pass"
    assert ids["contact_block"]["status"] == "pass"
    # The template is a two-column date/content layout: reading order must still hold.
    assert ids["reading_order"]["status"] == "pass"


def test_audit_keyword_coverage_follows_the_posting(session, approved_profile,
                                                    profile_data, evidence, job_record):
    cv_row, cv, report, _ = _generate(session, job_record)
    audit = report.ats_report["document_audit"]
    must = audit["keyword_coverage"]["must_have"]

    # FastAPI/PostgreSQL are in the posting and in the evidence: they must count.
    assert {"Python", "FastAPI"} <= set(must["covered"])
    # Docker is a posting requirement the candidate cannot evidence.
    assert "Docker" in must["unevidenced"]
    assert audit["score"] > 50


def test_audit_detects_a_lost_text_layer(tmp_path, approved_profile, profile_data,
                                         evidence, job_record, session):
    cv_row, cv, report, _ = _generate(session, job_record)
    import pymupdf

    blank = tmp_path / "blank.pdf"
    with pymupdf.open() as document:
        page = document.new_page()
        page.draw_rect(pymupdf.Rect(50, 50, 200, 100), fill=(0.2, 0.2, 0.2))
        document.save(str(blank))

    audit = audit_document(cv=cv, job=job_record, profile=profile_data,
                           evidence=evidence, pdf_path=blank, docx_path=cv_row.docx_path)
    ids = {item["id"]: item for item in audit["criteria"]}
    assert ids["text_layer"]["status"] == "fail"
    assert audit["status"] == "blocked"
    assert "Text layer and extraction" in audit["blockers"]


def test_audit_reports_tables_and_images(tmp_path, session, approved_profile,
                                        profile_data, evidence, job_record):
    cv_row, cv, report, _ = _generate(session, job_record)
    from docx import Document

    table_doc = tmp_path / "table.docx"
    document = Document()
    document.add_paragraph("ADA LOVELACE")
    document.add_table(rows=2, cols=2)
    document.save(str(table_doc))

    audit = audit_document(cv=cv, job=job_record, profile=profile_data,
                           evidence=evidence, pdf_path=None, docx_path=table_doc)
    ids = {item["id"]: item for item in audit["criteria"]}
    assert ids["format_safety"]["status"] != "pass"
    assert "table" in ids["format_safety"]["detail"]
    assert audit["parsed"]["source"] == "docx"


def test_audit_is_deterministic(session, approved_profile, profile_data, evidence,
                                job_record):
    cv_row, cv, report, _ = _generate(session, job_record)
    first = audit_document(cv=cv, job=job_record, profile=profile_data, evidence=evidence,
                           pdf_path=cv_row.pdf_path, docx_path=cv_row.docx_path)
    second = audit_document(cv=cv, job=job_record, profile=profile_data, evidence=evidence,
                            pdf_path=cv_row.pdf_path, docx_path=cv_row.docx_path)
    assert first["score"] == second["score"]
    assert first["criteria"] == second["criteria"]


def test_missing_files_return_an_honest_zero(job_record, profile_data, evidence):
    audit = audit_document(cv=TailoredCV(), job=job_record, profile=profile_data,
                           evidence=evidence, pdf_path=None, docx_path=None)
    assert audit["score"] == 0
    assert audit["status"] == "blocked"
    assert read_document(pdf_path=None, docx_path=None).characters == 0


def test_preview_renders_pages_without_a_data_url(session, approved_profile,
                                                 profile_data, evidence, job_record):
    from ui.pdf_preview import page_images

    cv_row, cv, report, _ = _generate(session, job_record)
    images, total = page_images(cv_row.pdf_path)
    assert total >= 1
    assert len(images) == total
    assert images[0].startswith(b"\x89PNG")
    assert Path(cv_row.pdf_path).exists()
