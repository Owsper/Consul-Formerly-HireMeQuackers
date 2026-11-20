"""ATS knowledge, readiness reporting and export parse guarantees."""

from __future__ import annotations

from pathlib import Path

from core.ats_rules import (
    ATS_RULES_VERSION, ALLOWED_FONTS, HARD_PARSE_RULES, KNOCKOUT_NOTE,
    apply_layout_signals, ats_prompt_rules, build_ats_report, job_terms,
    standard_heading_set,
)
from core.schemas import CVBullet, CVEntry, CVSection, TailoredCV
from services.cv_tailoring import tailor_cv, validate_cv
from services.document_export import export_cv
from services.layout_verification import compare_layout, extract_metrics


def test_rules_module_is_versioned_and_covers_the_hard_parse_rules():
    assert ATS_RULES_VERSION
    keys = {rule.key for rule in HARD_PARSE_RULES}
    assert {
        "single_column", "no_tables", "no_text_boxes", "body_contact",
        "standard_headings", "standard_fonts", "plain_bullets", "text_layer",
    } <= keys
    assert "Times New Roman" in ALLOWED_FONTS
    assert "professional experience" in standard_heading_set()
    assert "berufserfahrung" in standard_heading_set()
    text = ats_prompt_rules()
    assert "ATS RULES" in text and "keyword dump" in text
    assert "Knockout" in KNOCKOUT_NOTE


def test_prompts_receive_the_shared_rules_and_keyword_targets():
    from services.llm_service import render_prompt

    tailoring = render_prompt(
        "cv_tailoring", job_json="{}", profile_json="{}", evidence_list="",
        requirements="{}", keyword_targets="Python (evidenced)",
        ats_rules="RULE-BLOCK", output_language="en",
    )
    assert "RULE-BLOCK" in tailoring
    assert "Python (evidenced)" in tailoring
    assert "$ats_rules" not in tailoring

    audit = render_prompt(
        "cv_validation", cv_json="{}", profile_json="{}", evidence_list="",
        job_json="{}", keyword_targets="Python", ats_rules="RULE-BLOCK",
    )
    assert "RULE-BLOCK" in audit
    assert "$keyword_targets" not in audit


def test_job_terms_and_coverage_only_count_terms_the_candidate_can_evidence(
        profile_data, evidence, job_record):
    terms = job_terms(job_record)
    assert "Python" in terms.must_have
    assert "Docker" in terms.must_have
    assert "Kubernetes" in terms.nice_to_have
    assert "German" in terms.must_have  # from "German (C1)", level is not invented

    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    report = build_ats_report(cv, profile_data, evidence, job_record)
    must = report["keyword_coverage"]["must_have"]
    assert report["version"] == ATS_RULES_VERSION
    assert report["parse_risk"] == "low", report["parse_risk_reasons"]
    assert must["available"] >= 3
    assert "Docker" in must["unevidenced"], "Docker is not in the ledger and must not count"
    assert all(term not in must["missing_evidenced"] for term in must["unevidenced"])
    assert report["keyword_coverage"]["target_title"] == job_record.title
    assert report["parse_checks"]["title_alignment"] is True
    assert report["quantified_bullets"]["with_metrics"] >= 1
    assert any("Never add a missing keyword" in tip for tip in report["recommendations"])


def test_nonstandard_heading_raises_parse_risk_and_a_fix(profile_data, evidence,
                                                         job_record):
    cv = TailoredCV(
        header={"name": "Ada Lovelace", "contact_lines": ["ada@example.com"]},
        summary="Backend engineer.",
        sections=[CVSection(heading="My Journey", kind="entries", entries=[
            CVEntry(title="Engineer", organization="Shop GmbH", bullets=[
                CVBullet(text="Built Python APIs.", evidence_ids=[evidence[0].evidence_id]),
                CVBullet(text="Responsible for maintaining systems.",
                         evidence_ids=[evidence[0].evidence_id]),
            ]),
        ])],
    )
    report = build_ats_report(cv, profile_data, evidence, job_record)
    assert report["parse_risk"] == "medium"
    assert report["parse_checks"]["standard_headings"] is False
    assert any("Rename the 'My Journey' heading" in tip
               for tip in report["recommendations"])
    assert report["content_quality"]["vague_responsibility_count"] == 1
    assert any("vague duty statements" in tip for tip in report["recommendations"])


def test_layout_signals_can_upgrade_parse_risk(profile_data, evidence, job_record):
    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    report = build_ats_report(cv, profile_data, evidence, job_record)
    merged = apply_layout_signals(report, {"checks": [
        {"name": "text_layer", "passed": False},
        {"name": "no_text_overflow", "passed": False},
        {"name": "page_count", "passed": True},
    ]})
    assert merged["parse_risk"] == "high"
    assert merged["layout_checked"] is True
    assert merged["parse_checks"]["layout_text_layer"] is False
    assert any("text layer" in reason for reason in merged["parse_risk_reasons"])


def test_validation_exposes_ats_report_without_blocking_a_clean_cv(
        profile_data, evidence, job_record):
    cv, report = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    assert report.passed is True
    assert report.ats_report
    assert report.ats_report["keyword_coverage"]["must_have"]["available"] >= 3
    assert report.ats_checks["standard_headings"] is True
    # The report is reproducible from the CV alone and never invents terms.
    direct = validate_cv(cv, profile_data, evidence, job_record)
    assert direct.ats_report["version"] == ATS_RULES_VERSION


def test_exports_guarantee_text_layer_and_clean_docx(profile_data, evidence,
                                                     job_record, tmp_path):
    from docx import Document

    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    files = export_cv(cv, out_dir=tmp_path, version=1, formats=("docx", "pdf", "txt"))
    metrics = extract_metrics(files["pdf"])
    assert metrics["characters"] > 200
    assert metrics["images"] == 0
    layout = compare_layout(files["pdf"])
    checks = {check["name"]: check for check in layout["checks"]}
    for name in ("text_layer", "no_embedded_images", "no_icon_fonts"):
        assert checks[name]["passed"], (name, checks[name])
    document = Document(files["docx"])
    assert not document.tables
    assert not document.inline_shapes
    assert any(p.text.startswith("•") for p in document.paragraphs)
    assert Path(files["txt"]).read_text(encoding="utf-8").startswith("ADA LOVELACE")


def test_image_only_conversion_falls_back_to_a_text_layer(profile_data, evidence,
                                                         job_record, tmp_path,
                                                         monkeypatch):
    from reportlab.pdfgen import canvas

    import services.document_export as exporter

    cv, _ = tailor_cv(profile_data, evidence, job_record, use_llm=False)

    def blank_pdf(docx, pdf, timeout=120):
        target = Path(pdf)
        target.parent.mkdir(parents=True, exist_ok=True)
        page = canvas.Canvas(str(target), pagesize=(595.28, 841.89))
        page.showPage()
        page.save()
        return target

    monkeypatch.setattr(exporter, "convert_docx_to_pdf", blank_pdf)
    files = exporter.export_cv(cv, out_dir=tmp_path, version=9, formats=("pdf",))
    metrics = extract_metrics(files["pdf"])
    assert metrics["characters"] > 200
    assert exporter.pdf_render_source(files["pdf"]) == "measured_renderer"
