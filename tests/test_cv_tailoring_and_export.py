from pathlib import Path

from core.schemas import (
    CVBullet, CVEntry, CVSection, JobRecord, ProjectEntry, TailoredCV,
)
from services.cv_tailoring import (
    build_rule_based_cv, sanitize_cv, tailor_cv, validate_cv,
)
from services.document_export import export_cv, cv_to_text
from services.profile_service import synthesize_evidence


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


def _frontend_job(**overrides) -> JobRecord:
    data = {
        "source": "manual",
        "source_job_id": "frontend-1",
        "title": "Frontend Developer",
        "company": "Acme",
        "required_skills": ["HTML", "CSS", "FastAPI"],
        "description": "Build web interfaces with HTML and CSS and APIs with FastAPI.",
    }
    data.update(overrides)
    return JobRecord(**data)


def _project_titles(cv) -> list[str]:
    return [entry.title for section in cv.sections
            if "Project" in section.heading for entry in section.entries]


def test_one_must_have_technology_is_enough_to_include_a_project(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.employment = []
    profile.projects = [
        ProjectEntry(
            name="Vera", description="Desktop application with a backend for church management.",
            technologies=["Python", "PySide6", "FastAPI", "REST APIs"],
        ),
        ProjectEntry(
            name="Unrelated", description="Spreadsheet automation for a local club.",
            technologies=["Excel"],
        ),
    ]
    evidence = synthesize_evidence(profile)

    cv = build_rule_based_cv(profile, evidence, _frontend_job())
    titles = _project_titles(cv)

    # FastAPI is one must-have requirement, so Vera qualifies even though the
    # project does not claim HTML or CSS.
    assert any("Vera" in title for title in titles)
    assert all("Unrelated" not in title for title in titles)


def test_web_frontend_rejects_a_desktop_only_project(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.employment = []
    profile.projects = [
        ProjectEntry(
            name="Vera", description="Desktop application with a backend for church management.",
            technologies=["Python", "PySide6", "FastAPI", "REST APIs"],
        ),
        ProjectEntry(
            name="Web dashboard", description="Internal reporting dashboard.",
            technologies=["React", "TypeScript", "HTML", "CSS"],
        ),
    ]
    evidence = synthesize_evidence(profile)
    job = _frontend_job(
        required_skills=["React", "TypeScript", "JavaScript", "HTML", "CSS"],
        preferred_skills=["REST APIs"],
        description="Build responsive web applications with React and TypeScript.",
    )

    titles = _project_titles(build_rule_based_cv(profile, evidence, job))

    assert any("Web dashboard" in title for title in titles)
    assert all("Vera" not in title for title in titles)


def test_no_relevant_projects_is_reported_instead_of_silently_dropped(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.projects = [
        ProjectEntry(name="Vera", description="Desktop app with FastAPI.",
                     technologies=["Python", "PySide6", "FastAPI"]),
        ProjectEntry(name="OCR benchmark", description="Benchmarked OCR models.",
                     technologies=["Python", "PaddleOCR"]),
        ProjectEntry(name="Job tracker", description="Tracked job applications.",
                     technologies=["Python", "Streamlit"]),
    ]
    evidence = synthesize_evidence(profile)
    job = _frontend_job(
        required_skills=["React", "TypeScript"],
        description="Build web applications with React and TypeScript.",
    )

    cv, report = tailor_cv(profile, evidence, job, use_llm=False)

    assert _project_titles(cv) == []
    assert any(issue.code == "no_relevant_projects" for issue in report.issues)


def test_project_filter_is_the_same_with_two_projects(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.projects = [
        ProjectEntry(name="Vera", description="Desktop app with FastAPI.",
                     technologies=["Python", "PySide6", "FastAPI"]),
        ProjectEntry(name="OCR benchmark", description="Benchmarked OCR models.",
                     technologies=["Python", "PaddleOCR"]),
    ]
    evidence = synthesize_evidence(profile)
    job = _frontend_job(
        required_skills=["React", "TypeScript"],
        description="Build web applications with React and TypeScript.",
    )

    cv = build_rule_based_cv(profile, evidence, job)

    # A two-project profile must not bypass the relevance filter.
    assert _project_titles(cv) == []


def test_projects_are_kept_when_the_candidate_has_no_employment(profile_data):
    """A student CV must never lose every project just because none names a
    must-have technology (regression: the SAP HANA UX CV shipped empty)."""
    profile = profile_data.model_copy(deep=True)
    profile.employment = []
    profile.projects = [
        ProjectEntry(name="HireMeQuackers", description="Agentic AI job discovery tool.",
                     technologies=["Python", "Gemini API", "Streamlit"]),
        ProjectEntry(name="Mint", description="Benchmarked OCR models on handwritten samples.",
                     technologies=["Python", "PaddleOCR"]),
        ProjectEntry(name="Vera", description="Desktop app for church management.",
                     technologies=["Python", "PySide6", "FastAPI", "PostgreSQL"]),
    ]
    evidence = synthesize_evidence(profile)
    job = _frontend_job(
        required_skills=["SAP", "Figma"],
        description="Working student for UX tooling; Python scripts welcome.",
    )

    cv, report = tailor_cv(profile, evidence, job, use_llm=False)

    assert _project_titles(cv), "a student CV must not drop all projects"
    assert report.passed is True
    assert cv.all_bullets()


def test_language_requirements_do_not_block_projects(profile_data):
    profile = profile_data.model_copy(deep=True)
    profile.employment = []
    profile.projects = [
        ProjectEntry(name="Vera", description="Desktop app with FastAPI.",
                     technologies=["Python", "PySide6", "FastAPI", "REST APIs"]),
    ]
    evidence = synthesize_evidence(profile)
    job = _frontend_job(
        required_skills=[],
        languages=["English (C1)"],
        description="Build internal tools with Python and FastAPI.",
    )

    assert any("Vera" in title for title in _project_titles(
        build_rule_based_cv(profile, evidence, job)))


def test_text_export_prints_entry_dates_once():
    cv = TailoredCV(
        header={"name": "Ada Lovelace"},
        sections=[CVSection(heading="Education", kind="entries", entries=[
            CVEntry(title="BSc Software Engineering",
                    organization="University of Europe, Potsdam",
                    dates="09/2024 – present"),
        ])],
    )

    text = cv_to_text(cv)

    assert text.count("09/2024 – present") == 1
    assert "University of Europe, Potsdam" in text


def test_a_cv_without_skills_is_not_sendable(profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)
    cv.sections = [section for section in cv.sections if section.kind != "skills"]

    report = validate_cv(cv, profile_data, evidence, job_record)

    assert report.passed is False
    assert any(issue.code == "missing_skills" and issue.severity == "error"
               for issue in report.issues)


def test_a_cv_without_contact_details_is_not_sendable(profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)
    cv.header.contact_lines = []

    report = validate_cv(cv, profile_data, evidence, job_record)

    assert report.passed is False
    assert any(issue.code == "missing_personal_info" and issue.severity == "error"
               for issue in report.issues)


def test_a_cv_that_drops_recorded_certifications_is_not_sendable(
        profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)
    cv.sections = [section for section in cv.sections
                   if "certif" not in section.heading.lower()]

    report = validate_cv(cv, profile_data, evidence, job_record)

    assert report.passed is False
    assert any(issue.code == "missing_additional_info" and issue.severity == "error"
               for issue in report.issues)


def test_a_complete_deterministic_cv_passes_every_completeness_check(
        profile_data, evidence, job_record):
    cv = build_rule_based_cv(profile_data, evidence, job_record)

    report = validate_cv(cv, profile_data, evidence, job_record)

    assert report.passed is True, [i.message for i in report.issues if i.severity == "error"]
    assert not any(issue.code.startswith("missing_") for issue in report.issues)
