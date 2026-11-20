from pathlib import Path

from core.schemas import CVBullet, CVEntry, CVSection, TailoredCV
from services.cv_tailoring import (
    build_rule_based_cv, sanitize_cv, tailor_cv, validate_cv,
)
from services.document_export import export_cv, cv_to_text


def test_rule_based_cv_cites_evidence(profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)
    valid = {e.evidence_id for e in evidence if e.status.value != "rejected"}
    bullets = cv.all_bullets()
    assert bullets
    for bullet in bullets:
        assert bullet.evidence_ids
        assert set(bullet.evidence_ids) <= valid
    assert cv.header.name == "Ada Lovelace"
    assert "Python" in cv.summary or "Backend" in cv.summary


def test_academic_project_is_not_presented_as_employment(profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)
    headings = {section.heading for section in cv.sections}
    if "Academic Projects" in headings:
        academic = next(s for s in cv.sections if s.heading == "Academic Projects")
        titles = [e.title for e in academic.entries]
        assert "Thesis prototype" in titles
    experience = next((s for s in cv.sections if s.heading == "Professional Experience"), None)
    if experience:
        assert "Thesis prototype" not in [e.title for e in experience.entries]


def test_sanitizer_removes_uncited_bullets(profile_data, evidence):
    cv = TailoredCV(
        header={"name": "Ada", "title": "Engineer", "contact_lines": ["ada@example.com"]},
        summary="Backend engineer.",
        sections=[CVSection(heading="Professional Experience", kind="entries", entries=[
            CVEntry(title="Engineer", organization="Acme", bullets=[
                CVBullet(text="Built Python APIs.", evidence_ids=[evidence[0].evidence_id]),
                CVBullet(text="Managed a team of 50 engineers.", evidence_ids=[]),
            ])
        ])],
    )
    cleaned, removed = sanitize_cv(cv, profile_data, evidence)
    texts = [b.text for b in cleaned.all_bullets()]
    assert "Built Python APIs." in texts
    assert all("Managed a team" not in t for t in texts)
    assert any("Managed a team" in r for r in removed)


def test_validator_flags_invented_metrics_and_bogus_ids(profile_data, evidence, job_record):
    cv = TailoredCV(
        header={"name": "Ada", "contact_lines": ["ada@example.com"]},
        summary="Engineer.",
        sections=[CVSection(heading="Professional Experience", kind="entries", entries=[
            CVEntry(title="Engineer", organization="Acme", bullets=[
                CVBullet(text="Increased revenue by 987%.", evidence_ids=[evidence[0].evidence_id]),
                CVBullet(text="Used a fake reference.", evidence_ids=["ev-does-not-exist"]),
            ])
        ])],
    )
    report = validate_cv(cv, profile_data, evidence, job_record)
    assert report.passed is False
    assert report.unsupported_claims
    assert any(i.code == "unsupported_claims" for i in report.issues)
    assert report.evidence_coverage < 1


def test_tailor_cv_passes_and_exports(profile_data, evidence, job_record, tmp_path):
    cv, report = tailor_cv(profile_data, evidence, job_record, use_llm=False)
    assert cv.generator == "rule_based"
    assert report.passed is True
    files = export_cv(cv, out_dir=tmp_path, version=1, formats=("docx", "pdf", "txt"))
    assert set(files) == {"docx", "pdf", "txt"}
    for path in files.values():
        assert Path(path).exists() and Path(path).stat().st_size > 500
    assert Path(files["pdf"]).read_bytes().startswith(b"%PDF")
    # The master template sets the candidate name in caps.
    assert "ADA LOVELACE" in Path(files["txt"]).read_text(encoding="utf-8")
    assert "consul_CV" in Path(files["docx"]).name
    text = cv_to_text(cv)
    assert "PROFESSIONAL EXPERIENCE" in text.upper()


def test_cv_never_modifies_ground_truth(profile_data, evidence, job_record):
    before = profile_data.model_dump_json()
    tailor_cv(profile_data, evidence, job_record, use_llm=False)
    assert profile_data.model_dump_json() == before
